from app.agent.chat import CHAT_SYSTEM
from app.agent.providers.base import LLMResponse
from app.agent.chat_context import sanitize_chat_context
import json
from .test_conversations import create_thread, stream_turn
from .conftest import upload_csv, FAULTY_CSV


def test_presentation_prompt_allows_conceptual_composition_without_inventing_audit_data():
    assert '"version":2' in CHAT_SYSTEM
    assert 'mode":"conceptual"' in CHAT_SYSTEM
    assert 'accordion' in CHAT_SYSTEM and 'visualization' in CHAT_SYSTEM
    assert 'n’invente' in CHAT_SYSTEM or "n'invente" in CHAT_SYSTEM
    assert 'AU PLUS UNE' not in CHAT_SYSTEM


async def test_v2_fenced_presentation_survives_stream_and_persistence(client, monkeypatch):
    output = 'Une explication.\n\n```viz\n{"version":2,"type":"composition","mode":"conceptual","children":[{"type":"heading","text":"Architecture"}]}\n```\n\nSuite.'

    class StreamingProvider:
        provider_id = 'test'
        model_id = 'test'
        async def stream_chat(self, system, messages, tools=None):
            assert '"version":2' in system
            for offset in range(0, len(output), 17):
                yield output[offset:offset + 17]
            yield LLMResponse(content=output)
        async def close(self):
            pass

    monkeypatch.setattr('app.agent.chat.build_provider', lambda *args, **kwargs: StreamingProvider())
    thread = await create_thread(client)
    events = await stream_turn(client, thread['id'], {'content': 'Explique avec un schéma', 'mode': 'new'})
    assert ''.join(event['text'] for event in events if event['type'] == 'text_delta') == output
    result = (await client.get(f"/api/conversations/{thread['id']}" )).json()
    assert result['messages'][-1]['parts'][0]['text'] == output


async def test_audit_tool_chain_preserves_numeric_source_identifiers(client, monkeypatch):
    import app.api.routes.sources as sources
    original = sources.new_id
    monkeypatch.setattr(sources, 'new_id', lambda kind: 'src_12345678' if kind == 'source' else original(kind))
    await upload_csv(client, 'orders.csv', FAULTY_CSV)
    thread = await create_thread(client)
    events = await stream_turn(client, thread['id'], {'content': 'audite cette source', 'mode': 'new'})
    result = next(event for event in events if event['type'] == 'tool_result' and event['tool'] == 'create_audit')
    assert result['status'] == 'complete', result['result']


async def test_source_id_restoration_is_workspace_checked_and_keeps_pii_masked():
    class Repo:
        async def get_source(self, source_id, workspace_id):
            return object() if source_id == 'src_12345678' and workspace_id == 'ws_valid' else None

    original = [{'role': 'tool', 'name': 'list_sources', 'content': json.dumps({'sources': [
        {'id': 'src_12345678', 'name': 'alice@example.com'}, {'id': 'src_87654321', 'name': 'External'}]})}]
    cleaned, _ = await sanitize_chat_context(original, Repo(), 'ws_valid')
    payload = json.loads(cleaned[0]['content'])
    assert payload['sources'][0]['id'] == 'src_12345678'
    assert payload['sources'][1]['id'] != 'src_87654321'
    assert 'alice@example.com' not in cleaned[0]['content']
