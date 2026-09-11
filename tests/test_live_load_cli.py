"""Safety checks for the task-owned PostgreSQL load acceptance wrapper."""

from __future__ import annotations

import re
import socket

import pytest

from tests.acceptance import live_load


def _free_http_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _args():
    return live_load._parser().parse_args(["--base-url", f"http://127.0.0.1:{_free_http_port()}"])


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        (
            "LIVECLASSROOM_POSTGRES_HOST",
            "db.example.invalid",
            "LIVECLASSROOM_POSTGRES_HOST",
        ),
        ("LIVECLASSROOM_POSTGRES_PORT", "5432", "LIVECLASSROOM_POSTGRES_PORT"),
        ("LIVECLASSROOM_POSTGRES_TEST_NAME", "production", "must not be inherited"),
    ],
)
def test_validate_rejects_inherited_non_task_owned_database_settings(variable, value, message):
    environment = {variable: value}

    with pytest.raises(ValueError, match=re.escape(message)):
        live_load._validate(_args(), environment)


def test_main_pins_settings_and_generates_a_fresh_task_owned_database(monkeypatch):
    captured = {}

    def fake_run(command, *, cwd, env, check):
        captured.update(command=command, cwd=cwd, env=env, check=check)

        class Completed:
            returncode = 0

        return Completed()

    monkeypatch.setattr(live_load.subprocess, "run", fake_run)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "host.settings")
    monkeypatch.setenv("LIVECLASSROOM_POSTGRES_HOST", "localhost")
    monkeypatch.setenv("LIVECLASSROOM_POSTGRES_PORT", live_load.POSTGRES_PORT)
    monkeypatch.delenv("LIVECLASSROOM_POSTGRES_TEST_NAME", raising=False)

    result = live_load.main(["--base-url", f"http://127.0.0.1:{_free_http_port()}"])

    assert result == 0
    assert captured["check"] is False
    environment = captured["env"]
    assert environment["DJANGO_SETTINGS_MODULE"] == "tests.postgres_settings"
    assert environment["LIVECLASSROOM_POSTGRES_HOST"] == live_load.POSTGRES_HOST
    assert environment["LIVECLASSROOM_POSTGRES_PORT"] == live_load.POSTGRES_PORT
    assert re.fullmatch(r"task52_live_load_[0-9]+_[0-9]+", environment["LIVECLASSROOM_POSTGRES_TEST_NAME"])
    assert "--create-db" in captured["command"]
