"""Phase 2B/4 — tools génériques Odoo read-only, testés avec un connecteur factice
(sans serveur Odoo) : découverte, métadonnées, requêtes bornées, relations,
agrégats, blacklist modèles/champs, domaine avec opérateur interdit, preuves."""

from __future__ import annotations

import asyncio

from app.tools.odoo_generic_tools import (
    OdooAggregateInput,
    OdooDescribeModelInput,
    OdooFollowRelationInput,
    OdooListModelsInput,
    OdooQueryRecordsInput,
    _validate_domain,
    tool_odoo_aggregate_records,
    tool_odoo_describe_model,
    tool_odoo_follow_relation,
    tool_odoo_list_models,
    tool_odoo_query_records,
)

FIELDS = {
    "name": {"type": "char", "string": "Référence"},
    "amount_total": {"type": "float", "string": "Total"},
    "partner_id": {"type": "many2one", "string": "Client", "relation": "res.partner"},
    "line_ids": {"type": "one2many", "string": "Lignes", "relation": "sale.order.line"},
    "user_password": {"type": "char", "string": "Mot de passe"},
    "attachment": {"type": "binary", "string": "Pièce"},
}


class FakeOdooConnector:
    """Substitut minimal du connecteur Odoo (aucun serveur requis)."""

    def __init__(self):
        self.closed = False

    async def list_accessible_models(self, limit=500):
        return [
            {"model": "sale.order", "name": "Commandes", "readable": True, "record_count": 42},
            {"model": "x_custom_survey", "name": "Custom Survey", "readable": True, "record_count": 3},
            {"model": "res.users.log", "name": "Log", "readable": False, "reason": "blacklist"},
        ]

    async def describe_model(self, model):
        from app.connectors.odoo.generic import (
            model_is_allowed, relations_from_fields, sanitize_fields,
        )

        if not model_is_allowed(model):
            return {"model": model, "allowed": False,
                    "reason": "modèle technique/sensible interdit"}
        count = 42 if model == "sale.order" else 3
        safe = sanitize_fields(FIELDS)
        return {"model": model, "allowed": True, "record_count": count,
                "fields": [{"name": n, "string": meta.get("string", n),
                            "type": meta["type"], "relation": meta.get("relation"),
                            "required": False} for n, meta in sorted(safe.items())],
                "relations": relations_from_fields(safe),
                "excluded_sensitive_fields": sorted(set(FIELDS) - set(safe))}

    async def query_records(self, model, domain, fields, limit=50, order=None):
        if model == "x_forbidden":
            return {"allowed": False, "error": "modèle interdit"}
        rows = [{"name": f"SO-{i}", "amount_total": 100.0 * i} for i in range(5)]
        if fields:
            rows = [{f: r.get(f) for f in fields} for r in rows]
        return {"allowed": True, "model": model, "count": min(len(rows), limit), "records": rows[:limit]}

    async def follow_relation(self, model, record_id, relation_field, limit=50):
        if relation_field == "partner_id":
            return {"allowed": True, "relation_type": "many2one", "comodel": "res.partner",
                    "records": [{"id": 7, "name": "Client A"}]}
        if relation_field == "line_ids":
            return {"allowed": True, "relation_type": "one2many", "comodel": "sale.order.line",
                    "records": [{"id": 1}, {"id": 2}], "total_linked": 2}
        return {"allowed": True, "error": f"champ de relation inconnu : {relation_field}"}

    async def aggregate_records(self, model, group_by, domain, aggregate_field=None, aggregate_op="count", limit=20):
        from app.connectors.odoo.generic import sanitize_fields

        safe = sanitize_fields(FIELDS)
        if group_by not in safe:
            return {"allowed": True, "error": f"champ de groupement inconnu : {group_by}"}
        read_fields = [group_by] + ([aggregate_field] if aggregate_field else [])
        rows = await self.query_records(model, domain, read_fields, limit=200)
        buckets: dict[str, int] = {}
        sums: dict[str, float] = {}
        for r in rows["records"]:
            key = str(r.get(group_by))
            buckets[key] = buckets.get(key, 0) + 1
            if aggregate_field and isinstance(r.get(aggregate_field), (int, float)):
                sums[key] = sums.get(key, 0) + float(r[aggregate_field])
        groups = [{"group": k, "count": c, **({"sum": sums[k]} if aggregate_field else {})}
                  for k, c in sorted(buckets.items(), key=lambda kv: -kv[1])[:limit]]
        return {"allowed": True, "model": model, "group_by": group_by,
                "fallback": "search_read", "groups": groups}

    async def close(self):
        self.closed = True


