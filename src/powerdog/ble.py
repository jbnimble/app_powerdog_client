import asyncio
from asyncio import Task
from asyncio.subprocess import Process
from enum import StrEnum
import logging
import platform
from typing import Callable

from bleak import BleakClient, BleakScanner, BLEDevice, AdvertisementData, BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService
from bleak.exc import BleakDeviceNotFoundError, BleakError, BleakGATTProtocolError

from powerdog.event import EventData
from powerdog.data import GattData, GattType, BluetoothDeviceMeta, DeviceMetaService, DeviceMetaChar, DeviceMetaDesc
from powerdog.util import PowerdogUtil

class BluetoothEvent(StrEnum):
    BLE_SCANNER_STARTED =     'ble_scanner_started'
    BLE_SCANNER_DEVICE =      'ble_scanner_device'
    BLE_SCANNER_STOPPED =     'ble_scanner_stopped'
    BLE_CLIENT_STARTED =      'ble_client_started'
    BLE_CLIENT_STOPPED =      'ble_client_stopped'
    BLE_CLIENT_META_DATA =    'ble_client_meta_data'
    BLE_CLIENT_DISCONNECTED = 'ble_client_disconnected'
    BLE_NOTIFY_STARTED =      'ble_notify_started'
    BLE_NOTIFY_FAIL_START =   'ble_notify_fail_start'
    BLE_NOTIFY_FAIL_STOP =    'ble_notify_fail_stop'
    BLE_NOTIFY_STOPPED =      'ble_notify_stopped'
    BLE_SERVICE_FOUND =       'ble_service_found'
    BLE_NOTIFY_DATA =         'ble_notify_data'

# class BluetoothEventAdapter:
#     """ TODO BleakAdapter code in bleak develop branch and unreleased, method to get the connected devices, eventually use to check for performing a force disconnect """
#     def __init__(self):
#         self.logger: Logger = logging.getLogger(self.__class__.__name__)

#     async def start(self) -> None:
#         self.logger.info('get adapter')
#         adapter = await BleakAdapter.get()
#         self.logger.info('get connected devices')
#         ble_devices = adapter.get_connected_devices()
#         self.logger.info(f'devices = {ble_devices}')

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
        self.context_keep_alive.set()
        self.context: BleakClient = None

    async def on_notify(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """ Callback for start_notify characteristic data """
        if sender == self.notify_specifier:
            self.on_event(EventData(BluetoothEvent.BLE_NOTIFY_DATA, data.hex()))
        else:
            self.logger.warning(f'on_notify unknown characteristic={sender} data={data.hex()}')

    def on_disconnected(self, client):
        """ Callback when BleakClient disconnects, cannot be async """
        self.on_event(EventData(BluetoothEvent.BLE_CLIENT_DISCONNECTED))

    async def start_client(self):
        self.context_keep_alive.clear()
        async with BleakClient(address_or_ble_device=self.device, disconnected_callback=self.on_disconnected) as context:
            self.context = context
            self.on_event(EventData(BluetoothEvent.BLE_CLIENT_STARTED, context))
            await self.context_keep_alive.wait()
        self.on_event(EventData(BluetoothEvent.BLE_CLIENT_STOPPED))
        self.context = None
        self.logger.info('Stopped')

    def stop_client(self) -> None:
        self.context_keep_alive.set()

    def is_stopped(self) -> bool:
        return (not self.context and self.context_keep_alive.is_set()) or (self.context and not self.context.is_connected)

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

    async def get_meta_data(self) -> None:
        def fix_data(value: str) -> str:
            """ Remove unicode null's and if contains newline characters then ensure only alphanumeric """
            result = value.replace('\u0000', '')
            if result.find('\r') >= 0 or result.find('\n') >= 0:
                result = ''.join([char for char in result if char.isalnum()])
            return result

        result = BluetoothDeviceMeta()
        result.name = self.device.name
        result.address = self.device.address
        result.details = self.device.details
        service_list = []

        for serv in self.context.services.services.values():
            meta_service = DeviceMetaService(handle=serv.handle, uuid=serv.uuid, description=serv.description)
            char_list = []
            for char in serv.characteristics:
                detail_char = DeviceMetaChar(handle=char.handle, uuid=char.uuid, description=char.description)
                if len(char.properties) > 0:
                    detail_char.properties = char.properties
                try:
                    data: bytearray = await self.context.read_gatt_char(char_specifier=char)
                    data_hex = data.hex()
                    data_ascii = fix_data(PowerdogUtil.bytearray_to_ascii(data))
                    if len(data_hex) > 0:
                        detail_char.hex_data = data_hex
                    if len(data_ascii) > 0:
                        detail_char.asc_data = data_ascii
                except BleakGATTProtocolError as e:
                    pass

                desc_list = []
                for desc in char.descriptors:
                    detail_desc = DeviceMetaDesc(handle=desc.handle, uuid=desc.handle, description=desc.description)
                    try:
                        data: bytearray = await self.context.read_gatt_descriptor(desc_specifier=desc, use_cached=False)
                        data_hex = data.hex()
                        data_ascii = fix_data(PowerdogUtil.bytearray_to_ascii(data))
                        if len(data_hex) > 0:
                            detail_desc.hex_data = data_hex
                        if len(data_ascii) > 0:
                            detail_desc.asc_data = data_ascii
                    except BleakGATTProtocolError as e:
                        pass

                    desc_list.append(detail_desc)
                if len(desc_list) > 0:
                    detail_char.descriptor = desc_list
                char_list.append(detail_char)
            if len(char_list) > 0:
                meta_service.characteristic = char_list
            if len(service_list) > 0:
                result.service = service_list
            service_list.append(meta_service)
        self.on_event(EventData(BluetoothEvent.BLE_CLIENT_META_DATA, result))

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
        self.context_keep_alive.set()
        self.context: BleakScanner = None
        self.device_lock = asyncio.Lock()
        self.device_set = set()

    def on_event(self, event_data: EventData) -> None:
        if self.on_event_cb:
            self.on_event_cb(event_data)
        else:
            self.logger.info(f'Event noop {event_data}')

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
        self.logger.info('Stopped')

    def stop_scanner(self) -> None:
        self.context_keep_alive.set()

    def is_stopped(self) -> bool:
        return not self.context and self.context_keep_alive.is_set()

    def is_scanner_activated(self) -> bool:
        return not self.context_keep_alive.is_set() and self.context

class BluetoothNative:
    def __init__(self):
        # NOTE could change to event-based, no need currently
        self.logger: Logger = logging.getLogger(self.__class__.__name__)

    async def disconnect(self, address: str) -> None:
        """ BLE disconnect of existing BLE connection """
        if not address:
            self.logger.warning('disconnect skipped, no address')
        elif platform.system() == 'Linux':
            try:
                process: Process = await asyncio.create_subprocess_exec('bluetoothctl', 'disconnect', address,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                async for line_bytes in process.stdout:
                    # change logging.DEBUG to see STDOUT of process
                    self.logger.debug(f'{line_bytes.decode().strip()}')
                async for line_bytes in process.stderr:
                    self.logger.error(f'{line_bytes.decode().strip()}')
                await process.wait()
                self.logger.info(f'disconnect completed code={process.returncode} address={address}')
            except Exception as e:
                self.logger.error(f'disconnect failed, platform={platform.system()} address={address} due to {e}')
        else:
            self.logger.warning(f'disconnect skipped, platform={platform.system()} address={address}')
