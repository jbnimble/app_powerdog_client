import asyncio
import json

from bleak import BleakClient, BleakScanner, BLEDevice
from data import WatchdogDataValue

class DevicePrinter:
    """ create JSON string representing the metadata for a BLEDevice and service collection """
    def __init__(self, device: BLEDevice, service_collection):
        self.device = device
        self.service_collection = service_collection

    def get_characteristic_object(item) -> {}:
        data = {'handle': item.handle, 'uuid': item.uuid, 'description': item.description, 'properties': [], 'descriptors': []}
        for prop in item.properties:
            data['properties'].append(prop)
        for desc in item.descriptors:
            data['descriptors'].append(DevicePrinter.get_descriptor_object(desc))
        return data

    def get_descriptor_object(item) -> {}:
        return {'handle': item.handle, 'uuid': item.uuid, 'description': item.description}

    def __str__(self):
        result = {'address': self.device.address, 'name': self.device.name, 'services': {}, 'characteristics': {}, 'descriptors': {}}
        for key,val in self.service_collection.services.items():
            result['services'][key] = {'handle': key, 'uuid': val.uuid, 'description': val.description, 'characteristics': []}
            for item in val.characteristics:
                result['services'][key]['characteristics'].append(DevicePrinter.get_characteristic_object(item))
        for key,val in self.service_collection.characteristics.items():
            result['characteristics'][key] = DevicePrinter.get_descriptor_object(val)
        for key,val in self.service_collection.descriptors.items():
            result['descriptors'][key] = DevicePrinter.get_descriptor_object(val)
        return json.dumps(result, indent=4)

class DeviceLister:
    """ scan for BLE devices forever or for `scan_sec` seconds """
    def __init__(self, scan_sec: int = 0):
        self.scan_sec = scan_sec
        self.address_tracker = set()

    async def execute(self):
        def scanner_detection(device: BLEDevice, data):
            if device.address not in self.address_tracker:
                print(f'{{"address": "{device.address}", "name": "{device.name}"}}')
                self.address_tracker.add(device.address)

        async with BleakScanner(detection_callback=scanner_detection) as scanner:
            if self.scan_sec <= 0:
                # wait forever
                print(f'scanning...')
                await asyncio.Future()
            else:
                # wait for scan_sec
                print(f'scanning for {self.scan_sec} seconds...')
                await asyncio.sleep(delay=self.scan_sec)

class DeviceEnumerator:
    """ connect to a given address and enumerate its capabilities """
    def __init__(self, address: str, scan_sec: int = 0):
        self.address = address
        self.scan_sec = scan_sec
        self.device: BLEDevice = None

    async def execute(self):
        def scanner_detection(device: BLEDevice, data):
            if not self.device and device.address == self.address:
                self.device = device
                print(f'{{"address": "{device.address}", "name": "{device.name}"}}')

        async with BleakScanner(detection_callback=scanner_detection) as scanner:
            if self.scan_sec <= 0:
                # wait forever, until found
                while not self.device:
                    print(f'scanning...')
                    await asyncio.sleep(delay=1.0)
            else:
                # wait for scan_sec
                print(f'scanning for {self.scan_sec} seconds...')
                for _ in range(0, self.scan_sec):
                    await asyncio.sleep(delay=1.0)
                    if self.device:
                        break

        async with BleakClient(address_or_ble_device=self.device) as client:
            print(DevicePrinter(self.device, client.services))

class DeviceServiceConnector:
    """ Connect ot the device address and service_uuid for data """
    def __init__(self, address: str, scan_sec: int = 0, notify_sec: int = 0, service_uuid: str = None, decode_data: bool = False):
        self.address = address
        self.scan_sec = scan_sec
        self.notify_sec = notify_sec
        self.service_uuid = service_uuid
        self.decode_data = decode_data
        self.device: BLEDevice = None

    async def execute(self):
        def scanner_detection(device: BLEDevice, data):
            if not self.device and device.address == self.address:
                self.device = device
                print(f'{{"address": "{device.address}", "name": "{device.name}"}}')

        def client_service_notify(sender, data: bytearray):
            if self.decode_data:
                print(f'{WatchdogDataValue(data.hex()).json_str()}')
            else:
                print(f'{data.hex()}')

        async with BleakScanner(detection_callback=scanner_detection) as scanner:
            if self.scan_sec <= 0:
                # wait forever, until found
                while not self.device:
                    print(f'scanning...')
                    await asyncio.sleep(delay=1.0)
            else:
                # wait for scan_sec
                print(f'scanning for {self.scan_sec} seconds...')
                for _ in range(0, self.scan_sec):
                    await asyncio.sleep(delay=1.0)
                    if self.device:
                        break

        async with BleakClient(address_or_ble_device=self.device) as client:
            characteristic = None
            for entry in client.services.characteristics.values():
                if entry.uuid == self.service_uuid:
                    characteristic = entry
                    break
            if characteristic:
                print(f'start notify for handle={characteristic.handle} uuid={characteristic.uuid}')
                await client.start_notify(char_specifier=characteristic, callback=client_service_notify)

                if self.notify_sec <= 0:
                    await asyncio.Future()
                else:
                    for _ in range(0, self.notify_sec):
                        await asyncio.sleep(delay=1.0)
                await client.stop_notify(char_specifier=characteristic)
            else:
                print(f'Failed to find service characteristic uuid={self.service_uuid}')
