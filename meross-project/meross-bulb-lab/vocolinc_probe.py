import argparse
import http.client
import json
import socket
import time
from pathlib import Path
from typing import Any


DEFAULT_HOST = "10.0.1.4"
DEFAULT_PORT = 8080
CAPTURE_DIR = Path(__file__).resolve().parent / "captures" / "vocolinc"

KNOWN_MDNS = {
    "service": "VOCOlinc-DL2201-1ea079._hap._tcp.local",
    "host": "VOCOlinc-DL2201-1ea079.local",
    "port": 8080,
    "txt": {
        "c#": "1",
        "ff": "2",
        "id": "0E:E6:28:E9:74:75",
        "md": "DL2201",
        "pv": "1.1",
        "s#": "34",
        "sf": "0",
        "ci": "5",
        "sh": "v4Igeg==",
        "aws": "0",
        "alc2": "0",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description="Unauthenticated read-only HAP probe for VOCOlinc DL2201.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Accessory IP/host. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HAP TCP port. Default: {DEFAULT_PORT}")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    return parser.parse_args()


def pretty_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def tcp_check(host: str, port: int, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "elapsed_ms": round((time.monotonic() - started) * 1000, 3)}
    except OSError as exc:
        return {
            "ok": False,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        }


def http_get(host: str, port: int, path: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    conn = http.client.HTTPConnection(host, port=port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"User-Agent": "meross-bulb-lab-vocolinc-probe"})
        response = conn.getresponse()
        body = response.read().decode("utf-8", errors="replace")
        parsed = None
        parse_error = None
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
        return {
            "path": path,
            "http_status": response.status,
            "http_reason": response.reason,
            "headers": dict(response.getheaders()),
            "raw_body": body,
            "parsed_json": parsed,
            "parse_error": parse_error,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        }
    except OSError as exc:
        return {
            "path": path,
            "transport_error_type": exc.__class__.__name__,
            "transport_error": str(exc),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        }
    finally:
        conn.close()


def save_capture(record: dict[str, Any]) -> Path:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = CAPTURE_DIR / f"{stamp}_unauthenticated_probe.json"
    path.write_text(pretty_json(record) + "\n", encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    print("Known HAP Bonjour advertisement:")
    print(pretty_json(KNOWN_MDNS))
    print()

    print(f"TCP connectivity check: {args.host}:{args.port}")
    tcp = tcp_check(args.host, args.port, args.timeout)
    print(pretty_json(tcp))
    print()

    # GET /accessories is the normal HAP accessory database read endpoint.
    # On a paired accessory, an unauthenticated client is expected to be rejected.
    requests = [
        http_get(args.host, args.port, "/accessories", args.timeout),
        http_get(args.host, args.port, "/characteristics?id=1.1", args.timeout),
    ]

    for result in requests:
        print("=" * 80)
        print(f"GET {result['path']}")
        print(f"HTTP status: {result.get('http_status')} {result.get('http_reason')}")
        if result.get("transport_error"):
            print(f"Transport error: {result['transport_error_type']}: {result['transport_error']}")
        print("Headers:")
        print(pretty_json(result.get("headers")))
        print("Raw body:")
        print(result.get("raw_body") or "<empty>")
        print("Parsed JSON:")
        print(pretty_json(result.get("parsed_json")) if result.get("parsed_json") is not None else "<none>")
        print(f"Parse error: {result.get('parse_error')}")
        print(f"Elapsed: {result.get('elapsed_ms')} ms")

    capture = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mdns": KNOWN_MDNS,
        "target": {"host": args.host, "port": args.port},
        "tcp": tcp,
        "http_gets": requests,
        "safety": {
            "pair_setup_attempted": False,
            "pairings_endpoint_touched": False,
            "control_writes_sent": False,
            "pairing_state_modified": False,
        },
    }
    capture_path = save_capture(capture)
    print()
    print(f"Saved capture: {capture_path}")
    return 0 if tcp.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
