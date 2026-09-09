"""Authorization and request-local staging for retained Markdown documents."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from django.http import Http404

from liveclassroom.models import ActivityRunRevision, ClassroomAsset, LiveSession

from .assets import can_read_session_asset, open_asset
from .classroom import ClassroomError
from .permissions import can_read_asset


@dataclass(frozen=True)
class StagedDocument:
    path: Path
    filename: str


def _markdown_asset(asset: ClassroomAsset | None) -> ClassroomAsset:
    if asset is None or asset.kind != ClassroomAsset.Kind.MARKDOWN:
        raise Http404("Document not found")
    return asset


def authorize_asset_document(*, actor, asset_id) -> ClassroomAsset:
    try:
        asset = ClassroomAsset.objects.get(public_id=asset_id)
    except ClassroomAsset.DoesNotExist as exc:
        raise Http404("Document not found") from exc
    if not can_read_asset(actor, asset):
        raise Http404("Document not found")
    return _markdown_asset(asset)


def authorize_session_document(
    *, request, session_id, revision_id, asset_id
) -> tuple[LiveSession, ActivityRunRevision]:
    try:
        revision = ActivityRunRevision.objects.select_related("activity", "asset", "activity__session").get(
            pk=revision_id,
            activity__session_id=session_id,
            asset__public_id=asset_id,
        )
    except ActivityRunRevision.DoesNotExist as exc:
        raise Http404("Document not found") from exc
    session = revision.activity.session
    _markdown_asset(revision.asset)
    if not can_read_session_asset(request, session, revision):
        raise Http404("Document not found")
    return session, revision


@contextmanager
def stage_markdown_asset(asset: ClassroomAsset) -> Iterator[StagedDocument]:
    asset = _markdown_asset(asset)
    handle = None
    try:
        handle, _size = open_asset(asset)
        if asset.source == ClassroomAsset.Source.SERVER_PATH:
            handle.close()
            handle = None
            path = Path(asset.server_path).resolve(strict=True)
            yield StagedDocument(path=path, filename=path.name)
            return

        filename = Path(asset.original_name).name
        if not filename or Path(filename).suffix.lower() != ".md":
            raise ClassroomError("The Markdown filename is invalid.")
        with TemporaryDirectory(prefix="liveclassroom-document-") as directory:
            path = Path(directory) / filename
            digest = hashlib.sha256()
            with path.open("wb") as output:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            handle.close()
            handle = None
            if asset.sha256 and digest.hexdigest() != asset.sha256:
                raise ClassroomError("The uploaded file content has changed.")
            yield StagedDocument(path=path, filename=filename)
    finally:
        if handle is not None:
            handle.close()
