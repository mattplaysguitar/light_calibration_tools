from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import sys
import time
from pathlib import Path
from secrets import token_hex
from typing import Any

from .exceptions import MerossLocalError


DEFAULT_PORT = 80
DEFAULT_PATH = "/config"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

METHOD_GET = "GET"
METHOD_SET = "SET"

SYSTEM_ALL_NAMESPACE = "Appliance.System.All"
SYSTEM_ABILITY_NAMESPACE = "Appliance.System.Ability"
LIGHT_NAMESPACE = "Appliance.Control.Light"
TOGGLEX_NAMESPACE = "Appliance.Control.ToggleX"

ERROR_INVALID_KEY = 5001

LIGHT_CAPACITY_RGB = 1
LIGHT_CAPACITY_TEMPERATURE = 2
LIGHT_CAPACITY_LUMINANCE = 4
LIGHT_CAPACITY_RGB_LUMINANCE = LIGHT_CAPACITY_RGB | LIGHT_CAPACITY_LUMINANCE
LIGHT_CAPACITY_TEMPERATURE_LUMINANCE = LIGHT_CAPACITY_TEMPERATURE | LIGHT_CAPACITY_LUMINANCE


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def compute_signature(message_id: str, key: str, timestamp: int) -> str:
    material = f"{message_id}{key}{timestamp}".encode("utf-8")
    return hashlib.md5(material, usedforsecurity=False).hexdigest()


