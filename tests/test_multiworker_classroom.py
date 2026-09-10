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
    status, response_body, replay, _elapsed_ms = _timed_request(url, cookie=cookie, body=body, key=key)
    return status, response_body, replay


def _timed_request(url: str, *, cookie: str, body: bytes | None = None, key: str | None = None):
    started = time.monotonic()
    headers = {"Cookie": cookie}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key is not None:
        headers["Idempotency-Key"] = key
    request = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=45) as response:
            return (
                response.status,
                response.read(),
                response.headers.get("Idempotent-Replay"),
                (time.monotonic() - started) * 1000,
            )
    except HTTPError as error:
        return (
            error.code,
            error.read(),
            error.headers.get("Idempotent-Replay"),
            (time.monotonic() - started) * 1000,
        )


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


def _wait_for_final_version(websocket, expected: int, timeout_seconds: float = 45) -> int:
    deadline = time.monotonic() + timeout_seconds
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


def _percentile(values: list[float], fraction: float) -> float:
    """Return a nearest-rank percentile for a small, deterministic report."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _close_socket(websocket) -> None:
    try:
        websocket.close()
    except Exception:
        pass


def _close_sockets(websockets) -> None:
    """Close many task-owned clients without serial close-handshake latency."""
    if not websockets:
        return
    with ThreadPoolExecutor(max_workers=min(len(websockets), 64)) as pool:
        list(pool.map(_close_socket, websockets))


def _spawn_worker(*, repo_root: Path, env: dict[str, str], port: int, log_path: Path, append: bool = False):
    mode = "a" if append else "w"
    with log_path.open(mode) as log:
        return subprocess.Popen(
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
                # The synthetic 200-socket setup can take longer than uvicorn's
                # 20-second default ping window while the task-owned workers
                # process the concurrent HTTP writes. Keep the worker alive for
                # the bounded experiment; this is not a production setting.
                "--ws-ping-interval",
                "120",
                "--ws-ping-timeout",
                "120",
            ],
            cwd=repo_root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )


def _restart_worker(*, worker, port: int, repo_root: Path, env: dict[str, str], log_path: Path, base_url: str):
    """Restart one process owned by this test and wait for its health endpoint."""
    if worker.poll() is None:
        worker.terminate()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=10)
    replacement = _spawn_worker(repo_root=repo_root, env=env, port=port, log_path=log_path, append=True)
    _wait_for_health(base_url, replacement, time.monotonic() + 45)
    return replacement


@pytest.mark.django_db(transaction=True)
def test_two_uvicorn_workers_preserve_http_retries_reconnect_and_realtime_state(tmp_path: Path):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for the multiworker acceptance")
    pytest.importorskip("uvicorn")
    connect = pytest.importorskip("websockets.sync.client").connect
    participant_count = int(os.environ.get("LIVECLASSROOM_LOAD_PARTICIPANTS", "100"))
    relay_timeout = float(os.environ.get("LIVECLASSROOM_LOAD_RELAY_TIMEOUT", "45"))
    if participant_count < 1 or relay_timeout <= 0:
        raise ValueError("LIVECLASSROOM_LOAD_PARTICIPANTS and LIVECLASSROOM_LOAD_RELAY_TIMEOUT must be positive")

    teacher = get_user_model().objects.create_user(username="multiworker-teacher")
    classrooms = []
    for classroom_index in range(2):
        session = create_session(owner=teacher, title=f"Multiworker classroom {classroom_index}")
        definition = create_activity_definition(
            owner=teacher,
            title=f"One observation {classroom_index}",
            type_key="liveclassroom.short_text",
            definition={"prompt": "What did you observe?"},
        )
        start_session(session=session, actor=teacher)
        activity = launch_item(session=session, item=definition, actor=teacher)
        publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
        update_channel_visibility(session=session, channel="participants", actor=teacher, show_aggregate=True)
        participants = []
        for index in range(participant_count):
            participant = join_guest(
                session=session,
                display_name=f"Student {classroom_index}-{index}",
                guest_id=f"multi-{classroom_index}-{index}",
            )
            client = Client()
            client_session = client.session
            client_session[f"liveclassroom.participant.{session.pk}"] = participant.pk
            client_session.save()
            participants.append(
                {
                    "index": index,
                    "cookie": f"{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}",
                }
            )
        classrooms.append({"session": session, "activity": activity, "participants": participants})

    teacher_client = Client()
    teacher_client.force_login(teacher)
    teacher_cookie = f"{settings.SESSION_COOKIE_NAME}={teacher_client.cookies[settings.SESSION_COOKIE_NAME].value}"
    repo_root = Path(__file__).resolve().parents[1]
    ports = [_free_port()]
    while len(ports) < 2:
        candidate = _free_port()
        if candidate not in ports:
            ports.append(candidate)
    base_urls = [f"http://127.0.0.1:{port}" for port in ports]
    log_paths = [tmp_path / f"uvicorn-{index}.log" for index in range(2)]
    workers = []
    socket_records = []
    request_latencies = []
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
            workers.append(_spawn_worker(repo_root=repo_root, env=worker_env, port=port, log_path=log_path))
        startup_deadline = time.monotonic() + 45
        for base_url, worker in zip(base_urls, workers):
            _wait_for_health(base_url, worker, startup_deadline)

        # Exercise teacher publish/settings over HTTP before the participant load.
        for classroom in classrooms:
            session = classroom["session"]
            activity = classroom["activity"]
            publish_body = json.dumps({"activity_id": activity.id, "channel": "participants"}).encode()
            publish_result = _timed_request(
                f"{base_urls[0]}{reverse('liveclassroom:api-v1-publish-channel', args=[session.pk])}",
                cookie=teacher_cookie,
                body=publish_body,
                key=f"teacher-publish-{session.pk}",
            )
            assert publish_result[0] == 200, publish_result[:3]
            request_latencies.append(publish_result[3])
            settings_body = json.dumps(
                {
                    "channel": "participants",
                    "show_prompt": True,
                    "show_aggregate": True,
                    "show_own_status": True,
                }
            ).encode()
            settings_result = _timed_request(
                f"{base_urls[1]}{reverse('liveclassroom:api-v1-channel-settings', args=[session.pk])}",
                cookie=teacher_cookie,
                body=settings_body,
                key=f"teacher-settings-{session.pk}",
            )
            assert settings_result[0] == 200, settings_result[:3]
            request_latencies.append(settings_result[3])

        # Connect two classrooms with the configured client count; the default is 100
        # per classroom. Distribution remains even when a small diagnostic override is used.
        for classroom_index, classroom in enumerate(classrooms):
            websocket_path = f"/ws/liveclassroom/sessions/{classroom['session'].pk}/"
            for participant in classroom["participants"]:
                worker_index = (participant["index"] * 2) // participant_count
                websocket = connect(
                    f"ws://127.0.0.1:{ports[worker_index]}{websocket_path}",
                    additional_headers={"Cookie": participant["cookie"]},
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=None,
                )
                ready = json.loads(websocket.recv(timeout=10))
                assert ready == {"type": "connection.ready", "session_id": classroom["session"].pk}
                socket_records.append(
                    {
                        "classroom_index": classroom_index,
                        "participant_index": participant["index"],
                        "cookie": participant["cookie"],
                        "worker_index": worker_index,
                        "websocket": websocket,
                    }
                )

        accepted_writes = set()
        started = time.monotonic()

        def submit(record, *, suffix: str, answer: str):
            classroom = classrooms[record["classroom_index"]]
            activity = classroom["activity"]
            body = json.dumps(
                {
                    "activity_revision_id": activity.current_revision_id,
                    "answer": {"text": answer},
                },
                separators=(",", ":"),
            ).encode()
            endpoint = reverse("liveclassroom:api-v1-submit", args=[activity.pk])
            worker_index = record["worker_index"]
            first = _timed_request(
                f"{base_urls[worker_index]}{endpoint}",
                cookie=record["cookie"],
                body=body,
                key=f"multiworker-{suffix}-{record['classroom_index']}-{record['participant_index']}",
            )
            request_latencies.append(first[3])
            if first[0] == 201:
                accepted_writes.add((suffix, record["classroom_index"], record["participant_index"]))
            return first

        records = list(socket_records)
        with ThreadPoolExecutor(max_workers=16) as pool:
            initial = list(
                pool.map(
                    lambda record: submit(
                        record,
                        suffix="initial",
                        answer=f"observation-{record['classroom_index']}-{record['participant_index']}",
                    ),
                    records,
                )
            )
        assert all(result[0] == 201 for result in initial), [result[:3] for result in initial]

        # Replays cross workers and must not create another durable revision.
        def replay(record):
            classroom = classrooms[record["classroom_index"]]
            activity = classroom["activity"]
            endpoint = reverse("liveclassroom:api-v1-submit", args=[activity.pk])
            body = json.dumps(
                {
                    "activity_revision_id": activity.current_revision_id,
                    "answer": {"text": f"observation-{record['classroom_index']}-{record['participant_index']}"},
                },
                separators=(",", ":"),
            ).encode()
            result = _timed_request(
                f"{base_urls[1 - record['worker_index']]}{endpoint}",
                cookie=record["cookie"],
                body=body,
                key=f"multiworker-initial-{record['classroom_index']}-{record['participant_index']}",
            )
            request_latencies.append(result[3])
            return result

        with ThreadPoolExecutor(max_workers=16) as pool:
            retries = list(pool.map(replay, records))
        assert all(result[0] == 201 and result[2] == "true" for result in retries), [result[:3] for result in retries]
        connections.close_all()
        assert all(
            SubmissionRevision.objects.filter(submission__activity=classroom["activity"]).count() == participant_count
            for classroom in classrooms
        )

        # Explicitly drop a subset. A restart closes all sockets on worker zero, which
        # models a task-owned process failure; every affected client then reconnects.
        dropped = [record for record in records if record["participant_index"] % 20 == 0]
        restart_affected = [record for record in records if record["worker_index"] == 0]
        affected = list({id(record): record for record in dropped + restart_affected}.values())
        _close_sockets([record["websocket"] for record in affected])
        workers[0] = _restart_worker(
            worker=workers[0],
            port=ports[0],
            repo_root=repo_root,
            env=worker_env,
            log_path=log_paths[0],
            base_url=base_urls[0],
        )
        for record in affected:
            classroom = classrooms[record["classroom_index"]]
            websocket_path = f"/ws/liveclassroom/sessions/{classroom['session'].pk}/"
            reconnect_worker = 1 - record["worker_index"]
            record["websocket"] = connect(
                f"ws://127.0.0.1:{ports[reconnect_worker]}{websocket_path}",
                additional_headers={"Cookie": record["cookie"]},
                open_timeout=10,
                close_timeout=5,
                ping_interval=None,
            )
            record["worker_index"] = reconnect_worker
            ready = json.loads(record["websocket"].recv(timeout=10))
            assert ready == {"type": "connection.ready", "session_id": classroom["session"].pk}

        # Every learner edits once after reconnect. This is the acknowledged-write
        # ledger used below to reconcile durable revisions.
        with ThreadPoolExecutor(max_workers=16) as pool:
            edits = list(
                pool.map(
                    lambda record: submit(
                        record,
                        suffix="edit",
                        answer=f"edited-{record['classroom_index']}-{record['participant_index']}",
                    ),
                    records,
                )
            )
        assert all(result[0] == 201 for result in edits), [result[:3] for result in edits]
        assert len(accepted_writes) == participant_count * 4
        assert all(
            SubmissionRevision.objects.filter(submission__activity=classroom["activity"]).count()
            == participant_count * 2
            for classroom in classrooms
        )

        # Close and reveal after all edits; this exercises a teacher state transition
        # after the reconnect without invalidating the accepted answer ledger.
        for classroom in classrooms:
            activity = classroom["activity"]
            result = _timed_request(
                f"{base_urls[0]}{reverse('liveclassroom:api-v1-close-and-show-answer', args=[activity.pk])}",
                cookie=teacher_cookie,
                body=b"{}",
                key=f"teacher-reveal-{activity.pk}",
            )
            request_latencies.append(result[3])
            assert result[0] == 200, result[:3]

        # HTTP is authoritative after notification loss/restart; relay delivery is
        # checked using the final state event from each independent classroom.
        final_versions = {}
        for classroom_index, classroom in enumerate(classrooms):
            session = classroom["session"].__class__.objects.get(pk=classroom["session"].pk)
            final_version = session.state_version
            final_versions[classroom_index] = final_version
            final_event_id = (
                SessionEvent.objects.filter(session=session)
                .order_by("-sequence")
                .values_list("id", flat=True)
                .first()
            )
            state_record = next(
                record for record in records if record["classroom_index"] == classrooms.index(classroom)
            )
            state_url = (
                f"{base_urls[state_record['worker_index']]}"
                f"{reverse('liveclassroom:api-v1-state', args=[session.pk])}?channel=participants"
            )
            state_result = _timed_request(state_url, cookie=state_record["cookie"])
            request_latencies.append(state_result[3])
            state_status, state_body = state_result[0], state_result[1]
            state = json.loads(state_body)
            assert state_status == 200
            assert state["state_version"] == final_version
            assert state["aggregate"]["submission_count"] == participant_count
            assert publish_notification(session.pk, {"version": final_version, "event_id": final_event_id})

        # Every accepted write is reconciled through HTTP/database state above.
        # Relay delivery is sampled from reconnecting clients so a missed event
        # remains a bounded diagnostic instead of creating an unbounded 200-socket
        # wait when a worker has just restarted.
        sample_stride = max(1, participant_count // 10)
        convergence_records = [record for record in records if record["participant_index"] % sample_stride == 0]
        with ThreadPoolExecutor(max_workers=min(len(convergence_records), 64)) as pool:
            observed_versions = list(
                pool.map(
                    lambda record: _wait_for_final_version(
                        record["websocket"], final_versions[record["classroom_index"]], relay_timeout
                    ),
                    convergence_records,
                )
            )
        assert all(
            version >= final_versions[record["classroom_index"]]
            for record, version in zip(convergence_records, observed_versions)
        )
        print(
            f"{participant_count * 2} students, {participant_count * 4} accepted writes and "
            f"{participant_count * 4} HTTP retries across 2 classrooms/2 workers; "
            f"websocket convergence sample={len(convergence_records)} "
            f"p50={_percentile(request_latencies, 0.50):.1f}ms "
            f"p95={_percentile(request_latencies, 0.95):.1f}ms "
            f"max={max(request_latencies):.1f}ms duration={time.monotonic() - started:.2f}s"
        )
    except BaseException as exc:
        failure = exc
        raise
    finally:
        _close_sockets([record["websocket"] for record in socket_records])
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
