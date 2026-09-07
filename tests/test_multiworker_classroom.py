import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client
from django.urls import reverse

from liveclassroom.models import SessionEvent, SubmissionRevision
from liveclassroom.realtime.postgres import publish_notification
from liveclassroom.services.classroom import (
    create_activity_definition,
    join_guest,
    launch_item,
    publish_activity_to_channel,
    start_session,
    update_channel_visibility,
)
from liveclassroom.services.plans import create_session


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(url: str, *, cookie: str, body: bytes | None = None, key: str | None = None):
    headers = {"Cookie": cookie}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key is not None:
        headers["Idempotency-Key"] = key
    request = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, response.read(), response.headers.get("Idempotent-Replay")
    except HTTPError as error:
        return error.code, error.read(), error.headers.get("Idempotent-Replay")


def _wait_for_health(base_url: str, process: subprocess.Popen, deadline: float) -> None:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"worker exited with status {process.returncode}")
        try:
            status, body, _ = _request(f"{base_url}/health/", cookie="")
            if status == 200 and json.loads(body)["status"] == "ok":
                return
        except (OSError, URLError, ValueError, KeyError):
            pass
        time.sleep(0.05)
    raise TimeoutError(f"worker did not become healthy: {base_url}")


def _wait_for_final_version(websocket, expected: int) -> int:
    deadline = time.monotonic() + 45
    observed = -1
    while time.monotonic() < deadline:
        try:
            raw = websocket.recv(timeout=min(5, max(0.1, deadline - time.monotonic())))
        except TimeoutError:
            continue
        payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        version = payload.get("version")
        if isinstance(version, int):
            observed = max(observed, version)
            if observed >= expected:
                return observed
    raise TimeoutError(f"websocket observed {observed}, expected at least {expected}")


@pytest.mark.django_db(transaction=True)
def test_two_uvicorn_workers_preserve_http_retries_and_realtime_state(tmp_path: Path):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for the multiworker acceptance")
    pytest.importorskip("uvicorn")
    connect = pytest.importorskip("websockets.sync.client").connect

    teacher = get_user_model().objects.create_user(username="multiworker-teacher")
    session = create_session(owner=teacher, title="Multiworker classroom")
    definition = create_activity_definition(
        owner=teacher,
        title="One observation",
        type_key="liveclassroom.short_text",
        definition={"prompt": "What did you observe?"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    update_channel_visibility(session=session, channel="participants", actor=teacher, show_aggregate=True)

    cookies = []
    for index in range(100):
        participant = join_guest(session=session, display_name=f"Student {index}", guest_id=f"multi-{index}")
        client = Client()
        client_session = client.session
        client_session[f"liveclassroom.participant.{session.pk}"] = participant.pk
        client_session.save()
        cookies.append(f"{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}")
    repo_root = Path(__file__).resolve().parents[1]
    ports = [_free_port()]
    while len(ports) < 2:
        candidate = _free_port()
        if candidate not in ports:
            ports.append(candidate)
    base_urls = [f"http://127.0.0.1:{port}" for port in ports]
    log_paths = [tmp_path / f"uvicorn-{index}.log" for index in range(2)]
    workers = []
    websockets = []
    failure = None
    try:
        worker_env = os.environ.copy()
        worker_env.update(
            {
                "DJANGO_SETTINGS_MODULE": "tests.postgres_settings",
                "LIVECLASSROOM_POSTGRES_NAME": str(connection.settings_dict["NAME"]),
                "PYTHONPATH": ".:src",
            }
        )
        for port, log_path in zip(ports, log_paths):
            with log_path.open("w") as log:
                workers.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "standalone.liveclassroom_site.asgi:application",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                            "--lifespan",
                            "on",
                            "--no-access-log",
                            "--log-level",
                            "warning",
                        ],
                        cwd=repo_root,
                        env=worker_env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                )
        startup_deadline = time.monotonic() + 45
        for base_url, worker in zip(base_urls, workers):
            _wait_for_health(base_url, worker, startup_deadline)

        websocket_path = f"/ws/liveclassroom/sessions/{session.pk}/"
        for index, cookie in enumerate(cookies):
            websocket = connect(
                f"ws://127.0.0.1:{ports[index // 50]}{websocket_path}",
                additional_headers={"Cookie": cookie},
                open_timeout=10,
                close_timeout=5,
                ping_interval=None,
            )
            websockets.append(websocket)
            ready = json.loads(websocket.recv(timeout=10))
            assert ready == {"type": "connection.ready", "session_id": session.pk}

        endpoint = reverse("liveclassroom:api-v1-submit", args=[activity.pk])
        revision_id = activity.current_revision_id

        def submit(index: int):
            body = json.dumps(
                {"activity_revision_id": revision_id, "answer": {"text": f"observation-{index}"}},
                separators=(",", ":"),
            ).encode()
            first_worker = index // 50
            first = _request(
                f"{base_urls[first_worker]}{endpoint}",
                cookie=cookies[index],
                body=body,
                key=f"multiworker-response-{index}",
            )
            replay = _request(
                f"{base_urls[1 - first_worker]}{endpoint}",
                cookie=cookies[index],
                body=body,
                key=f"multiworker-response-{index}",
            )
            return index, first, replay

        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=16) as pool:
            responses = list(pool.map(submit, range(100)))
        assert all(
            first[1] == replay[1]
            and first[0] == replay[0] == 201
            and first[2] is None
            and replay[2] == "true"
            for _, first, replay in responses
        ), responses
        connections.close_all()
        assert SubmissionRevision.objects.filter(submission__activity=activity).count() == 100

        session = session.__class__.objects.get(pk=session.pk)
        final_version = session.state_version
        final_event_id = (
            SessionEvent.objects.filter(session=session)
            .order_by("-sequence")
            .values_list("id", flat=True)
            .first()
        )
        state_url = f"{base_urls[0]}{reverse('liveclassroom:api-v1-state', args=[session.pk])}?channel=participants"
        state_status, state_body, _ = _request(state_url, cookie=cookies[0])
        state = json.loads(state_body)
        assert state_status == 200
        assert state["state_version"] == final_version
        assert state["aggregate"]["submission_count"] == 100

        # A final small notification covers events missed before a worker's relay subscribed.
        assert publish_notification(session.pk, {"version": final_version, "event_id": final_event_id})
        with ThreadPoolExecutor(max_workers=16) as pool:
            observed_versions = list(pool.map(lambda ws: _wait_for_final_version(ws, final_version), websockets))
        assert all(version >= final_version for version in observed_versions)
        print(f"100 students, 200 HTTP submissions across 2 workers: {time.monotonic() - started:.2f}s")
    except BaseException as exc:
        failure = exc
        raise
    finally:
        for websocket in websockets:
            try:
                websocket.close()
            except Exception:
                pass
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=10)
        if failure is not None:
            for log_path in log_paths:
                if log_path.exists():
                    print(f"worker log {log_path}:\n{log_path.read_text()[-4000:]}")
