"""Phase 7/10 — privacy-aware AI context : sanitization PII + preview d'exposition.

- masquage email/téléphone/IBAN/identifiants dans le CONTEXTE (jamais dans les preuves) ;
- classify_exposure : catégories + compteurs sans jamais renvoyer les valeurs ;
- faux positifs téléphone (dates, ids courts) écartés.
"""

from __future__ import annotations

from app.privacy import classify_exposure, sanitize_context


def test_email_masked_with_prefix_kept():
    out, counts = sanitize_context({"contact": "jean.dupont@corp.fr"})
    assert counts.get("email") == 1
    assert "@corp.fr" not in str(out["contact"])  # domaine masqué
    assert "jean" in out["contact"]  # préfixe court conservé pour l'auditabilité


def test_iban_masked():
    out, counts = sanitize_context({"note": "virement vers FR7630006000011234567890189 ok"})
    assert counts.get("iban") == 1
    assert "3000600000111234567890" not in out["note"]


def test_short_numbers_not_flagged_as_phone():
    out, counts = sanitize_context({"ref": "commande 2026-01-01 #42"})
    assert counts.get("phone", 0) == 0


def test_original_untouched():
    original = {"email": "a@b.co"}
    out, _ = sanitize_context(original)
    assert original["email"] == "a@b.co"  # la source n'est jamais modifiée


def test_classify_exposure_never_returns_values():
    data = {"email": "secret.person@bigcorp.com", "phone": "+33 6 12 34 56 78"}
    preview = classify_exposure(data)
    text = str(preview)
    assert "secret.person" not in text and "+33 6 12" not in text
    cats = {c["category"] for c in preview["categories"]}
    assert "email" in cats and "phone" in cats
    assert preview["total_redactions"] >= 2