class FakeStore:
    def __init__(self):
        self.saved = []

    def save(self, **kwargs):
        # strict comme le vrai store : evidence_id obligatoire (régression live 3A)
        if not kwargs.get("evidence_id"):
            raise TypeError("store.save requiert evidence_id (contrat réel)")
        self.saved.append(kwargs)
        return type("Ev", (), {"id": kwargs["evidence_id"], **{k: v for k, v in kwargs.items() if k != "evidence_id"}})()


class FakeRepo:
    async def create_evidence_meta(self, ev):
        self.ev = ev


class FakeConnectors:
    def __init__(self, connector):
        self._connector = connector

    async def get_source(self, source_id):
        from app.models import SourceConnection, SourceStatus, SourceType

        return SourceConnection(id=source_id, name="Odoo démo", type=SourceType.odoo,
                                status=SourceStatus.connected)

    def build(self, source):
        return self._connector


def _ctx():
    from app.models import AuditMission

    mission = AuditMission(id="m1", title="t", objective="o", source_ids=["src_odoo"])
    return ToolContext(mission=mission, run_id="r1", source=None, secrets={},
                       store=FakeStore(), repo=FakeRepo(),
                       connectors=FakeConnectors(FakeOdooConnector()), extra={})


# import placé après définition de _ctx pour la lisibilité ; les tests suivants l'utilisent
from app.harness.contracts import ToolContext  # noqa: E402


def test_list_models_blacklists_technical():
    result = asyncio.run(tool_odoo_list_models(_ctx(), OdooListModelsInput(source_id="src_odoo")))
    models = [m["model"] for m in result.preview["models"]]
    assert "sale.order" in models and "x_custom_survey" in models
    assert all(not m.startswith("res.users.log") for m in models)


def test_describe_excludes_sensitive_and_binary_fields():
    result = asyncio.run(tool_odoo_describe_model(_ctx(), OdooDescribeModelInput(source_id="src_odoo", model="sale.order")))
    fields = [f["name"] for f in result.preview["fields"]]
    assert "user_password" not in fields and "attachment" not in fields
    assert {r["type"] for r in result.preview["relations"]} == {"many2one", "one2many"}
    assert result.preview["excluded_sensitive_fields"] == ["attachment", "user_password"]


def test_describe_forbidden_model():
    result = asyncio.run(tool_odoo_describe_model(_ctx(), OdooDescribeModelInput(source_id="src_odoo", model="ir.cron")))
    assert result.preview["allowed"] is False and result.status == "error"


def test_query_records_bounded_and_evidence_created():
    ctx = _ctx()
    args = {"source_id": "src_odoo", "model": "sale.order",
            "domain": [["amount_total", ">", "0"]], "fields": ["name", "amount_total"],
            "limit": 3}
    result = asyncio.run(tool_odoo_query_records(ctx, args))
    assert result.status == "success" and result.record_count == 3
    assert result.evidence_ids, "une evidence record_set doit être créée"
    assert ctx.store.saved[0]["type_"] == "record_set"
    # aperçu borné pour le LLM (régression live 3A : succès sans preview = observation vide)
    assert result.preview["record_count"] == 3
    assert result.preview["sample"] and "name" in result.preview["sample"][0]
    assert "get_evidence_excerpt" in result.preview["sample_note"]


def test_domain_operator_allowlist():
    assert _validate_domain([["name", "ilike", "SO"]]) is None
    err = _validate_domain([["name", "write", "x"]])
    assert err and "non autorisé" in err
    err2 = _validate_domain([["a", "=", 1], "n'importe quoi"])
    assert err2 and "invalide" in err2


