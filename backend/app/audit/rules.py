"""Moteur de règles de données déterministes (docs/09, docs/11 DATA-01).

Règles vérifiables : colonnes requises, typage, nullité, unicité de clé métier,
plages et non-négativité. Chaque violation cite la règle ET la ligne concernée.
Le LLM n'invente jamais ces violations : il les reçoit en observations.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field


class Rule(BaseModel):
    id: str
    type: Literal["required_columns", "not_null", "dtype", "unique", "non_negative", "range"]
    column: str | None = None
    columns: list[str] | None = None
    dtype: Literal["datetime", "numeric", "string"] | None = None
    min: float | None = None
    max: float | None = None
    description: str = ""


class RuleSet(BaseModel):
    id: str
    name: str
    description: str
    contract_note: str = ""  # signification métier de la clé (docs/09 — mapping contrôlé)
    rules: list[Rule] = Field(default_factory=list)


class RuleViolation(BaseModel):
    rule_id: str
    rule_type: str
    column: str | None
    row_index: int | None
    value: str | None = None
    message: str


class RuleSetResult(BaseModel):
    rule_set_id: str
    rows: int
    violations: list[RuleViolation] = Field(default_factory=list)
    rules_evaluated: int
    rules_failed: list[str] = Field(default_factory=list)
    valid: bool

    @property
    def violation_count(self) -> int:
        return len(self.violations)


# ---------- Rule sets intégrés (démo + réutilisables) ----------

ORDERS_RULESET = RuleSet(
    id="rs_orders_v1",
    name="Contrat de données — Commandes",
    description="Colonnes requises, typage, unicité de order_id, quantités/prix non négatifs.",
    contract_note="order_id est l'identifiant métier de la commande ; plusieurs lignes par commande doivent être explicitement autorisées par le contrat (ici : 1 ligne = 1 commande).",
    rules=[
        Rule(id="R1", type="required_columns", columns=["order_id", "order_date", "quantity", "unit_price", "currency"], description="colonnes du contrat présentes"),
        Rule(id="R2", type="not_null", column="order_id", description="order_id renseigné"),
        Rule(id="R3", type="not_null", column="quantity", description="quantity renseignée"),
        Rule(id="R4", type="not_null", column="unit_price", description="unit_price renseigné"),
        Rule(id="R5", type="dtype", column="order_date", dtype="datetime", description="order_date typée date"),
        Rule(id="R6", type="dtype", column="quantity", dtype="numeric", description="quantity numérique"),
        Rule(id="R7", type="unique", column="order_id", description="unicité de order_id (clé métier identifiée)"),
        Rule(id="R8", type="non_negative", column="quantity", description="quantity >= 0"),
        Rule(id="R9", type="non_negative", column="unit_price", description="unit_price >= 0"),
    ],
)

INVOICES_RULESET = RuleSet(
    id="rs_invoices_v1",
    name="Contrat de données — Factures",
    description="Colonnes requises, typage, unicité de invoice_id, référence commande renseignée.",
    contract_note="invoice_id est l'identifiant métier de la facture ; order_id relie la facture à sa commande.",
    rules=[
        Rule(id="R1", type="required_columns", columns=["invoice_id", "order_id", "invoice_date", "quantity_invoiced", "amount"], description="colonnes du contrat présentes"),
        Rule(id="R2", type="not_null", column="invoice_id", description="invoice_id renseigné"),
        Rule(id="R3", type="not_null", column="order_id", description="order_id renseigné"),
        Rule(id="R4", type="dtype", column="invoice_date", dtype="datetime", description="invoice_date typée date"),
        Rule(id="R5", type="dtype", column="quantity_invoiced", dtype="numeric", description="quantity_invoiced numérique"),
        Rule(id="R6", type="unique", column="invoice_id", description="unicité de invoice_id"),
        Rule(id="R7", type="non_negative", column="quantity_invoiced", description="quantity_invoiced >= 0"),
    ],
)

RULE_SETS: dict[str, RuleSet] = {rs.id: rs for rs in [ORDERS_RULESET, INVOICES_RULESET]}


def get_rule_set(rule_set_id: str) -> RuleSet | None:
    return RULE_SETS.get(rule_set_id)


# ---------- Évaluation déterministe ----------

def _to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def evaluate_rule_set(df: pd.DataFrame, ruleset: RuleSet, max_violations: int = 200) -> RuleSetResult:
    violations: list[RuleViolation] = []
    rules_failed: list[str] = []

    def add(rule: Rule, column: str | None, row_index: int | None, value: Any, message: str) -> None:
        if len(violations) < max_violations:
            violations.append(RuleViolation(
                rule_id=rule.id, rule_type=rule.type, column=column, row_index=row_index,
                value=None if value is None or (isinstance(value, float) and pd.isna(value)) else str(value),
                message=message,
            ))

    for rule in ruleset.rules:
        rule_failed = False
        if rule.type == "required_columns":
            missing = [c for c in (rule.columns or []) if c not in df.columns]
            if missing:
                rule_failed = True
                add(rule, None, None, None, f"colonnes manquantes: {missing}")

        elif rule.type == "not_null":
            col = rule.column
            if col not in df.columns:
                rule_failed = True
                add(rule, col, None, None, f"colonne absente: {col}")
            else:
                for idx in df.index[df[col].isna()]:
                    rule_failed = True
                    add(rule, col, int(idx), None, f"valeur nulle dans {col}")

        elif rule.type == "dtype":
            col = rule.column
            if col not in df.columns:
                rule_failed = True
                add(rule, col, None, None, f"colonne absente: {col}")
            elif rule.dtype == "datetime":
                parsed = _to_datetime(df[col])
                bad = df.index[parsed.isna() & df[col].notna()]
                for idx in bad:
                    rule_failed = True
                    add(rule, col, int(idx), df.at[idx, col], f"date invalide: {df.at[idx, col]!r}")
            elif rule.dtype == "numeric":
                numeric = pd.to_numeric(df[col], errors="coerce")
                bad = df.index[numeric.isna() & df[col].notna()]
                for idx in bad:
                    rule_failed = True
                    add(rule, col, int(idx), df.at[idx, col], f"valeur non numérique: {df.at[idx, col]!r}")

        elif rule.type == "unique":
            col = rule.column
            if col not in df.columns:
                rule_failed = True
                add(rule, col, None, None, f"colonne absente: {col}")
            else:
                dup_mask = df[col].duplicated(keep=False) & df[col].notna()
                seen: dict[Any, int] = {}
                for idx in df.index[dup_mask]:
                    value = df.at[idx, col]
                    seen[value] = seen.get(value, 0) + 1
                for idx in df.index[dup_mask]:
                    value = df.at[idx, col]
                    rule_failed = True
                    add(rule, col, int(idx), value, f"valeur dupliquée {value!r} ({seen[value]} occurrences)")

        elif rule.type == "non_negative":
            col = rule.column
            if col not in df.columns:
                rule_failed = True
                add(rule, col, None, None, f"colonne absente: {col}")
            else:
                numeric = pd.to_numeric(df[col], errors="coerce")
                for idx in df.index[numeric < 0]:
                    rule_failed = True
                    add(rule, col, int(idx), df.at[idx, col], f"valeur négative {df.at[idx, col]!r}")

        elif rule.type == "range":
            col = rule.column
            if col not in df.columns:
                rule_failed = True
                add(rule, col, None, None, f"colonne absente: {col}")
            else:
                numeric = pd.to_numeric(df[col], errors="coerce")
                for idx in df.index:
                    v = numeric.at[idx]
                    if pd.isna(v):
                        continue
                    lo, hi = rule.min, rule.max
                    if (lo is not None and v < lo) or (hi is not None and v > hi):
                        rule_failed = True
                        add(rule, col, int(idx), df.at[idx, col], f"valeur hors plage [{lo}, {hi}]: {df.at[idx, col]!r}")

        if rule_failed:
            rules_failed.append(rule.id)

    return RuleSetResult(
        rule_set_id=ruleset.id,
        rows=int(len(df)),
        violations=violations,
        rules_evaluated=len(ruleset.rules),
        rules_failed=rules_failed,
        valid=len(violations) == 0,
    )


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Profiling statistique (docs/05 data_profile) — agrégats, jamais un dump de lignes."""
    profile: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": len(df.columns),
        "column_profiles": [],
    }
    for col in df.columns:
        s = df[col]
        entry: dict[str, Any] = {
            "name": str(col),
            "dtype": str(s.dtype),
            "nulls": int(s.isna().sum()),
            "unique": int(s.nunique(dropna=True)),
        }
        numeric = pd.to_numeric(s, errors="coerce")
        if numeric.notna().sum() > 0 and (pd.api.types.is_numeric_dtype(s) or numeric.notna().mean() > 0.9):
            entry["numeric_stats"] = {
                "min": float(numeric.min()),
                "max": float(numeric.max()),
                "mean": round(float(numeric.mean()), 4) if numeric.notna().sum() else None,
                "negatives": int((numeric < 0).sum()),
            }
        else:
            vc = s.dropna().astype(str).value_counts().head(8)
            entry["top_values"] = {k: int(v) for k, v in vc.items()}
        profile["column_profiles"].append(entry)
    return profile
