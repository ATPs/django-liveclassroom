"""Tests for LiveClassroom activity plugin registry, built-in types, and system checks."""

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import Error, Warning
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.checks import check_activity_registry
from liveclassroom.registry import (
    ActivityType,
    activity_registry,
    register_activity_type,
)


@pytest.fixture
def clean_registry():
    """Ensure custom test activity types do not leak across tests."""
    original_keys = set(activity_registry._types.keys())
    yield
    current_keys = set(activity_registry._types.keys())
    for key in current_keys - original_keys:
        activity_registry.unregister(key)


def test_builtin_activity_types_registered_with_complete_manifests():
    expected_types = {
        "liveclassroom.single_choice",
        "liveclassroom.multiple_choice",
        "liveclassroom.true_false",
        "liveclassroom.poll",
        "liveclassroom.short_text",
        "liveclassroom.numeric",
        "liveclassroom.rating",
        "liveclassroom.ranking",
        "liveclassroom.word_cloud",
        "liveclassroom.markdown",
        "liveclassroom.media",
        "liveclassroom.timer",
        "liveclassroom.question",
    }
    registered_keys = {item.key for item in activity_registry.all()}
    assert expected_types.issubset(registered_keys)

    required_surfaces = {"editor", "student_renderer", "display_renderer", "analytics"}
    for key in expected_types:
        activity_type = activity_registry.get(key)
        assert activity_type.capabilities, f"{key} should have capabilities"
        manifest = activity_type.frontend_manifest
        assert isinstance(manifest, dict), f"{key} manifest must be a dict"
        assert required_surfaces.issubset(manifest.keys()), f"{key} missing surfaces"
        for surface, path in manifest.items():
            assert isinstance(path, str) and path.strip(), f"{key} surface {surface} is empty"


def test_word_cloud_definition_validation():
    wc = activity_registry.get("liveclassroom.word_cloud")

    # Valid definitions
    empty_def = wc.validate({})
    assert isinstance(empty_def, dict)

    valid_def = wc.validate(
        {
            "prompt": "What comes to mind?",
            "max_length": 50,
            "stop_words": ["the", "a", "CustomWord"],
        }
    )
    assert valid_def["prompt"] == "What comes to mind?"
    assert valid_def["max_length"] == 50
    assert valid_def["stop_words"] == ["the", "a", "customword"]

    # Invalid definitions
    with pytest.raises(ValueError, match="must be an object"):
        wc.validate("not an object")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="prompt must be non-empty"):
        wc.validate({"prompt": ""})

    with pytest.raises(ValueError, match="max_length must be an integer"):
        wc.validate({"max_length": "invalid"})

    with pytest.raises(ValueError, match="max_length must be an integer"):
        wc.validate({"max_length": True})

    with pytest.raises(ValueError, match="max_length must be greater than zero"):
        wc.validate({"max_length": 0})

    with pytest.raises(ValueError, match="stop_words must be a list"):
        wc.validate({"stop_words": "not-a-list"})

    with pytest.raises(ValueError, match="stop word must be non-empty"):
        wc.validate({"stop_words": ["valid", ""]})


def test_word_cloud_submission_normalization_and_validation():
    wc = activity_registry.get("liveclassroom.word_cloud")

    # Normalization accepts "text" or "value"
    assert wc.normalize({"text": "  Hello World  "}) == {"text": "Hello World"}
    assert wc.normalize({"value": "Python"}) == {"text": "Python"}

    with pytest.raises(ValueError, match="A text answer cannot be empty"):
        wc.normalize({"text": "   "})

    with pytest.raises(ValueError, match="A text answer is too long"):
        wc.normalize({"text": "x" * 4001})

    # Validation against max_length in definition
    definition = {"max_length": 10}
    assert wc.validate_answer({"text": "short"}, definition) == {"text": "short"}

    with pytest.raises(ValueError, match="exceeds the configured maximum length"):
        wc.validate_answer({"text": "this is too long text"}, definition)


