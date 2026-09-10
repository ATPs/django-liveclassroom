from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.http import HttpResponse
from django.test import override_settings

from examples.extension import ExampleGradingExtension
from liveclassroom.extensions import (
    ExtensionAuthorizationError,
    ExtensionConfigurationError,
    ExtensionInvocationError,
    ExtensionRegistry,
    adapt_activity_type,
    adapt_frontend_manifest,
    adapt_host_adapter,
    adapt_slide_provider,
    invoke_document,
    invoke_grading_score,
    invoke_grading_validate,
    load_extensions,
)
from liveclassroom.providers import ContentReference
from liveclassroom.registry import activity_registry


@dataclass
class FakeSlideProvider:
    key: str = "example.liveclassroom.slides"

    def parse_reference(self, url, *, request=None):
        return ContentReference(self.key, "note", {"url": url})

    def describe(self, reference, *, request=None):
        return {"provider": reference.provider, "kind": reference.kind}

    def validate_reference(self, reference, *, request=None):
        return reference

    def embed_url(self, reference, *, request=None):
        return str(reference.value["url"])


class FakeHostAdapter:
    key = "example.liveclassroom.host"
    protocol_version = 1
    capabilities = frozenset({"host.authorize", "host.identity"})

    def resolve_actor(self, *, request):
        return None

    def can_author(self, *, actor, resource):
        return True

    def can_deliver(self, *, actor, resource):
        return True

    def can_view_roster(self, *, actor, course_id):
        return False

    def can_view_named_responses(self, *, actor, session_id):
        return False

    def can_grade(self, *, actor, attempt_id):
        return True

    def course_summary(self, *, actor, course_id):
        return {"id": course_id}

    def list_roster(self, *, actor, course_id):
        return []


class BrokenGrading:
    key = "example.liveclassroom.broken"
    protocol_version = 1
    capabilities = frozenset({"grading.score", "grading.validate"})

    def validate(self, definition):
        raise RuntimeError("private provider diagnostic")

    def score(self, answer, definition):
        return {"credential": "must never escape"}


def allow(*, actor, request, resource):
    return actor == "teacher" and resource is not None


def test_standalone_example_loads_without_optional_provider():
    registry = load_extensions(
        {"example": "examples.extension.ExampleGradingExtension"},
        kind="grading",
        required_methods=("validate", "score"),
    )
    extension = registry.get("example.liveclassroom.reviewed_grading")
    definition = invoke_grading_validate(
        extension,
        {"prompt": "2 + 2?", "expected": "4"},
        actor="teacher",
        authorize=allow,
    )
    assert invoke_grading_score(extension, {"value": "4"}, definition, actor="teacher", authorize=allow)["score"] == 1


def test_settings_loader_and_missing_optional_extension_are_safe(settings):
    with override_settings(
        LIVECLASSROOM={
            "EXTENSIONS": {"example": "examples.extension.ExampleGradingExtension"},
        }
    ):
        registry = load_extensions(kind="grading", required_methods=("validate", "score"))
    assert registry.keys() == ("example.liveclassroom.reviewed_grading",)


def test_duplicate_missing_and_unsupported_extensions_fail_deterministically():
    registry = ExtensionRegistry(kind="grading", required_methods=("validate", "score"))
    extension = ExampleGradingExtension()
    registry.register(extension)
    with pytest.raises(ExtensionConfigurationError, match="Duplicate"):
        registry.register(extension)
    with pytest.raises(ExtensionConfigurationError, match="unsupported protocol"):
        registry.register(
            type(
                "Future",
                (),
                {
                    "key": "example.liveclassroom.future",
                    "protocol_version": 99,
                    "capabilities": frozenset({"grading.score"}),
                    "validate": lambda self, definition: definition,
                    "score": lambda self, answer, definition: {},
                },
            )()
        )


def test_typed_manifests_and_slide_provider_records_validate_shape():
    manifest = adapt_frontend_manifest(
        "example.liveclassroom.frontend",
        {
            surface: f"example/{surface}.js"
            for surface in ("editor", "student_renderer", "display_renderer", "analytics")
        },
    )
    assert manifest.manifest["editor"] == "example/editor.js"
    provider = adapt_slide_provider(FakeSlideProvider())
    assert provider.key == "example.liveclassroom.slides"
    host = adapt_host_adapter(FakeHostAdapter())
    assert host.key == "example.liveclassroom.host"
    activity = adapt_activity_type(activity_registry.get("liveclassroom.poll"))
    assert activity.key == "liveclassroom.poll"


def test_authorization_capability_and_provider_failures_are_safe():
    extension = ExampleGradingExtension()
    with pytest.raises(ExtensionAuthorizationError, match="denied"):
        invoke_grading_score(extension, {"value": "4"}, {"expected": "4"}, actor=None, authorize=allow)
    with pytest.raises(ExtensionInvocationError, match="failed safely"):
        invoke_grading_validate(BrokenGrading(), {"prompt": "x", "expected": "y"}, actor="teacher", authorize=allow)
    with pytest.raises(ExtensionInvocationError, match="unsafe"):
        invoke_grading_score(BrokenGrading(), {"value": "x"}, {"expected": "y"}, actor="teacher", authorize=allow)


class FakeDocument:
    key = "example.liveclassroom.document"
    protocol_version = 1
    capabilities = frozenset({"document.render"})

    def render(self, request, reference, *, mode):
        return HttpResponse(f"{reference.kind}:{mode}")


def test_document_receives_request_and_reference_after_authorization():
    reference = ContentReference("example.liveclassroom.slides", "note", {"url": "/note"})
    response = invoke_document(
        FakeDocument(),
        request=object(),
        reference=reference,
        mode="slides",
        actor="teacher",
        authorize=allow,
    )
    assert response.content == b"note:slides"
