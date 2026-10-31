from __future__ import annotations

import json
import re
import select
import signal
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Literal


ALC_PORT = 12345
HAP_SERVICE_TYPE = "_hap._tcp"
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class VocolincError(RuntimeError):
    pass


class VocolincLocalError(VocolincError):
    pass


class VocolincRemoteError(VocolincError):
    pass


@dataclass(frozen=True)
class VocolincService:
    name: str
    service_type: str
    host: str | None = None
    hap_port: int | None = None
    ip: str | None = None
    txt: dict[str, str] | None = None

    @property
    def alc_configured(self) -> bool:
        return _txt_flag_configured(self.txt or {}, "alc2")

    @property
    def aws_configured(self) -> bool:
        return _txt_flag_configured(self.txt or {}, "aws")


def alc_encode(message: str | dict[str, Any]) -> bytes:
    if isinstance(message, dict):
        message = json.dumps(message, separators=(",", ":"), ensure_ascii=True)

    payload = message.encode("utf-8")
    out = bytearray(b"ALC\x00")
    out.extend(struct.pack("<I", len(payload)))

    previous = 28
    for plain_byte in payload:
        out.append(previous ^ plain_byte)
        previous = plain_byte

    return bytes(out)


def alc_decode(packet: bytes) -> str:
    if len(packet) < 8:
        raise VocolincLocalError("ALC packet is shorter than 8 byte header")

    length = struct.unpack("<I", packet[4:8])[0]
    encrypted = packet[8:]
    if len(encrypted) != length:
        raise VocolincLocalError(f"ALC payload length mismatch: expected {length}, got {len(encrypted)}")

    decoded = bytearray()
    previous = 28
    for encrypted_byte in encrypted:
        plain_byte = previous ^ encrypted_byte
        decoded.append(plain_byte)
        previous = plain_byte

    return decoded.decode("utf-8")


