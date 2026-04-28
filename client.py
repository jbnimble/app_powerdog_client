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
    """
    https://bleak.readthedocs.io/en/latest/index.html
    """
    def __init__(self, device: BLEDevice, service: BleakGATTCharacteristic, on_data_callback):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.service = service
        self.prev_raw_data: str = None
        self.on_data_callback = on_data_callback

    def on_disconnected(self, client):
        self.logger.info(f'Disconnected {client}')

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
            pass # TODO handle other data_type's

    async def execute(self):
        async with BleakClient(address_or_ble_device=self.device, disconnected_callback=self.on_disconnected) as client:
            if client.is_connected:
                self.logger.info(f'Connected {client}')
            await client.start_notify(char_specifier=self.service, callback=self.on_notify)
            await asyncio.Future() # wait forever

class PowerdogConfig:
    def __init__(self):
        self.address: str = None
        self.service: str = None
        self.broker_host: str = None
        self.broker_port: int = -1
        self.broker_user: str = None
        self.broker_pass: str = None
        self.subscribe_topics: bool = False

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

    # POWERDOG > address is required
    if 'POWERDOG' in config and 'address' in config['POWERDOG']:
        client_config.address = config['POWERDOG'].get('address')
    else:
        raise configparser.NoOptionError('address', 'POWERDOG')
    # POWERDOG > service is required
    if 'POWERDOG' in config and 'service' in config['POWERDOG']:
        client_config.service = config['POWERDOG'].get('service')
    else:
        raise configparser.NoOptionError('service', 'POWERDOG')
    # BROKER section required
    if 'BROKER' not in config:
        raise configparser.NoSectionError('BROKER')

    client_config.broker_host = config['BROKER'].get('host', fallback='localhost')
    client_config.broker_port = config['BROKER'].getint('port', fallback=1883)
    client_config.broker_user = config['BROKER'].get('user', fallback=None)
    client_config.broker_pass = config['BROKER'].get('pass', fallback=None)
    client_config.subscribe_topics = config['BROKER'].getboolean('subscribe_topics', fallback=False)

    try:
        asyncio.run(PowerdogClient(config=client_config).execute())
    except KeyboardInterrupt:
        print('Program interrupted by user (Ctrl+C). Shutting down')

if __name__ == '__main__':
    main()
