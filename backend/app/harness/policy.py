"""Policy Gate (docs/05 niveau 2) : schéma, scope, permission, budget avant exécution.

- `read` : lecture seule autorisée si la source est dans le périmètre de mission.
- `approved-tests` : tests potentiellement actifs (API/Web) => approbation humaine explicite
  enregistrée dans `mission.approved_plan`.
- `local` : calcul backend sur des preuves de la mission uniquement (pas d'accès externe).
"""

from __future__ import annotations

from ..core.errors import PolicyViolation
from ..models import AuditMission, PermissionLevel, SourceConnection
from .contracts import ToolSpec


class PolicyGate:
    def check(self, spec: ToolSpec, args: dict, mission: AuditMission, source: SourceConnection | None) -> None:
        """Lève PolicyViolation si l'appel doit être refusé. Journalisation faite par l'exécuteur."""
        source_id = args.get("source_id")

        # 1. Scope : la source doit appartenir à la mission (docs/13 cross-project).
        if source_id is not None and source_id not in mission.source_ids:
            raise PolicyViolation(
                f"source_id={source_id} hors périmètre de la mission {mission.id}"
            )
        if source_id is not None and source is None:
            raise PolicyViolation(f"source inexistante: {source_id}")

        # 2. Cohérence type de source.
        if source is not None and spec.source_types:
            if source.type not in spec.source_types:
                raise PolicyViolation(
                    f"tool {spec.name} incompatible avec la source de type {source.type.value}"
                )

        # 3. Permission.
        if spec.permission == PermissionLevel.approved_tests:
            if not self._is_approved(mission, spec.name, source_id):
                raise PolicyViolation(
                    f"tool {spec.name} requiert l'approbation humaine explicite (approved-tests)"
                )

        # 4. Tools locales : evidence_id doit appartenir à la mission (vérifié au niveau tool
        #    via le repo, mais on refuse déjà une mission sans source/périmètre vide).
        if spec.permission == PermissionLevel.local and not mission.source_ids:
            raise PolicyViolation("mission sans sources : aucune preuve locale à traiter")

    @staticmethod
    def _is_approved(mission: AuditMission, tool: str, source_id: str | None) -> bool:
        plan = mission.approved_plan or {}
        approved = plan.get("approved_actions", [])
        for action in approved:
            if action.get("tool") == tool:
                if source_id is None or action.get("source_id") in (None, source_id):
                    return True
        return False
