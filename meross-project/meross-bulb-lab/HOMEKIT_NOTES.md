# VOCOlinc DL2201 HomeKit Access

Known local HAP service:

- Service: `VOCOlinc-DL2201-1ea079._hap._tcp.local`
- Host: `VOCOlinc-DL2201-1ea079.local`
- IP: `10.0.1.4`
- Port: `8080`
- Model TXT field: `DL2201`
- Pairing status TXT field: `sf=0`, meaning already paired
- Category TXT field: `ci=5`, lighting

## Current Python Controller Options

`aiohomekit` is the current Python HAP controller/client library used by Home Assistant. It supports IP HomeKit controller behavior and stores controller pairing data, but its public API is not yet stable.

`homekit` / `homekit_python` is older but includes useful CLI tools: discovery, pairing, reading accessories, listing pairings, and adding additional pairings. Its docs are especially explicit that reading accessory data requires a pairing-data file.

## Pairing Model

An already paired HAP accessory does not expose its accessory/service/characteristic database to a random unauthenticated HTTP client. Reads such as `/accessories` and `/characteristics` require an encrypted Pair-Verify session based on an existing controller pairing.

HAP supports adding an additional controller with Pairings/AddPairing, but that operation must be performed by an already paired admin controller. A new Python controller cannot self-authorize against an accessory with `sf=0`.

## Apple Home Credentials

Apple documents HomeKit identity as Ed25519 key pairs stored in Keychain and synchronized with iCloud Keychain. There is no normal supported Python API for exporting Apple Home's existing HAP controller credentials and using them directly.

Some unofficial extraction approaches exist, but they involve protected Keychain access groups and may require disabling macOS system protections. That is not the least disruptive path and should not be the first approach.

## Least Disruptive Path

The safest path is to add a separate Python/Home Assistant controller using supported HomeKit sharing or additional-controller mechanisms:

1. Prefer Home Assistant's HomeKit Controller integration if it can be authorized through the existing Home setup or vendor workflow.
2. If using raw Python tooling, create a new controller identity/pairing file.
3. Have an existing admin controller authorize that new controller as an additional pairing, if the chosen tooling and accessory support it.
4. Only after a valid pairing file exists, read `/accessories` and identify `On`, `Brightness`, and `ColorTemperature` characteristic IDs.

Do not factory reset or remove Apple Home pairing unless you intentionally choose to re-onboard the lamp.

## Sources

- `aiohomekit`: https://pypi.org/project/aiohomekit/
- `aiohomekit` pairing code: https://github.com/Jc2k/aiohomekit/blob/main/aiohomekit/controller/ip/discovery.py
- `homekit_python` controller CLI docs: https://github.com/jlusiardi/homekit_python
- Apple HomeKit security overview: https://support.apple.com/guide/security/communication-security-sec3a881ccb1/web
- Apple HomeKit accessory setup API: https://developer.apple.com/documentation/homekit/hmhome/addandsetupaccessories%28with%3Acompletionhandler%3A%29
