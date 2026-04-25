# App PowerDog Client

Client to interface with `Hughes Power Watchdog` via BLE

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install --requirement requirements.txt
source .venv/bin/activate
```

## App

The code uses `asyncio` and is setup to quit when `Ctrl-C` is used

```bash
# help usage
python3 app.py --help

# scan all BLE devices, find the Watchdog device address, usually named "PMS..." or "PMD..."
python3 app.py

# enumerate the properties of a BLE device
python3 app.py --device-enumerate --device-address="AA:BB:CC:DD:EE:FF"

# read the Watchdog data
python3 app.py --device-address="AA:BB:CC:DD:EE:FF" --service-uuid="0000ffe2-0000-1000-8000-00805f9b34fb" --decode-data
```
