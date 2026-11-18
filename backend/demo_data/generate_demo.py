"""Générateur de jeux de données de démo (docs/12) — entreprises test, fautes contrôlées, ground truth.

Usage :
    uv run python demo_data/generate_demo.py faulty   # anomalies injectées (seed 9831)
    uv run python demo_data/generate_demo.py clean    # dataset conforme (seed 42)
    uv run python demo_data/generate_demo.py all

Les jeux sont « inédits pour le run » : la ground truth reste cachée à l'agent
(visible_to_agent=false) et sert uniquement à l'évaluation.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "demo"

STATUS = ["draft", "sent", "sale", "done", "cancel"]


def _dates(seed_random: random.Random, n: int):
    base = date(2026, 9, 1)
    return [base + timedelta(days=seed_random.randint(0, 60)) for _ in range(n)]


def generate_orders(path: Path, *, faulty: bool, seed: int, n_orders: int = 40) -> dict:
    rng = random.Random(seed)
    rows = []
    order_ids = [f"SO-{1000 + i}" for i in range(n_orders)]
    dts = _dates(rng, n_orders)
    for i, oid in enumerate(order_ids):
        rows.append({
            "order_id": oid,
            "order_date": dts[i].isoformat(),
            "customer_id": f"CUST-{200 + rng.randint(0, 25)}",
            "product": rng.choice(["P-001", "P-002", "P-003", "P-004", "P-005"]),
            "quantity": rng.randint(1, 20),
            "unit_price": round(rng.uniform(10, 500), 2),
            "currency": rng.choice(["MAD", "EUR"]),
            "status": rng.choice(STATUS),
        })

    injected: list[dict] = []
    if faulty:
        # 1. quantité négative (interdite par le contrat)
        i_neg = rng.randrange(n_orders)
        rows[i_neg]["quantity"] = -3
        injected.append({"case_id": rows[i_neg]["order_id"], "injected_issue": "negative_quantity",
                         "expected_rule": "R8", "row_index": i_neg})
        # 2. doublon d'identifiant métier
        i_dup = rng.randrange(1, n_orders)
        rows[i_dup]["order_id"] = rows[0]["order_id"]
        injected.append({"case_id": rows[0]["order_id"], "injected_issue": "duplicate_order_id",
                         "expected_rule": "R7", "row_index": i_dup})
        # 3. date invalide
        i_date = rng.randrange(n_orders)
        rows[i_date]["order_date"] = "2026-13-45"
        injected.append({"case_id": rows[i_date]["order_id"], "injected_issue": "invalid_date",
                         "expected_rule": "R5", "row_index": i_date})
        # 4. prix unitaire manquant
        i_null = rng.randrange(n_orders)
        rows[i_null]["unit_price"] = None
        injected.append({"case_id": rows[i_null]["order_id"], "injected_issue": "missing_unit_price",
                         "expected_rule": "R4", "row_index": i_null})

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["order_id", "order_date", "customer_id", "product", "quantity", "unit_price", "currency", "status"])
        writer.writeheader()
        writer.writerows(rows)
    return {"file": path.name, "rows": len(rows), "injected_issues": injected}


def generate_invoices(path: Path, *, faulty: bool, seed: int, n: int = 30) -> dict:
    rng = random.Random(seed + 1)
    dts = _dates(rng, n)
    rows, injected = [], []
    order_pool = [f"SO-{1000 + i}" for i in range(40)]
    for i in range(n):
        oid = rng.choice(order_pool)
        qty = rng.randint(1, 15)
        rows.append({
            "invoice_id": f"INV-{3000 + i}",
            "order_id": oid,
            "invoice_date": dts[i].isoformat(),
            "quantity_invoiced": qty,
            "amount": round(qty * rng.uniform(20, 300), 2),
            "currency": rng.choice(["MAD", "EUR"]),
        })
    if faulty:
        # 5. facture détachée : référence commande inexistante
        i_ghost = rng.randrange(n)
        rows[i_ghost]["order_id"] = "SO-9999"
        injected.append({"case_id": rows[i_ghost]["invoice_id"], "injected_issue": "detached_invoice",
                         "expected_evidence_sources": ["invoice", "orders"]})
        # 6. quantité facturée > plausibilité (facturation excessive)
        i_over = rng.randrange(n)
        rows[i_over]["quantity_invoiced"] = 999
        injected.append({"case_id": rows[i_over]["invoice_id"], "injected_issue": "invoice_quantity_mismatch",
                         "expected_category": "suspected_business_inconsistency"})

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["invoice_id", "order_id", "invoice_date", "quantity_invoiced", "amount", "currency"])
        writer.writeheader()
        writer.writerows(rows)
    return {"file": path.name, "rows": len(rows), "injected_issues": injected}


def generate_ground_truth(dir_path: Path, scenario_id: str, seed: int, *datasets: dict) -> None:
    truth = {
        "scenario_id": scenario_id,
        "seed": seed,
        "visible_to_agent": False,
        "datasets": datasets,
        "expected_categories": sorted({i["injected_issue"] for d in datasets for i in d["injected_issues"]}),
    }
    (dir_path / "ground_truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8")


def generate(kind: str = "faulty") -> Path:
    if kind == "faulty":
        seed, scenario = 9831, "demo_faulty"
    elif kind == "clean":
        seed, scenario = 42, "demo_clean"
    else:
        raise ValueError("kind doit valoir 'faulty', 'clean' ou 'all'")

    out = DEMO_DIR / kind
    out.mkdir(parents=True, exist_ok=True)
    ds_orders = generate_orders(out / "orders.csv", faulty=kind == "faulty", seed=seed)
    ds_invoices = generate_invoices(out / "invoices.csv", faulty=kind == "faulty", seed=seed)
    # variantes de format pour tester XLSX/JSON
    _write_json_copy(out / "orders.json", out / "orders.csv")
    generate_ground_truth(out, scenario, seed, ds_orders, ds_invoices)
    return out


def _write_json_copy(dest: Path, src: Path) -> None:
    with open(src, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    dest.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    kinds = sys.argv[1:] or ["all"]
    targets = ["faulty", "clean"] if "all" in kinds else kinds
    for k in targets:
        out = generate(k)
        truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
        print(f"[demo:{k}] {out} — scénarios injectés: {truth['expected_categories']}")
