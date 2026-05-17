# App PowerDog Client

Client to interface with `Watchdog` devices via Bluetooth Low Energy (BLE)

- send data to MQTT broker
- Home Assistant [MQTT integration with device discovery](https://www.home-assistant.io/integrations/mqtt/)

The `Watchdog` devices come in 30Amp and 50Amp configurations. A 30Amp device has LINE1 data, and a 50Amp device has LINE1/LINE2 data.

## MQTT Integration

Publish topics:

- topic = powerdog/status, payload = str
- topic = homeassistant/device/powerdog/config, payload = json
- topic = powerdog/L1/voltage, payload = float
- topic = powerdog/L1/amperage, payload = float
- topic = powerdog/L1/wattage, payload = float
- topic = powerdog/L1/power_usage, payload = float
- topic = powerdog/L1/error_code, payload = int
- topic = powerdog/L1/error_status, payload = str
- topic = powerdog/L2/voltage, payload = float
- topic = powerdog/L2/amperage, payload = float
- topic = powerdog/L2/wattage, payload = float
- topic = powerdog/L2/power_usage, payload = float
- topic = powerdog/L2/error_code, payload = int
- topic = powerdog/L2/error_status, payload = str

Subscribe topics:

- topic = homeassistant/status, payload = str
    NOTE: this topic is configurable in Home Assistant, but defaults to this value

## BLE Connection Troubleshooting

- In testing the `Watchdog` device only allows a single client connection at a time
- The app may not properly disconnect from BLE if shutdown, logic has been aded to attempt a native disconnect

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
