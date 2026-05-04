# App PowerDog Client

Client to interface with `Hughes Power Watchdog` via BLE and send data to `MQTT` for use by `Home Assistant`

## Local Development

- Git clone repository
- Create a `config.ini`, example [config.ini](docs/config.ini), with the values for your environment
- Execute these commands:

```bash
# Execute local dev setup script
./scripts/setup_local_dev.sh
# Activate virtualenv
source .venv/bin/activate
# Run app
./src/powerdog/client.py --config-file=data/config.ini
```

## App(s)

The code uses `asyncio` and is setup to quit when `Ctrl-C` is used

```bash
# scan all BLE devices, find the Watchdog device address, named "PMS..." or "PMD..."
python3 app.py

# enumerate the properties of a BLE device
python3 app.py --device-enumerate --device-address="AA:BB:CC:DD:EE:FF"

# read the Watchdog data
python3 app.py --device-address="AA:BB:CC:DD:EE:FF" --service-uuid="0000ffe2-0000-1000-8000-00805f9b34fb" --decode-data
```

## Current Plans

- add `line1_topic_prefix` and `line2_topic_prefix` config
- add bluetooth adapter name to config, in case multiple BT adapters on system
- change logging level to `key = level` so log levels can be modified per logger
- fix `pylock.toml` to have the correct dependencies, move away from `requirements.txt`
- make it stable over long time periods

## Future Plans

- discovery for automatically finding `Watchdog` devices
- pip installable package
- Home Assistant native plugin
