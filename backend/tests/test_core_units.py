"""Tests unitaires : redaction, store de preuves, secrets, Policy Gate, providers."""

from __future__ import annotations

import pytest

from app.audit.controls import get_control
from app.audit.rules import evaluate_rule_set, get_rule_set
from app.agent.providers import build_provider
from app.core.redact import redact
from app.evidence.secrets_store import SecretsStore
from app.evidence.store import EvidenceStore
from app.harness.policy import PolicyGate
from app.models import AuditMission, PermissionLevel, SourceConnection, SourceType
from app.tools.all_tools import TOOL_DEFS


def test_redact_masks_sensitive_values():
    data = {
        "password": "hunter2",
        "Authorization": "Bearer abc",
        "nested": {"api_key": "sk-123", "value": "ok"},
        "list": [{"token": "x"}, {"plain": "y"}],
    }
    out = redact(data)
    assert out["password"] == "[REDACTED]"
    assert out["Authorization"] == "[REDACTED]"
    assert out["nested"]["api_key"] == "[REDACTED]"
    assert out["nested"]["value"] == "ok"
    assert out["list"][0]["token"] == "[REDACTED]"
    assert out["list"][1]["plain"] == "y"


def test_evidence_store_checksum_and_immutability(tmp_path):
    store = EvidenceStore(tmp_path / "ev")
    ev = store.save(
        mission_id="mission_1", run_id="run_1", source_id="src_1", type_="record_set",
        title="t", payload={"records": [{"a": 1}]}, provenance={"tool": "x"},
        evidence_id="ev_test0001",
    )
    loaded = store.load(ev)
    assert loaded["payload"]["records"] == [{"a": 1}]
    # modification hors bande → l'intégrité échoue explicitement (docs/13)
    path = store.root / ev.storage_ref
    raw = path.read_bytes().replace(b'"a":1', b'"a":2')
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        store.load(ev)
    assert store.verify(ev) is False


def test_secrets_store_roundtrip(tmp_path):
    secrets = SecretsStore(tmp_path / "secrets.json")
    ref = secrets.put({"password": "s3cret"})
    assert ref.startswith("sec_")
    assert secrets.get(ref) == {"password": "s3cret"}
    assert secrets.get("sec_inconnu") == {}
    secrets.delete(ref)
    assert secrets.get(ref) == {}


def test_policy_gate_scope_and_approval():
    gate = PolicyGate()
    mission = AuditMission(id="mission_1", title="t", objective="t", source_ids=["src_file"])
    file_source = SourceConnection(id="src_file", name="f", type=SourceType.file)

    specs = {d["spec"]["name"]: d["spec"] for d in TOOL_DEFS}

    class Spec:
        def __init__(self, s):
            self.name = s["name"]
            self.source_types = s["source_types"]
            self.permission = PermissionLevel(s["permission"])

    # hors périmètre → refus
    with pytest.raises(Exception):
        gate.check(Spec(specs["data_profile"]), {"source_id": "src_autre"}, mission, None)
    # tool api sur source fichier → refus type
    api_source = SourceConnection(id="src_api", name="a", type=SourceType.api)
    with pytest.raises(Exception):
        gate.check(Spec(specs["data_profile"]), {"source_id": "src_api"}, mission, api_source)
    # approved-tests sans approbation → refus
    web_spec = Spec(specs["web_run_journey"])
    web_source = SourceConnection(id="src_web", name="w", type=SourceType.web)
    mission.source_ids = ["src_web"]
    with pytest.raises(Exception):
        gate.check(web_spec, {"source_id": "src_web"}, mission, web_source)
    # avec approbation explicite → passe
    mission.approved_plan = {"approved_actions": [{"tool": "web_run_journey", "source_id": "src_web"}]}
    gate.check(web_spec, {"source_id": "src_web"}, mission, web_source)


def test_rules_engine_detects_and_passes(faulty_csv, clean_csv):
    import pandas as pd
    from io import StringIO

    ruleset = get_rule_set("rs_orders_v1")
    assert ruleset is not None

    result_bad = evaluate_rule_set(pd.read_csv(StringIO(faulty_csv)), ruleset)
    assert not result_bad.valid
    rule_ids = {v.rule_id for v in result_bad.violations}
    assert {"R5", "R7", "R8", "R4"} <= rule_ids  # date invalide, doublon, négatif, null
    assert any(v.row_index is not None for v in result_bad.violations)

    result_ok = evaluate_rule_set(pd.read_csv(StringIO(clean_csv)), ruleset)
    assert result_ok.valid
    assert result_ok.violation_count == 0


def test_control_catalog_versions():
    c = get_control("DATA-01")
    assert c is not None and c.version == "v1" and c.criterion
    assert get_control("INCONNU") is None


def test_provider_factory():
    provider = build_provider({"provider": "mock"})
    assert provider.provider_id == "mock"
    with pytest.raises(ValueError):
        build_provider({"provider": "openai", "model": "gpt-4o-mini", "api_key": ""})


@pytest.mark.asyncio
async def test_mock_provider_plan_and_findings_protocol():
    from app.agent.providers.mock import MockLLMProvider
    from app.agent.prompts import findings_request, plan_request

    mock = MockLLMProvider("data_audit")
    plan_prompt = plan_request(
        {"id": "mission_1", "objective": "o", "control_ids": ["DATA-01"], "time_range": {}, "limits": {}},
        [{"source_id": "src_1", "type": "file", "initial_evidence_ids": ["ev_1"], "rule_set_id": "rs_orders_v1"}],
        [], [{"id": "DATA-01", "version": "v1"}],
    )
    resp = await mock.chat("sys", [{"role": "user", "content": plan_prompt}])
    plan = __import__("json").loads(resp.content)
    tools = [s["tool"] for s in plan["steps"]]
    assert "discover_source" in tools and "data_validate" in tools

    findings_prompt = findings_request(
        [{"id": "ev_val", "type": "validation", "source_id": "src_1", "title": "t",
          "observed_at": "now", "summary": {"valid": False, "violation_count": 3, "rows": 10, "rule_set_id": "rs_orders_v1", "violations_sample": []}}],
        [{"id": "DATA-01", "version": "v1"}], "o",
    )
    resp2 = await mock.chat("sys", [{"role": "user", "content": findings_prompt}])
    findings = __import__("json").loads(resp2.content)["findings"]
    assert len(findings) == 1
    assert findings[0]["evidence_refs"] == ["ev_val"]
    assert findings[0]["control_id"] == "DATA-01"
