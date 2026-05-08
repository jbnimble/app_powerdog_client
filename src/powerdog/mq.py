import asyncio
import logging

from asyncio_paho import AsyncioPahoClient

from powerdog.data import PowerdogData, BrokerMessage, PowerdogDataType, BrokerConfig

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
