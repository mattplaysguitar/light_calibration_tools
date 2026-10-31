from __future__ import annotations

from typing import Any

from .exceptions import MerossRemoteError


class MerossRemoteClient:
    """Cloud-control placeholder, deliberately separate from local LAN control."""

    def __init__(self, *, email: str | None = None, password: str | None = None, token: str | None = None):
        self.email = email
        self.password = password
        self.token = token

    def login(self) -> dict[str, Any]:
        raise MerossRemoteError("Remote Meross login is not implemented yet.")

    def get_state(self, device_id: str) -> dict[str, Any]:
        raise MerossRemoteError("Remote Meross reads are not implemented yet.")

    def set_on(self, device_id: str, on: bool) -> dict[str, Any]:
        raise MerossRemoteError("Remote Meross writes are not implemented yet.")

    def set_brightness(self, device_id: str, brightness: int) -> dict[str, Any]:
        raise MerossRemoteError("Remote Meross writes are not implemented yet.")

    def set_color_temperature(self, device_id: str, temperature: int) -> dict[str, Any]:
        raise MerossRemoteError("Remote Meross writes are not implemented yet.")
