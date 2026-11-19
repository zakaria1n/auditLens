from app.agent.providers.base import LLMResponse

async def test_llm_settings_keep_key_and_test_selected_model(client, monkeypatch):
    seen = []
    class StubProvider:
        provider_id = 'opencode'
        model_id = 'chosen-free'
        async def chat(self, system, messages, tools=None):
            return LLMResponse(content='ok')
        async def close(self):
            pass
    def factory(config):
        seen.append(config.copy())
        return StubProvider()
    monkeypatch.setattr('app.api.routes.settings_llm.build_provider', factory)
    secret = 'test-key-not-real'
    first = await client.put('/api/settings/llm', json={'provider':'opencode', 'model':'first-free', 'api_key':secret, 'base_url':'https://example.invalid'})
    assert first.status_code == 200 and secret not in first.text
    settings = await client.get('/api/settings/llm')
    assert settings.json()['key_configured'] is True and settings.json()['base_url'] is None and secret not in settings.text
    saved = await client.put('/api/settings/llm', json={'provider':'opencode', 'model':'chosen-free'})
    assert saved.status_code == 200
    tested = await client.post('/api/settings/llm/test', json={'provider':'opencode', 'model':'other-free'})
    assert tested.json()['ok'] is True
    assert seen[-1]['model'] == 'other-free' and seen[-1]['api_key'] == secret
    assert secret not in tested.text
    await client.post('/api/settings/llm/test', json={'provider':'compatible', 'model':'other'})
    assert seen[-1]['api_key'] == ''

async def test_catalogue_filters_free_models_and_includes_big_pickle(client, monkeypatch):
    import json
    from io import BytesIO
    class Response(BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()
    def item(model):
        return {'id':model, 'name':model, 'type':'chat', 'capabilities':{'tools':{'supported':True}}}
    payload = json.dumps({'data':[item('big-pickle'),item('alpha-free'),item('paid-model')]}).encode()
    monkeypatch.setattr('app.api.routes.settings_llm.urllib.request.urlopen', lambda *args, **kwargs: Response(payload))
    response = await client.get('/api/settings/llm/opencode/models')
    assert [model['id'] for model in response.json()['models']] == ['big-pickle','alpha-free']

def test_opencode_free_limit_message_does_not_invent_ip_quota():
    from app.agent.providers.openai_compatible import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider('opencode', 'big-pickle', 'dummy')
    message = provider._friendly_error(Exception('FreeUsageLimitError'))
    assert 'FreeUsageLimitError' in message
    assert 'quota anonyme' not in message and 'pour cette IP' not in message

async def test_quick_model_change_preserves_provider_credentials_and_url(client):
    secret = 'private-test-value'
    await client.put('/api/settings/llm', json={'provider':'compatible', 'model':'first', 'api_key':secret, 'base_url':'https://example.invalid/v1'})
    changed = await client.patch('/api/settings/llm/model', json={'provider':'compatible', 'model':' second '})
    assert changed.status_code == 200
    assert changed.json() == {'provider':'compatible', 'model':'second'}
    config = (await client.get('/api/settings/llm')).json()
    assert config['provider'] == 'compatible' and config['model'] == 'second'
    assert config['key_configured'] is True and config['base_url'] == 'https://example.invalid/v1'
    assert secret not in changed.text
    assert (await client.patch('/api/settings/llm/model', json={'provider':'opencode','model':'big-pickle'})).status_code == 409
    assert (await client.patch('/api/settings/llm/model', json={'provider':'compatible','model':'   '})).status_code == 422
    assert (await client.get('/api/settings/llm')).json()['model'] == 'second'


# ==========================================================================
# Choix facilité du modèle : catalogues suggérés par provider
# ==========================================================================


async def test_provider_models_curated_lists(client):
    """Chaque provider majeur renvoie une liste de suggestions non vide avec la
    forme attendue (id + libellé) et une note de fraîcheur explicite."""
    for provider, expected_first in (
        ("openai", "gpt-4.1-mini"),
        ("anthropic", "claude-sonnet-4-5"),
        ("deepseek", "deepseek-chat"),
        ("gemini", "gemini-2.5-flash"),
    ):
        r = await client.get(f"/api/settings/llm/models?provider={provider}")
        assert r.status_code == 200, provider
        body = r.json()
        assert body["ok"] is True and body["source"] == "curated"
        assert body["models"], f"liste vide pour {provider}"
        assert body["models"][0]["id"] == expected_first
        assert all("id" in m and "name" in m for m in body["models"])
        assert "nov" in body["note"].lower() or "saisi" in body["note"].lower()


async def test_provider_models_special_cases(client):
    """mock = son modèle unique ; compatible = saisie libre expliquée ;
    opencode-cli = renvoyé vers le catalogue dynamique ; inconnu → 400."""
    r = await client.get("/api/settings/llm/models?provider=mock")
    assert r.json()["models"] == [{"id": "mock-scripted-v1", "name": r.json()["models"][0]["name"]}]

    r = await client.get("/api/settings/llm/models?provider=compatible")
    body = r.json()
    assert body["source"] == "none" and body["models"] == []
    assert "base_url" in body["note"] and "saisi" in body["note"].lower()

    r = await client.get("/api/settings/llm/models?provider=opencode-cli")
    body = r.json()
    assert body["source"] == "none" and "opencode/models" in body["note"]

    r = await client.get("/api/settings/llm/models?provider=inconnu")
    assert r.status_code == 400
