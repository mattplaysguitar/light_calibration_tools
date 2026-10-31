from __future__ import annotations

import time
from typing import Literal

from .local import MerossLocalClient
from .remote import MerossRemoteClient


ControlMode = Literal["local", "remote"]


class MerossDevice:
    """Small import-friendly API for one Meross device.

    Use `mode="local"` with an IP address and Meross key for LAN control.
    Remote mode is intentionally isolated until cloud auth is verified.
    """

    def __init__(
        self,
        *,
        mode: ControlMode,
        host: str | None = None,
        key: str | None = None,
        device_id: str | None = None,
        local: MerossLocalClient | None = None,
        remote: MerossRemoteClient | None = None,
        channel: int = 0,
    ):
        self.mode = mode
        self.host = host
        self.device_id = device_id
        self.channel = channel
        self.local = local or (MerossLocalClient(host, key=key) if host else None)
        self.remote = remote

        if mode == "local" and self.local is None:
            raise ValueError("Local Meross devices require host or local client.")
        if mode == "remote" and (self.remote is None or self.device_id is None):
            raise ValueError("Remote Meross devices require remote client and device_id.")

    @classmethod
    def local_ip(cls, host: str, *, key: str | None = None, channel: int = 0) -> "MerossDevice":
        return cls(mode="local", host=host, key=key, channel=channel)

    @classmethod
    def remote_device(
        cls,
        device_id: str,
        remote: MerossRemoteClient,
        *,
        channel: int = 0,
    ) -> "MerossDevice":
        return cls(mode="remote", device_id=device_id, remote=remote, channel=channel)

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
            return self.local.set_on(on, channel=self.channel)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_on(self.device_id, on)

    def set_brightness(self, brightness: int) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_brightness(brightness, channel=self.channel)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_brightness(self.device_id, brightness)

    def set_rgb(self, red: int, green: int, blue: int, brightness: int | None = None) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_rgb(red, green, blue, brightness=brightness, channel=self.channel)
        raise NotImplementedError("Remote Meross RGB writes are not implemented yet.")

    def set_color(self, rgb: int, brightness: int | None = None) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_color(rgb, brightness=brightness, channel=self.channel)
        raise NotImplementedError("Remote Meross RGB writes are not implemented yet.")

    def set_color_temperature(self, temperature: int, brightness: int | None = None) -> dict:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_color_temperature(temperature, brightness=brightness, channel=self.channel)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_color_temperature(self.device_id, temperature)

    def blink(self, seconds: float = 5.0) -> None:
        try:
            self.turn_on()
            time.sleep(seconds)
        finally:
            self.turn_off()
