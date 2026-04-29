import asyncio
import logging
from typing import Callable

from bleak import BleakClient, BleakScanner, BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from data import PowerdogData, PowerdogDataType, PowerdogConfig

class PowerdogDecoder:
    """
    Decode the notify service data

    The data is a 20 byte hex string, with the following patterns:
    5245534554.............................. resetting
    72656c6179206f6e........................ relay on
    ..................................000000 check point line 1, previous data was line 1
    ..................................010101 check point line 2, previous data was line 2
    010320vvvvvvvvaaaaaaaawwwwwwwwppppppppee > data line (v=volts, a=amps, w=watts, p=power, e=error)
    """

    def decode(raw_data: str) -> PowerdogData:
        """ Expects a hex string, decodes the values and outputs a PowerdogData """
        result = PowerdogData()

        index_06 = 6
        index_14 = 14
        index_22 = 22
        index_30 = 30
        index_34 = 34
        index_38 = 38
        index_40 = 40

        if raw_data and raw_data.startswith('72656c6179206f6e'):
            result.data_type = PowerdogDataType.RELAY.value
        if raw_data and raw_data.startswith('5245534554'):
            result.data_type = PowerdogDataType.RESET.value
        if raw_data and len(raw_data) == index_40:
            if not raw_data.startswith('010320') and raw_data[index_34:index_40] == '000000':
                result.data_type = PowerdogDataType.LINE1.value
            if not raw_data.startswith('010320') and raw_data[index_34:index_40] == '010101':
                result.data_type = PowerdogDataType.LINE2.value
            if raw_data.startswith('010320'):
                result.data_type = PowerdogDataType.DATA.value
                index_ranges = [('voltage',index_06,index_14), ('amperage',index_14,index_22), ('wattage',index_22,index_30), ('power_usage',index_30,index_38)]
                for attr_name,index_start,index_end in index_ranges:
                    data = int(raw_data[index_start:index_end], 16) / 10000.0
                    setattr(result, attr_name, data)
                result.error = int(raw_data[index_38:index_40], 16)

        return result

class AsyncServiceNotifier:
    """
    - Find BLEDevice that matches address
    - Connect to BLE device
    - Find service via UUID
    - Start service notification's
    - Auto-connect if BLE device disconnects

    References: https://bleak.readthedocs.io/en/latest/index.html
    """
    def __init__(self, config: PowerdogConfig, on_data_callback: Callable[[PowerdogData], None]):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        self.on_data_callback = on_data_callback
        self.is_device_found = asyncio.Event()
        self.is_notify_started = asyncio.Event()
        self.device = None
        self.service = None
        self.prev_data: PowerdogData = None

    def on_scanner_detection(self, device: BLEDevice, data):
        if not self.device and device.address == self.config.address:
            self.device = device
            self.is_device_found.set()
            self.logger.info(f'BLE client {self.device}')

    def find_service(self, client):
        for entry in client.services.characteristics.values():
            if entry.uuid == self.config.service:
                self.service = entry
                break
        if self.service:
            self.logger.info(f'Service found {self.service}')
        else:
            self.logger.warning(f'Failed to find service uuid={self.config.service}')

    def on_client_disconnected(self, client):
        self.logger.info(f'Disconnected {client}')
        self.is_notify_started.clear()

    async def on_service_notify(self, sender: BleakGATTCharacteristic, data: bytearray):
        if not self.is_notify_started.is_set():
            self.is_notify_started.set()
            self.logger.info('Service started')

        pd_data = PowerdogDecoder.decode(raw_data=data.hex())
        self.logger.debug(f'on_notify {pd_data}')

        if pd_data.data_type == PowerdogDataType.DATA.value:
            self.prev_data = pd_data # save data until next LINE1 or LINE2 notification
        elif self.prev_data and (pd_data.data_type == PowerdogDataType.LINE1.value or pd_data.data_type == PowerdogDataType.LINE2.value):
            result = self.prev_data
            result.data_type = pd_data.data_type # update LINE1 or LINE2 type on previous data
            await self.on_data_callback(result)
            self.prev_data = None
        else:
            self.logger.warning(f'Unhandled data={pd_data} prev={self.prev_data}')

    async def restart_loop(self, client) -> None:
        while True:
            if not client.is_connected:
                self.logger.info(f'Connecting {client}')
                try:
                    await client.connect()
                except asyncio.TimeoutError as e:
                    self.logger.warning(f'Timeout when connecting {client}')
                if client.is_connected:
                    self.logger.info(f'Connected {client}')
                else:
                    self.logger.info(f'Connection failed {client}')
            if not self.is_notify_started.is_set():
                self.logger.info('Service starting')
                await client.start_notify(char_specifier=self.service, callback=self.on_service_notify)
                await self.is_notify_started.wait()
            await asyncio.sleep(3.0)

    async def execute(self):
        async with BleakScanner(detection_callback=self.on_scanner_detection) as scanner:
            await self.is_device_found.wait()

        async with BleakClient(address_or_ble_device=self.device, disconnected_callback=self.on_client_disconnected) as client:
            if client.is_connected:
                self.logger.info(f'Connected {client}')
            self.find_service(client=client)
            await self.restart_loop(client)
