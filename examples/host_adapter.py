"""Minimal host-adapter configuration example.

Configure the dotted path in Django settings::

    LIVECLASSROOM = {"HOST_ADAPTER": "myproject.liveclassroom.HostAdapter"}

The example intentionally contains no host-model imports.  A real adapter
should resolve the current request actor and recheck each sensitive action.
"""

from liveclassroom.integrations.host import DefaultHostAdapter


class HostAdapter(DefaultHostAdapter):
    """Replace these methods with host-owned course and roster policy."""

    def can_author(self, *, actor, resource) -> bool:
        return super().can_author(actor=actor, resource=resource)
