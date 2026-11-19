"""Connecteur Odoo Local — lecture seule via XML-RPC (docs/07).

- API historique /xmlrpc/2 disponible sur toutes les versions ; JSON-2 sera un adapter V2.
- Compte technique READ-ONLY uniquement ; aucune méthode write/create/unlink exposée.
- discover() interroge modules installés + fields_get avant toute collecte (docs/07).
"""

from __future__ import annotations

import asyncio
import xmlrpc.client
from typing import Any

from ...core.redact import redact

# Modèles métier interrogés (docs/07 — capabilities minimales)
AUDIT_MODELS = {
    "sale.order": {"date_field": "date_order", "label": "Commandes de vente"},
    "account.move": {"date_field": "invoice_date", "label": "Factures"},
    "stock.picking": {"date_field": "scheduled_date", "label": "Livraisons"},
    "stock.move": {"date_field": "date", "label": "Mouvements de stock"},
    "purchase.order": {"date_field": "date_order", "label": "Achats"},
}

# Champs collectés : minimisation (pas d'emails, pas d'écritures détaillées — docs/07)
FIELD_SETS = {
    "sale.order": ["name", "partner_id", "date_order", "state", "amount_total", "amount_untaxed", "currency_id"],
    "account.move": ["name", "move_type", "partner_id", "invoice_date", "state", "amount_total", "amount_residual", "currency_id", "ref"],
    "stock.picking": ["name", "origin", "partner_id", "scheduled_date", "state", "picking_type_id"],
    "stock.move": ["reference", "product_id", "product_uom_qty", "quantity", "state", "date", "picking_id"],
    "purchase.order": ["name", "partner_id", "date_order", "state", "amount_total", "currency_id"],
}

# Lignes : indispensables pour réconcilier quantités commandées / livrées / facturées (docs/11 ERP-01/02)
LINE_SETS = {
    "sale.order": (
        "sale.order.line",
        ["order_id", "product_id", "product_uom_qty", "qty_delivered", "qty_invoiced", "price_unit", "display_type"],
    ),
    "account.move": (
        "account.move.line",
        ["move_id", "product_id", "quantity", "price_unit", "price_subtotal", "display_type"],
    ),
    "purchase.order": (
        "purchase.order.line",
        ["order_id", "product_id", "product_uom_qty", "qty_received", "price_unit"],
    ),
}

MAX_LIMIT = 500


