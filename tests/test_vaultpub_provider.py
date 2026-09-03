import pytest

from liveclassroom.integrations.vaultpub import VaultPubProvider
from liveclassroom.providers import ContentReference, ProviderError


def test_registered_vault_reference_decodes_unicode_and_embeds_without_management_routes():
    provider = VaultPubProvider()
    reference = provider.parse_reference(
        "http://[IP]:9000/database/vaultpub/vault/server/__slides__/general/"
        "XCLabServer001%20%E5%9E%8B%E5%8F%B7.md"
    )

    assert reference.kind == "vault"
    assert reference.value["alias"] == "server"
    assert reference.value["note_path"] == "general/XCLabServer001 " + chr(0x578B) + chr(0x53F7) + ".md"
    assert provider.embed_url(reference).endswith("/__slides__/general/XCLabServer001%20%E5%9E%8B%E5%8F%B7.md?embed=1")
    assert "/api/" not in provider.embed_url(reference)


def test_share_and_standalone_references_are_scoped():
    provider = VaultPubProvider()
    share = provider.parse_reference("/database/vaultpub/share/abc123/__slides__/Deck.md")
    standalone = provider.parse_reference("/__slides__/Deck.md")
    assert share.kind == "share"
    assert standalone.kind == "standalone"
    with pytest.raises(ProviderError):
        provider.parse_reference("/database/vaultpub/vault/server/__slides__/../Secret.md")


def test_protected_grants_require_host_callback():
    provider = VaultPubProvider()
    reference = ContentReference("vaultpub", "share", {"token": "abc", "note_path": "Deck.md"})
    with pytest.raises(ProviderError, match="host adapter"):
        provider.grant_participant_access(reference, session=object(), participant=object())
