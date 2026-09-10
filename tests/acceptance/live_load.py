"""Run the task-owned PostgreSQL/ASGI load acceptance suite.

This is deliberately a thin command-line wrapper around the checked-in tests.
The tests create synthetic data and start their own loopback workers; the
wrapper only validates the target and supplies repeatable load settings. It
never connects to a remote URL or to a non-loopback PostgreSQL server.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run two task-owned LiveClassroom load workers and PostgreSQL recovery checks."
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="loopback HTTP URL and free port for worker zero, for example http://127.0.0.1:18520",
    )
    parser.add_argument(
        "--classrooms",
        type=int,
        default=2,
        help="number of simultaneous classrooms (the acceptance contract requires 2)",
    )
    parser.add_argument(
        "--participants-per-class",
        type=int,
        default=100,
        help="synthetic participants in each classroom (default: 100)",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0,
        help="unreported warm-up write interval before measurement (default: 0)",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=0,
        help="measured sustained write interval (pass 600 for the full ten-minute contract)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=1,
        help="minimum delay between sustained write rounds (default: 1)",
    )
    parser.add_argument(
        "--relay-timeout-seconds",
        type=float,
        default=45,
        help="maximum wait for sampled PostgreSQL relay convergence (default: 45)",
    )
    return parser


def _validate(args: argparse.Namespace, environment: dict[str, str]) -> int:
    if args.classrooms != 2:
        raise ValueError("--classrooms must be exactly 2 for this acceptance contract")
    if args.participants_per_class < 1:
        raise ValueError("--participants-per-class must be positive")
    if args.warmup_seconds < 0 or args.duration_seconds < 0:
        raise ValueError("--warmup-seconds and --duration-seconds cannot be negative")
    if args.warmup_seconds and not args.duration_seconds:
        raise ValueError("--duration-seconds is required when --warmup-seconds is non-zero")
    if args.interval_seconds <= 0 or args.relay_timeout_seconds <= 0:
        raise ValueError("--interval-seconds and --relay-timeout-seconds must be positive")

    parsed = urlsplit(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("--base-url must be an http loopback URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("--base-url must not contain a path, query, fragment, or credentials")
    if parsed.port is None or not (1 <= parsed.port <= 65535):
        raise ValueError("--base-url must include a valid TCP port")

    # The wrapper owns worker startup. A listening port could belong to a host
    # service or another run, so fail before pytest creates any database rows.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((parsed.hostname, parsed.port))
        except OSError as exc:
            raise ValueError(f"--base-url port is not free: {args.base_url}") from exc

    postgres_host = environment.get("LIVECLASSROOM_POSTGRES_HOST", "127.0.0.1")
    if postgres_host not in {"127.0.0.1", "localhost"}:
        raise ValueError("LIVECLASSROOM_POSTGRES_HOST must be loopback for task-owned acceptance")
    return parsed.port


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment = os.environ.copy()
    try:
        _validate(args, environment)
    except ValueError as exc:
        _parser().error(str(exc))

    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": environment.get("DJANGO_SETTINGS_MODULE", "tests.postgres_settings"),
            "LIVECLASSROOM_LOAD_BASE_URL": args.base_url,
            "LIVECLASSROOM_LOAD_PARTICIPANTS": str(args.participants_per_class),
            "LIVECLASSROOM_LOAD_WARMUP_SECONDS": str(args.warmup_seconds),
            "LIVECLASSROOM_LOAD_DURATION_SECONDS": str(args.duration_seconds),
            "LIVECLASSROOM_LOAD_INTERVAL_SECONDS": str(args.interval_seconds),
            "LIVECLASSROOM_LOAD_RELAY_TIMEOUT": str(args.relay_timeout_seconds),
            "PYTHONPATH": f".:src{os.pathsep}{environment.get('PYTHONPATH', '')}".rstrip(os.pathsep),
        }
    )
    environment.setdefault("LIVECLASSROOM_POSTGRES_TEST_NAME", f"task52_live_load_{os.getpid()}_{int(time.time())}")

    command = [
        sys.executable,
        "-m",
        "pytest",
        "--create-db",
        "-q",
        "-s",
        "-rA",
        "tests/test_classroom_load.py",
        "tests/test_multiworker_classroom.py",
        "tests/test_assessment_resilience_postgres.py",
    ]
    print(
        "task-owned load configuration: "
        f"base_url={args.base_url} classrooms={args.classrooms} "
        f"participants_per_class={args.participants_per_class} "
        f"warmup_seconds={args.warmup_seconds} duration_seconds={args.duration_seconds}"
    )
    completed = subprocess.run(command, cwd=REPO_ROOT, env=environment, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