def test_word_cloud_aggregation_and_export():
    wc = activity_registry.get("liveclassroom.word_cloud")

    definition = {"stop_words": ["ignoreme"]}
    submissions = [
        {"text": "Python is great! Python, Django, and Web development."},
        {"text": "I love Python and Django!"},
        {"text": "Web development with Django is fast; ignoreme please."},
    ]

    result = wc.aggregate(submissions, definition=definition)

    assert result["submission_count"] == 3
    # Check that raw answers are provided for moderation
    assert len(result["raw_answers"]) == 3
    assert "Python is great! Python, Django, and Web development." in result["raw_answers"]

    # Check that punctuation and stop words are filtered, and counts are accurate
    words = result["words"]
    assert words["python"] == 3
    assert words["django"] == 3
    assert words["development"] == 2
    assert words["web"] == 2
    assert words["great"] == 1
    assert words["fast"] == 1

    # Stop words (built-in default 'is', 'and', 'with', 'i' and custom 'ignoreme') filtered
    assert "is" not in words
    assert "and" not in words
    assert "with" not in words
    assert "ignoreme" not in words

    # Export
    assert wc.export({"text": "sample"}) == {"text": "sample"}


def test_timer_definition_validation_and_capabilities():
    timer = activity_registry.get("liveclassroom.timer")
    assert "timed" in timer.capabilities

    # Valid definition
    valid = timer.validate({"duration_seconds": 60, "label": "Break", "auto_start": True})
    assert valid["duration_seconds"] == 60
    assert valid["label"] == "Break"
    assert valid["auto_start"] is True

    # Float duration
    valid_float = timer.validate({"duration_seconds": 30.5})
    assert valid_float["duration_seconds"] == 30.5

    # Rejections
    with pytest.raises(ValueError, match="duration_seconds is required"):
        timer.validate({})

    with pytest.raises(ValueError, match="duration_seconds must be a positive number"):
        timer.validate({"duration_seconds": -10})

    with pytest.raises(ValueError, match="duration_seconds must be a positive number"):
        timer.validate({"duration_seconds": 0})

    with pytest.raises(ValueError, match="duration_seconds must be a positive number"):
        timer.validate({"duration_seconds": True})

    with pytest.raises(ValueError, match="duration_seconds must be a positive number"):
        timer.validate({"duration_seconds": "not-a-number"})

    with pytest.raises(ValueError, match="label must be text"):
        timer.validate({"duration_seconds": 10, "label": 123})

    with pytest.raises(ValueError, match="auto_start must be a boolean"):
        timer.validate({"duration_seconds": 10, "auto_start": "yes"})

    # Export
    assert timer.export({"time": 10}) == {"time": 10}


def test_markdown_definition_validation_and_capabilities():
    md = activity_registry.get("liveclassroom.markdown")
    assert "content" in md.capabilities

    # Valid definition
    valid = md.validate({"markdown": "# Heading\nSome content", "title": "Overview"})
    assert valid["markdown"] == "# Heading\nSome content"
    assert valid["title"] == "Overview"

    # Rejections
    with pytest.raises(ValueError, match="markdown content is required"):
        md.validate({})

    with pytest.raises(ValueError, match="markdown content is required"):
        md.validate({"markdown": "   "})

    with pytest.raises(ValueError, match="markdown content is required"):
        md.validate({"markdown": 123})

    with pytest.raises(ValueError, match="title must be text"):
        md.validate({"markdown": "Content", "title": 999})

    # Export
    assert md.export({"viewed": True}) == {"viewed": True}


def test_media_definition_validation_and_capabilities():
    media = activity_registry.get("liveclassroom.media")
    assert "content" in media.capabilities

    # Valid definitions
    valid_img = media.validate({"url": "https://example.com/pic.png", "media_type": "image", "caption": "Diagram"})
    assert valid_img["url"] == "https://example.com/pic.png"
    assert valid_img["media_type"] == "image"
    assert valid_img["caption"] == "Diagram"

    for valid_type in ("image", "video", "audio"):
        assert media.validate({"url": "https://example.com/test", "media_type": valid_type})["media_type"] == valid_type

    # iframe requires the host to opt in via LIVECLASSROOM["ALLOW_IFRAME"].
    with pytest.raises(ValueError, match="iframes is disabled"):
        media.validate({"url": "https://example.com/test", "media_type": "iframe"})
    with override_settings(LIVECLASSROOM={"ALLOW_IFRAME": True}):
        assert media.validate({"url": "https://example.com/test", "media_type": "iframe"})["media_type"] == "iframe"

    # Rejections
    with pytest.raises(ValueError, match="url is required"):
        media.validate({})

    with pytest.raises(ValueError, match="url is required"):
        media.validate({"url": "   "})

    with pytest.raises(ValueError, match="media_type must be one of"):
        media.validate({"url": "https://example.com/test", "media_type": "executable"})

    with pytest.raises(ValueError, match="caption must be text"):
        media.validate({"url": "https://example.com/test", "media_type": "image", "caption": 42})

    # Executable and credential-bearing URLs are rejected regardless of type.
    for bad_url in ("javascript:alert(1)", "data:text/html,hi", "file:///etc/passwd", "https://user:pass@example.com/x.png"):
        with pytest.raises(ValueError):
            media.validate({"url": bad_url, "media_type": "image"})

    # Export
    assert media.export({"watched_seconds": 15}) == {"watched_seconds": 15}


