import argparse
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


DEFAULT_HOST = "10.0.1.9"
DEFAULT_PORT = 80
DEFAULT_PATH = "/config"
CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
ENV_PATH = Path(__file__).resolve().parent / ".env"

METHOD_GET = "GET"
METHOD_SET = "SET"
ERROR_INVALID_KEY = 5001

REQUESTS = [
    ("system_ability", "Appliance.System.Ability", {"ability": {}}),
    ("system_all", "Appliance.System.All", {"all": {}}),
    ("control_light", "Appliance.Control.Light", {"light": {}}),
]

DUMP_REQUESTS = [
    ("system_hardware", "Appliance.System.Hardware", {"hardware": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("system_firmware", "Appliance.System.Firmware", {"firmware": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("system_debug", "Appliance.System.Debug", {"debug": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("system_online", "Appliance.System.Online", {"online": {}}, True, "meross_lan ARGS_GETPUSH / P_DICT"),
    ("system_time", "Appliance.System.Time", {"time": {}}, True, "meross_lan ARGS_GETPUSH / P_DICT"),
    ("system_clock", "Appliance.System.Clock", {"clock": {}}, False, "meross_lan ARGS_PUSHQ; no direct GET declared"),
    ("system_runtime", "Appliance.System.Runtime", {"runtime": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("system_position", "Appliance.System.Position", {"position": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("system_report", "Appliance.System.Report", {"report": {}}, False, "meross_lan ARGS_PUSH; no direct GET declared"),
    ("control_light", "Appliance.Control.Light", {"light": {}}, True, "meross_lan ARGS_GETSETPUSH / P_DICT"),
    ("control_togglex", "Appliance.Control.ToggleX", {"togglex": {}}, True, "meross_lan ARGS_GETSETPUSH / P_DICT"),
    ("control_overtemp", "Appliance.Control.OverTemp", {"overTemp": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("config_info", "Appliance.Config.Info", {"info": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("config_overtemp", "Appliance.Config.OverTemp", {"overTemp": {}}, True, "meross_lan ARGS_GET / P_DICT"),
    ("config_trace", "Appliance.Config.Trace", {"trace": {}}, False, "meross_lan ARGS_NO_Q; no direct GET declared"),
]

INTERESTING_FIELD_NAMES = {
    "capacity",
    "rgb",
    "temperature",
    "luminance",
    "transform",
    "onoff",
    "overTemp",
    "overtemp",
    "runtime",
    "signal",
    "mem",
    "memory",
    "uptime",
    "chipType",
    "uuid",
    "macAddress",
    "wifiMac",
    "version",
    "compileTime",
    "homekitVersion",
    "encrypt",
    "innerIp",
    "server",
    "port",
    "sysStatus",
    "apiStatus",
}


class ProbeError(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def pretty_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


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
    start = time.monotonic()
    conn = http.client.HTTPConnection(host, port=port, timeout=timeout)

    try:
        conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
        response = conn.getresponse()
        raw_bytes = response.read()
    except socket.timeout as exc:
        raise ProbeError("HTTP timeout", str(exc)) from exc
    except ConnectionRefusedError as exc:
        raise ProbeError("TCP connection failure", str(exc)) from exc
    except OSError as exc:
        raise ProbeError("TCP connection failure", str(exc)) from exc
    except http.client.HTTPException as exc:
        raise ProbeError("HTTP protocol error", str(exc)) from exc
    finally:
        conn.close()

    elapsed_ms = round((time.monotonic() - start) * 1000, 3)
    raw_body = raw_bytes.decode("utf-8", errors="replace")
    response_headers = dict(response.getheaders())

    parsed = None
    parse_error = None
    if not raw_body:
        parse_error = "Empty response"
    else:
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            parse_error = f"Invalid JSON: {exc}"

    error_code, error_message, meross_error_kind = classify_meross_error(parsed)
    return {
        "http_status": response.status,
        "http_reason": response.reason,
        "response_headers": response_headers,
        "raw_body": raw_body,
        "parsed_json": parsed,
        "parse_error": parse_error,
        "meross_error_code": error_code,
        "meross_error_message": error_message,
        "meross_error_kind": meross_error_kind,
        "elapsed_ms": elapsed_ms,
    }


def safe_host_dirname(host: str) -> str:
    return host.replace(":", "_").replace("/", "_")


def save_capture(name: str, record: dict[str, Any], host: str | None = None) -> Path:
    capture_dir = CAPTURE_DIR / safe_host_dirname(host) if host else CAPTURE_DIR
    capture_dir.mkdir(parents=True, exist_ok=True)
    path = capture_dir / f"{name}.json"
    path.write_text(pretty_json(record) + "\n", encoding="utf-8")
    return path


def save_dump_capture(name: str, record: dict[str, Any]) -> Path:
    capture_dir = CAPTURE_DIR / "dump"
    capture_dir.mkdir(parents=True, exist_ok=True)
    path = capture_dir / f"{name}.json"
    path.write_text(pretty_json(record) + "\n", encoding="utf-8")
    return path


def print_request_debug(host: str, port: int, path: str, name: str, message: dict[str, Any], key_used: bool):
    header = message["header"]
    print("=" * 80)
    print(f"Request: {name}")
    print(f"Destination IP: {host}")
    print(f"Destination port: {port}")
    print(f"HTTP path: {path}")
    print(f"Namespace: {header['namespace']}")
    print(f"Method: {header['method']}")
    print(f"Payload: {pretty_json(message['payload'])}")
    print(f"messageId: {header['messageId']}")
    print(f"Timestamp: {header['timestamp']}")
    print(f"timestampMs: {header['timestampMs']}")
    print(f"Whether a key is being used: {'yes' if key_used else 'no'}")


def print_response_debug(result: dict[str, Any]):
    print(f"HTTP status: {result.get('http_status')} {result.get('http_reason')}")
    print(f"Response headers: {pretty_json(result.get('response_headers'))}")
    print("Raw response body:")
    print(result.get("raw_body") if result.get("raw_body") else "<empty>")
    print("Parsed JSON:")
    print(pretty_json(result.get("parsed_json")) if result.get("parsed_json") is not None else "<none>")
    print(f"Parse error: {result.get('parse_error')}")
    print(f"Meross error code: {result.get('meross_error_code')}")
    print(f"Meross error message: {result.get('meross_error_message')}")
    print(f"Meross error kind: {result.get('meross_error_kind')}")
    print(f"Elapsed request time: {result.get('elapsed_ms')} ms")


def parse_args():
    parser = argparse.ArgumentParser(description="Read-only local Meross MSL120D LAN probe.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bulb IP address. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port. Default: {DEFAULT_PORT}")
    parser.add_argument("--path", default=DEFAULT_PATH, help=f"Meross HTTP path. Default: {DEFAULT_PATH}")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument("--key", help="Meross device/account key. Prefer MEROSS_KEY instead.")
    parser.add_argument("--dump", action="store_true", help="Run a safe read-only namespace dump.")
    parser.add_argument(
        "--allow-empty-key",
        action="store_true",
        help="Send exactly one read-only pass signed with an empty key. Use only to test older keyless behavior.",
    )
    return parser.parse_args()


def response_result_label(response_record: dict[str, Any]) -> str:
    if "transport_error_kind" in response_record:
        return response_record["transport_error_kind"]
    if response_record.get("parse_error"):
        return response_record["parse_error"]
    meross_error = response_record.get("meross_error_kind")
    if meross_error:
        return meross_error
    parsed = response_record.get("parsed_json")
    method = None
    payload = None
    if isinstance(parsed, dict):
        header = parsed.get("header")
        if isinstance(header, dict):
            method = header.get("method")
        payload = parsed.get("payload")
    if method == "GETACK":
        if payload in ({}, None):
            return "GETACK / empty"
        return "GETACK / useful"
    return str(method or response_record.get("http_status") or "unknown")


def walk_interesting_fields(namespace: str, value: Any, path: str = "") -> list[dict[str, Any]]:
    fields = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in INTERESTING_FIELD_NAMES:
                fields.append({"namespace": namespace, "field": child_path, "raw_value": child})
            fields.extend(walk_interesting_fields(namespace, child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.extend(walk_interesting_fields(namespace, child, f"{path}[{index}]"))
    return fields


def run_dump(args: argparse.Namespace, key: str) -> int:
    summary = []
    interesting_fields = []
    exit_code = 0

    for name, namespace, payload, has_get, payload_source in DUMP_REQUESTS:
        print("=" * 80)
        print(f"Namespace: {namespace}")
        print(f"GET payload source: {payload_source}")
        print(f"Request payload: {pretty_json(payload)}")

        request_record = {
            "destination": {"host": args.host, "port": args.port, "path": args.path},
            "request_name": name,
            "namespace": namespace,
            "method": METHOD_GET,
            "payload_source": payload_source,
            "key_used": bool(key),
            "secret_key_in_source": False,
        }

        if not has_get:
            response_record = {
                "skipped": True,
                "reason": "Current meross_lan namespace grammar does not declare a direct GET for this namespace.",
            }
            print("Skipped: no direct GET declared by current meross_lan namespace grammar.")
            result_label = "not queried / no GET declared"
        else:
            message = build_message(namespace, METHOD_GET, payload, key)
            request_record["request_body"] = message
            try:
                response_record = send_meross_message(args.host, args.port, args.path, message, args.timeout)
            except ProbeError as exc:
                response_record = {
                    "transport_error_kind": exc.kind,
                    "transport_error_detail": exc.detail,
                }
                print(f"{exc.kind}: {exc.detail}")
                exit_code = 1
            else:
                print(f"HTTP status: {response_record.get('http_status')} {response_record.get('http_reason')}")
                print("Raw response:")
                print(response_record.get("raw_body") or "<empty>")
                print("Parsed JSON:")
                print(pretty_json(response_record.get("parsed_json")) if response_record.get("parsed_json") is not None else "<none>")
                print(f"Meross error code/message: {response_record.get('meross_error_code')} / {response_record.get('meross_error_message')}")
                if response_record.get("parse_error") or response_record.get("meross_error_kind"):
                    exit_code = 1

            result_label = response_result_label(response_record)
            interesting_fields.extend(walk_interesting_fields(namespace, response_record.get("parsed_json")))

        capture = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request": request_record,
            "response": response_record,
            "result": result_label,
        }
        capture_path = save_dump_capture(name, capture)
        print(f"Saved dump capture: {capture_path}")
        summary.append((namespace, result_label))

    print()
    print("Namespace                         Result")
    print("---------------------------------------------------")
    for namespace, result in summary:
        print(f"{namespace:<33} {result}")

    print()
    print("Newly discovered fields potentially relevant to light-engine reverse engineering")
    print("--------------------------------------------------------------------------------")
    if not interesting_fields:
        print("None found in parsed responses.")
    else:
        seen = set()
        for field in interesting_fields:
            key_tuple = (field["namespace"], field["field"], json.dumps(field["raw_value"], sort_keys=True, default=str))
            if key_tuple in seen:
                continue
            seen.add(key_tuple)
            print(f"{field['namespace']} | {field['field']} | {field['raw_value']!r}")
    print()
    print("Interpretation note: field relevance is tentative unless documented by meross_lan constants or namespace handling.")
    return exit_code


def main() -> int:
    load_dotenv()
    args = parse_args()
    key = args.key if args.key is not None else os.environ.get("MEROSS_KEY")

    if key is None and not args.allow_empty_key:
        print("No Meross key was provided, so no network requests were sent.")
        print("Set MEROSS_KEY or pass --key. The HomeKit setup code is not the Meross key.")
        print("For a bulb still paired to the Meross app/cloud, meross_lan documents cloud account recovery as the least disruptive way to obtain the device key.")
        return 2

    if key is None:
        key = ""
        print("Warning: using an empty key for one read-only probe pass.")

    if args.dump:
        return run_dump(args, key)

    exit_code = 0
    for name, namespace, payload in REQUESTS:
        message = build_message(namespace, METHOD_GET, payload, key)
        print_request_debug(args.host, args.port, args.path, name, message, key_used=bool(key))

        request_record = {
            "destination": {"host": args.host, "port": args.port, "path": args.path},
            "request_name": name,
            "request_body": message,
            "secret_key_in_source": False,
            "key_used": bool(key),
        }

        try:
            response_record = send_meross_message(args.host, args.port, args.path, message, args.timeout)
        except ProbeError as exc:
            response_record = {
                "transport_error_kind": exc.kind,
                "transport_error_detail": exc.detail,
            }
            print(f"{exc.kind}: {exc.detail}")
            exit_code = 1
        else:
            print_response_debug(response_record)
            if response_record.get("parse_error") or response_record.get("meross_error_kind"):
                exit_code = 1

        capture = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request": request_record,
            "response": response_record,
        }
        capture_path = save_capture(name, capture, args.host)
        print(f"Saved capture: {capture_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