def test_follow_relation_many2one_and_one2many():
    ctx = _ctx()
    args = OdooFollowRelationInput(source_id="src_odoo", model="sale.order",
                                   record_id=5, relation_field="partner_id")
    result = asyncio.run(tool_odoo_follow_relation(ctx, args))
    assert result.status == "success" and result.record_count == 1
    assert result.preview["comodel"] == "res.partner" and result.preview["sample"]
    args2 = OdooFollowRelationInput(source_id="src_odoo", model="sale.order",
                                    record_id=5, relation_field="line_ids")
    result2 = asyncio.run(tool_odoo_follow_relation(ctx, args2))
    assert result2.record_count == 2
    assert result2.preview["total_linked"] == 2


def test_aggregate_success():
    ctx = _ctx()
    args = OdooAggregateInput(source_id="src_odoo", model="sale.order",
                              group_by="partner_id", aggregate_field="amount_total",
                              aggregate_op="sum")
    result = asyncio.run(tool_odoo_aggregate_records(ctx, args))
    assert result.status == "success"


# ==========================================================================
# Phase 3A — régression live : follow_relation doit lire le comodèle avec des
# champs sanitisés (sinon Odoo renvoie TOUS les champs, images base64 comprises)
# ==========================================================================

from app.connectors.odoo.connector import OdooConnector  # noqa: E402


class _StubbedOdooConnector(OdooConnector):
    """Transport XML-RPC remplacé par des réponses scriptées."""

    def __init__(self):
        super().__init__({"url": "http://stub", "db": "d", "username": "u"}, {})
        self.uid = 1
        self.calls: list[tuple] = []

    async def _call(self, model, method, args, kwargs=None):
        self.calls.append((model, method, kwargs or {}))
        if (model, method) == ("sale.order", "fields_get"):
            return {"partner_id": {"type": "many2one", "relation": "res.partner"},
                    "name": {"type": "char"}}
        if (model, method) == ("sale.order", "read"):
            return [{"id": 2, "partner_id": [7, "Client A"]}]
        if (model, method) == ("res.partner", "fields_get"):
            return {"name": {"type": "char"}, "image_1920": {"type": "binary"},
                    "payment_token_ids": {"type": "one2many", "relation": "payment.token"}}
        if (model, method) == ("res.partner", "read"):
            # fidèle à Odoo : seuls les champs demandés sont renvoyés
            base = {"id": 7, "name": "Client A", "image_1920": "base64…",
                    "api_key": "SK-LIVE-SECRET"}
            return [{f: base.get(f) for f in kwargs.get("fields") or sorted(base)}]
        raise AssertionError(f"appel inattendu: {model}.{method}")


def test_follow_relation_sanitizes_comodel_fields_and_redacts():
    conn = _StubbedOdooConnector()
    out = asyncio.run(conn.follow_relation("sale.order", 2, "partner_id"))
    assert out["allowed"] is True and out["comodel"] == "res.partner"
    row = out["records"][0]
    assert row["name"] == "Client A"
    assert "image_1920" not in row, "champ binaire exclu du read du comodèle"
    read_kwargs = [kw for m, meth, kw in conn.calls if (m, meth) == ("res.partner", "read")][0]
    assert read_kwargs["fields"] == ["name"], "lecture comodèle restreinte aux champs sûrs"


def test_query_records_redacts_sensitive_values_defense_in_depth():
    """Un champ 'api_key' (variante à underscore) échappe à sanitize_fields mais la
    valeur est redactée par le connecteur — même défense que le read spécialisé."""
    conn = _StubbedOdooConnector()

    async def extra(model, method, args, kwargs=None):
        if (model, method) == ("res.partner", "fields_get") and kwargs.get("attributes") == ["type"]:
            return {"name": {"type": "char"}, "api_key": {"type": "char"}}  # non exclu par sanitize_fields
        if (model, method) == ("res.partner", "search_read"):
            return [{"name": "Client A", "api_key": "SK-LIVE-SECRET"}]
        return await _StubbedOdooConnector._call(conn, model, method, args, kwargs)

    conn._call = extra  # type: ignore[method-assign]
    out = asyncio.run(conn.query_records("res.partner", [], None, limit=5))
    assert out["allowed"] is True
    assert out["records"][0]["name"] == "Client A"
    assert out["records"][0]["api_key"] == "[REDACTED]"
