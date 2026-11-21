from types import SimpleNamespace

from app.agent.orchestrator import _sanitize_evidence_summaries


def test_trusted_evidence_references_survive_pii_masking_without_leaking_content():
    evidence = SimpleNamespace(id='ev_12345678', source_id='src_12345678', type='profile',
                               title='Contact alice@example.com', observed_at='2026-01-01',
                               summary={'phone': '0612345678'})
    cleaned, counts, exposure = _sanitize_evidence_summaries([evidence])
    assert cleaned[0]['id'] == 'ev_12345678'
    assert cleaned[0]['source_id'] == 'src_12345678'
    assert 'alice@example.com' not in str(cleaned)
    assert '0612345678' not in str(cleaned)
    assert counts and exposure['total_redactions'] > 0
