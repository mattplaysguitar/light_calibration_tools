import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

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
RESULTS_PATH = CAPTURE_DIR / "spectral_tests.jsonl"
LIGHT_NAMESPACE = "Appliance.Control.Light"
TOGGLEX_NAMESPACE = "Appliance.Control.ToggleX"

# Current meross_lan capacity constants: RGB=1, TEMPERATURE=2, LUMINANCE=4.
LIGHT_CAPACITY_RGB_LUMINANCE = 1 | 4
LIGHT_CAPACITY_TEMPERATURE_LUMINANCE = 2 | 4

TESTS = [
    {
        "id": "red_10",
        "label": "Red at 10% luminance",
        "light": {"channel": 0, "capacity": LIGHT_CAPACITY_RGB_LUMINANCE, "rgb": 0xFF0000, "luminance": 10, "transform": 0},
    },
    {
        "id": "green_10",
        "label": "Green at 10%",
        "light": {"channel": 0, "capacity": LIGHT_CAPACITY_RGB_LUMINANCE, "rgb": 0x00FF00, "luminance": 10, "transform": 0},
    },
    {
        "id": "blue_10",
        "label": "Blue at 10%",
        "light": {"channel": 0, "capacity": LIGHT_CAPACITY_RGB_LUMINANCE, "rgb": 0x0000FF, "luminance": 10, "transform": 0},
    },
    {
        "id": "warmest_white_10",
        "label": "Warmest white at 10%",
        "light": {"channel": 0, "capacity": LIGHT_CAPACITY_TEMPERATURE_LUMINANCE, "temperature": 1, "luminance": 10, "transform": 0},
    },
    {
        "id": "coolest_white_10",
        "label": "Coolest white at 10%",
        "light": {"channel": 0, "capacity": LIGHT_CAPACITY_TEMPERATURE_LUMINANCE, "temperature": 100, "luminance": 10, "transform": 0},
    },
]


def parse_args():
    parser = argparse.ArgumentParser(description="Manual spectral test workflow for a Meross MSL120D bulb.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bulb IP/hostname. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port. Default: {DEFAULT_PORT}")
    parser.add_argument("--path", default=DEFAULT_PATH, help=f"Meross HTTP path. Default: {DEFAULT_PATH}")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument("--key", help="Meross device/account key. Prefer MEROSS_KEY or .env instead.")
    parser.add_argument("--read", action="store_true", help="Only GET Appliance.Control.Light and ToggleX.")
    parser.add_argument("--requested-light-object", help="Optional raw Appliance.Control.Light object JSON.")
    parser.add_argument("--spectrometer-file", help="Path/name of the manually collected spectrum file.")
    parser.add_argument("--notes", default="", help="Free-form notes.")
    return parser.parse_args()


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def parse_json_object(value: str):
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed


