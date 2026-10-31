import argparse
import ipaddress
import json
import os
import re
import select
import signal
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from meross_probe import (
    DEFAULT_PATH,
    DEFAULT_PORT,
    ERROR_INVALID_KEY,
    METHOD_GET,
    build_message,
    load_dotenv,
    pretty_json,
    send_meross_message,
)


DISCOVERY_NAMESPACE = "Appliance.System.All"
DISCOVERY_PAYLOAD = {"all": {}}
DISCOVERY_OUTPUT = Path(__file__).resolve().parent / "captures" / "discovered_devices.json"
LOCAL_NAMES_PATH = Path(__file__).resolve().parent / "local_names.json"
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def resolve_local_names(host: str) -> list[str]:
    names = set()

    try:
        name, _, aliases = socket.gethostbyaddr(host)
    except OSError:
        pass
    else:
        names.add(name.rstrip("."))
        names.update(alias.rstrip(".") for alias in aliases if alias)

    try:
        name = socket.getnameinfo((host, 0), socket.NI_NAMEREQD)
    except OSError:
        pass
    else:
        names.add(name[0].rstrip("."))

    fqdn = socket.getfqdn(host).rstrip(".")
    if fqdn and fqdn != host:
        names.add(fqdn)

    return sorted(names)


def add_name(name_map: dict[str, set[str]], ip_address: str, name: str) -> None:
    clean_name = name.strip().rstrip(".")
    if not clean_name or clean_name == "?" or clean_name == ip_address:
        return
    name_map.setdefault(ip_address, set()).add(clean_name)


def collect_arp_names() -> dict[str, set[str]]:
    name_map: dict[str, set[str]] = {}
    try:
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return name_map

    for line in result.stdout.splitlines():
        match = re.match(r"^(.+?) \(((?:\d{1,3}\.){3}\d{1,3})\) at ", line)
        if not match:
            continue
        name, ip_address = match.groups()
        add_name(name_map, ip_address, name)
    return name_map


def collect_configured_names(path: Path = LOCAL_NAMES_PATH) -> dict[str, set[str]]:
    name_map: dict[str, set[str]] = {}
    if not path.exists():
        return name_map

    try:
        configured = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return name_map

    if not isinstance(configured, dict):
        return name_map

    for ip_address, names in configured.items():
        if isinstance(names, str):
            add_name(name_map, ip_address, names)
        elif isinstance(names, list):
            for name in names:
                if isinstance(name, str):
                    add_name(name_map, ip_address, name)
    return name_map


