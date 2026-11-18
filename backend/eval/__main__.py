"""CLI d'évaluation : uv run python -m eval --cases files_dev,files_eval --provider glm

Provider (défaut mock) : --provider mock | glm | compatible
  - mock   : déterministe, gratuit, CI-sûr
  - glm    : GLM-5.3-Flash via Z.AI Coding Plan (clé lue dans auth.json OpenCode si présente)

Systèmes comparés : baseline_a (déterministe pur), system_b (pipeline historique,
boucle désactivée), system_c (boucle agentique ADR-14). --trials N répète les
exécutions LLM pour mesurer la variance (docs/17).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .runner import run_all, write_report

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "eval"


def _provider_cfg(provider: str) -> dict:
    if provider == "mock":
        return {"provider": "mock"}
    if provider in ("glm", "compatible"):
        key = None
        try:
            auth = json.load(open(r"C:\Users\mk_de\.local\share\opencode\auth.json", encoding="utf-8"))
            key = auth.get("zai-coding-plan", {}).get("key")
        except Exception:
            pass
        if not key:
            print("clé zai introuvable — fallback mock", file=sys.stderr)
            return {"provider": "mock"}
        return {"provider": "compatible", "model": "glm-5.3-flash",
                "base_url": "https://api.z.ai/api/coding/paas/v4", "api_key": key,
                "disable_thinking": True}
    return {"provider": provider}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="files_dev,files_eval")
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--systems", default="baseline_a,system_b,system_c",
                        help="baseline_a,system_b,system_c")
    args = parser.parse_args()

    case_ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    systems = tuple(s.strip() for s in args.systems.split(",") if s.strip())
    results = asyncio.run(run_all(case_ids, _provider_cfg(args.provider),
                                  trials=args.trials, systems=systems))
    report = write_report(results, DATA_DIR)
    print(report.read_text(encoding="utf-8"))
    print(f"[eval] rapport + métriques écrits dans {DATA_DIR}")


if __name__ == "__main__":
    main()
