#!/usr/bin/env python

import argparse
import asyncio
from asyncio import Task, TaskGroup, Queue, QueueEmpty
from enum import StrEnum
from functools import partial
import json
import logging
from logging import Logger

from bleak import BLEDevice

from powerdog.ble import BluetoothEvent, BluetoothEventClient, BluetoothEventScanner, BluetoothNative
from powerdog.config import PowerdogConfig, BrokerConfig, ClientConfig, Configuration
from powerdog.data import PowerdogData, GattData, PowerdogModelType, BluetoothDeviceMeta, DiscoveryPayload, BLENotification
from powerdog.ha import MqttDiscovery
from powerdog.mq import BrokerEventClient, BrokerMessage, BrokerEvent, BrokerOneTimePublish
from powerdog.event import EventData
from powerdog.pd import PowerdogDecoder, DataLimiter, PowerdogDataType, PowerdogMessageMonitor
from powerdog.util import PowerdogUtil

class AppService:
    def __init__(self):
        self.ble_scanner: BluetoothEventScanner = None
        self.ble_client: BluetoothEventClient = None
        self.mq_client: BrokerEventClient = None
        self.data_limiter: DataLimiter = None
        self.message_monitor: PowerdogMessageMonitor = PowerdogMessageMonitor()

class AppData:
    def __init__(self, pd_config: PowerdogConfig, br_config: BrokerConfig, cl_config: ClientConfig):
        self.pd_config: PowerdogConfig = pd_config
        self.br_config: BrokerConfig = br_config
        self.cl_config: ClientConfig = cl_config
        self.ble_device_meta: BluetoothDeviceMeta = None
        self.discovery_payload: DiscoveryPayload = None
        self.prev_data: PowerdogData = None
        self.powerdog_discovery_topic: str = 'homeassistant/device/powerdog/config'
        self.powerdog_status_topic: str = 'powerdog/status'
        self.powerdog_status_online: str = 'online'
        self.powerdog_status_offline: str = 'offline'
        self.powerdog_command_topic: str = 'powerdog/set'
        self.powerdog_notify_desc_value: str = 'TX'
        self.powerdog_command_desc_value: str = 'RX'
        self.powerdog_command_reset: str = 'RESEt'
        self.powerdog_command_relay: str = 'RELAY ON'
        self.homeassistant_status_topic: str = 'homeassistant/status'
        self.homeassistant_status_online: str = 'online'
        self.homeassistant_status_offline: str = 'offline'
        self.ble_device: BLEDevice = None

class AppEvent(StrEnum):
    APP_START_SERVICES = 'app_start_services'

