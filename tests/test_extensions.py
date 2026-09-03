from dataclasses import dataclass

import pytest
from django.test import override_settings

from liveclassroom.ai import AIMessage, AIModel, AuthoringAIError, authoring_ai_backends
from liveclassroom.providers import ContentReference, ProviderError, content_providers


@dataclass
class DummyProvider:
    key: str = "dummy"

    def parse_reference(self, url, *, request=None):
        return ContentReference(self.key, "note", {"url": url})


class DummyAI:
    key = "dummy"

    def list_models(self, *, request=None):
        return [AIModel("test", "Test")]

    def complete(self, messages, *, model, request=None, attachments=None):
        return AIMessage("assistant", "Draft")


@pytest.mark.django_db
def test_content_provider_registry_loads_configured_instance():
    with override_settings(LIVECLASSROOM={"CONTENT_PROVIDERS": {"dummy": DummyProvider()}}):
        registry = content_providers()

    assert registry.keys() == ("dummy",)
    assert registry.get("dummy").parse_reference("https://example.test/note").value["url"]


@pytest.mark.django_db
def test_content_provider_registry_rejects_key_mismatch():
    with override_settings(LIVECLASSROOM={"CONTENT_PROVIDERS": {"other": DummyProvider()}}):
        with pytest.raises(ProviderError, match="key mismatch"):
            content_providers()


def test_ai_registry_returns_backend_and_safe_unknown_error():
    registry = authoring_ai_backends({"dummy": DummyAI()})

    assert registry.keys() == ("dummy",)
    assert list(registry.get("dummy").list_models())[0].identifier == "test"
    with pytest.raises(AuthoringAIError, match="Unknown"):
        registry.get("missing")
