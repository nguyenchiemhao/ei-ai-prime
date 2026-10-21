"""The Model Gateway (EA-24, FND-07): every model call goes through ``ModelGateway``.

Only ``transport`` imports the OpenAI SDK and the HTTP client; see
``docs/architecture/model-gateway.md``.
"""
