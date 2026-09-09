"""Optional standalone profile enabling in-process VaultPub document rendering."""

from .settings import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "vaultpub.django_app"]  # noqa: F405
