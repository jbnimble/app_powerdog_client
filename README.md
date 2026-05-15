# App PowerDog Client

Client to interface with `Watchdog` devices via Bluetooth Low Energy (BLE)

- send data to MQTT broker
- Home Assistant MQTT integration device discovery

The `Watchdog` devices come in 30Amp and 50Amp configurations. A 30Amp device has LINE1 data, and a 50Amp device has LINE1/LINE2 data.

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
