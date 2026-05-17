import asyncio
from enum import StrEnum
import logging
from typing import Callable

from asyncio_paho import AsyncioPahoClient

from powerdog.data import PowerdogData, BrokerMessage, PowerdogDataType, BrokerConfig
from powerdog.event import EventData

class AsyncBrokerClient:
    """
    - Connect to MQTT broker using BrokerConfig
    - Send BrokerMessage's via publish_messages()
    - Subscribe to BrokerConfig topics

    AsyncioPahoClient auto-retries to connect on connection failures
    https://pypi.org/project/asyncio-paho/
    https://github.com/toreamun/asyncio-paho/tree/main
    """
    def __init__(self, config: BrokerConfig, async_publish_discovery_callback):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        self.connected_flag = asyncio.Event()
        self.mqtt_client = None
        self.async_publish_discovery_callback = async_publish_discovery_callback

    def update_disconnected(self, message: str = ''):
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
        self.update_disconnected(message='connection fail')

    async def on_subscribed(self, client, userdata, message):
        self.logger.info(f'topic={message.topic} id={message.mid} qos={message.qos} retain={message.retain} state={message.state} timestamp={message.timestamp} payload={message.payload}')
        # detect if homeassistant has changed status
        if message.topic == 'homeassistant/status' and message.payload.decode('utf-8') == 'online':
            if self.async_publish_discovery_callback:
                await asyncio.sleep(2) # recommended to not immediately publish discovery after 'online' status
                await self.async_publish_discovery_callback()
            else:
                self.logger.warning('Callback not available for discovery publish')
        if message.topic == 'homeassistant/status' and message.payload.decode('utf-8') == 'offline':
            # TODO trigger stop sending data
            pass

    async def publish_messages(self, messages: [BrokerMessage]) -> None:
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.logger.debug(f'Publish messages = {messages}')
            for message in messages:
                await self.mqtt_client.asyncio_publish(topic=message.topic, payload=message.payload)
        else:
            self.update_disconnected(message='failed to publish messages')

    async def subscribe_config_topics(self) -> None:
        for topic in self.config.subscribe_topics:
            self.logger.info(f'Subscribing topic = {topic}')
            await self.mqtt_client.asyncio_subscribe(topic=topic)

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
            await self.subscribe_config_topics()
            await asyncio.Future() # wait forever

class BrokerEvent(StrEnum):
    BROKER_CLIENT_STARTING =       'broker_client_starting'
    BROKER_CLIENT_CONFIGURED =     'broker_client_configured'
    BROKER_CLIENT_CONNECTED =      'broker_client_connected'
    BROKER_CLIENT_FAILURE =        'broker_client_failure'
    BROKER_CLIENT_CONNECT_FAIL =   'broker_client_connect_fail'
    BROKER_CLIENT_MESSAGE_DATA =   'broker_client_message_data'
    BROKER_CLIENT_STOPPED =        'broker_client_stopped'
    BROKER_CLIENT_SUBSCRIBED =     'broker_client_subscribed'
    BROKER_CLIENT_SUBSCRIBE_FAIL = 'broker_client_subscribe_fail'
    BROKER_CLIENT_DECODED_DATA =   'broker_client_decoded_data'
    BROKER_CLIENT_DISCOVERY_SENT = 'broker_client_discovery_sent'
    BROKER_CLIENT_PUBLISH_FAIL =   'broker_client_publish_fail'

class BrokerEventClient:
    def __init__(self, config: BrokerConfig, on_event_cb: Callable[[EventData], None] = None):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self.on_event_cb = on_event_cb
        self._context_keep_alive = asyncio.Event()
        self._context_keep_alive.set()
        self._context: AsyncioPahoClient = None
        self.subscribed_topics = set()

    def _on_event(self, event_data: EventData) -> None:
        if self.on_event_cb:
            self.on_event_cb(event_data)
        else:
            self.logger.info(f'Event noop {event_data}')

    async def _on_connect_pass(self, client, userdata, flags_dict, result):
        self._on_event(EventData(BrokerEvent.BROKER_CLIENT_CONNECTED, client))

    async def _on_connect_fail(self, client, userdata, flags_dict, result):
        self._on_event(EventData(BrokerEvent.BROKER_CLIENT_CONNECT_FAIL, client))

    async def _on_subscribed(self, client, userdata, message):
        self._on_event(EventData(BrokerEvent.BROKER_CLIENT_MESSAGE_DATA, message))

    async def start_client(self):
        self._context_keep_alive.clear()
        self.subscribed_topics.clear()
        try:
            async with AsyncioPahoClient() as context:
                self._context = context
                self._on_event(EventData(BrokerEvent.BROKER_CLIENT_STARTING, self._context))
                # configure
                auth_message = 'no auth'
                if self._config.broker_user and self._config.broker_pass:
                    self._context.username_pw_set(username=self._config.broker_user, password=self._config.broker_pass)
                    auth_message = 'auth configured'
                self._context.asyncio_listeners.add_on_connect(callback=self._on_connect_pass)
                self._context.asyncio_listeners.add_on_connect_fail(callback=self._on_connect_fail)
                self._context.asyncio_listeners.add_on_message(callback=self._on_subscribed)
                # connect
                self._context.connect(self._config.broker_host, port=self._config.broker_port)
                self._on_event(EventData(BrokerEvent.BROKER_CLIENT_CONFIGURED, {'host': self._config.broker_host, 'port': self._config.broker_port, 'auth': auth_message}))
                await self._context_keep_alive.wait()
            self._on_event(EventData(BrokerEvent.BROKER_CLIENT_STOPPED))
        except Exception as e:
            self.logger.error(f'Client failure {e}')
            self._on_event(EventData(BrokerEvent.BROKER_CLIENT_FAILURE))
        self._context = None
        self.logger.info('Stopped')

    def stop_client(self) -> None:
        self._context_keep_alive.set()

    def is_active(self) -> bool:
        """ Status if client is active and connected to MQ broker """
        return self._context and not self._context_keep_alive.is_set() and self._context.is_connected()

    async def subscribe(self, topic: str) -> None:
        """ Subscribe to topic """
        try:
            if not self.is_active():
                raise Exception('Client not active')
            await self._context.asyncio_subscribe(topic=topic)
            self.subscribed_topics.add(topic)
            self._on_event(EventData(BrokerEvent.BROKER_CLIENT_SUBSCRIBED, topic))
        except Exception as e:
            self.logger.error(f'Subscribe failure {topic} caused {e}')
            self._on_event(EventData(BrokerEvent.BROKER_CLIENT_PUBLISH_FAIL))

    async def publish(self, messages: [BrokerMessage]) -> None:
        """ Publish BrokerMessage's """
        for message in messages:
            try:
                if not self.is_active():
                    raise Exception('Client not active')
                await self._context.asyncio_publish(topic=message.topic, payload=message.payload)
            except Exception as e:
                self.logger.error(f'Publish failure {message} caused {e}')
                self._on_event(EventData(BrokerEvent.BROKER_CLIENT_PUBLISH_FAIL))

class BrokerOneTimePublish:
    def __init__(self, config: BrokerConfig):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self._config = config

    async def publish(self, message: BrokerMessage) -> None:
        try:
            async with AsyncioPahoClient() as context:
                if self._config.broker_user and self._config.broker_pass:
                    context.username_pw_set(username=self._config.broker_user, password=self._config.broker_pass)
                context.connect(self._config.broker_host, port=self._config.broker_port)
                result = context.publish(message.topic, message.payload)
                self.logger.info(f'Published {message} with {result}')
        except Exception as e:
            self.logger.error(f'Client failure {e}')
