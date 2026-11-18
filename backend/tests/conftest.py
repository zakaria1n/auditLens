"""Fixtures de test : app isolée par test (data dir temporaire), client httpx ASGI."""

from __future__ import annotations

import os

import httpx
import pytest

os.environ.setdefault("AUDITLENS_DATA_DIR", "")  # réécrit par la fixture


@pytest.fixture()
async def client(tmp_path):
    os.environ["AUDITLENS_DATA_DIR"] = str(tmp_path)
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


FAULTY_CSV = """order_id,order_date,customer_id,product,quantity,unit_price,currency,status
SO-1000,2026-09-01,CUST-201,P-001,5,120.50,MAD,sale
SO-1001,2026-09-02,CUST-202,P-002,-3,80.00,MAD,done
SO-1002,2026-13-45,CUST-203,P-003,2,45.00,EUR,sent
SO-1001,2026-09-05,CUST-204,P-004,7,,EUR,draft
"""

CLEAN_CSV = """order_id,order_date,customer_id,product,quantity,unit_price,currency,status
SO-2000,2026-09-01,CUST-301,P-001,5,120.50,MAD,sale
SO-2001,2026-09-02,CUST-302,P-002,3,80.00,MAD,done
SO-2002,2026-09-03,CUST-303,P-003,2,45.00,EUR,sent
SO-2003,2026-09-04,CUST-304,P-004,7,15.25,EUR,draft
"""


@pytest.fixture()
def faulty_csv() -> str:
    return FAULTY_CSV


@pytest.fixture()
def clean_csv() -> str:
    return CLEAN_CSV


async def upload_csv(client: httpx.AsyncClient, name: str, content: str, rule_set_id: str = "rs_orders_v1") -> dict:
    resp = await client.post(
        "/api/sources/file",
        params={"name": name, "rule_set_id": rule_set_id},
        files={"file": (name, content.encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def run_mission(client: httpx.AsyncClient, source_id: str, *, scenario: str = "data_audit",
                      control_ids: list[str] | None = None, timeout: float = 15.0) -> dict:
    resp = await client.post("/api/missions", json={
        "title": "Mission test",
        "objective": "Vérifier la conformité du contrat de données commandes.",
        "source_ids": [source_id],
        "control_ids": control_ids or ["DATA-01"],
    })
    assert resp.status_code == 200, resp.text
    mission = resp.json()["mission"]

    resp = await client.post(f"/api/missions/{mission['id']}/run", json={
        "provider": "mock", "scenario": scenario,
    })
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    import asyncio

    async def wait_terminal():
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get(f"/api/runs/{run_id}")
            status = r.json()["run"]["status"]
            if status in ("completed", "review_required", "partial", "failed"):
                return r.json()["run"]
            await asyncio.sleep(0.1)
        raise TimeoutError("run non terminé")

    run = await wait_terminal()
    return {"run": run, "mission": mission, "run_id": run_id}