def alc_request(host: str, message: str | dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    raw_request = alc_encode(message)

    with socket.create_connection((host, ALC_PORT), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(raw_request)
        raw_response = _recv_alc_packet(sock)

    decoded = alc_decode(raw_response)
    try:
        return json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise VocolincLocalError(f"ALC response was not JSON: {decoded!r}") from exc


class VocolincLocalClient:
    """Local LAN client for VOCOlinc ALC TCP control on port 12345."""

    def __init__(self, host: str, timeout: float = 5.0):
        self.host = host
        self.timeout = timeout

    def request(self, message: str | dict[str, Any]) -> dict[str, Any]:
        return alc_request(self.host, message, timeout=self.timeout)

    def get_state(self) -> dict[str, Any]:
        return self.request({"op": "get"})

    def put_state(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.request({"op": "put", "state": state})

    def query(self, query: str) -> dict[str, Any]:
        return self.request({"op": "query", "query": query})

    def turn_on(self, service_id: str = "0") -> dict[str, Any]:
        return self.set_on(True, service_id=service_id)

    def turn_off(self, service_id: str = "0") -> dict[str, Any]:
        return self.set_on(False, service_id=service_id)

    def set_on(self, on: bool, service_id: str = "0") -> dict[str, Any]:
        return self.put_state({f"switch{service_id}": bool(on)})

    def set_brightness(self, brightness: int, service_id: str = "0") -> dict[str, Any]:
        brightness = max(0, min(100, int(brightness)))
        state: dict[str, Any] = {f"level{service_id}": brightness}
        if brightness == 0:
            state[f"switch{service_id}"] = False
        elif brightness > 0:
            state[f"switch{service_id}"] = True
        return self.put_state(state)

    def set_color_temperature(self, mired: int, service_id: str = "0") -> dict[str, Any]:
        return self.put_state({f"k{service_id}": int(mired), "effect_mode": 0})


class VocolincRemoteClient:
    """Remote/cloud API placeholder, deliberately separate from local control."""

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


ControlMode = Literal["local", "remote"]


class VocolincDevice:
    """Simple API for one VOCOlinc device."""

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

    def get_state(self) -> dict[str, Any]:
        if self.mode == "local":
            assert self.local is not None
            return self.local.get_state()
        assert self.remote is not None and self.device_id is not None
        return self.remote.get_state(self.device_id)

    def turn_on(self) -> dict[str, Any]:
        return self.set_on(True)

    def turn_off(self) -> dict[str, Any]:
        return self.set_on(False)

    def set_on(self, on: bool) -> dict[str, Any]:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_on(on, service_id=self.service_id)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_on(self.device_id, on)

    def set_brightness(self, brightness: int) -> dict[str, Any]:
        if self.mode == "local":
            assert self.local is not None
            return self.local.set_brightness(brightness, service_id=self.service_id)
        assert self.remote is not None and self.device_id is not None
        return self.remote.set_brightness(self.device_id, brightness)

    def set_color_temperature(self, mired: int) -> dict[str, Any]:
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


def discover_vocolinc(seconds: float = 3.0, model: str | None = None) -> list[VocolincService]:
    services = []
    for service_name in _browse_hap_names(seconds):
        if not service_name.startswith("VOCOlinc-"):
            continue

        resolved = _resolve_hap_service(service_name, seconds=min(seconds, 1.5))
        if resolved is None:
            services.append(VocolincService(name=service_name, service_type=HAP_SERVICE_TYPE))
            continue

        if model is not None and resolved.txt and resolved.txt.get("md") != model:
            continue

        services.append(resolved)

    return services


def print_discovered(services: list[VocolincService]) -> None:
    for service in services:
        print(f"{service.name}")
        print(f"  host: {service.host}")
        print(f"  hap port: {service.hap_port}")
        print(f"  ip: {service.ip}")
        print(f"  model: {(service.txt or {}).get('md')}")
        print(f"  alc configured: {service.alc_configured}")
        print(f"  aws configured: {service.aws_configured}")


def java_string_hashcode(value: str) -> int:
    result = 0
    for char in value:
        result = (31 * result + ord(char)) & 0xFFFFFFFF
    if result >= 0x80000000:
        result -= 0x100000000
    return result


def user_id_from_email(email: str) -> str:
    return str(java_string_hashcode(email.lower()))


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise VocolincLocalError("Socket closed before full ALC packet arrived")
        chunks.extend(chunk)
    return bytes(chunks)


def _recv_alc_packet(sock: socket.socket) -> bytes:
    header = _recv_exact(sock, 8)
    length = struct.unpack("<I", header[4:8])[0]
    return header + _recv_exact(sock, length)


def _txt_flag_configured(txt: dict[str, str], key: str) -> bool:
    value = txt.get(key)
    if value is None or value == "":
        return False
    try:
        return (int(value) & 1) == 0
    except ValueError:
        return False


def _run_dns_sd(args: list[str], seconds: float, stop_pattern: str | None = None) -> str:
    try:
        process = subprocess.Popen(
            ["dns-sd", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        raise VocolincLocalError("dns-sd is required for Bonjour discovery on macOS") from exc

    deadline = time.monotonic() + seconds
    output = []
    stop_re = re.compile(stop_pattern) if stop_pattern else None
    assert process.stdout is not None

    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.1)
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            break
        output.append(line)
        if stop_re and stop_re.search("".join(output)):
            break

    process.send_signal(signal.SIGINT)
    try:
        trailing, _ = process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        trailing, _ = process.communicate()
    output.append(trailing or "")
    return "".join(output)


def _browse_hap_names(seconds: float) -> list[str]:
    output = _run_dns_sd(["-B", HAP_SERVICE_TYPE, "local"], seconds)
    names = set()
    for line in output.splitlines():
        if " Add " not in line or "_hap._tcp" not in line:
            continue
        match = re.search(r"\slocal\.\s+_hap\._tcp\.\s+(.+)$", line)
        if match:
            names.add(match.group(1).strip())
    return sorted(names)


def _resolve_hap_service(service_name: str, seconds: float) -> VocolincService | None:
    output = _run_dns_sd(
        ["-L", service_name, HAP_SERVICE_TYPE, "local"],
        seconds,
        stop_pattern=r"can be reached at",
    )
    host = None
    port = None
    txt: dict[str, str] = {}

    for line in output.splitlines():
        match = re.search(r"can be reached at\s+(.+?)\.?:([0-9]+)", line)
        if match:
            host = _decode_dns_sd_escapes(match.group(1).rstrip("."))
            port = int(match.group(2))
            continue

        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("Lookup "):
            txt.update(_parse_txt_line(stripped))

    if not host:
        return None

    ip = _resolve_ipv4(host, seconds)
    return VocolincService(
        name=service_name,
        service_type=HAP_SERVICE_TYPE,
        host=host,
        hap_port=port,
        ip=ip,
        txt=txt,
    )


def _resolve_ipv4(host: str, seconds: float) -> str | None:
    try:
        return socket.gethostbyname(host)
    except OSError:
        pass

    output = _run_dns_sd(["-G", "v4", host], seconds, stop_pattern=IPV4_RE.pattern)
    match = IPV4_RE.search(output)
    if match:
        return match.group(0)
    return None


def _parse_txt_line(line: str) -> dict[str, str]:
    txt = {}
    for part in line.split():
        if "=" in part:
            key, value = part.split("=", 1)
            txt[key] = value
    return txt


def _decode_dns_sd_escapes(value: str) -> str:
    return re.sub(r"\\([0-9]{3})", lambda match: chr(int(match.group(1), 10)), value)