def test_choice_numeric_and_ranking_builtins():
    # single_choice
    sc = activity_registry.get("liveclassroom.single_choice")
    def_sc = sc.validate({"options": ["Red", "Green", "Blue"], "answer": "A"})
    assert def_sc["options"][0] == {"id": "A", "text": "Red"}
    norm_sc = sc.normalize({"choice": "A"})
    assert sc.validate_answer(norm_sc, def_sc) == {"choice": "A"}
    with pytest.raises(ValueError, match="not part of this activity"):
        sc.validate_answer({"choice": "Z"}, def_sc)
    assert sc.score(norm_sc, def_sc) == {"is_correct": True, "score": 1}
    assert sc.score({"choice": "B"}, def_sc) == {"is_correct": False, "score": 0}

    # multiple_choice
    mc = activity_registry.get("liveclassroom.multiple_choice")
    def_mc = mc.validate({"options": ["X", "Y", "Z"], "answer": ["A", "B"]})
    norm_mc = mc.normalize({"choices": ["A", "B"]})
    assert sc.validate_answer(norm_sc, def_sc)
    assert mc.score(norm_mc, def_mc) == {"is_correct": True, "score": 1}

    # numeric
    num = activity_registry.get("liveclassroom.numeric")
    def_num = num.validate({"minimum": 0, "maximum": 100, "step": 5})
    norm_num = num.normalize({"value": "25"})
    assert norm_num["value"] == 25.0
    assert num.validate_answer(norm_num, def_num) == {"value": 25.0}
    with pytest.raises(ValueError, match="above the allowed maximum"):
        num.validate_answer({"value": 105}, def_num)

    # ranking
    rank = activity_registry.get("liveclassroom.ranking")
    def_rank = rank.validate({"options": ["First", "Second"]})
    norm_rank = rank.normalize({"ranking": ["A", "B"]})
    assert rank.validate_answer(norm_rank, def_rank) == {"ranking": ["A", "B"]}
    with pytest.raises(ValueError, match="not part of this activity"):
        rank.validate_answer({"ranking": ["Unknown"]}, def_rank)


def test_third_party_activity_type_registration(clean_registry):
    def validate_submission(submission, definition):
        if len(submission["snippet"]) > 0:
            return submission
        raise ValueError("empty snippet")

    def aggregate_submissions(submissions):
        snippets = [sub.get("snippet", "") for sub in submissions]
        return {"submission_count": len(snippets), "total_chars": sum(len(s) for s in snippets)}

    custom_type = ActivityType(
        key="vendor.code_snippet",
        validate_definition=lambda d: {"language": d.get("language", "python"), "code": str(d.get("code", "")).strip()},
        normalize_submission=lambda s: {"snippet": str(s.get("snippet", "")).strip()},
        validate_submission=validate_submission,
        aggregate_submissions=aggregate_submissions,
        export_submission=lambda s: {"exported_snippet": s.get("snippet")},
        capabilities=frozenset({"content", "aggregate"}),
        frontend_manifest={
            "editor": "vendor/code_snippet_editor.js",
            "student_renderer": "vendor/code_snippet_student.js",
            "display_renderer": "vendor/code_snippet_display.js",
            "analytics": "vendor/code_snippet_analytics.js",
        },
    )

    register_activity_type(custom_type)
    retrieved = activity_registry.get("vendor.code_snippet")
    assert retrieved is custom_type

    validated_def = retrieved.validate({"code": "print('hello world')"})
    assert validated_def == {"language": "python", "code": "print('hello world')"}

    normalized_sub = retrieved.normalize({"snippet": "x = 42"})
    assert normalized_sub == {"snippet": "x = 42"}

    assert retrieved.validate_answer(normalized_sub, validated_def) == {"snippet": "x = 42"}
    assert retrieved.aggregate([{"snippet": "a"}, {"snippet": "bc"}]) == {"submission_count": 2, "total_chars": 3}
    assert retrieved.aggregate_public([{"snippet": "a"}, {"snippet": "bc"}]) == {"submission_count": 2}
    assert retrieved.export(normalized_sub) == {"exported_snippet": "x = 42"}


