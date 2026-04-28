#!/usr/bin/env python

import argparse
import asyncio
from asyncio import TaskGroup
import configparser
import logging
from typing import Callable

from bleak import BleakClient, BleakScanner, BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from asyncio_paho import AsyncioPahoClient

from data import WatchdogDataValue, WatchdogDataType

logging.basicConfig(level=logging.INFO)

class PowerdogConfig:
    def __init__(self):
        self.address: str = None
        self.service: str = None
        self.broker_host: str = None
        self.broker_port: int = -1
        self.broker_user: str = None
        self.broker_pass: str = None
        self.subscribe_topics: bool = False
        # TODO: add BLE timeout value

    def configure(self, config_file: str):
        config = configparser.ConfigParser()
        config.read(config_file)
        # POWERDOG > address is required
        if 'POWERDOG' in config and 'address' in config['POWERDOG']:
            self.address = config['POWERDOG'].get('address')
        else:
            raise configparser.NoOptionError('address', 'POWERDOG')
        # POWERDOG > service is required
        if 'POWERDOG' in config and 'service' in config['POWERDOG']:
            self.service = config['POWERDOG'].get('service')
        else:
            raise configparser.NoOptionError('service', 'POWERDOG')
        # BROKER section required
        if 'BROKER' not in config:
            raise configparser.NoSectionError('BROKER')

        self.broker_host = config['BROKER'].get('host', fallback='localhost')
        self.broker_port = config['BROKER'].getint('port', fallback=1883)
        self.broker_user = config['BROKER'].get('user', fallback=None)
        self.broker_pass = config['BROKER'].get('pass', fallback=None)
        self.subscribe_topics = config['BROKER'].getboolean('subscribe_topics', fallback=False)

class PowerdogMessageMapper:
    """
    Map the WatchdogDataType and WatchdogDataValue to MQTT topics:
    powerdog/L1/voltage
    powerdog/L1/amperage
    powerdog/L1/wattage
    powerdog/L1/power_usage
    powerdog/L1/error
    powerdog/L2/voltage
    powerdog/L2/amperage
    powerdog/L2/wattage
    powerdog/L2/power_usage
    powerdog/L2/error
    """
    def __init__(self, line: WatchdogDataType, data: WatchdogDataValue):
        self.line: WatchdogDataType = line
        self.data: WatchdogDataValue = data

    def messages(self) -> []:
        result = []
        line_code = 'L1' if self.line == WatchdogDataType.LINE1 else 'L2'
        error_code = 0 if not self.data.error else self.data.error.value

        result.append({'topic': f'powerdog/{line_code}/voltage', 'payload': self.data.voltage})
        result.append({'topic': f'powerdog/{line_code}/amperage', 'payload': self.data.amperage})
        result.append({'topic': f'powerdog/{line_code}/wattage', 'payload': self.data.wattage})
        result.append({'topic': f'powerdog/{line_code}/power_usage', 'payload': self.data.power_usage})
        result.append({'topic': f'powerdog/{line_code}/error', 'payload': error_code})

        return result

class ServiceNotifier:
    """
    https://bleak.readthedocs.io/en/latest/index.html
    """
    def __init__(self, config: PowerdogConfig, on_data_callback: Callable[[WatchdogDataValue], None]):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        self.on_data_callback = on_data_callback
        self.is_device_found = asyncio.Event()
        self.is_notify_started = asyncio.Event()
        self.device = None
        self.service = None
        self.prev_raw_data: str = None

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
            pass # TODO handle other data_type's

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

class MessageSender:
    """
    AsyncioPahoClient auto-retries to connect on connection failures
    https://pypi.org/project/asyncio-paho/
    https://github.com/toreamun/asyncio-paho/tree/main
    """
    def __init__(self, config: PowerdogConfig):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        self.connected_flag = asyncio.Event()
        self.mqtt_client = None

    def disconnected(self, message: str = ''):
        self.connected_flag.clear()
        self.logger.info(f'Disconnected MQTT@{self.config.broker_host}:{self.config.broker_port} {message}')

    async def on_connect_pass(self, client, userdata, flags_dict, result):
        self.mqtt_client = client
        if self.mqtt_client.is_connected():
            self.connected_flag.set()
            self.logger.info(f'Connected MQTT@{self.config.broker_host}:{self.config.broker_port}')
        else:
            self.logger.info(f'Connecting MQTT@{self.config.broker_host}:{self.config.broker_port}')

    async def on_connect_fail(self, client, userdata, flags_dict, result):
        self.disconnected(message='connection fail')

    async def on_subscribed(self, client, userdata, message):
        self.logger.info(f'Subscribed topic = {message.topic}: {message.payload}')

    async def publish_messages(self, messages: []) -> None:
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.logger.debug(f'Publish messages = {messages}')
            for message in messages:
                await self.mqtt_client.asyncio_publish(topic=message['topic'], payload=message['payload'])
        elif self.connected_flag.is_set():
                self.disconnected(message='failed to publish messages')

    async def subscribe_all_powerdog(self) -> None:
        for line_code in ['L1', 'L2']:
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/voltage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/amperage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/wattage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/power_usage')
            await self.mqtt_client.asyncio_subscribe(topic=f'powerdog/{line_code}/error')

    async def execute(self):
        async with AsyncioPahoClient() as client:
            auth_message = 'no authentication provided'
            if self.config.broker_user and self.config.broker_pass:
                client.username_pw_set(username=self.config.broker_user, password=self.config.broker_pass)
                auth_message = 'authentication configured'
            self.logger.info(f'Configuring MQTT@{self.config.broker_host}:{self.config.broker_port} {auth_message}')
            client.asyncio_listeners.add_on_message(callback=self.on_subscribed)
            client.asyncio_listeners.add_on_connect(callback=self.on_connect_pass)
            client.asyncio_listeners.add_on_connect_fail(callback=self.on_connect_fail)
            client.connect_async(host=self.config.broker_host, port=self.config.broker_port)
            await self.connected_flag.wait()
            if self.config.subscribe_topics:
                await self.subscribe_all_powerdog()
            await asyncio.Future() # wait forever

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
            await self.sender.publish_messages(PowerdogMessageMapper(line, value).messages())
        else:
            self.logger.debug(f'MQTT not connected line={line} value={value}')

    async def execute(self):
        async with TaskGroup() as group:
            notifier = ServiceNotifier(config=self.config, on_data_callback=self.on_data_ready)
            group.create_task(notifier.execute())
            self.sender = MessageSender(config=self.config)
            group.create_task(self.sender.execute())

def main():
    arg_parser = argparse.ArgumentParser(description='Powerdog Client')
    arg_parser.add_argument('--config-file', help='INI style configuration file', default='config.ini')
    args = arg_parser.parse_args()

    client_config = PowerdogConfig()
    client_config.configure(config_file=args.config_file)

    try:
        asyncio.run(PowerdogClient(config=client_config).execute())
    except KeyboardInterrupt:
        print('Program interrupted by user (Ctrl+C). Shutting down')

if __name__ == '__main__':
    main()
