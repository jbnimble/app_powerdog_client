#!/usr/bin/env python

import argparse
import asyncio
from asyncio import TaskGroup
import configparser
import logging

from bleak import BleakClient, BleakScanner, BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from asyncio_paho import AsyncioPahoClient

from data import WatchdogDataValue, WatchdogDataType

logging.basicConfig(level=logging.INFO)

class DeviceScanner:
    def __init__(self, address: str):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.address = address
        self.device: BLEDevice = None
        self.event: Event = None

    def on_detection(self, device: BLEDevice, data):
        if self.address and not self.device and device.address == self.address:
            self.device = device
            self.event.set()

    async def execute(self) -> BLEDevice | None:
        async with BleakScanner(detection_callback=self.on_detection) as scanner:
            self.event = asyncio.Event()
            await self.event.wait()
            self.logger.info(f'BLE client {self.device}')
            return self.device

class ServiceFinder:
    def __init__(self, device: BLEDevice, uuid: str):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.uuid = uuid

    async def execute(self) -> BleakGATTCharacteristic | None:
        result = None
        async with BleakClient(address_or_ble_device=self.device) as client:
            for entry in client.services.characteristics.values():
                if entry.uuid == self.uuid:
                    result = entry
                    break
            self.logger.info(f'BLE service {result}')
            return result

class ServiceNotifier:
    def __init__(self, device: BLEDevice, service: BleakGATTCharacteristic, on_data_callback):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.service = service
        self.prev_raw_data: str = None
        self.on_data_callback = on_data_callback

    async def on_notify(self, sender: BleakGATTCharacteristic, data: bytearray):
        data_hex = data.hex()
        value = WatchdogDataValue(raw_data=data_hex)
        self.logger.debug(f'on_notify {value}')

        if value.data_type == WatchdogDataType.DATA:
            self.prev_raw_data = data_hex
        elif self.prev_raw_data and (value.data_type == WatchdogDataType.LINE1 or value.data_type == WatchdogDataType.LINE2):
            result = WatchdogDataValue(self.prev_raw_data)
            result.data_type = value.data_type
            await self.on_data_callback(result)
            self.prev_raw_data = None
        else:
            pass # unknown value, TODO handle other data_type's

    async def execute(self):
        async with BleakClient(address_or_ble_device=self.device) as client:
            await client.start_notify(char_specifier=self.service, callback=self.on_notify)
            await asyncio.Future()

class PowerdogConfig:
    def __init__(self):
        self.address: str = None
        self.service: str = None
        self.broker_host: str = None
        self.broker_port: int = -1
        self.broker_user: str = None
        self.broker_pass: str = None

class MessageSender:
    def __init__(self, config: PowerdogConfig):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        self.mqtt_client = None

    async def on_get_message(self, client, userdata, message):
        self.logger.info(f'Subscribed topic = {message.topic}: {message.payload}')

    async def publish_messages(self, messages: []) -> None:
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.logger.debug(f'Publish messages = {messages}')
            for message in messages:
                await self.mqtt_client.asyncio_publish(topic=message['topic'], payload=message['payload'])
        else:
            self.logger.warning('Skipped publishing messages')

    async def subscribe_all_powerdog(self) -> None:
        for line_code in ['L1', 'L2']:
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/voltage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/amperage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/wattage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/power_usage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/error')

    async def execute(self):
        async with AsyncioPahoClient() as client:
            self.mqtt_client = client
            client.username_pw_set(username=self.config.broker_user, password=self.config.broker_pass)
            client.asyncio_listeners.add_on_message(callback=self.on_get_message)
            client.connect_async(host=self.config.broker_host, port=self.config.broker_port)

            await asyncio.sleep(delay=3.0) # TODO: change sleep to wait until is_connected() == True
            self.logger.info(f'is_connected = {client.is_connected()}')

            await self.subscribe_all_powerdog()
            # await client.asyncio_publish(topic='my_test', payload='hello world')

            await asyncio.Future()

class PowerdogTopicMapper:
    def __init__(self, line, value):
        self.line = line
        self.value = value

    def values(self) -> []:
        result = []
        line_code = 'L1' if self.line == WatchdogDataType.LINE1 else 'L2'
        error_code = 0 if not self.value.error else self.value.error.value

        result.append({'topic': f'powerdog/{line_code}/voltage', 'payload': self.value.voltage})
        result.append({'topic': f'powerdog/{line_code}/amperage', 'payload': self.value.amperage})
        result.append({'topic': f'powerdog/{line_code}/wattage', 'payload': self.value.wattage})
        result.append({'topic': f'powerdog/{line_code}/power_usage', 'payload': self.value.power_usage})
        result.append({'topic': f'powerdog/{line_code}/error', 'payload': error_code})

        return result

class PowerdogClient:
    def __init__(self, config: PowerdogConfig):
        self.config: PowerdogConfig = config
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.sender = None

    async def on_data_ready(self, data: WatchdogDataValue):
        line = data.data_type
        value = WatchdogDataValue(raw_data=data.raw_data)
        self.logger.debug(f'on_data_ready line={line} > {value}')

        if self.sender:
            await self.sender.publish_messages(PowerdogTopicMapper(line, value).values())
        else:
            self.logger.warning(f'MQTT not connected line={line} value={value}')

    async def execute(self):
        device = await DeviceScanner(address=self.config.address).execute()
        service = await ServiceFinder(device=device, uuid=self.config.service).execute()
        
        async with TaskGroup() as group:
            notifier = ServiceNotifier(device=device, service=service, on_data_callback=self.on_data_ready)
            group.create_task(notifier.execute())
            self.sender = MessageSender(config=self.config)
            group.create_task(self.sender.execute())

def main():
    arg_parser = argparse.ArgumentParser(description='Powerdog Client')
    arg_parser.add_argument('--config-file', help='INI style configuration file', default='config.ini')
    args = arg_parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config_file)

    client_config = PowerdogConfig()
    client_config.address = config['POWERDOG']['address']
    client_config.service = config['POWERDOG']['service']
    client_config.broker_host = config['BROKER']['host']
    client_config.broker_port = int(config['BROKER']['port'])
    client_config.broker_user = config['BROKER']['user']
    client_config.broker_pass = config['BROKER']['pass']

    try:
        asyncio.run(PowerdogClient(config=client_config).execute())
    except KeyboardInterrupt:
        print('Program interrupted by user (Ctrl+C). Shutting down')

if __name__ == '__main__':
    main()
