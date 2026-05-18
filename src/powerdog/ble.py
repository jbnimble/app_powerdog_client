import asyncio
from asyncio import Task
from asyncio.subprocess import Process
from enum import StrEnum
import logging
import platform
from typing import Callable
from uuid import UUID

from bleak import BleakClient, BleakScanner, BLEDevice, AdvertisementData, BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService
from bleak.exc import BleakDeviceNotFoundError, BleakError, BleakGATTProtocolError

from powerdog.event import EventData
from powerdog.data import GattData, GattType, BluetoothDeviceMeta, DeviceMetaService, DeviceMetaChar, DeviceMetaDesc, BLENotification
from powerdog.util import PowerdogUtil

class BluetoothEvent(StrEnum):
    BLE_SCANNER_STARTED =     'ble_scanner_started'
    BLE_SCANNER_DEVICE =      'ble_scanner_device'
    BLE_SCANNER_FAILED =      'ble_scanner_failed'
    BLE_SCANNER_STOPPED =     'ble_scanner_stopped'
    BLE_CLIENT_STARTED =      'ble_client_started'
    BLE_CLIENT_FAILURE =      'ble_client_failure'
    BLE_CLIENT_STOPPED =      'ble_client_stopped'
    BLE_CLIENT_META_DATA =    'ble_client_meta_data'
    BLE_CLIENT_META_FAILURE = 'ble_client_meta_failure'
    BLE_CLIENT_DISCONNECTED = 'ble_client_disconnected'
    BLE_NOTIFY_STARTED =      'ble_notify_started'
    BLE_NOTIFY_FAIL_START =   'ble_notify_fail_start'
    BLE_NOTIFY_FAIL_STOP =    'ble_notify_fail_stop'
    BLE_NOTIFY_STOPPED =      'ble_notify_stopped'
    BLE_NOTIFY_NOT_FOUND =    'ble_notify_not_found'
    BLE_NOTIFY_FOUND =        'ble_notify_found'
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
    def __init__(self, on_event_cb: Callable[[EventData], None] = None):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self._device = None
        self._on_event_cb = on_event_cb
        self._notify_specifier_set = set()
        self._context_keep_alive = asyncio.Event()
        self._context_keep_alive.set()
        self._context: BleakClient = None

    def _on_event(self, event_data: EventData) -> None:
        if self._on_event_cb:
            self._on_event_cb(event_data)

    async def _on_notify(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """ Callback for start_notify characteristic data """
        self._on_event(EventData(BluetoothEvent.BLE_NOTIFY_DATA, BLENotification(sender=sender, data=data.hex())))

    def _on_disconnected(self, client):
        """ Callback when BleakClient disconnects, cannot be async """
        self._on_event(EventData(BluetoothEvent.BLE_CLIENT_DISCONNECTED))

    async def start_client(self, device: BLEDevice | str):
        """ Connect to provided BLE device """
        self._device = device
        self._context_keep_alive.clear()
        try:
            async with BleakClient(address_or_ble_device=self._device, disconnected_callback=self._on_disconnected) as context:
                self._context = context
                self._on_event(EventData(BluetoothEvent.BLE_CLIENT_STARTED, context))
                await self._context_keep_alive.wait()
            self._on_event(EventData(BluetoothEvent.BLE_CLIENT_STOPPED))
        except Exception as e:
            self.logger.error(f'Client failure {e}')
            self._on_event(EventData(BluetoothEvent.BLE_CLIENT_FAILURE))
        self._context = None
        self._device = None
        self.logger.info('Stopped')

    def stop_client(self) -> None:
        """ Trigger client stop """
        self._context_keep_alive.set()

    def is_notify(self, char_specifier: BleakGATTCharacteristic) -> bool:
        """" Status if char_specifier is an active notifier """
        return char_specifier in self._notify_specifier_set

    def is_active(self) -> bool:
        """ Status if client is active and connected to BLE device """
        return self._context and not self._context_keep_alive.is_set() and self._context.is_connected

    async def start_notify(self, char_specifier: BleakGATTCharacteristic) -> None:
        """ Start notifications for char_specifier """
        try:
            if not self.is_active():
                raise Exception('Client not active')
            await self._context.start_notify(char_specifier=char_specifier, callback=self._on_notify)
            self._notify_specifier_set.add(char_specifier)
            self._on_event(EventData(BluetoothEvent.BLE_NOTIFY_STARTED, char_specifier))
        except Exception as e:
            self.logger.error(f'Start notify failure {char_specifier} caused {e}')
            self._on_event(EventData(BluetoothEvent.BLE_NOTIFY_FAIL_START, char_specifier))

    async def stop_notify(self, char_specifier: BleakGATTCharacteristic) -> None:
        """ Stop notifications for char_specifier """
        try:
            if not self.is_active():
                raise Exception('Client not active')
            await self._context.stop_notify(char_specifier=char_specifier)
            self._notify_specifier_set.remove(char_specifier)
            self._on_event(EventData(BluetoothEvent.BLE_NOTIFY_STOPPED, char_specifier))
        except Exception as e:
            self.logger.error(f'Stop notify failure {char_specifier} caused {e}')
            self._on_event(EventData(BluetoothEvent.BLE_NOTIFY_FAIL_STOP, char_specifier))

    def get_char_by_uuid(self, char_uuid: str) -> BleakGATTCharacteristic | None:
        result = None
        if self.is_active() and char_uuid:
            result = self._context.services.get_characteristic(specifier=char_uuid)
        return result

    async def write_gatt_char(self, char_specifier: BleakGATTCharacteristic, data: bytes) -> None:
        if self.is_active():
            await self._context.write_gatt_char(char_specifier=char_specifier, data=data, response=True)

    async def read_gatt_char(self, char_specifier: BleakGATTCharacteristic) -> None:
        if self.is_active():
            try:
                data = await self._context.read_gatt_char(char_specifier=char_specifier)
                data_hex = data.hex()
                data_ascii = PowerdogUtil.bytearray_to_ascii(data)
                self.logger.info(f'READ {char_specifier} hex={data_hex} asc={data_ascii}')
            except Exception as e:
                self.logger.error(f'READ GATT {char_specifier} caused {e}')

    async def get_meta_data(self) -> None:
        """ Send event with BluetoothDeviceMeta or failure event """
        if not self._context or not self._device:
            self._on_event(EventData(BluetoothEvent.BLE_CLIENT_META_FAILURE))
            return

        def fix_data(value: str) -> str:
            """ Remove unicode null's and if contains newline characters then ensure only alphanumeric """
            result = value.replace('\u0000', '')
            if result.find('\r') >= 0 or result.find('\n') >= 0:
                result = ''.join([char for char in result if char.isalnum()])
            return result

        result = BluetoothDeviceMeta()
        result.name = self._device.name
        result.address = self._device.address
        result.details = self._device.details
        service_list = []

        for serv in self._context.services.services.values():
            meta_service = DeviceMetaService(handle=serv.handle, uuid=serv.uuid, description=serv.description)
            char_list = []
            for char in serv.characteristics:
                detail_char = DeviceMetaChar(handle=char.handle, uuid=char.uuid, description=char.description)
                if len(char.properties) > 0:
                    detail_char.properties = char.properties
                try:
                    data: bytearray = await self._context.read_gatt_char(char_specifier=char)
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
                        data: bytearray = await self._context.read_gatt_descriptor(desc_specifier=desc, use_cached=False)
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
        self._on_event(EventData(BluetoothEvent.BLE_CLIENT_META_DATA, result))

class BluetoothEventScanner:
    """
    BLE device scanner with EventData callback and Event enum

    TODO allow special args to BleakScanner (service_uuids, scanning_mode, bluez, cb, backend, kwargs)
    """
    def __init__(self, on_event_cb: Callable[[EventData], None] = None, allow_duplicates: bool = True):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.on_event_cb = on_event_cb
        self.allow_duplicates = allow_duplicates
        self._context_keep_alive = asyncio.Event()
        self._context_keep_alive.set()
        self._context: BleakScanner = None
        self.device_lock = asyncio.Lock()
        self.device_set = set()

    def _on_event(self, event_data: EventData) -> None:
        if self.on_event_cb:
            self.on_event_cb(event_data)

    async def _on_scanner_detection(self, device: BLEDevice, data: AdvertisementData):
        if self.allow_duplicates:
            self._on_event(EventData(BluetoothEvent.BLE_SCANNER_DEVICE, {'device': device, 'data': data}))
        else:
            async with self.device_lock:
                if device not in self.device_set:
                    self.device_set.add(device)
                    self._on_event(EventData(BluetoothEvent.BLE_SCANNER_DEVICE, {'device': device, 'data': data}))

    async def start_scanner(self):
        self.device_set.clear()
        self._context_keep_alive.clear()
        try:
            async with BleakScanner(detection_callback=self._on_scanner_detection) as context:
                self._context = context
                self._on_event(EventData(BluetoothEvent.BLE_SCANNER_STARTED, context))
                await self._context_keep_alive.wait()
            self._on_event(EventData(BluetoothEvent.BLE_SCANNER_STOPPED))
        except Exception as e:
            self.logger.error(f'Scanner failure {e}')
            self._on_event(EventData(BluetoothEvent.BLE_SCANNER_FAILED))
        self._context = None
        self.logger.info('Stopped')

    def stop_scanner(self) -> None:
        self._context_keep_alive.set()

    def is_active(self) -> bool:
        return self._context and not self._context_keep_alive.is_set()

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
