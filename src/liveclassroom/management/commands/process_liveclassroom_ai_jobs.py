"""Process durable LiveClassroom authoring jobs without a host queue adapter."""

import secrets
import time

from django.core.management.base import BaseCommand

from liveclassroom.services.authoring import claim_next_authoring_job, recover_expired_authoring_jobs, run_authoring_job


class Command(BaseCommand):
    help = "Process queued LiveClassroom AI authoring jobs with lease recovery."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process currently available work and exit.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum jobs to process before exit.")
        parser.add_argument("--poll-seconds", type=int, default=5, help="Idle polling interval for worker mode.")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise ValueError("--limit must be positive.")
        if options["poll_seconds"] < 1:
            raise ValueError("--poll-seconds must be positive.")
        worker_token = secrets.token_urlsafe(32)
        processed = 0
        recovered = recover_expired_authoring_jobs()
        while processed < limit:
            job = claim_next_authoring_job(worker_token=worker_token)
            if job is None:
                if options["once"]:
                    break
                time.sleep(options["poll_seconds"])
                recovered += recover_expired_authoring_jobs()
                continue
            run_authoring_job(job_id=job.id, actor=job.thread.owner, worker_token=worker_token)
            processed += 1
        self.stdout.write(f"processed={processed} recovered={recovered}")
