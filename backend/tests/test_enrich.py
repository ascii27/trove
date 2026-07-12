import json
from types import SimpleNamespace

from app import enrich


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(self._payload))])


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def test_enrich_maps_structured_output():
    payload = {
        "summary": "It argues X.",
        "topics": ["AI", "evals"],
        "category": "paper",
        "source_type": "primary",
        "claims": ["Benchmarks reward completion.", "Reviewability predicts adoption."],
    }
    client = _FakeClient(payload)
    result = enrich.enrich("Some title", "the article body", client=client, model="claude-haiku-4-5")

    assert result.summary == "It argues X."
    assert result.topics == ["AI", "evals"]
    assert result.category == "paper"
    assert result.source_type == "primary"
    assert result.claims[0].startswith("Benchmarks")

    # sends a structured-output request to the configured model
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["output_config"]["format"]["type"] == "json_schema"


def test_enrich_truncates_long_body():
    payload = {"summary": "s", "topics": [], "category": "other", "source_type": "analysis", "claims": []}
    client = _FakeClient(payload)
    enrich.enrich("t", "x" * 50000, client=client)
    prompt = client.messages.calls[0]["messages"][0]["content"]
    # body is capped well under the raw length
    assert len(prompt) < 20000
