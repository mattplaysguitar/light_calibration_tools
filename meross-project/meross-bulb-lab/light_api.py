import os 
import time
import uuid
import hashlib
import requests
import subprocess
import re
import json

MEROSS_KEY = "3d0c08d20bcfe628ecb96dddb796c9b7"


def get_mdns_info():
    try:
        scan = subprocess.run(
            ["dns-sd", "-B", "_hap._tcp", "local"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = scan.stdout

    except subprocess.TimeoutExpired as error:
        output = error.stdout

    if isinstance(output, bytes):
        output = output.decode()

    devices = []

    for line in output.splitlines():
        if "_hap._tcp." in line and "Add" in line:
            parts = line.split()
            name = line.split("_hap._tcp.")[-1].strip()
            devices.append({
                "service_type": "_hap._tcp",
                "name": name,
            })

    return devices


def resolve_mdns_names():
    devices = get_mdns_info()
    addresses = []

    for device in devices:
        try:
            address_lookup = subprocess.run(
                ["dns-sd", "-L", device["name"], device["service_type"], "local"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = address_lookup.stdout

        except subprocess.TimeoutExpired as error:
            output = error.stdout

        if isinstance(output, bytes):
            output = output.decode()
        
        data = 

        addresses.append(output)




    print(addresses)
def meross_get(host, namespace, payload):
    message_id = uuid.uuid4().hex
    timestamp = int(time.time())

    sign = hashlib.md5(
        f"{message_id}{MEROSS_KEY}{timestamp}".encode()
    ).hexdigest()

    message = {
        "header": {
            "messageId": message_id,
            "namespace": namespace,
            "method": "GET",
            "from": "/app/python/subcribe",
            "timestamp": timestamp,
            "sign": sign,
        },
        "payload": payload
    }

    reponse = requests.post(
        f"http://{host}/config",
        json=message,
        timeout=5,
    )
    print(reponse)
    reponse.raise_for_status()
    return reponse.json()