def request(host: str, port: int, path: str, timeout: float, key: str, namespace: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    message = build_message(namespace, method, payload, key)
    response = send_meross_message(host, port, path, message, timeout)
    return {"request": message, "response": response}


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


def print_readback(light_get: dict[str, Any], togglex_get: dict[str, Any]) -> None:
    print("Appliance.Control.Light:")
    print(pretty_json(extract_payload(light_get, "light")))
    print()
    print("Appliance.Control.ToggleX:")
    print(pretty_json(extract_payload(togglex_get, "togglex")))


def select_menu_test() -> dict[str, Any] | str | None:
    print("Select one spectral test:")
    print("1. Read current light state only")
    for index, test in enumerate(TESTS, start=2):
        print(f"{index}. {test['label']}")
    print("7. Custom raw light object")
    print("8. Exit")

    choice = input("> ").strip().lower()
    if choice in {"8", "q", "quit", "exit"}:
        return None
    if choice == "1":
        return "read"
    if choice == "7":
        raw = input("Raw light object JSON: ").strip()
        return {"id": "custom_raw", "label": "Custom raw light object", "light": parse_json_object(raw)}

    try:
        index = int(choice)
    except ValueError:
        raise ValueError("Enter a menu number.")

    test_index = index - 2
    if test_index < 0 or test_index >= len(TESTS):
        raise ValueError("Choose 1 through 8.")
    return TESTS[test_index]


def confirm_send() -> bool:
    answer = input("Send this SET? Type yes to send [default: no]: ").strip().lower()
    return answer in {"yes", "y"}


def capture_path(host: str, test_id: str) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    directory = CAPTURE_DIR / safe_host_dirname(host) / "spectral_tests"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{stamp}_{test_id}.json"


def append_result_record(record: dict[str, Any]) -> None:
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    with RESULTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(compact_json(record) + "\n")


def build_result_record(test_id: str, requested: dict[str, Any] | None, reported: dict[str, Any] | None, notes: str, spectrometer_file: str | None) -> dict[str, Any]:
    light = reported or requested or {}
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "test_id": test_id,
        "requested_light_object": requested,
        "reported_light_object": reported,
        "namespace": LIGHT_NAMESPACE,
        "capacity": light.get("capacity"),
        "rgb": light.get("rgb"),
        "temperature": light.get("temperature"),
        "luminance": light.get("luminance"),
        "onoff": light.get("onoff"),
        "transform": light.get("transform"),
        "notes": notes or None,
        "spectrometer_file": spectrometer_file,
    }


def read_current(args: argparse.Namespace, key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    light_get = get_light(args.host, args.port, args.path, args.timeout, key)
    togglex_get = get_togglex(args.host, args.port, args.path, args.timeout, key)
    print_readback(light_get, togglex_get)
    return light_get, togglex_get


def run_set_test(args: argparse.Namespace, key: str, test: dict[str, Any]) -> int:
    set_payload = {"light": test["light"]}
    set_message = build_message(LIGHT_NAMESPACE, METHOD_SET, set_payload, key)

    print()
    print(f"Selected: {test['label']}")
    print("Exact JSON that will be sent:")
    print(pretty_json(set_message))
    print()

    if not confirm_send():
        print("Canceled. No SET request was sent.")
        return 0

    set_response = send_meross_message(args.host, args.port, args.path, set_message, args.timeout)
    print()
    print("SET response:")
    print(pretty_json(set_response.get("parsed_json")) if set_response.get("parsed_json") else set_response.get("raw_body"))
    print()

    light_get, togglex_get = read_current(args, key)
    reported_light = extract_payload(light_get, "light")
    test_id = str(uuid4())

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
        "set": {"request": set_message, "response": set_response},
        "get_light": light_get,
        "get_togglex": togglex_get,
    }

    output_path = capture_path(args.host, test["id"])
    output_path.write_text(json.dumps(capture, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    result_record = build_result_record(
        test_id=test_id,
        requested=test["light"],
        reported=reported_light if isinstance(reported_light, dict) else None,
        notes=args.notes,
        spectrometer_file=args.spectrometer_file,
    )
    append_result_record(result_record)

    print()
    print(f"Saved capture: {output_path}")
    print(f"Recorded spectral test: {test_id}")
    return 0


def main() -> int:
    load_dotenv()
    args = parse_args()
    key = args.key if args.key is not None else os.environ.get("MEROSS_KEY")
    if not key:
        print("No Meross key was provided, so no request was sent.")
        print("Set MEROSS_KEY in .env or pass --key.")
        return 2

    if args.read:
        read_current(args, key)
        return 0

    if args.requested_light_object:
        try:
            test = {"id": "requested_raw", "label": "Requested raw light object", "light": parse_json_object(args.requested_light_object)}
        except (ValueError, json.JSONDecodeError) as exc:
            print(exc)
            return 2
        return run_set_test(args, key, test)

    try:
        selection = select_menu_test()
    except (ValueError, json.JSONDecodeError) as exc:
        print(exc)
        return 2

    if selection is None:
        print("Exiting.")
        return 0
    if selection == "read":
        read_current(args, key)
        return 0

    return run_set_test(args, key, selection)


if __name__ == "__main__":
    raise SystemExit(main())
