import argparse
import json
import time

from vocolinc import (
    VocolincLocalClient,
    discover_vocolinc,
    print_discovered,
    user_id_from_email,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Local VOCOlinc ALC control test tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="Find VOCOlinc devices using Bonjour/mDNS.")
    discover.add_argument("--seconds", type=float, default=3.0)
    discover.add_argument("--model", help="Optional model filter, for example DL2201.")

    read = subparsers.add_parser("read", help="Read current local ALC state.")
    read.add_argument("host", help="Device IP address, for example 10.0.1.4.")

    session = subparsers.add_parser("session", help="Start a local ALC session using your VOCOlinc email.")
    session.add_argument("host")
    session.add_argument("--email", required=True)

    on = subparsers.add_parser("on", help="Turn a service on.")
    on.add_argument("host")
    on.add_argument("--service-id", default="0")

    off = subparsers.add_parser("off", help="Turn a service off.")
    off.add_argument("host")
    off.add_argument("--service-id", default="0")

    blink = subparsers.add_parser("blink", help="Turn one or more lamps on briefly, then off.")
    blink.add_argument("hosts", nargs="+")
    blink.add_argument("--seconds", type=float, default=5.0)
    blink.add_argument("--service-id", default="0")

    brightness = subparsers.add_parser("brightness", help="Set brightness 0-100.")
    brightness.add_argument("host")
    brightness.add_argument("value", type=int)
    brightness.add_argument("--service-id", default="0")

    cct = subparsers.add_parser("cct", help="Set color temperature in mireds.")
    cct.add_argument("host")
    cct.add_argument("mired", type=int)
    cct.add_argument("--service-id", default="0")

    raw = subparsers.add_parser("raw", help="Send a raw state object.")
    raw.add_argument("host")
    raw.add_argument("state_json", help='Example: \'{"switch0":true}\'')

    return parser.parse_args()


def print_json(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()

    if args.command == "discover":
        print_discovered(discover_vocolinc(seconds=args.seconds, model=args.model))
        return 0

    if args.command == "read":
        client = VocolincLocalClient(args.host)
        print_json(client.get_state())
    elif args.command == "session":
        client = VocolincLocalClient(args.host)
        print_json(client.start_session(user_id_from_email(args.email)))
    elif args.command == "on":
        client = VocolincLocalClient(args.host)
        print_json(client.set_on(True, service_id=args.service_id))
    elif args.command == "off":
        client = VocolincLocalClient(args.host)
        print_json(client.set_on(False, service_id=args.service_id))
    elif args.command == "blink":
        clients = [(host, VocolincLocalClient(host)) for host in args.hosts]
        try:
            for host, host_client in clients:
                print(f"{host} on")
                print_json(host_client.set_on(True, service_id=args.service_id))
            time.sleep(args.seconds)
        finally:
            for host, host_client in clients:
                print(f"{host} off")
                print_json(host_client.set_on(False, service_id=args.service_id))
    elif args.command == "brightness":
        client = VocolincLocalClient(args.host)
        print_json(client.set_brightness(args.value, service_id=args.service_id))
    elif args.command == "cct":
        client = VocolincLocalClient(args.host)
        print_json(client.set_color_temperature(args.mired, service_id=args.service_id))
    elif args.command == "raw":
        client = VocolincLocalClient(args.host)
        print_json(client.put_state(json.loads(args.state_json)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
