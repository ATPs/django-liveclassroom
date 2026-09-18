"""Guard the requested source-file size limit for first-party code."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "frontend" / "src", ROOT / "src" / "liveclassroom", ROOT / "standalone", ROOT / "tests")
SOURCE_SUFFIXES = {".css", ".html", ".py", ".ts", ".tsx"}
GENERATED_OR_THIRD_PARTY = {
    ROOT / "src" / "liveclassroom" / "static" / "liveclassroom" / "app.js",
    ROOT / "src" / "liveclassroom" / "static" / "liveclassroom" / "pdf.worker.min.mjs",
}


def test_first_party_source_files_do_not_exceed_1500_lines():
    oversized: list[str] = []
    for source_root in SOURCE_ROOTS:
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if path in GENERATED_OR_THIRD_PARTY or "chunks" in path.parts:
                continue
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            if line_count > 1500:
                oversized.append(f"{path.relative_to(ROOT)} ({line_count} lines)")
    assert not oversized, "First-party source files exceed 1500 lines: " + ", ".join(oversized)
