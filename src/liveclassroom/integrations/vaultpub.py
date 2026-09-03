"""Safe URL/reference adapter for the VaultPub Django portal."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from liveclassroom.providers import ContentReference, ProviderError

_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")


@dataclass
class VaultPubProvider:
    """Parse and embed portal Slide View URLs without exposing source paths."""

    key: str = "vaultpub"
    portal_prefix: str = "/database/vaultpub"
    grant_factory: object | None = None
    revoke_factory: object | None = None

    def parse_reference(self, url: str, *, request=None) -> ContentReference:
        """Return a structured registered-vault/share reference for one note."""
        if not isinstance(url, str) or not url.strip():
            raise ProviderError("A VaultPub URL is required.")
        try:
            parsed = urlsplit(url.strip())
        except ValueError as exc:
            # Documentation commonly uses ``[IP]`` as a literal host placeholder.
            # Treat it as the neutral host name ``IP`` while retaining the path.
            if "[IP]" not in url:
                raise ProviderError("Invalid VaultPub URL.") from exc
            try:
                parsed = urlsplit(url.replace("[IP]", "IP", 1))
            except ValueError as fallback_exc:
                raise ProviderError("Invalid VaultPub URL.") from fallback_exc
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise ProviderError("VaultPub URLs must use HTTP or HTTPS.")
        prefix = "/" + self.portal_prefix.strip("/")
        path = parsed.path or ""
        if path.startswith(prefix + "/"):
            remainder = path[len(prefix) + 1 :]
            parts = remainder.split("/")
            if len(parts) >= 4 and parts[0] == "vault" and parts[2] == "__slides__":
                alias, note_path = parts[1], unquote("/".join(parts[3:]))
                if not _ALIAS.fullmatch(alias):
                    raise ProviderError("The VaultPub vault alias is invalid.")
                return self._reference("vault", {"alias": alias, "note_path": self._note_path(note_path)}, parsed)
            if len(parts) >= 4 and parts[0] == "share" and parts[2] == "__slides__":
                token, note_path = parts[1], unquote("/".join(parts[3:]))
                if not token or len(token) > 255 or "/" in token:
                    raise ProviderError("The VaultPub share token is invalid.")
                return self._reference("share", {"token": token, "note_path": self._note_path(note_path)}, parsed)
        if path.startswith("/__slides__/"):
            note_path = self._note_path(unquote(path[len("/__slides__/") :]))
            return self._reference("standalone", {"note_path": note_path}, parsed)
        raise ProviderError("URL is not a VaultPub Slide View note.")

    def _note_path(self, value: str) -> str:
        """Normalize an encoded note path while rejecting traversal."""
        if not value or any(part in {"", ".", ".."} for part in value.split("/")):
            raise ProviderError("The VaultPub note path is invalid.")
        normalized = posixpath.normpath("/" + value).lstrip("/")
        if normalized != value or normalized.startswith("../"):
            raise ProviderError("The VaultPub note path is invalid.")
        return normalized

    def _reference(self, kind: str, fields: dict[str, str], parsed) -> ContentReference:
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "embed"]
        value = {**fields, "path": parsed.path, "query": query}
        if parsed.scheme and parsed.netloc:
            value["origin"] = f"{parsed.scheme}://{parsed.netloc}"
        return ContentReference(self.key, kind, value)

    def validate_reference(self, reference: ContentReference, *, request=None) -> ContentReference:
        """Re-parse canonical fields to reject references altered in storage."""
        if reference.provider != self.key or reference.kind not in {"vault", "share", "standalone"}:
            raise ProviderError("This is not a VaultPub reference.")
        note_path = self._note_path(str(reference.value.get("note_path", "")))
        fields = {key: str(value) for key, value in reference.value.items() if key in {"alias", "token", "note_path"}}
        fields["note_path"] = note_path
        origin = reference.value.get("origin")
        if origin:
            fields["origin"] = str(origin)
        return ContentReference(self.key, reference.kind, fields)

    def describe(self, reference: ContentReference, *, request=None) -> dict[str, object]:
        """Return safe metadata and a fingerprint for cue-point comparisons."""
        reference = self.validate_reference(reference, request=request)
        note_path = str(reference.value["note_path"])
        identity = {
            key: value
            for key, value in reference.value.items()
            if key in {"alias", "token", "note_path"}
        }
        canonical = json.dumps(
            {"kind": reference.kind, **identity}, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return {
            "provider": self.key,
            "kind": reference.kind,
            "title": note_path.rsplit("/", 1)[-1].removesuffix(".md"),
            "note_path": note_path,
            "source_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    def search(self, query: str, *, request=None) -> list[dict[str, object]]:
        """Leave discovery to the host portal, where vault permissions are available."""
        raise ProviderError("VaultPub search requires a host adapter.")

    def embed_url(self, reference: ContentReference, *, request=None) -> str:
        """Build a same-origin opt-in Slide View URL with no management query."""
        reference = self.validate_reference(reference, request=request)
        note_path = quote(str(reference.value["note_path"]), safe="/-._~")
        if reference.kind == "vault":
            path = f"{self.portal_prefix.rstrip('/')}/vault/{reference.value['alias']}/__slides__/{note_path}"
        elif reference.kind == "share":
            path = f"{self.portal_prefix.rstrip('/')}/share/{reference.value['token']}/__slides__/{note_path}"
        else:
            path = f"/__slides__/{note_path}"
        query = {"embed": "1"}
        # Keep the generated URL same-origin with the host page. A host adapter
        # can turn this relative path into an absolute URL after re-authorizing it.
        return urlunsplit(("", "", path, urlencode(query), ""))

    def grant_participant_access(
        self, reference: ContentReference, *, session, participant, request=None
    ) -> dict[str, object]:
        """Delegate protected grants to the host, never fabricate an authorization token."""
        if not callable(self.grant_factory):
            raise ProviderError("VaultPub participant grants require a host adapter.")
        return self.grant_factory(reference, session=session, participant=participant, request=request)

    def revoke_participant_access(self, grant: dict[str, object]) -> None:
        """Delegate revocation to the host adapter when one is configured."""
        if callable(self.revoke_factory):
            self.revoke_factory(grant)
