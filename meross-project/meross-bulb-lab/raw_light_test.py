import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from meross_probe import (
    DEFAULT_HOST,
    DEFAULT_PATH,
    DEFAULT_PORT,
    METHOD_GET,
    METHOD_SET,
    build_message,
    load_dotenv,
    pretty_json,
    safe_host_dirname,
    send_meross_message,
)


CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
LIGHT_NAMESPACE = "Appliance.Control.Light"
TOGGLEX_NAMESPACE = "Appliance.Control.ToggleX"

# Current meross_lan capacity constants:
# RGB=1, TEMPERATURE=2, LUMINANCE=4.
LIGHT_CAPACITY_RGB_LUMINANCE = 1 | 4
LIGHT_CAPACITY_TEMPERATURE_LUMINANCE = 2 | 4

TESTS = [
    {
        "id": "red_10",
        "label": "red, 10% luminance",
        "light": {
            "channel": 0,
            "capacity": LIGHT_CAPACITY_RGB_LUMINANCE,
            "rgb": 0xFF0000,
            "luminance": 10,
            "transform": 0,
        },
    },
    {
        "id": "green_10",
        "label": "green, 10% luminance",
        "light": {
            "channel": 0,
            "capacity": LIGHT_CAPACITY_RGB_LUMINANCE,
            "rgb": 0x00FF00,
            "luminance": 10,
            "transform": 0,
        },
    },
    {
        "id": "blue_10",
        "label": "blue, 10% luminance",
        "light": {
            "channel": 0,
            "capacity": LIGHT_CAPACITY_RGB_LUMINANCE,
            "rgb": 0x0000FF,
            "luminance": 10,
            "transform": 0,
        },
    },
    {
        "id": "warmest_white_10",
        "label": "warmest white, 10% luminance",
        "light": {
            "channel": 0,
            "capacity": LIGHT_CAPACITY_TEMPERATURE_LUMINANCE,
            "temperature": 1,
            "luminance": 10,
            "transform": 0,
        },
    },
    {
        "id": "coolest_white_10",
        "label": "coolest white, 10% luminance",
        "light": {
            "channel": 0,
            "capacity": LIGHT_CAPACITY_TEMPERATURE_LUMINANCE,
            "temperature": 100,
            "luminance": 10,
            "transform": 0,
        },
    },
]


def parse_args():
    parser = argparse.ArgumentParser(description="Interactive conservative raw Appliance.Control.Light tests.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bulb IP/hostname. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port. Default: {DEFAULT_PORT}")
    parser.add_argument("--path", default=DEFAULT_PATH, help=f"Meross HTTP path. Default: {DEFAULT_PATH}")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument("--key", help="Meross device/account key. Prefer MEROSS_KEY or .env instead.")
    return parser.parse_args()


def select_test() -> dict[str, Any] | None:
    print("Select one raw-light test:")
    for index, test in enumerate(TESTS, start=1):
        print(f"{index}. {test['label']}")
    print("q. quit")

    choice = input("> ").strip().lower()
    if choice in {"q", "quit", "exit"}:
        return None

    try:
        index = int(choice)
    except ValueError:
        raise ValueError("Enter a test number or q.")

    if index < 1 or index > len(TESTS):
        raise ValueError(f"Choose a number from 1 to {len(TESTS)}.")
    return TESTS[index - 1]


def capture_path(host: str, test_id: str) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    directory = CAPTURE_DIR / safe_host_dirname(host) / "raw_light_tests"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{stamp}_{test_id}.json"


def request(
    host: str,
    port: int,
    path: str,
    timeout: float,
    key: str,
    namespace: str,
    method: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    message = build_message(namespace, method, payload, key)
    response = send_meross_message(host, port, path, message, timeout)
    return {
        "request": message,
        "response": response,
    }


def get_light(host: str, port: int, path: str, timeout: float, key: str) -> dict[str, Any]:
    return request(host, port, path, timeout, key, LIGHT_NAMESPACE, METHOD_GET, {"light": {}})


def get_togglex(host: str, port: int, path: str, timeout: float, key: str) -> dict[str, Any]:
    return request(host, port, path, timeout, key, TOGGLEX_NAMESPACE, METHOD_GET, {"togglex": [{"channel": 0}]})


def extract_payload(record: dict[str, Any], key: str) -> Any:
    parsed = record.get("response", {}).get("parsed_json")
    if not isinstance(parsed, dict):
        return None
    payload = parsed.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload.get(key)


def main() -> int:
    load_dotenv()
    args = parse_args()
    key = args.key if args.key is not None else os.environ.get("MEROSS_KEY")
    if not key:
        print("No Meross key was provided, so no SET request was sent.")
        print("Set MEROSS_KEY in .env or pass --key.")
        return 2

    while True:
        try:
            test = select_test()
        except ValueError as exc:
            print(exc)
            print()
            continue

        if test is None:
            print("Quitting.")
            return 0

        set_payload = {"light": test["light"]}
        set_message_preview = build_message(LIGHT_NAMESPACE, METHOD_SET, set_payload, key)

        print()
        print(f"Selected: {test['label']}")
        print("Exact JSON that will be sent:")
        print(pretty_json(set_message_preview))
        print()
        set_response = send_meross_message(
            args.host,
            args.port,
            args.path,
            set_message_preview,
            args.timeout,
        )
        print()
        print("SET response:")
        print(pretty_json(set_response.get("parsed_json")) if set_response.get("parsed_json") else set_response.get("raw_body"))

        light_get = get_light(args.host, args.port, args.path, args.timeout, key)
        togglex_get = get_togglex(args.host, args.port, args.path, args.timeout, key)

        print()
        print("Returned Appliance.Control.Light state:")
        print(pretty_json(extract_payload(light_get, "light")))
        print()
        print("Returned Appliance.Control.ToggleX state:")
        print(pretty_json(extract_payload(togglex_get, "togglex")))

        capture = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host": args.host,
            "test": {
                "id": test["id"],
                "label": test["label"],
                "capacity_semantics": {
                    "rgb": 1,
                    "temperature": 2,
                    "luminance": 4,
                    "rgb_luminance": LIGHT_CAPACITY_RGB_LUMINANCE,
                    "temperature_luminance": LIGHT_CAPACITY_TEMPERATURE_LUMINANCE,
                },
            },
            "requested_state": set_payload,
            "set": {
                "request": set_message_preview,
                "response": set_response,
            },
            "get_light": light_get,
            "get_togglex": togglex_get,
        }

        output_path = capture_path(args.host, test["id"])
        output_path.write_text(json.dumps(capture, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        print()
        print(f"Saved capture: {output_path}")
        print()


if __name__ == "__main__":
    raise SystemExit(main())
