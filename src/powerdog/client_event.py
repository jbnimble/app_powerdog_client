#!/usr/bin/env python

import argparse
import asyncio
from asyncio import Task
from asyncio import TaskGroup, Queue, QueueEmpty
from enum import StrEnum
from functools import partial
import json
import logging
from logging import Logger

from bleak import BLEDevice

from powerdog.ble import BluetoothEvent, BluetoothEventClient, BluetoothEventScanner, BluetoothNative
from powerdog.config import PowerdogConfig, BrokerConfig, ClientConfig, Configuration
from powerdog.data import PowerdogData, GattData, PowerdogModelType, BluetoothDeviceMeta
from powerdog.ha import MqttDiscovery
from powerdog.mq import BrokerEventClient, BrokerMessage, BrokerEvent
from powerdog.event import EventData, EventQueue
from powerdog.pd import PowerdogDecoder, DataLimiter, PowerdogDataType
from powerdog.util import PowerdogUtil

class TerminateTaskGroup(Exception):
    """ Exception raised to terminate a task group """

class AppService:
    def __init__(self):
        self.ble_scanner: BluetoothEventScanner = None
        self.ble_client: BluetoothEventClient = None
        self.mq_client: BrokerEventClient = None
        self.data_limiter: DataLimiter = None

class AppData:
    def __init__(self, pd_config: PowerdogConfig, br_config: BrokerConfig, cl_config: ClientConfig):
        self.pd_config: PowerdogConfig = pd_config
        self.br_config: BrokerConfig = br_config
        self.cl_config: ClientConfig = cl_config
        self.mqtt_discovery: MqttDiscovery = None
        self.prev_data: PowerdogData = None
        self.discovery_topic: str = None
        self.gatt_data: [GattData] = None
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
        self.event_queue = EventQueue()
        self.service.ble_scanner = BluetoothEventScanner(on_event_cb=self.on_event_data, allow_duplicates=False)
        self.service.data_limiter = DataLimiter(config=self.data.pd_config)

    def app_start(self) -> None:
        self.ble_scanner_start()
        self.broker_start()
        self.create_task(self.do_native_disconnect())

    def app_stop(self) -> None:
        self.logger.info('App > stopping')
        self.service.ble_scanner.stop_scanner()
        if self.service.ble_client:
            self.service.ble_client.stop_client()
        if self.service.mq_client:
            self.service.mq_client.stop_client()

    def is_app_stopped(self) -> bool:
        if not self.service.ble_scanner.is_stopped():
            return False
        if self.service.ble_client and not self.service.ble_client.is_stopped():
            return False
        if self.service.mq_client and not self.service.mq_client.is_stopped():
            return False
        return True

    async def do_native_disconnect(self) -> None:
        """ Wait for a period, if no Powerdog BLE device found, then attempt native disconnect """
        await asyncio.sleep(10)
        if self.service.ble_scanner.is_scanner_activated() and not self.data.ble_device:
            self.logger.info('BLE native > disconnect')
            await BluetoothNative().disconnect(self.data.pd_config.address)

    def on_event_data(self, event_data: EventData) -> None:
        def on_event_queue_done(task: Task, event_data: EventData) -> None:
            """ callback for create_task """
            task_error = task.exception()
            if task_error:
                self.logger.error(f'Failed on_event_data {event_data} exception={task_error}')
        try:
            task = self.task_group.create_task(self.event_queue.put(event_data))
            task.add_done_callback(partial(on_event_queue_done, event_data=event_data))
        except Exception as e:
            self.logger.error(f'Failed on on_event_data {event_data} failed to queue')

    def create_task(self, coro):
        return self.task_group.create_task(coro)

    def ble_scanner_start(self) -> None:
        self.logger.info('BLE scanner > start')
        self.task_group.create_task(self.service.ble_scanner.start_scanner())
        # TODO disconnect timer

    def on_scanner_device(self, ble_device: BLEDevice) -> None:
        self.logger.info(f'BLE scanner > device {ble_device}')
        if ble_device.address == self.data.pd_config.address and ble_device.name:
            self.data.ble_device = ble_device
            self.ble_scanner_stop()
        else:
            self.detect_powerdog_device(ble_device)

    def ble_scanner_stop(self) -> None:
        self.logger.info('BLE scanner > stop')
        self.service.ble_scanner.stop_scanner()

    def detect_powerdog_device(self, ble_device: BLEDevice) -> None:
        """ config address not provided, then attempt to detect Powerdog device """
        if not self.data.ble_device and not self.data.pd_config.address and ble_device.address and ble_device.name and PowerdogUtil.get_model_type(ble_device.name) != PowerdogModelType.UNKNOWN:
            self.logger.info(f'BLE scanner > detected {ble_device}')
            self.data.ble_device = ble_device
            self.ble_scanner_stop()

    def ble_client_start(self) -> None:
        self.logger.info(f'BLE client > start {self.data.ble_device}')
        self.service.ble_client = BluetoothEventClient(device=self.data.ble_device, create_event_cb=self.create_task, on_event_cb=self.on_event_data)
        self.task_group.create_task(self.service.ble_client.start_client())

    def on_ble_client_started(self) -> None:
        self.task_group.create_task(self.service.ble_client.get_meta_data())

    def on_ble_client_metadata(self, meta_data: BluetoothDeviceMeta) -> None:
        self.logger.info('BLE client > metadata')
        if self.data.pd_config.device_meta_path:
            # self.logger.info(f'meta_data=\n{meta_data}')
            try:
                with open(self.data.pd_config.device_meta_path, mode='w') as file:
                    json.dump(meta_data, file, indent=4, default=PowerdogUtil.json_serializer)
            except Exception as e:
                self.logger.error(f'Failed to write file due to: {e}')
        # TODO is this where we want to trigger discovery?
        self.task_group.create_task(self.publish_discovery_payload())

    def ble_client_stop(self) -> None:
        self.logger.info('BLE client > stop')
        self.service.ble_client.stop_client()

    def find_ble_service(self, service_uuid: str) -> None:
        self.logger.info(f'BLE service > find {service_uuid}')
        self.service.ble_client.find_service(service_uuid)

    def ble_client_notify_start(self) -> None:
        self.logger.info('BLE notify service > start')
        self.service.ble_client.start_notify()

    def ble_client_notify_stop(self) -> None:
        self.logger.info('BLE notify service > stop')
        self.service.ble_client.stop_notify()

    def broker_start(self) -> None:
        if self.data.br_config.broker_host:
            self.logger.info(f'Broker > configuring {self.data.br_config.broker_host}:{self.data.br_config.broker_port}')
            self.service.mq_client = BrokerEventClient(config=self.data.br_config, on_event_cb=self.on_event_data)
            self.task_group.create_task(self.service.mq_client.start_client())
        else:
            self.logger.info('Broker > configuring (noop)')

    def broker_stop(self) -> None:
        self.logger.info('Broker > stop')
        self.service.mq_client.stop_client()

    def subscribe_config_topics(self) -> None:
        for topic in self.data.br_config.subscribe_topics:
            self.logger.info(f'Broker > subscribe {topic}')
            self.task_group.create_task(self.service.mq_client.subscribe(topic=topic))

    def decode_service_data(self, data: str) -> None:
        pd_data = PowerdogDecoder.decode(raw_data=data)

        if pd_data.data_type == PowerdogDataType.DATA.value:
            self.data.prev_data = pd_data # save data until next LINE1 or LINE2 notification
        elif self.data.prev_data and (pd_data.data_type == PowerdogDataType.LINE1.value or pd_data.data_type == PowerdogDataType.LINE2.value):
            result = self.data.prev_data
            result.data_type = pd_data.data_type # update LINE1 or LINE2 type on previous DATA line
            if self.service.data_limiter.check(result):
                self.on_event_data(EventData(BrokerEvent.BROKER_CLIENT_DECODED_DATA, result))

    def publish_broker_data(self, data: PowerdogData) -> None:
        broker_messages = PowerdogUtil.get_broker_messages(data)
        self.task_group.create_task(self.service.mq_client.publish(broker_messages))

    async def publish_discovery_payload(self) -> None:
        if self.service.mq_client:
            self.data.mqtt_discovery = MqttDiscovery(device_name=self.data.ble_device.name, device_address=self.data.ble_device.address, gatt_data=self.data.gatt_data)
            discovery_payload = self.data.mqtt_discovery.get_payload()
            payload = discovery_payload.to_dict()
            model = payload['device']['model'] if payload and payload['device'] and payload['device']['model'] else None
            if payload and model:
                self.data.discovery_topic = f'homeassistant/device/powerdog/{model}/config'
                # TODO would like to subscribe to this topic much earlier in the process
                await self.service.mq_client.subscribe(topic=self.data.discovery_topic)
                self.logger.info(f'Broker discovery > publish {self.data.discovery_topic}')
                await self.service.mq_client.publish([BrokerMessage(self.data.discovery_topic, json.dumps(payload))])
            else:
                self.logger.warning(f'Payload missing {payload}')
            # publish powerdog/status, removes "Unavailable" status from sensors in Home Assistant
            await self.service.mq_client.publish([BrokerMessage('powerdog/status', 'online')])
        else:
            self.logger.info('Broker discovery > publish (noop)')

    def on_subscribed_message(self, message) -> None:
        if message.topic == 'homeassistant/status' and message.payload.decode('utf-8') == 'online':
            self.logger.info(f'Topic {message.topic} {message.payload}')
            if not self.service.ble_client.is_notify_activated():
                self.ble_client_notify_start()
            else:
                self.logger.info('BLE notify service > started (noop)')
        elif message.topic == 'homeassistant/status' and message.payload.decode('utf-8') == 'offline':
            self.logger.info(f'Topic {message.topic} {message.payload}')
            self.ble_client_notify_stop()
        elif message.topic == self.data.discovery_topic:
            self.on_event_data(EventData(BrokerEvent.BROKER_CLIENT_DISCOVERY_SENT, message))
        elif message.topic.startswith('homeassistant/device/powerdog/'):
            self.logger.info(f'Topic {message.topic} > config message sent')
        elif message.topic == 'powerdog/status':
            self.logger.info(f'Topic {message.topic} {message.payload}')
        else:
            self.logger.info(f'Message from {message.topic}={message.payload}')

    # async def test_stuff(self) -> None:
    #     await asyncio.sleep(10)
    #     if self.service.ble_client.is_notify_activated():
    #         self.ble_client_notify_stop()
    #         await asyncio.sleep(5)
    #     if self.service.ble_client.is_client_activated():
    #         self.ble_client_stop()
    #     await asyncio.sleep(4)
    #     raise TerminateTaskGroup()

    # async def test_mq(self) -> None:
    #     await asyncio.sleep(7)
    #     self.broker_stop()
    #     await asyncio.sleep(3)
    #     raise TerminateTaskGroup()

    async def main(self) -> None:
        self.on_event_data(EventData(AppEvent.APP_START_SERVICES))

        # event-to-action loop using event_queue
        while not self.event_to_action_loop.is_set():
            event_data: EventData = await self.event_queue.get()

            if event_data.name == AppEvent.APP_START_SERVICES:
                self.app_start()
            # BLE scanner events
            elif event_data.name == BluetoothEvent.BLE_SCANNER_STARTED:
                self.logger.info('BLE scanner > started')
            elif event_data.name == BluetoothEvent.BLE_SCANNER_DEVICE:
                self.on_scanner_device(event_data.data['device'])
            elif event_data.name == BluetoothEvent.BLE_SCANNER_STOPPED:
                self.logger.info('BLE scanner > stopped')
                if self.data.ble_device:
                    self.ble_client_start()
            # BLE client events
            elif event_data.name == BluetoothEvent.BLE_CLIENT_STARTED:
                self.logger.info(f'BLE client > started {event_data.data}')
                self.on_ble_client_started()
            elif event_data.name == BluetoothEvent.BLE_CLIENT_STOPPED:
                self.logger.info('BLE client > stopped')
            elif event_data.name == BluetoothEvent.BLE_SERVICE_FOUND:
                self.logger.info(f'BLE notify service > found {event_data.data}')
                self.ble_client_notify_start()
            elif event_data.name == BluetoothEvent.BLE_NOTIFY_STARTED:
                self.logger.info('BLE notify service > started')
            elif event_data.name == BluetoothEvent.BLE_NOTIFY_DATA:
                self.logger.debug(f'Broker > notification {event_data.data}')
                self.decode_service_data(event_data.data)
            elif event_data.name == BluetoothEvent.BLE_NOTIFY_STOPPED:
                self.logger.info('BLE notify service > stopped')
            elif event_data.name == BluetoothEvent.BLE_CLIENT_META_DATA:
                self.on_ble_client_metadata(event_data.data)
            elif event_data.name == BluetoothEvent.BLE_CLIENT_DISCONNECTED:
                self.logger.info('BLE client > disconnected')
            # Broker events
            elif event_data.name == BrokerEvent.BROKER_CLIENT_CONNECTED:
                self.logger.info('Broker > connected')
                self.subscribe_config_topics()
            elif event_data.name == BrokerEvent.BROKER_CLIENT_STARTING:
                self.logger.info('Broker > starting')
            elif event_data.name == BrokerEvent.BROKER_CLIENT_CONFIGURED:
                self.logger.info('Broker > configured')
            elif event_data.name == BrokerEvent.BROKER_CLIENT_SUBSCRIBED:
                self.logger.info(f'Broker > subscribed {event_data.data}')
            elif event_data.name == BrokerEvent.BROKER_CLIENT_DECODED_DATA:
                self.logger.debug(f'Broker > decoded {event_data.data}')
                self.publish_broker_data(event_data.data)
            elif event_data.name == BrokerEvent.BROKER_CLIENT_MESSAGE_DATA:
                self.logger.debug(f'Broker > topic {event_data.data.topic} payload {event_data.data.payload}')
                self.on_subscribed_message(event_data.data)
            elif event_data.name == BrokerEvent.BROKER_CLIENT_DISCOVERY_SENT:
                self.logger.info('Broker discovery > published')
                self.find_ble_service(self.data.pd_config.service)
            elif event_data.name == BrokerEvent.BROKER_CLIENT_STOPPED:
                self.logger.info('Broker > stopped')
            else:
                self.logger.info(f'{event_data}')

    async def execute(self) -> None:
        try:
            async with TaskGroup() as task_group:
                self.task_group = task_group
                self.task_group.create_task(coro=self.main())
        except asyncio.CancelledError:
            # Attempt a clean shutdown, captures Ctrl-C KeyboardInterrupt
            self.app_stop()
            time_limit = 10.0
            while not self.is_app_stopped():
                time_wait = 0.1
                time_limit = time_limit - time_wait
                await asyncio.sleep(time_wait)
                if time_limit <= 0.0:
                    ble_scanner_state = self.service.ble_scanner.is_stopped()
                    ble_client_state = not self.service.ble_client or self.service.ble_client.is_stopped()
                    mq_client_state = not self.service.mq_client or self.service.mq_client.is_stopped()
                    self.logger.warning(f'App > stopping, time limit reached ble_scanner_stopped={ble_scanner_state} ble_client_stopped={ble_client_state} mq_client_stopped={mq_client_state}')
                    break
        except TerminateTaskGroup:
            # used during testing to forcefully quit the TaskGroup
            self.logger.info('App > stopping via terminate')
        self.logger.info('App > stopped')

def main():
    logging.basicConfig(format='%(asctime)s %(levelname)s:%(name)s %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')
    # logging.getLogger("asyncio").setLevel(logging.WARNING)

    arg_parser = argparse.ArgumentParser(description='Powerdog Client')
    arg_parser.add_argument('--config-file', help='INI style configuration file', default='config.ini')
    args = arg_parser.parse_args()

    config = Configuration(config_file=args.config_file)
    pd_config = config.powerdog()
    br_config = config.broker()
    cl_config = config.client()

    app = App(pd_config=pd_config, br_config=br_config, cl_config=cl_config)
    asyncio.run(app.execute(), debug=False)

if __name__ == '__main__':
    main()
