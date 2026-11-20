"""Gemini tool calls must retain opaque provider metadata in the current turn."""

from types import SimpleNamespace

import pytest

from app.agent.providers.base import LLMResponse
from app.agent.providers.openai_compatible import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_streamed_gemini_tool_metadata_round_trip():
    signature = {"google": {"thought_signature": "opaque-test-signature"}}
    tc = SimpleNamespace(index=0, id="call-1", function=SimpleNamespace(name="lookup", arguments='{"x":1}'), extra_content=signature)
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[tc]))])

    class Stream:
        def __aiter__(self):
            async def iterate():
                yield chunk
            return iterate()

        async def close(self):
            pass

    async def create(**kwargs):
        assert kwargs['stream'] is True
        return Stream()

    provider = OpenAICompatibleProvider('gemini', 'gemini-test', 'test-key')
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = [item async for item in provider.stream_chat('system', [], [])][-1]
    assert isinstance(result, LLMResponse)
    call = result.tool_calls[0]
    assert call.extra_content == signature
    messages = [{'role': 'assistant', 'content': None, 'tool_calls': [call.model_dump()]},
                {'role': 'tool', 'tool_call_id': call.id, 'content': '{}'}]
    assert provider._map_messages('system', messages)[1]['tool_calls'][0]['extra_content'] == signature


def test_non_gemini_does_not_forward_opaque_metadata():
    provider = OpenAICompatibleProvider('openai', 'model', 'test-key')
    messages = [{'role': 'assistant', 'tool_calls': [{'id': '1', 'name': 'f', 'arguments': {},
                                                       'extra_content': {'google': {'thought_signature': 'x'}}}]}]
    assert 'extra_content' not in provider._map_messages('system', messages)[1]['tool_calls'][0]


def test_gemini_bad_request_diagnostic_does_not_echo_private_body():
    class BadRequestError(Exception):
        status_code = 400

    provider = OpenAICompatibleProvider('gemini', 'gemini-test', 'test-key')
    error = provider._friendly_error(BadRequestError('missing thought_signature; private prompt SECRET'))
    assert 'signature' in error
    assert 'SECRET' not in error
