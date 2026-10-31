"""Discover local smart lights via mDNS (HomeKit advertisements).

Discovery does not imply HomeKit pairing credentials or vendor-specific control.
Advertised HAP port is deliberately NOT passed to the Meross HTTP adapter.
"""
import time
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

SERVICE_TYPE = '_hap._tcp.local.'


class Collector(ServiceListener):
    def __init__(self, zc):
        self.zc = zc
        self.services = {}

    def add_service(self, zc, service_type, name):
        self._collect(service_type, name)

    def update_service(self, zc, service_type, name):
        self._collect(service_type, name)

    def remove_service(self, zc, service_type, name):
        self.services.pop(name, None)

    def _collect(self, service_type, name):
        info = self.zc.get_service_info(service_type, name, timeout=2500)
        if info is None:
            return
        instance = name.removesuffix('.' + SERVICE_TYPE)
        lowercase = instance.lower()
        if lowercase.startswith('vocolinc-'):
            kind = 'vocolinc'
        elif lowercase.startswith(('msl', 'mss', 'meross')):
            kind = 'meross'
        else:
            kind = 'other'
        addresses = info.parsed_addresses()
        ipv4 = next((address for address in addresses if ':' not in address), None)
        txt = {key.decode('utf-8', 'replace'): val.decode('utf-8','replace') for key, val in info.properties.items() if val is not None}
        self.services[name] = {
            'service': instance,
            'kind': kind,
            'model': txt.get('md', ''),
            'host_name': info.server.rstrip('.'),
            'address': ipv4,
            'hap_port': info.port,
            'homekit_id': txt.get('id', ''),
        }


def discover(project=None, seconds=8, include_other=False):
    """List lights and smart switches. The project arg is kept for CLI compatibility."""
    with Zeroconf() as zc:
        listener = Collector(zc)
        browser = ServiceBrowser(zc, SERVICE_TYPE, listener)
        try:
            time.sleep(max(1, seconds))
        finally:
            browser.cancel()
        records = list(listener.services.values())
    return sorted((r for r in records if r['address'] and (include_other or r['kind'] != 'other')),
                  key=lambda r: (r['kind'], r['service']))


def resolve_device(project, service, kind, seconds=8):
    matches = [r for r in discover(project, seconds) if r['service'].casefold() == service.casefold()]
    if not matches:
        raise SystemExit(f'mDNS service {service!r} not found. Run --list-lights again.')
    record = matches[0]
    if record['kind'] != kind:
        raise SystemExit(f'Service {service!r} is {record["kind"]}, not {kind}.')
    if record['model'].upper().startswith('MSS'):
        raise SystemExit(f'{service!r} is a smart plug, not a dimmable bulb.')
    return record
