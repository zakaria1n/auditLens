import json

import pytest

from app.agent.presentation_repair import repair_presentation
from app.agent.providers.base import LLMResponse


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def chat(self, system, messages, tools=None):
        self.calls += 1
        assert tools is None
        return LLMResponse(content=self.result)


def spec():
    return {'version': 2, 'type': 'composition', 'mode': 'conceptual',
            'children': [{'type': 'heading', 'content': 'Architecture'}]}


async def test_repair_one_tool_free_call_preserves_data():
    corrected = {**spec(), 'children': [{'type': 'heading', 'text': 'Architecture'}]}
    provider = Provider(json.dumps(corrected))
    assert await repair_presentation(provider, spec(), {'path': '$.children[0].text'}) == corrected
    assert provider.calls == 1


@pytest.mark.parametrize('output', [
    'not json',
    json.dumps({'version': 2, 'type': 'composition', 'mode': 'conceptual', 'children': [{'type': 'heading', 'text': 'Invented'}]}),
    json.dumps({'version': 2, 'type': 'composition', 'mode': 'conceptual', 'children': [{'type': 'heading', 'text': 'Architecture', 'evidence_refs': ['ev_12345678']}]}),
])
async def test_repair_rejects_invalid_json_changed_values_and_evidence(output):
    provider = Provider(output)
    with pytest.raises(ValueError):
        await repair_presentation(provider, spec(), {})
    assert provider.calls == 1


async def test_repair_refuses_unverified_evidence_before_provider_call():
    provider = Provider('{}')
    raw = {**spec(), 'evidence_refs': ['ev_12345678']}
    with pytest.raises(ValueError):
        await repair_presentation(provider, raw, {})
    assert provider.calls == 0


async def test_repair_never_sends_sensitive_content_to_provider():
    provider = Provider('{}')
    raw = {**spec(), 'children': [{'type': 'paragraph', 'text': 'alice@example.com'}]}
    with pytest.raises(ValueError):
        await repair_presentation(provider, raw, {})
    assert provider.calls == 0


async def test_repair_refuses_rearranged_values():
    raw = {'version': 2, 'type': 'composition', 'mode': 'conceptual', 'children': [
        {'type': 'paragraph', 'text': 'A'}, {'type': 'paragraph', 'text': 'B'}]}
    altered = {**raw, 'children': list(reversed(raw['children']))}
    provider = Provider(json.dumps(altered))
    with pytest.raises(ValueError):
        await repair_presentation(provider, raw, {})


async def test_repair_route_checks_conversation_and_never_echoes_provider_errors(client, monkeypatch):
    import app.agent.providers as providers
    from .test_conversations import create_thread

    class BrokenProvider(Provider):
        async def chat(self, system, messages, tools=None):
            raise RuntimeError('secret private provider response')
        async def close(self):
            pass

    monkeypatch.setattr(providers, 'build_provider', lambda *args, **kwargs: BrokenProvider(''))
    payload = {'specification': spec(), 'issue': {}}
    assert (await client.post('/api/conversations/unknown/repair-presentation', json=payload)).status_code == 404
    thread = await create_thread(client)
    response = await client.post(f"/api/conversations/{thread['id']}/repair-presentation", json=payload)
    assert response.status_code == 422 and 'secret' not in response.text
    again = await client.post(f"/api/conversations/{thread['id']}/repair-presentation", json=payload)
    assert again.status_code == 409