class OdooConnector:
    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]):
        self.url = str(config.get("url", "")).rstrip("/")
        self.db = str(config.get("db", ""))
        self.username = str(config.get("username", ""))
        self.password = str(secrets.get("password", "") or secrets.get("api_key", ""))
        self.uid: int | None = None
        self._timeout = float(config.get("timeout_s", 15))
        allowed = config.get("allow_private_host", True)  # Odoo local : explicitement autorisé (docs/05)
        self.allow_private = bool(allowed)

    # ---------- transport XML-RPC (sync, exécuté en thread) ----------
    def _proxy(self, endpoint: str) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/{endpoint}", allow_none=True)

    def _auth_sync(self) -> int:
        common = self._proxy("common")
        uid = common.version() and common.authenticate(self.db, self.username, self.password, {})
        if not uid:
            raise PermissionError("authentification Odoo refusée (compte read-only requis)")
        return int(uid)

    def _call_sync(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        models = self._proxy("object")
        return models.execute_kw(self.db, self.uid, self.password, model, method, args, kwargs or {})

    async def _call(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        if self.uid is None:
            self.uid = await asyncio.to_thread(self._auth_sync)
        return await asyncio.to_thread(self._call_sync, model, method, args, kwargs)

    # ---------- contrat connecteur ----------
    async def test_connection(self) -> tuple[bool, str]:
        try:
            info = await asyncio.to_thread(lambda: self._proxy("common").version())
            version = info.get("server_version", "?")
            self.uid = await asyncio.to_thread(self._auth_sync)
            return True, f"connecté — Odoo {version} (compte {self.username})"
        except Exception as exc:  # noqa: BLE001
            return False, f"connection_failed: {type(exc).__name__}: {exc}"

    async def discover(self) -> dict[str, Any]:
        """Modules installés + champs disponibles des modèles d'audit (docs/07)."""
        caps: dict[str, Any] = {"connector": "odoo", "models": {}}
        try:
            installed = await self._call(
                "ir.module.module", "search_read",
                [[["state", "=", "installed"]]], {"fields": ["name"], "limit": 200},
            )
            caps["installed_modules"] = sorted({m["name"] for m in installed})
            for model, meta in AUDIT_MODELS.items():
                try:
                    fields = await self._call(model, "fields_get", [], {"attributes": ["string", "type"]})
                    available = [f for f in FIELD_SETS[model] if f in fields]
                    count = await self._call(model, "search_count", [[]])
                    caps["models"][model] = {
                        "label": meta["label"], "available": True,
                        "fields_available": available,
                        "missing_fields": [f for f in FIELD_SETS[model] if f not in fields],
                        "record_count": count,
                    }
                except Exception as exc:  # modèle absent (module non installé)
                    caps["models"][model] = {"available": False, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001
            caps["discover_error"] = f"{type(exc).__name__}: {exc}"
        return caps

    # ---------- lectures ciblées ----------
    async def read(self, model: str, date_range: dict | None, limit: int) -> dict[str, Any]:
        if model not in FIELD_SETS:
            raise ValueError(f"modèle non autorisé pour l'audit: {model}")
        limit = min(max(1, int(limit or 100)), MAX_LIMIT)
        domain: list = []
        date_field = AUDIT_MODELS[model]["date_field"]
        if date_range and date_range.get("from"):
            domain.append([date_field, ">=", date_range["from"]])
        if date_range and date_range.get("to"):
            domain.append([date_field, "<=", date_range["to"]])
        records = await self._call(
            model, "search_read",
            [domain], {"fields": FIELD_SETS[model], "limit": limit, "order": f"{date_field} desc"},
        )

        # Lignes associées (réconciliation quantités) + pickings + quants pour le stock.
        lines: list = []
        pickings: list = []
        quants: list = []
        ids = [r["id"] for r in records][:200]
        if ids and model in LINE_SETS:
            line_model, line_fields = LINE_SETS[model]
            parent_field = "order_id" if model != "account.move" else "move_id"
            try:
                lines = await self._call(
                    line_model, "search_read",
                    [[[parent_field, "in", ids]]], {"fields": line_fields, "limit": MAX_LIMIT},
                )
            except Exception:
                lines = []  # modèle de ligne absent (module sans lignes) : collecte d'en-tête seule
        if model == "stock.move" and records:
            picking_ids = sorted({r["picking_id"][0] for r in records if r.get("picking_id")})[:100]
            if picking_ids:
                try:
                    pickings = await self._call(
                        "stock.picking", "search_read",
                        [[["id", "in", picking_ids]]],
                        {"fields": ["name", "origin", "state", "scheduled_date"], "limit": 100},
                    )
                except Exception:
                    pickings = []
            # Quantités on-hand (stock.quant) : évidence pour les règles de stock négatif.
            try:
                quants = await self._call(
                    "stock.quant", "search_read",
                    [[["quantity", "!=", 0]]],
                    {"fields": ["product_id", "location_id", "quantity", "reserved_quantity"], "limit": 200},
                )
            except Exception:
                quants = []  # accès refusé ou modèle absent : limitation notée côté réconciliation

        return {
            "model": model,
            "date_field": date_field,
            "date_range": date_range or {},
            "records": [redact(r) for r in records],
            "lines": [redact(l) for l in lines],
            "pickings": [redact(p) for p in pickings],
            "quants": [redact(q) for q in quants],
            "record_count": len(records),
            "limit": limit,
            "warnings": (
                [f"limit_reached:{limit}"] if len(records) == limit else []
            ),
        }

    # ---------- accès générique READ-ONLY (Phase 2B/4) ----------

    async def list_accessible_models(self, limit: int = 500) -> list[dict[str, Any]]:
        """Modèles non-transitoires accessibles au compte d'audit (ir.model), hors
        namespaces techniques/sensibles. Probe search_count => readable."""
        from .generic import model_is_allowed

        rows = await self._call(
            "ir.model", "search_read",
            [[["transient", "=", False]]],
            {"fields": ["model", "name"], "limit": min(limit, 1000)},
        )
        out: list[dict[str, Any]] = []
        for row in rows[:limit]:
            model = str(row.get("model") or "")
            if not model_is_allowed(model):
                continue
            try:
                count = await self._call(model, "search_count", [[]])
            except Exception as exc:  # accès refusé => non lisible, explicitement
                out.append({"model": model, "name": str(row.get("name") or ""),
                            "readable": False, "reason": str(exc)[:120]})
                continue
            out.append({"model": model, "name": str(row.get("name") or ""),
                        "readable": True, "record_count": count})
        return out

    async def describe_model(self, model: str) -> dict[str, Any]:
        """Métadonnées d'un modèle : champs sûrs, types, relations, count, accès."""
        from .generic import model_is_allowed, relations_from_fields, sanitize_fields

        if not model_is_allowed(model):
            return {"model": model, "allowed": False,
                    "reason": "modèle technique/sensible interdit à la lecture générique"}
        count = await self._call(model, "search_count", [[]])
        fields_meta = await self._call(model, "fields_get", [], {
            "attributes": ["string", "type", "relation", "required", "store"],
        })
        safe = sanitize_fields(fields_meta)
        return {
            "model": model, "allowed": True, "record_count": count,
            "fields": [
                {"name": name, "string": str(meta.get("string") or name),
                 "type": str(meta.get("type")), "relation": meta.get("relation"),
                 "required": bool(meta.get("required"))}
                for name, meta in sorted(safe.items())
            ],
            "relations": relations_from_fields(safe),
            "excluded_sensitive_fields": sorted(set(fields_meta) - set(safe)),
        }

    async def query_records(self, model: str, domain: list, fields: list[str] | None,
                            limit: int = 50, order: str | None = None) -> dict[str, Any]:
        """search_read borné : champs sûrs uniquement, limite <= 200."""
        from .generic import model_is_allowed, sanitize_fields

        if not model_is_allowed(model):
            return {"allowed": False, "error": f"modèle interdit : {model}"}
        fields_meta = await self._call(model, "fields_get", [], {"attributes": ["type"]})
        safe = sanitize_fields(fields_meta)
        if fields:
            unknown = [f for f in fields if f not in safe]
            if unknown:
                return {"allowed": True, "error": f"champs inconnus/refusés : {unknown}",
                        "available_fields": sorted(safe.keys())[:100]}
            read_fields = fields
        else:
            read_fields = sorted(safe.keys())[:60]
        limit = max(1, min(int(limit), MAX_LIMIT))
        kwargs: dict[str, Any] = {"limit": limit}
        if order:
            kwargs["order"] = str(order)[:120]
        rows = await self._call(model, "search_read", [domain], {"fields": read_fields, **kwargs})
        return {"allowed": True, "model": model, "count": len(rows), "records": rows}

    async def follow_relation(self, model: str, record_id: int, relation_field: str,
                              limit: int = 50) -> dict[str, Any]:
        """Suit une relation depuis un enregistrement : many2one => cible ;
        one2many/many2many => liés (lecture bornée du comodel)."""
        from .generic import MAX_RELATION_RECORDS, model_is_allowed, sanitize_fields

        if not model_is_allowed(model):
            return {"allowed": False, "error": f"modèle source interdit : {model}"}
        fields_meta = await self._call(model, "fields_get", [], {
            "attributes": ["type", "relation"],
        })
        meta = fields_meta.get(relation_field)
        if meta is None:
            relations = [
                f for f, fm in sanitize_fields(fields_meta).items()
                if fm.get("type") in ("many2one", "one2many", "many2many")
            ]
            return {"allowed": True, "error": f"champ de relation inconnu : {relation_field}",
                    "available_relations": relations}
        ftype = str(meta.get("type"))
        comodel = str(meta.get("relation") or "")
        if not model_is_allowed(comodel):
            return {"allowed": True, "error": f"comodèle interdit : {comodel}"}
        rec = await self._call(model, "read", [[int(record_id)]], {"fields": [relation_field]})
        if not rec:
            return {"allowed": True, "error": f"enregistrement {record_id} introuvable dans {model}"}
        limit = max(1, min(int(limit), MAX_RELATION_RECORDS))
        if ftype == "many2one":
            target = rec[0].get(relation_field) or [None]
            target_id = target[0] if isinstance(target, list) else target
            if not target_id:
                return {"allowed": True, "relation_type": ftype, "comodel": comodel, "records": []}
            rows = await self._call(comodel, "read", [[int(target_id)]])
            return {"allowed": True, "relation_type": ftype, "comodel": comodel, "records": rows}
        linked_ids = rec[0].get(relation_field) or []
        ids = [int(i) for i in linked_ids][:limit]
        if not ids:
            return {"allowed": True, "relation_type": ftype, "comodel": comodel, "records": []}
        rows = await self._call(comodel, "read", [ids[:limit]])
        return {"allowed": True, "relation_type": ftype, "comodel": comodel, "records": rows,
                "total_linked": len(linked_ids)}

    async def aggregate_records(self, model: str, group_by: str, domain: list,
                                aggregate_field: str | None = None,
                                aggregate_op: str = "count", limit: int = 20) -> dict[str, Any]:
        """read_group borné (ou repli déterministe par search_read borné)."""
        from .generic import MAX_RELATION_RECORDS, model_is_allowed, sanitize_fields

        if not model_is_allowed(model):
            return {"allowed": False, "error": f"modèle interdit : {model}"}
        fields_meta = await self._call(model, "fields_get", [], {"attributes": ["type"]})
        safe = sanitize_fields(fields_meta)
        if group_by not in safe:
            return {"allowed": True, "error": f"champ de groupement inconnu : {group_by}",
                    "available_fields": sorted(safe.keys())[:100]}
        if aggregate_field and aggregate_field not in safe:
            return {"allowed": True, "error": f"champ d'agrégat inconnu : {aggregate_field}"}
        limit = max(1, min(int(limit), MAX_RELATION_RECORDS))
        spec = [group_by]
        if aggregate_field:
            spec.append(aggregate_field)
        try:
            rows = await self._call(model, "read_group", [domain, spec, [group_by]],
                                    {"limit": limit, "orderby": group_by + " count desc"})
            return {"allowed": True, "model": model, "group_by": group_by,
                    "aggregate_field": aggregate_field, "groups": rows}
        except Exception:  # read_group indisponible => repli déterministe borné
            read_fields = [group_by] + ([aggregate_field] if aggregate_field else [])
            rows = await self._call(model, "search_read", [domain],
                                    {"fields": read_fields, "limit": MAX_RELATION_RECORDS})
            buckets: dict[str, int] = {}
            sums: dict[str, float] = {}
            for r in rows:
                key = str(r.get(group_by))
                buckets[key] = buckets.get(key, 0) + 1
                if aggregate_field and isinstance(r.get(aggregate_field), (int, float)):
                    sums[key] = sums.get(key, 0) + float(r[aggregate_field])
            groups = [{"group": k, "count": c, **({"sum": sums[k]} if aggregate_field else {})}
                      for k, c in sorted(buckets.items(), key=lambda kv: -kv[1])[:limit]]
            return {"allowed": True, "model": model, "group_by": group_by,
                    "fallback": "search_read", "groups": groups}


    async def close(self) -> None:
        self.uid = None