def test_system_check_passes_on_builtin_registry():
    messages = check_activity_registry()
    errors = [m for m in messages if isinstance(m, Error)]
    warnings = [m for m in messages if isinstance(m, Warning)]
    assert not errors, f"System check reported errors on built-ins: {errors}"
    assert not warnings, f"System check reported warnings on built-ins: {warnings}"

    # Also run Django check command directly
    call_command("check")


def test_system_check_detects_malformed_plugins(clean_registry):
    manifest = {
        "editor": "test/editor.js",
        "student_renderer": "test/student.js",
        "display_renderer": "test/display.js",
        "analytics": "test/analytics.js",
    }

    # 1. Unnamespaced key
    bad_key_type = ActivityType(key="unnamespaced", frontend_manifest=manifest)
    activity_registry.register(bad_key_type, replace=True)
    messages = check_activity_registry()
    e001_errors = [m for m in messages if m.id == "liveclassroom.E001"]
    assert len(e001_errors) == 1
    assert "unnamespaced" in e001_errors[0].msg
    activity_registry.unregister("unnamespaced")

    # 2. Missing frontend manifest
    bad_manifest_type = ActivityType(key="test.missing_manifest", frontend_manifest={})
    activity_registry.register(bad_manifest_type, replace=True)
    messages = check_activity_registry()
    e002_errors = [
        m for m in messages
        if m.id == "liveclassroom.E002" and getattr(m.obj, "key", "") == "test.missing_manifest"
    ]
    assert len(e002_errors) == 1
    activity_registry.unregister("test.missing_manifest")

    # 3. Incomplete frontend manifest (missing 'analytics')
    incomplete_manifest = dict(manifest)
    del incomplete_manifest["analytics"]
    bad_surface_type = ActivityType(key="test.incomplete_manifest", frontend_manifest=incomplete_manifest)
    activity_registry.register(bad_surface_type, replace=True)
    messages = check_activity_registry()
    e002_surface_errors = [
        m for m in messages
        if m.id == "liveclassroom.E002" and getattr(m.obj, "key", "") == "test.incomplete_manifest"
    ]
    assert any("analytics" in m.msg for m in e002_surface_errors)
    activity_registry.unregister("test.incomplete_manifest")

    # 4. Invalid capabilities (empty string capability)
    bad_cap_type = ActivityType(
        key="test.bad_cap",
        capabilities=frozenset({""}),
        frontend_manifest=manifest,
    )
    activity_registry.register(bad_cap_type, replace=True)
    messages = check_activity_registry()
    e003_errors = [
        m for m in messages
        if m.id == "liveclassroom.E003" and getattr(m.obj, "key", "") == "test.bad_cap"
    ]
    assert len(e003_errors) >= 1
    activity_registry.unregister("test.bad_cap")

    # 5. Unrecognized capability triggers Warning (liveclassroom.W001)
    unknown_cap_type = ActivityType(
        key="test.unknown_cap",
        capabilities=frozenset({"future_feature"}),
        frontend_manifest=manifest,
    )
    activity_registry.register(unknown_cap_type, replace=True)
    messages = check_activity_registry()
    w001_warnings = [
        m for m in messages
        if m.id == "liveclassroom.W001" and getattr(m.obj, "key", "") == "test.unknown_cap"
    ]
    assert len(w001_warnings) == 1
    assert "future_feature" in w001_warnings[0].msg
    activity_registry.unregister("test.unknown_cap")


@pytest.mark.django_db
def test_api_activity_types_includes_frontend_manifest():
    teacher = get_user_model().objects.create_user(username="manifest_teacher", password="password")
    client = Client()

    # Unauthenticated request rejected
    res_unauth = client.get(reverse("liveclassroom:api-v1-activity-types"))
    assert res_unauth.status_code == 403

    # Authenticated teacher request succeeds
    client.force_login(teacher)
    res = client.get(reverse("liveclassroom:api-v1-activity-types"))
    assert res.status_code == 200

    data = res.json()
    assert data["protocol_version"] == 1
    types_list = data["activity_types"]
    assert len(types_list) >= 12

    for type_info in types_list:
        assert "key" in type_info
        assert "capabilities" in type_info
        manifest = type_info.get("frontend_manifest")
        assert isinstance(manifest, dict), f"{type_info['key']} missing frontend_manifest dict"
        for surface in ("editor", "student_renderer", "display_renderer", "analytics"):
            assert surface in manifest, f"{type_info['key']} missing surface {surface}"
            assert isinstance(manifest[surface], str) and manifest[surface]
