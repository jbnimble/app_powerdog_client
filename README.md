# App PowerDog Client

Client to interface with `Watchdog` devices via Bluetooth Low Energy (BLE)

- send data to MQTT broker
- Home Assistant MQTT integration device discovery

The `Watchdog` devices come in 30Amp and 50Amp configurations. A 30Amp device has LINE1 data, and a 50Amp device has LINE1/LINE2 data.

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

## Current Plans/Ideas

- HTTP client interface
- add "RELAY ON" capability
- add "RESET" capability
- add `line1_topic_prefix` and `line2_topic_prefix` config
- add bluetooth adapter name to config, in case multiple BT adapters on system
- change logging level to `key = level` so log levels can be modified per logger
- fix `pylock.toml` to have the correct dependencies, move away from `requirements.txt`
- make it stable over long time periods
- pip installable package
- Home Assistant native plugin
- switch to https://github.com/empicano/aiomqtt
