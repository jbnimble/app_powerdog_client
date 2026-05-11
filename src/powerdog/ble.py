import asyncio
from asyncio import Task
from enum import StrEnum
import logging
import platform
from typing import Callable

from bleak import BleakClient, BleakScanner, BLEDevice, AdvertisementData, BleakGATTCharacteristic
from bleak.exc import BleakDeviceNotFoundError, BleakError, BleakGATTProtocolError

from powerdog.event import EventData
from powerdog.data import GattData, GattType
from powerdog.util import PowerdogUtil

class BluetoothEvent(StrEnum):
    BLE_SCANNER_DEVICE =    'ble_scanner_device'
    BLE_SCANNER_STARTED =   'ble_scanner_started'
    BLE_SCANNER_STOPPED =   'ble_scanner_stopped'
    BLE_CLIENT_STARTED =    'ble_client_started'
    BLE_CLIENT_STOPPED =    'ble_client_stopped'
    BLE_CLIENT_CLOSED =     'ble_client_closed'
    BLE_NOTIFY_STARTED =    'ble_notify_started'
    BLE_NOTIFY_FAIL_START = 'ble_notify_fail_start'
    BLE_NOTIFY_FAIL_STOP =  'ble_notify_fail_stop'
    BLE_NOTIFY_STOPPED =    'ble_notify_stopped'
    BLE_SERVICE_FOUND =     'ble_service_found'
    BLE_NOTIFY_DATA =       'ble_notify_data'
    BLE_GATT_DATA =         'ble_gatt_data'

