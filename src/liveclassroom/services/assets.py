"""Validation and private delivery helpers for classroom presentation files."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path
from typing import BinaryIO

from django.core.files.uploadedfile import UploadedFile

from liveclassroom.conf import asset_max_bytes, server_file_paths_allowed
from liveclassroom.models import ClassroomAsset

from .classroom import ClassroomError

_FORMAT_DETAILS = {
    ".md": (ClassroomAsset.Kind.MARKDOWN, "text/markdown; charset=utf-8"),
    ".pdf": (ClassroomAsset.Kind.PDF, "application/pdf"),
    ".pptx": (
        ClassroomAsset.Kind.PPTX,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    ".mp4": (ClassroomAsset.Kind.VIDEO, "video/mp4"),
    ".webm": (ClassroomAsset.Kind.VIDEO, "video/webm"),
}
_MAX_PPTX_ENTRIES = 10_000
_MAX_PPTX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024


def asset_descriptor(asset: ClassroomAsset, *, content_url: str | None = None, download_url: str | None = None) -> dict:
    result = {
        "id": str(asset.public_id),
        "name": asset.original_name,
        "kind": asset.kind,
        "size": asset.byte_size,
    }
    if content_url:
        result["content_url"] = content_url
    if download_url:
        result["download_url"] = download_url
    return result


def _format_for_name(name: str) -> tuple[str, str]:
    suffix = Path(name).suffix.lower()
    try:
        return _FORMAT_DETAILS[suffix]
    except KeyError as exc:
        raise ClassroomError("Only .md, .pdf, .pptx, .mp4, and .webm files are supported.") from exc


def _rewind(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
    except (AttributeError, OSError) as exc:
        raise ClassroomError("The selected file cannot be read.") from exc


def _read_prefix(handle: BinaryIO, size: int = 32) -> bytes:
    _rewind(handle)
    data = handle.read(size)
    _rewind(handle)
    return data


def _validate_pptx(handle: BinaryIO) -> None:
    _rewind(handle)
    try:
        with zipfile.ZipFile(handle) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_PPTX_ENTRIES:
                raise ClassroomError("The PowerPoint file has too many archive entries.")
            if sum(entry.file_size for entry in entries) > _MAX_PPTX_UNCOMPRESSED_BYTES:
                raise ClassroomError("The PowerPoint file expands beyond the safe limit.")
            names = {entry.filename for entry in entries}
    except (OSError, zipfile.BadZipFile) as exc:
        raise ClassroomError("The selected PowerPoint file is invalid.") from exc
    finally:
        _rewind(handle)
    if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
        raise ClassroomError("The selected PowerPoint file is invalid.")


def validate_asset_file(handle: BinaryIO, *, name: str, size: int) -> tuple[str, str]:
    """Validate a supported file without trusting its extension or MIME header."""
    if size < 1:
        raise ClassroomError("The selected file is empty.")
    if size > asset_max_bytes():
        raise ClassroomError(f"The selected file exceeds the {asset_max_bytes()} byte limit.")
    kind, content_type = _format_for_name(name)
    prefix = _read_prefix(handle)
    if kind == ClassroomAsset.Kind.MARKDOWN:
        _rewind(handle)
        try:
            text = handle.read().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ClassroomError("Markdown files must be UTF-8 text.") from exc
        finally:
            _rewind(handle)
        if "\x00" in text:
            raise ClassroomError("Markdown files must not contain binary data.")
    elif kind == ClassroomAsset.Kind.PDF and not prefix.startswith(b"%PDF-"):
        raise ClassroomError("The selected PDF file is invalid.")
    elif kind == ClassroomAsset.Kind.PPTX:
        if not prefix.startswith(b"PK"):
            raise ClassroomError("The selected PowerPoint file is invalid.")
        _validate_pptx(handle)
    elif name.lower().endswith(".mp4") and (len(prefix) < 12 or prefix[4:8] != b"ftyp"):
        raise ClassroomError("The selected MP4 file is invalid.")
    elif name.lower().endswith(".webm") and not prefix.startswith(b"\x1aE\xdf\xa3"):
        raise ClassroomError("The selected WebM file is invalid.")
    return kind, content_type


def _sha256(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    _rewind(handle)
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
    _rewind(handle)
    return digest.hexdigest()


def create_uploaded_asset(*, owner, uploaded_file: UploadedFile) -> ClassroomAsset:
    if not getattr(owner, "is_authenticated", False):
        raise ClassroomError("An authenticated teacher is required to upload a file.")
    name = Path(uploaded_file.name or "").name
    if not name:
        raise ClassroomError("The selected file needs a filename.")
    size = int(getattr(uploaded_file, "size", 0))
    kind, content_type = validate_asset_file(uploaded_file, name=name, size=size)
    asset = ClassroomAsset(
        owner=owner,
        source=ClassroomAsset.Source.UPLOAD,
        original_name=name,
        kind=kind,
        content_type=content_type,
        byte_size=size,
        sha256=_sha256(uploaded_file),
    )
    asset.content_file.save(name, uploaded_file, save=False)
    asset.save()
    return asset


def create_server_path_asset(*, owner, raw_path: str) -> ClassroomAsset:
    if not getattr(owner, "is_superuser", False) or not server_file_paths_allowed():
        raise ClassroomError("Server file references are restricted to enabled superuser accounts.")
    if not isinstance(raw_path, str) or not raw_path.strip() or "\x00" in raw_path:
        raise ClassroomError("A valid absolute server path is required.")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ClassroomError("The server path must be absolute.")
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise ClassroomError("The selected server file is unavailable.") from exc
    if not path.is_file() or not os.access(path, os.R_OK):
        raise ClassroomError("The selected server file is unavailable.")
    with path.open("rb") as handle:
        kind, content_type = validate_asset_file(handle, name=path.name, size=path.stat().st_size)
    return ClassroomAsset.objects.create(
        owner=owner,
        source=ClassroomAsset.Source.SERVER_PATH,
        server_path=str(path),
        original_name=path.name,
        kind=kind,
        content_type=content_type,
        byte_size=path.stat().st_size,
    )


def open_asset(asset: ClassroomAsset) -> tuple[BinaryIO, int]:
    """Open and revalidate the current bytes; server references intentionally stay live."""
    if asset.source == ClassroomAsset.Source.UPLOAD:
        if not asset.content_file:
            raise ClassroomError("The uploaded file is unavailable.")
        handle = asset.content_file.open("rb")
        size = asset.content_file.size
    else:
        try:
            path = Path(asset.server_path).resolve(strict=True)
            if not path.is_file() or not os.access(path, os.R_OK):
                raise OSError
            size = path.stat().st_size
            handle = path.open("rb")
        except OSError as exc:
            raise ClassroomError("The referenced server file is unavailable.") from exc
    try:
        kind, content_type = validate_asset_file(handle, name=asset.original_name, size=size)
        if kind != asset.kind or content_type != asset.content_type:
            raise ClassroomError("The referenced file format has changed.")
        return handle, size
    except Exception:
        handle.close()
        raise


def discard_uploaded_asset(asset: ClassroomAsset) -> None:
    """Remove a newly stored upload when its enclosing command cannot complete."""
    if asset.source == ClassroomAsset.Source.UPLOAD and asset.content_file:
        asset.content_file.delete(save=False)
