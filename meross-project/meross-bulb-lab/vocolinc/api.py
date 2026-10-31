from __future__ import annotations

import time
from typing import Literal

from .local import VocolincLocalClient
from .remote import VocolincRemoteClient


ControlMode = Literal["local", "remote"]


class VocolincDevice:
    """Small import-friendly API for one VOCOlinc device.

    Use `mode="local"` with an IP address for LAN ALC control.
    Use `mode="remote"` later when cloud support is implemented.
    """

    def __init__(
        self,
        *,
        mode: ControlMode,
        host: str | None = None,
        device_id: str | None = None,
        local: VocolincLocalClient | None = None,
        remote: VocolincRemoteClient | None = None,
        service_id: str = "0",
    ):
        self.mode = mode
        self.host = host
        self.device_id = device_id
        self.service_id = service_id
        self.local = local or (VocolincLocalClient(host) if host else None)
        self.remote = remote

        if mode == "local" and self.local is None:
            raise ValueError("Local VOCOlinc devices require host or local client.")
        if mode == "remote" and (self.remote is None or self.device_id is None):
            raise ValueError("Remote VOCOlinc devices require remote client and device_id.")

    @classmethod
    def local_ip(cls, host: str, *, service_id: str = "0") -> "VocolincDevice":
        return cls(mode="local", host=host, service_id=service_id)

    @classmethod
    def remote_device(
        cls,
        device_id: str,
        remote: VocolincRemoteClient,
        *,
        service_id: str = "0",
    ) -> "VocolincDevice":
        return cls(mode="remote", device_id=device_id, remote=remote, service_id=service_id)

    def get_state(self) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.get_state()
        assert self.remote is not None and self.device_id is not None
        return self.remote.get_state(self.device_id)

    def turn_on(self) -> dict:
        return self.set_on(True)

    def turn_off(self) -> dict:
        return self.set_on(False)

    def set_on(self, on: bool) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_on(on, service_id=self.service_id)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_on(self.device_id, on)

    def set_brightness(self, brightness: int) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_brightness(brightness, service_id=self.service_id)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_brightness(self.device_id, brightness)

    def set_color_temperature(self, mired: int) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_color_temperature(mired, service_id=self.service_id)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_color_temperature(self.device_id, mired)

    def blink(self, seconds: float = 5.0) -> None:
        try:
            self.turn_on()
            time.sleep(seconds)
        finally:
            self.turn_off()
