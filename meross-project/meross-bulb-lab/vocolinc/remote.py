from __future__ import annotations

from typing import Any

from .exceptions import VocolincRemoteError


class VocolincRemoteClient:
    """Cloud-control client placeholder.

    This is intentionally separate from local LAN control. It does not implement
    login or cloud writes until the VOCOlinc cloud endpoints and signing scheme
    have been verified from source or traffic captures.
    """

    def __init__(self, *, email: str | None = None, password: str | None = None, token: str | None = None):
        self.email = email
        self.password = password
        self.token = token

    def login(self) -> dict[str, Any]:
        raise VocolincRemoteError("Remote VOCOlinc login is not implemented yet.")

    def get_state(self, device_id: str) -> dict[str, Any]:
        raise VocolincRemoteError("Remote VOCOlinc reads are not implemented yet.")

    def set_on(self, device_id: str, on: bool) -> dict[str, Any]:
        raise VocolincRemoteError("Remote VOCOlinc writes are not implemented yet.")

    def set_brightness(self, device_id: str, brightness: int) -> dict[str, Any]:
        raise VocolincRemoteError("Remote VOCOlinc writes are not implemented yet.")

    def set_color_temperature(self, device_id: str, mired: int) -> dict[str, Any]:
        raise VocolincRemoteError("Remote VOCOlinc writes are not implemented yet.")
