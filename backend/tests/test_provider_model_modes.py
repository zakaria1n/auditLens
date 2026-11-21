from types import SimpleNamespace

import pytest

from app.agent.providers.openai_compatible import OpenAICompatibleProvider


@pytest.mark.parametrize(('provider', 'model', 'token_key', 'thinking'), [
    ('openai', 'gpt-5-mini', 'max_completion_tokens', False),
    ('deepseek', 'deepseek-flash', 'max_tokens', True),
    ('gemini', 'gemini-4-hydrogen', 'max_tokens', False),
])
async def test_chat_request_uses_model_compatible_options(provider, model, token_key, thinking):
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='ok', tool_calls=[]))], usage=None)

    adapter = OpenAICompatibleProvider(provider, model, 'test-key')
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    await adapter.chat('system', [{'role': 'user', 'content': 'test'}])
    assert captured[token_key] == 8192
    assert ('extra_body' in captured) is thinking
    if thinking:
        assert captured['extra_body']['thinking']['type'] == 'disabled'