def build_message(namespace: str, method: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
    timestamp = int(time.time())
    message_id = token_hex(16)
    return {
        "header": {
            "messageId": message_id,
            "namespace": namespace,
            "method": method,
            "payloadVersion": 1,
            "triggerSrc": "MerossClient",
            "from": "MerossClient",
            "timestamp": timestamp,
            "timestampMs": 0,
            "sign": compute_signature(message_id, key, timestamp),
        },
        "payload": payload,
    }


def classify_meross_error(parsed: Any) -> tuple[int | None, str | None, str | None]:
    if not isinstance(parsed, dict):
        return None, None, None
    payload = parsed.get("payload")
    if not isinstance(payload, dict):
        return None, None, None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None, None, None

    code = error.get("code")
    detail = error.get("detail") or error.get("message")
    if code == ERROR_INVALID_KEY:
        kind = "Meross authentication/signature error"
    else:
        kind = "Device-side error"
    return code, str(detail) if detail is not None else None, kind


def send_meross_message(
    host: str,
    port: int,
    path: str,
    message: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    body = compact_json(message)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"meross-bulb-lab Python/{sys.version_info.major}.{sys.version_info.minor}",
    }
    conn = http.client.HTTPConnection(host, port=port, timeout=timeout)

    try:
        conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
        response = conn.getresponse()
        raw_bytes = response.read()
    except socket.timeout as exc:
        raise MerossLocalError(f"HTTP timeout: {exc}") from exc
    except ConnectionRefusedError as exc:
        raise MerossLocalError(f"TCP connection failure: {exc}") from exc
    except OSError as exc:
        raise MerossLocalError(f"TCP connection failure: {exc}") from exc
    except http.client.HTTPException as exc:
        raise MerossLocalError(f"HTTP protocol error: {exc}") from exc
    finally:
        conn.close()

    raw_body = raw_bytes.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError as exc:
        raise MerossLocalError(f"Meross response was not JSON: {raw_body!r}") from exc

    error_code, error_message, error_kind = classify_meross_error(parsed)
    if error_code is not None:
        detail = f"{error_kind}: code={error_code}"
        if error_message:
            detail = f"{detail}, message={error_message}"
        raise MerossLocalError(detail)

    if response.status < 200 or response.status >= 300:
        raise MerossLocalError(f"HTTP {response.status} {response.reason}: {raw_body}")

    if not isinstance(parsed, dict):
        raise MerossLocalError("Meross response was empty or not a JSON object")

    return parsed


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("'\"")
        if name and name not in os.environ:
            os.environ[name] = value


def load_key_from_env(name: str = "MEROSS_KEY") -> str | None:
    load_dotenv()
    return os.environ.get(name)


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _rgb_to_int(red: int, green: int, blue: int) -> int:
    red = max(0, min(255, int(red)))
    green = max(0, min(255, int(green)))
    blue = max(0, min(255, int(blue)))
    return (red << 16) | (green << 8) | blue


def _extract_payload(response: dict[str, Any], key: str) -> Any:
    payload = response.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload.get(key)


class MerossLocalClient:
    """Local LAN client for Meross HTTP control through /config."""

    def __init__(
        self,
        host: str,
        *,
        key: str | None = None,
        port: int = DEFAULT_PORT,
        path: str = DEFAULT_PATH,
        timeout: float = 5.0,
    ):
        self.host = host
        self.key = key if key is not None else load_key_from_env()
        self.port = port
        self.path = path
        self.timeout = timeout
        if not self.key:
            raise ValueError("Meross local control requires key or MEROSS_KEY.")

    def request(self, namespace: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.key is not None
        message = build_message(namespace, method, payload, self.key)
        return send_meross_message(self.host, self.port, self.path, message, self.timeout)

    def get(self, namespace: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request(namespace, METHOD_GET, payload)

    def set(self, namespace: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request(namespace, METHOD_SET, payload)

    def get_state(self) -> dict[str, Any]:
        light = self.get_light()
        togglex = self.get_togglex()
        return {
            "light": _extract_payload(light, "light"),
            "togglex": _extract_payload(togglex, "togglex"),
            "raw": {
                "light": light,
                "togglex": togglex,
            },
        }

    def get_system_all(self) -> dict[str, Any]:
        return self.get(SYSTEM_ALL_NAMESPACE, {"all": {}})

    def get_ability(self) -> dict[str, Any]:
        return self.get(SYSTEM_ABILITY_NAMESPACE, {"ability": {}})

    def get_light(self) -> dict[str, Any]:
        return self.get(LIGHT_NAMESPACE, {"light": {}})

    def get_togglex(self, channel: int = 0) -> dict[str, Any]:
        return self.get(TOGGLEX_NAMESPACE, {"togglex": [{"channel": int(channel)}]})

    def turn_on(self, channel: int = 0) -> dict[str, Any]:
        return self.set_on(True, channel=channel)

    def turn_off(self, channel: int = 0) -> dict[str, Any]:
        return self.set_on(False, channel=channel)

    def set_on(self, on: bool, channel: int = 0) -> dict[str, Any]:
        payload = {"togglex": {"channel": int(channel), "onoff": 1 if on else 0}}
        return self.set(TOGGLEX_NAMESPACE, payload)

    def set_light(self, light: dict[str, Any]) -> dict[str, Any]:
        normalized = {"channel": 0, **light}
        return self.set(LIGHT_NAMESPACE, {"light": normalized})

    def set_brightness(self, brightness: int, channel: int = 0) -> dict[str, Any]:
        brightness = _clamp_percent(brightness)
        if brightness == 0:
            return self.set_on(False, channel=channel)
        return self.set_light(
            {
                "channel": int(channel),
                "capacity": LIGHT_CAPACITY_LUMINANCE,
                "luminance": brightness,
                "transform": 0,
            }
        )

    def set_rgb(self, red: int, green: int, blue: int, brightness: int | None = None, channel: int = 0) -> dict[str, Any]:
        light = {
            "channel": int(channel),
            "capacity": LIGHT_CAPACITY_RGB,
            "rgb": _rgb_to_int(red, green, blue),
            "transform": 0,
        }
        if brightness is not None:
            light["capacity"] |= LIGHT_CAPACITY_LUMINANCE
            light["luminance"] = _clamp_percent(brightness)
        return self.set_light(light)

    def set_color(self, rgb: int, brightness: int | None = None, channel: int = 0) -> dict[str, Any]:
        rgb = max(0, min(0xFFFFFF, int(rgb)))
        light = {
            "channel": int(channel),
            "capacity": LIGHT_CAPACITY_RGB,
            "rgb": rgb,
            "transform": 0,
        }
        if brightness is not None:
            light["capacity"] |= LIGHT_CAPACITY_LUMINANCE
            light["luminance"] = _clamp_percent(brightness)
        return self.set_light(light)

    def set_color_temperature(self, temperature: int, brightness: int | None = None, channel: int = 0) -> dict[str, Any]:
        temperature = _clamp_percent(temperature)
        light = {
            "channel": int(channel),
            "capacity": LIGHT_CAPACITY_TEMPERATURE,
            "temperature": temperature,
            "transform": 0,
        }
        if brightness is not None:
            light["capacity"] |= LIGHT_CAPACITY_LUMINANCE
            light["luminance"] = _clamp_percent(brightness)
        return self.set_light(light)