class App:
    def __init__(self, pd_config: PowerdogConfig, br_config: BrokerConfig, cl_config: ClientConfig):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.data = AppData(pd_config=pd_config, br_config=br_config, cl_config=cl_config)
        self.service = AppService()
        self.task_group = None
        self.event_to_action_loop = asyncio.Event()
        self.event_queue = Queue()
        self.service.ble_scanner = BluetoothEventScanner(on_event_cb=self.on_event_data, allow_duplicates=False)
        self.service.ble_client = BluetoothEventClient(on_event_cb=self.on_event_data)
        self.service.mq_client = BrokerEventClient(config=self.data.br_config, on_event_cb=self.on_event_data)
        self.service.data_limiter = DataLimiter(config=self.data.pd_config)

    def app_start(self) -> None:
        self.ble_scanner_start()
        self.broker_start()
        self.create_task(self.do_native_disconnect())

    async def app_stop(self) -> None:
        self.logger.debug('App > stopping')
        self.service.ble_scanner.stop_scanner()
        self.service.ble_client.stop_client()
        self.service.mq_client.stop_client()
        self.event_to_action_loop.set()

        time_limit = 10.0
        while not self.is_app_stopped():
            time_wait = 0.1
            time_limit = time_limit - time_wait
            await asyncio.sleep(time_wait)
            if time_limit <= 0.0:
                ble_scanner_state = self.service.ble_scanner.is_active()
                ble_client_state = self.service.ble_client.is_active()
                mq_client_state = self.service.mq_client.is_active()
                self.logger.warning(f'App > stopping, time limit reached ble_scanner={ble_scanner_state} ble_client={ble_client_state} mq_client={mq_client_state}')
                break

    def is_app_stopped(self) -> bool:
        return not self.service.ble_scanner.is_active() and not self.service.ble_client.is_active() and not self.service.mq_client.is_active()

    async def do_native_disconnect(self) -> None:
        """ Wait for a period, if no Powerdog BLE device found, then attempt native disconnect """
        await asyncio.sleep(10)
        if self.service.ble_scanner.is_active() and not self.data.ble_device:
            self.logger.info('BLE native > disconnect')
            await BluetoothNative().disconnect(self.data.pd_config.address)

    def on_event_data(self, event_data: EventData) -> None:
        self.event_queue.put_nowait(event_data)

    def create_task(self, coro):
        return self.task_group.create_task(coro)

    def ble_scanner_start(self) -> None:
        self.logger.debug('BLE scanner > start')
        self.task_group.create_task(self.service.ble_scanner.start_scanner())

    def on_scanner_device(self, ble_device: BLEDevice) -> None:
        if ble_device.address == self.data.pd_config.address and ble_device.name:
            self.data.ble_device = ble_device
            self.logger.info(f'BLE scanner > matching {ble_device}')
            self.ble_scanner_stop()
        elif not self.data.ble_device and not self.data.pd_config.address and ble_device.address and ble_device.name and PowerdogUtil.get_model_type(ble_device.name) != PowerdogModelType.UNKNOWN:
            self.logger.info(f'BLE scanner > detected {ble_device}')
            self.data.ble_device = ble_device
            self.ble_scanner_stop()
        else:
            self.logger.info(f'BLE scanner > device {ble_device}')

    def ble_scanner_stop(self) -> None:
        self.logger.debug('BLE scanner > stop')
        self.service.ble_scanner.stop_scanner()

    def ble_client_start(self) -> None:
        self.logger.debug(f'BLE client > start {self.data.ble_device}')
        self.task_group.create_task(self.service.ble_client.start_client(self.data.ble_device))

    def on_ble_client_started(self) -> None:
        self.task_group.create_task(self.service.ble_client.get_meta_data())

    def on_ble_client_metadata(self, meta_data: BluetoothDeviceMeta) -> None:
        self.logger.info('BLE client > metadata')
        self.data.ble_device_meta = meta_data
        self.write_meta_to_file()

    def write_meta_to_file(self):
        if self.data.pd_config.device_meta_path:
            try:
                with open(self.data.pd_config.device_meta_path, mode='w') as file:
                    json.dump(self.data.ble_device_meta, file, indent=4, default=PowerdogUtil.json_serializer)
            except Exception as e:
                self.logger.error(f'Failed to write {self.data.pd_config.device_meta_path} due to: {e}')

    def ble_client_stop(self) -> None:
        self.logger.debug('BLE client > stop')
        self.service.ble_client.stop_client()

    def ble_client_notify_start(self) -> None:
        self.logger.debug('BLE notify service > start')
        if self.service.ble_client.is_active() and self.data.ble_device_meta:
            uuid = self.data.ble_device_meta.find_char_uuid_by_descriptor_data(self.data.powerdog_notify_desc_value)
            char = self.service.ble_client.get_char_by_uuid(uuid)
            self.create_task(self.service.ble_client.start_notify(char))

    def ble_client_notify_stop(self) -> None:
        self.logger.debug('BLE notify service > stop')
        if self.service.ble_client.is_active() and self.data.ble_device_meta:
            uuid = self.data.ble_device_meta.find_char_uuid_by_descriptor_data(self.data.powerdog_notify_desc_value)
            char = self.service.ble_client.get_char_by_uuid(uuid)
            self.create_task(self.service.ble_client.stop_notify(char))

    def broker_start(self) -> None:
        if self.data.br_config.broker_host:
            self.logger.debug(f'Broker > configuring {self.data.br_config.broker_host}:{self.data.br_config.broker_port}')
            self.task_group.create_task(self.service.mq_client.start_client())
        else:
            self.logger.info('Broker > skipped')

    def broker_stop(self) -> None:
        self.logger.info('Broker > stop')
        self.service.mq_client.stop_client()

    def subscribe_config_topics(self) -> None:
        self.task_group.create_task(self.service.mq_client.subscribe(topic=self.data.powerdog_discovery_topic))
        self.task_group.create_task(self.service.mq_client.subscribe(topic=self.data.powerdog_status_topic))
        self.task_group.create_task(self.service.mq_client.subscribe(topic=self.data.powerdog_command_topic))
        self.task_group.create_task(self.service.mq_client.subscribe(topic=self.data.homeassistant_status_topic))

        if self.data.br_config.subscribe_topics and len(self.data.br_config.subscribe_topics) > 0:
            for topic in self.data.br_config.subscribe_topics:
                self.logger.info(f'Broker > subscribe {topic}')
                self.task_group.create_task(self.service.mq_client.subscribe(topic=topic))

    def decode_service_data(self, notification: BLENotification) -> None:
        self.service.message_monitor.on_message('powerdog_raw')

        pd_data: PowerdogData = PowerdogDecoder.decode(raw_data=notification.data)

        self.write_data_to_file(self.data.pd_config.device_data_path, notification.data)
        self.write_data_to_file(self.data.pd_config.decode_data_path, pd_data.__dict__, to_json=True)

        if pd_data.data_type == PowerdogDataType.DATA.value:
            self.data.prev_data = pd_data # save data until next LINE1 or LINE2 notification
        elif self.data.prev_data and (pd_data.data_type == PowerdogDataType.LINE1.value or pd_data.data_type == PowerdogDataType.LINE2.value):
            result = self.data.prev_data
            result.data_type = pd_data.data_type # update LINE1 or LINE2 type on previous DATA line
            if self.service.data_limiter.check(result):
                self.on_event_data(EventData(BrokerEvent.BROKER_CLIENT_DECODED_DATA, result))
                self.service.message_monitor.on_message('powerdog_decoded')
        elif pd_data.data_type == PowerdogDataType.RESET.value:
            self.logger.info(f'Powerdog command > reset')
            self.on_event_data(EventData(BrokerEvent.BROKER_CLIENT_DECODED_DATA, pd_data))
        elif pd_data.data_type == PowerdogDataType.RELAY.value:
            self.logger.info(f'Powerdog command > relay')
            self.on_event_data(EventData(BrokerEvent.BROKER_CLIENT_DECODED_DATA, pd_data))
        else:
            self.logger.info(f'Unknown data {notification} {pd_data}')

    def write_data_to_file(self, file_path: str, data: str, to_json: bool = False) -> None:
        if file_path:
            try:
                value = f'{json.dumps(data)}' if to_json else f'{data}'
                with open(file_path, mode='at') as file:
                    file.write(f'{value}\n')
                self.logger.debug(f'Wrote to {file_path} with {value}')
                self.service.message_monitor.on_message(file_path)
            except Exception as e:
                self.logger.error(f'Failed to write {file_path} due to: {e}')

    def handle_command(self, command: str) -> None:
        async def send_command(char_specifier, command: str) -> None:
            try:
                await self.service.ble_client.write_gatt_char(char_specifier, command.encode(encoding='ascii'))
                self.logger.info(f'BLE Client > command {char_specifier} command={command}')
            except Exception as e:
                self.logger.error(f'BLE Client > write {char_specifier} {command} failed {e}')
        if self.service.ble_client.is_active():
            char_uuid = self.data.ble_device_meta.find_char_uuid_by_descriptor_data(self.data.powerdog_command_desc_value)
            char_specifier = self.service.ble_client.get_char_by_uuid(char_uuid=char_uuid)
            if char_specifier and command in [self.data.powerdog_command_reset, self.data.powerdog_command_relay]:
                self.create_task(send_command(char_specifier=char_specifier, command=command))

    def publish_broker_data(self, data: PowerdogData) -> None:
        if self.service.mq_client.is_active():
            broker_messages = PowerdogUtil.get_broker_messages(data)
            self.task_group.create_task(self.service.mq_client.publish(broker_messages))

    def publish_discovery_payload(self) -> None:
        if self.service.mq_client.is_active():
            self.data.discovery_payload: DiscoveryPayload = MqttDiscovery.get_discovery_payload(self.data.ble_device_meta)
            self.logger.info(f'Broker discovery > publish {self.data.powerdog_discovery_topic}')
            self.create_task(self.service.mq_client.publish([BrokerMessage(self.data.powerdog_discovery_topic, json.dumps(self.data.discovery_payload.to_dict()))]))

    def on_subscribed_message(self, message) -> None:
        self.service.message_monitor.on_message('broker_subscribed')
        payload = str(message.payload, encoding='utf-8')
        if message.topic == self.data.powerdog_discovery_topic:
            self.on_event_data(EventData(BrokerEvent.BROKER_CLIENT_DISCOVERY_SENT, message))
        elif message.topic == self.data.powerdog_status_topic and payload == self.data.powerdog_status_online:
            self.logger.info(f'Received {message.topic}={payload}')
            self.ble_client_notify_start()
        elif message.topic == self.data.homeassistant_status_topic and payload == self.data.homeassistant_status_online:
            # HomeAssistant online
            self.logger.info(f'Received {message.topic}={payload}')
            self.on_homeassistant_online()
        elif message.topic == self.data.homeassistant_status_topic and payload == self.data.homeassistant_status_offline:
            # HomeAssistant offline
            self.logger.info(f'Received {message.topic}={payload}')
            self.ble_client_notify_stop()
        elif message.topic == self.data.powerdog_command_topic:
            self.handle_command(payload)
        else:
            self.logger.info(f'Received {message.topic}={message.payload}')

    async def publish_powerdog_online(self) -> None:
        """ publish powerdog/status, removes "Unavailable" status from sensors in Home Assistant """
        await self.service.mq_client.publish([BrokerMessage(self.data.powerdog_status_topic, 'online')])

    def on_homeassistant_online(self) -> None:
        # wait 2 seconds then publish discovery, gives HomeAssistant time to do some processing
        async def custom_task() -> None:
            await asyncio.sleep(2.0)
            self.publish_discovery_payload()
        self.create_task(custom_task())

    def on_discovery_published(self) -> None:
        # wait 2 seconds then publish online status, gives HomeAssistant time to process discovery
        async def custom_task() -> None:
            await asyncio.sleep(2.0)
            await self.publish_powerdog_online()
        self.create_task(custom_task())

    async def main(self) -> None:
        self.on_event_data(EventData(AppEvent.APP_START_SERVICES))

        while not self.event_to_action_loop.is_set():
            event: EventData = await self.event_queue.get()

            if event.name == AppEvent.APP_START_SERVICES:
                self.app_start()
            # BLE scanner events
            # elif event.name == BluetoothEvent.BLE_SCANNER_STARTED:
            #     self.logger.info('BLE scanner > started')
            elif event.name == BluetoothEvent.BLE_SCANNER_FAILED:
                self.logger.warning(f'BLE scanner > {event.name}')
            elif event.name == BluetoothEvent.BLE_SCANNER_DEVICE:
                self.on_scanner_device(event.data['device'])
            elif event.name == BluetoothEvent.BLE_SCANNER_STOPPED:
                self.logger.info('BLE scanner > stopped')
                if self.data.ble_device:
                    self.ble_client_start()
            # BLE client events
            elif event.name == BluetoothEvent.BLE_CLIENT_STARTED:
                self.logger.info(f'BLE client > started {event.data}')
                self.on_ble_client_started()
            elif event.name == BluetoothEvent.BLE_CLIENT_FAILURE:
                self.logger.warning(f'BLE client > {event.name}')
            # elif event.name == BluetoothEvent.BLE_CLIENT_STOPPED:
            #     self.logger.info('BLE client > stopped')
            elif event.name == BluetoothEvent.BLE_NOTIFY_STARTED:
                self.logger.info(f'BLE notify service > started {event.data}')
            elif event.name == BluetoothEvent.BLE_NOTIFY_DATA:
                self.logger.debug(f'Broker > notification {event.data}')
                self.decode_service_data(event.data)
            elif event.name == BluetoothEvent.BLE_NOTIFY_FAIL_START:
                self.logger.warning(f'BLE client > {event.name}')
            elif event.name == BluetoothEvent.BLE_NOTIFY_FAIL_STOP:
                self.logger.warning(f'BLE client > {event.name} {event.data}')
            elif event.name == BluetoothEvent.BLE_NOTIFY_STOPPED:
                self.logger.info('fBLE notify service > stopped {event.data}')
            elif event.name == BluetoothEvent.BLE_CLIENT_META_DATA:
                self.on_ble_client_metadata(event.data)
                self.publish_discovery_payload()
                self.ble_client_notify_start()
            elif event.name == BluetoothEvent.BLE_CLIENT_META_FAILURE:
                self.logger.warning(f'BLE client > {event.name}')
            elif event.name == BluetoothEvent.BLE_CLIENT_DISCONNECTED:
                self.logger.info('BLE client > disconnected')
            # Broker events
            elif event.name == BrokerEvent.BROKER_CLIENT_CONNECTED:
                self.logger.info('Broker > connected')
                self.subscribe_config_topics()
            # elif event.name == BrokerEvent.BROKER_CLIENT_STARTING:
            #     self.logger.debug('Broker > starting')
            # elif event.name == BrokerEvent.BROKER_CLIENT_CONFIGURED:
            #     self.logger.info('Broker > configured')
            elif event.name == BrokerEvent.BROKER_CLIENT_SUBSCRIBED:
                self.logger.info(f'Broker > subscribed {event.data}')
            elif event.name == BrokerEvent.BROKER_CLIENT_FAILURE:
                self.logger.warning(f'Broker > {event.name}')
            elif event.name == BrokerEvent.BROKER_CLIENT_CONNECT_FAIL:
                self.logger.warning(f'Broker > {event.name}')
            elif event.name == BrokerEvent.BROKER_CLIENT_SUBSCRIBE_FAIL:
                self.logger.warning(f'Broker > {event.name}')
            elif event.name == BrokerEvent.BROKER_CLIENT_PUBLISH_FAIL:
                self.logger.warning(f'Broker > {event.name}')
            elif event.name == BrokerEvent.BROKER_CLIENT_DECODED_DATA:
                self.logger.debug(f'Broker > decoded {event.data}')
                self.publish_broker_data(event.data)
            elif event.name == BrokerEvent.BROKER_CLIENT_MESSAGE_DATA:
                self.logger.debug(f'Broker > topic {event.data.topic} payload {event.data.payload}')
                self.on_subscribed_message(event.data)
            elif event.name == BrokerEvent.BROKER_CLIENT_DISCOVERY_SENT:
                self.logger.info('Broker discovery > published')
                self.on_discovery_published()
            # elif event.name == BrokerEvent.BROKER_CLIENT_STOPPED:
            #     self.logger.info('Broker > stopped')
            else:
                self.logger.debug(f'{event}')
            
            self.event_queue.task_done()

    async def execute(self) -> None:
        try:
            async with TaskGroup() as task_group:
                self.task_group = task_group
                self.task_group.create_task(coro=self.main())
        except asyncio.CancelledError:
            await self.app_stop()

        if self.data.br_config.broker_host:
            broker_otp = BrokerOneTimePublish(config=self.data.br_config)
            await broker_otp.publish(BrokerMessage(self.data.powerdog_status_topic, self.data.powerdog_status_offline))

        self.logger.info('App > stopped')

def main():
    arg_parser = argparse.ArgumentParser(description='Powerdog Client')
    arg_parser.add_argument('--config-file', help='INI style configuration file', default='config.ini')
    args = arg_parser.parse_args()

    config = Configuration(config_file=args.config_file)
    pd_config = config.powerdog()
    br_config = config.broker()
    cl_config = config.client()

    logging_format = '%(asctime)s %(levelname)s:%(name)s %(message)s'
    logging_datefmt = '%Y-%m-%d %H:%M:%S'

    if cl_config.log_level in logging.getLevelNamesMapping():
        logging.basicConfig(format=logging_format, level=logging.getLevelNamesMapping()[cl_config.log_level], datefmt=logging_datefmt)
    else:
        logging.basicConfig(format=logging_format, level=logging.INFO, datefmt=logging_datefmt)

    # logging.getLogger('bleak.backends.bluezdbus.client').setLevel(logging.DEBUG)

    app = App(pd_config=pd_config, br_config=br_config, cl_config=cl_config)
    asyncio.run(app.execute(), debug=False)

if __name__ == '__main__':
    main()
