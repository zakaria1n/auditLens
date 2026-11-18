"""Provider OpenCode CLI (ADR-19) : transport LLM via `opencode run`.

Les modèles `-free` d'OpenCode Zen refusent les appels REST directs depuis notre backend
(429 FreeUsageLimitError anonyme / 401 clé expirée) alors que l'app et le CLI OpenCode
fonctionnent avec la session de l'utilisateur. Ce provider utilise ce transport éprouvé :
sous-processus `opencode run -m <modèle>` dans un bac à sable isolé (aucun outil de l'agent
OpenCode ne peut toucher au dépôt AuditLens).

Contrat tool-calls : les outils AuditLens sont décrits DANS le prompt et la réponse
attendue est un JSON strict {"tool": ..., "arguments": {...}} (ou {"content": ...}) —
analysé en ProviderToolCall. Limites assumées : ~5-15 s par appel (démarrage CLI),
pas de usage tokens exposé (None, jamais inventé).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ...core.errors import ProviderError
from .base import LLMProvider, LLMResponse, ProviderToolCall

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _clean_output(raw: str) -> str:
    text = ANSI_RE.sub("", raw)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # retire l'en-tête du CLI (« > build · modèle … ») et les lignes de statut
    keep = [ln for ln in lines if not ln.strip().startswith(">")]
    return "\n".join(keep).strip()


def _extract_first_json(text: str) -> dict[str, Any] | None:
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = text.find("{", idx + 1)
    return None


class OpenCodeCliProvider(LLMProvider):
    provider_id = "opencode-cli"

    def __init__(self, model: str = "deepseek-v4.1-flash-free", timeout_s: int = 150):
        self._argv_prefix = self._resolve_executable()
        if self._argv_prefix is None:
            raise ProviderError(
                "provider 'opencode-cli' : exécutable 'opencode' introuvable sur le PATH — "
                "installez OpenCode CLI (https://opencode.ai) ou choisissez un autre provider."
            )
        self.model_id = model or "deepseek-v4.1-flash-free"
        self._timeout_s = timeout_s
        # bac à sable vide : l'agent OpenCode ne doit jamais lire/écrire dans AuditLens
        self._sandbox = Path(tempfile.mkdtemp(prefix="auditlens_opencode_"))

    @staticmethod
    def _resolve_executable() -> list[str] | None:
        """Windows : `opencode` peut être un .exe, un .cmd (shim npm) ou un script sh —
        seul un exécutable réel passe CreateProcess ; les .cmd passent par cmd /c."""
        exe = shutil.which("opencode.exe")
        if exe:
            return [exe]
        cmd = shutil.which("opencode.cmd")
        if cmd:
            return ["cmd.exe", "/c", cmd]
        plain = shutil.which("opencode")
        if plain and Path(plain).suffix.lower() in (".exe", ".cmd", ".bat"):
            if plain.lower().endswith((".cmd", ".bat")):
                return ["cmd.exe", "/c", plain]
            return [plain]
        # shim sh sans extension (Git Bash) : chercher un .cmd/.exe voisin
        if plain:
            base = Path(plain).with_name("opencode.cmd")
            if base.exists():
                return ["cmd.exe", "/c", str(base)]
        return None

    def _build_prompt(self, system: str, messages: list[dict], tools: list[dict] | None) -> str:
        parts = [f"[CONSIGNES SYSTÈME]\n{system}\n", "[CONVERSATION]\n"]
        for m in messages:
            role = m.get("role")
            if role == "user":
                parts.append(f"Utilisateur: {m.get('content', '')}")
            elif role == "assistant":
                calls = m.get("tool_calls") or []
                if calls:
                    parts.append(f"Assistant (appel d'outil): {json.dumps(calls, ensure_ascii=False)}")
                elif m.get("content"):
                    parts.append(f"Assistant: {m['content']}")
            elif role == "tool":
                parts.append(f"Résultat d'outil ({m.get('name', '')}): {m.get('content', '')}")
        if tools:
            catalog = [
                {"tool": t["name"], "description": t["description"], "parameters": t["parameters"]}
                for t in tools
            ]
            parts.append(
                "[OUTILS DISPONIBLES]\n"
                + json.dumps(catalog, ensure_ascii=False)
                + "\n\n[FORMAT DE RÉPONSE OBLIGATOIRE]\n"
                "Réponds UNIQUEMENT par un objet JSON, sans texte autour :\n"
                '- pour utiliser un outil : {"tool": "<nom>", "arguments": {...}}\n'
                '- pour répondre à l\'utilisateur : {"content": "<texte>"}'
            )
        return "\n".join(parts)

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        prompt = self._build_prompt(system, messages, tools)
        # le prompt passe par STDIN : cmd.exe corrompt les arguments multi-lignes
        proc = await asyncio.create_subprocess_exec(
            *self._argv_prefix, "run", "-m", f"opencode/{self.model_id}",
            cwd=str(self._sandbox),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise ProviderError(
                f"opencode-cli/{self.model_id}: délai dépassé ({self._timeout_s}s) — "
                "augmentez max_seconds de la mission ou choisissez un modèle plus rapide."
            ) from None
        if proc.returncode != 0:
            err = stderr.decode("utf-8", "replace")[-400:]
            raise ProviderError(f"opencode-cli/{self.model_id}: exit {proc.returncode} — {err}")
        text = _clean_output(stdout.decode("utf-8", "replace"))
        if not text:
            raise ProviderError(f"opencode-cli/{self.model_id}: réponse vide du CLI")

        total_chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        if tools:
            obj = _extract_first_json(text)
            if obj is not None and obj.get("tool"):
                call = ProviderToolCall(id="cli_call_1", name=str(obj["tool"]), arguments=obj.get("arguments") or {})
                return LLMResponse(content=None, tool_calls=[call], input_chars=total_chars, usage=None)
            if obj is not None and "content" in obj:
                return LLMResponse(content=str(obj["content"]), input_chars=total_chars, usage=None)
            # pas de JSON exploitable : texte brut → contenu (l'appelant décide)
            return LLMResponse(content=text, input_chars=total_chars, usage=None)
        return LLMResponse(content=text, input_chars=total_chars, usage=None)

    async def close(self) -> None:
        shutil.rmtree(self._sandbox, ignore_errors=True)