class BluetoothEventClient:
    """
    BLE device client with EventData callback and Event enum
    """
    def __init__(self, device: BLEDevice | str, create_event_cb, on_event_cb: Callable[[EventData], None] = None):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.create_event_cb = create_event_cb
        self.on_event_cb = on_event_cb
        self.notify_specifier: BleakGATTCharacteristic = None
        self.notify_activated = asyncio.Event()
        self.context_keep_alive = asyncio.Event()
        self.context: BleakClient = None

    async def on_notify(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """ Callback for start_notify characteristic data """
        if sender == self.notify_specifier:
            self.on_event(EventData(BluetoothEvent.BLE_NOTIFY_DATA, data.hex()))
        else:
            self.logger.warning(f'on_notify unknown characteristic={sender} data={data.hex()}')

    def on_disconnected(self, client):
        """ Callback when BleakClient disconnects, cannot be async """
        self.on_event(EventData(BluetoothEvent.BLE_CLIENT_CLOSED))

    async def start_client(self):
        self.context_keep_alive.clear()
        async with BleakClient(address_or_ble_device=self.device, disconnected_callback=self.on_disconnected) as context:
            self.context = context
            self.on_event(EventData(BluetoothEvent.BLE_CLIENT_STARTED, context))
            await self.context_keep_alive.wait()
        self.on_event(EventData(BluetoothEvent.BLE_CLIENT_STOPPED))
        self.context = None

    def stop_client(self) -> None:
        self.context_keep_alive.set()

    def find_service(self, service_uuid) -> None:
        if self.is_connected() and not self.notify_specifier:
            for entry in self.context.services.characteristics.values():
                if entry.uuid == service_uuid:
                    self.notify_specifier = entry
                    break
        if self.notify_specifier:
            self.on_event(EventData(BluetoothEvent.BLE_SERVICE_FOUND, self.notify_specifier))

    def start_notify(self) -> None:
        if self.notify_activated.is_set():
            self.logger.info('Skip start_notify, already activated')
        elif self.is_connected() and self.notify_specifier:
            task = self.create_event_cb(self.context.start_notify(char_specifier=self.notify_specifier, callback=self.on_notify)) # TODO adapter args
            task.add_done_callback(self.on_task_notify_started)
        else:
            self.logger.warning(f'Failed to start_notify connected={is_connected} char_specifier={self.notify_specifier}')

    def stop_notify(self) -> None:
        if self.context and self.context.is_connected and self.notify_specifier:
            task = self.create_event_cb(self.context.stop_notify(self.notify_specifier))
            task.add_done_callback(self.on_task_notify_stopped)

    def on_task_notify_started(self, task: Task) -> None:
        task_error = task.exception()
        if task_error:
            self.on_event(EventData(BluetoothEvent.BLE_NOTIFY_FAIL_START, task_error))
        else:
            self.notify_activated.set()
            self.on_event(EventData(BluetoothEvent.BLE_NOTIFY_STARTED))

    def on_task_notify_stopped(self, task: Task) -> None:
        task_error = task.exception()
        if task_error:
            self.on_event(EventData(BluetoothEvent.BLE_NOTIFY_FAIL_STOP, task_error))
        else:
            self.notify_activated.clear()
            self.on_event(EventData(BluetoothEvent.BLE_NOTIFY_STOPPED))

    def on_event(self, event_data: EventData) -> None:
        if self.on_event_cb:
            self.on_event_cb(event_data)
        else:
            self.logger.info(f'Event noop {event_data}')

    async def get_gatt_data(self) -> None:
        result = []
        for entry in self.context.services.characteristics.values():
            data_hex = None
            data_ascii = None
            error_code = None
            try:
                data = await self.context.read_gatt_char(char_specifier=entry)
                data_hex = data.hex()
                data_ascii = PowerdogUtil.bytearray_to_ascii(data)
            except BleakGATTProtocolError as e:
                error_code = e.code
            gatt_item = GattData(uuid=entry.uuid, data_hex=data_hex, data_ascii=data_ascii, error_code=error_code, description=entry.description, gatt_type=GattType.CHARACTERISTIC)
            result.append(gatt_item)

        # self.logger.info(f'TEST data={result}')

        self.on_event(EventData(BluetoothEvent.BLE_GATT_DATA, {'result': result}))

    def is_connected(self) -> bool:
        return self.context.is_connected if self.context else False

    def is_notify_activated(self) -> bool:
        return self.notify_activated.is_set()

    def is_client_activated(self) -> bool:
        return not self.context_keep_alive.is_set() and self.context

class BluetoothEventScanner:
    """
    BLE device scanner with EventData callback and Event enum

    TODO allow special args to BleakScanner (service_uuids, scanning_mode, bluez, cb, backend, kwargs)
    TODO handle exceptions by sending events
    """
    def __init__(self, on_event_cb: Callable[[EventData], None] = None, allow_duplicates: bool = True):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.on_event_cb = on_event_cb
        self.allow_duplicates = allow_duplicates
        self.context_keep_alive = asyncio.Event()
        self.context: BleakScanner = None
        self.device_lock = asyncio.Lock()
        self.device_set = set()

    async def on_scanner_detection(self, device: BLEDevice, data: AdvertisementData):
        if self.allow_duplicates:
            self.on_event(EventData(BluetoothEvent.BLE_SCANNER_DEVICE, {'device': device, 'data': data}))
        else:
            async with self.device_lock:
                if device not in self.device_set:
                    self.device_set.add(device)
                    self.on_event(EventData(BluetoothEvent.BLE_SCANNER_DEVICE, {'device': device, 'data': data}))

    async def start_scanner(self):
        self.device_set.clear()
        self.context_keep_alive.clear()
        async with BleakScanner(detection_callback=self.on_scanner_detection) as context:
            self.context = context
            self.on_event(EventData(BluetoothEvent.BLE_SCANNER_STARTED, context))
            await self.context_keep_alive.wait()
        self.on_event(EventData(BluetoothEvent.BLE_SCANNER_STOPPED))
        self.context = None

    def stop_scanner(self) -> None:
        self.context_keep_alive.set()

    def on_event(self, event_data: EventData) -> None:
        if self.on_event_cb:
            self.on_event_cb(event_data)
        else:
            self.logger.info(f'Event noop {event_data}')

class BluetoothNative:
    async def disconnect(address: str) -> None:
        """
        Native BLE disconnect, clean up dangling BLE connection
        """
        if platform.system() == 'Linux':
            process = await asyncio.create_subprocess_exec('bluetoothctl', 'disconnect', address)
            await process.wait()
        else:
            print(f'Skipped disconnect for unknown platform address={address}')