def run_dns_sd(args: list[str], seconds: float, stop_pattern: str | None = None) -> str:
    try:
        process = subprocess.Popen(
            ["dns-sd", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError:
        return ""

    deadline = time.monotonic() + seconds
    output_parts = []
    compiled_stop = re.compile(stop_pattern) if stop_pattern else None
    assert process.stdout is not None

    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.1)
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            break
        output_parts.append(line)
        if compiled_stop and compiled_stop.search("".join(output_parts)):
            break

    process.send_signal(signal.SIGINT)
    try:
        trailing_output, _ = process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        trailing_output, _ = process.communicate()
    output_parts.append(trailing_output or "")
    return "".join(output_parts)


def browse_hap_service_names(seconds: float) -> list[str]:
    output = run_dns_sd(["-B", "_hap._tcp", "local"], seconds)
    services = []
    for line in output.splitlines():
        if " Add " not in line or "_hap._tcp" not in line:
            continue
        match = re.search(r"\slocal\.\s+_hap\._tcp\.\s+(.+)$", line)
        if match:
            services.append(match.group(1).strip())
    return sorted(set(services))


def resolve_service_target(service_name: str, seconds: float) -> tuple[str | None, int | None]:
    output = run_dns_sd(["-L", service_name, "_hap._tcp", "local"], seconds, stop_pattern=r"can be reached at")
    for line in output.splitlines():
        match = re.search(r"can be reached at\s+(.+?)\.?:([0-9]+)", line)
        if match:
            host_name, port = match.groups()
            return host_name.rstrip("."), int(port)
    return None, None


def resolve_mdns_ipv4(host_name: str, seconds: float) -> str | None:
    output = run_dns_sd(["-G", "v4", host_name], seconds, stop_pattern=IPV4_RE.pattern)
    for line in output.splitlines():
        match = IPV4_RE.search(line)
        if match:
            return match.group(0)
    return None


def collect_hap_mdns_records(seconds: float, limit: int) -> list[dict[str, Any]]:
    records = []
    if seconds <= 0:
        return records

    resolve_seconds = min(seconds, 1.0)
    for service_name in browse_hap_service_names(seconds)[:limit]:
        host_name, _ = resolve_service_target(service_name, resolve_seconds)
        if not host_name:
            continue
        ip_address = resolve_mdns_ipv4(host_name, resolve_seconds)
        if not ip_address:
            continue
        records.append({
            "service": f"{service_name}._hap._tcp.local",
            "host": host_name,
            "ip": ip_address,
            "type": "_hap._tcp",
        })
    return records


def collect_hap_mdns_names(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    name_map: dict[str, set[str]] = {}
    for record in records:
        ip_address = record["ip"]
        add_name(name_map, ip_address, record["host"])
        add_name(name_map, ip_address, record["service"])
    return name_map


def collect_local_name_map(hap_records: list[dict[str, Any]]) -> dict[str, set[str]]:
    name_map = collect_configured_names()
    for ip_address, names in collect_arp_names().items():
        name_map.setdefault(ip_address, set()).update(names)
    for ip_address, names in collect_hap_mdns_names(hap_records).items():
        name_map.setdefault(ip_address, set()).update(names)
    return name_map


def parse_args():
    parser = argparse.ArgumentParser(description="Read-only LAN discovery for Meross HTTP devices.")
    parser.add_argument("--subnet", default="10.0.1.0/24", help="CIDR subnet to scan. Default: 10.0.1.0/24")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port. Default: {DEFAULT_PORT}")
    parser.add_argument("--path", default=DEFAULT_PATH, help=f"Meross HTTP path. Default: {DEFAULT_PATH}")
    parser.add_argument("--timeout", type=float, default=0.75, help="Per-host HTTP timeout in seconds.")
    parser.add_argument("--workers", type=int, default=32, help="Concurrent scan workers.")
    parser.add_argument("--mdns-seconds", type=float, default=3.0, help="Seconds to browse _hap._tcp mDNS names before scanning.")
    parser.add_argument("--mdns-service-limit", type=int, default=5, help="Maximum _hap._tcp services to resolve.")
    parser.add_argument("--key", help="Meross device/account key. Prefer MEROSS_KEY or .env instead.")
    return parser.parse_args()


def summarize_device(host: str, response: dict[str, Any], local_name_map: dict[str, set[str]]) -> dict[str, Any] | None:
    parsed = response.get("parsed_json")
    if not isinstance(parsed, dict):
        return None

    header = parsed.get("header", {})
    payload = parsed.get("payload", {})
    all_payload = payload.get("all", {}) if isinstance(payload, dict) else {}
    system = all_payload.get("system", {}) if isinstance(all_payload, dict) else {}
    digest = all_payload.get("digest", {}) if isinstance(all_payload, dict) else {}
    hardware = system.get("hardware", {}) if isinstance(system, dict) else {}
    firmware = system.get("firmware", {}) if isinstance(system, dict) else {}

    device_type = hardware.get("type")
    uuid = hardware.get("uuid") or header.get("uuid")
    if not device_type and not uuid:
        return None

    local_names = set(resolve_local_names(host))
    local_names.update(local_name_map.get(host, set()))

    return {
        "host": host,
        "localNames": sorted(local_names),
        "uuid": uuid,
        "type": device_type,
        "subType": hardware.get("subType"),
        "hardwareVersion": hardware.get("version"),
        "firmwareVersion": firmware.get("version"),
        "homekitVersion": firmware.get("homekitVersion"),
        "innerIp": firmware.get("innerIp"),
        "macAddress": hardware.get("macAddress"),
        "wifiMac": firmware.get("wifiMac"),
        "light": digest.get("light") if isinstance(digest, dict) else None,
        "togglex": digest.get("togglex") if isinstance(digest, dict) else None,
    }


def probe_host(host: str, port: int, path: str, timeout: float, key: str, local_name_map: dict[str, set[str]]) -> dict[str, Any] | None:
    message = build_message(DISCOVERY_NAMESPACE, METHOD_GET, DISCOVERY_PAYLOAD, key)
    try:
        response = send_meross_message(host, port, path, message, timeout)
    except Exception:
        return None

    if response.get("meross_error_code") == ERROR_INVALID_KEY:
        return {
            "host": host,
            "error": "Meross authentication/signature error",
            "detail": response.get("meross_error_message"),
        }

    if response.get("http_status") != 200 or response.get("parse_error"):
        return None

    return summarize_device(host, response, local_name_map)


def main() -> int:
    load_dotenv()
    args = parse_args()
    key = args.key if args.key is not None else os.environ.get("MEROSS_KEY")
    if not key:
        print("No Meross key was provided, so no discovery requests were sent.")
        print("Set MEROSS_KEY in .env or pass --key.")
        return 2

    network = ipaddress.ip_network(args.subnet, strict=False)
    hosts = [str(host) for host in network.hosts()]
    hap_records = collect_hap_mdns_records(args.mdns_seconds, args.mdns_service_limit)
    local_name_map = collect_local_name_map(hap_records)
    print(f"Scanning {len(hosts)} hosts on {network} with read-only {DISCOVERY_NAMESPACE} requests.")
    print("The key is loaded but will not be printed.")
    if hap_records:
        print("Bonjour _hap._tcp services:")
        for record in hap_records:
            print(f"{record['ip']}: {record['host']} [{record['service']}]")
    if local_name_map:
        print(f"Loaded local names for {len(local_name_map)} LAN address(es).")
        for ip_address in sorted(local_name_map, key=lambda value: tuple(int(part) for part in value.split("."))):
            print(f"{ip_address}: {', '.join(sorted(local_name_map[ip_address]))}")

    found: list[dict[str, Any]] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(probe_host, host, args.port, args.path, args.timeout, key, local_name_map): host
            for host in hosts
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                found.append(result)
                if "error" in result:
                    print(f"{result['host']}: {result['error']}")
                else:
                    names = ", ".join(result.get("localNames") or [])
                    suffix = f" [{names}]" if names else ""
                    print(f"{result['host']}: {result.get('type')} {result.get('uuid')}{suffix}")

    found.sort(key=lambda item: tuple(int(part) for part in item["host"].split(".")))
    DISCOVERY_OUTPUT.parent.mkdir(exist_ok=True)
    DISCOVERY_OUTPUT.write_text(pretty_json({
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "subnet": str(network),
        "localNameSources": ["local_names.json", "reverse-dns", "getnameinfo", "getfqdn", "arp", "_hap._tcp mdns"],
        "bonjourServices": hap_records,
        "count": len(found),
        "devices": found,
    }) + "\n", encoding="utf-8")

    print(f"Found {len(found)} candidate Meross device(s) in {round(time.monotonic() - started, 2)} seconds.")
    print(f"Saved discovery results: {DISCOVERY_OUTPUT}")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
