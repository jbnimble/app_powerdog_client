import asyncio
import logging

from asyncio_paho import AsyncioPahoClient

from data import PowerdogData, BrokerMessage, PowerdogDataType, BrokerConfig

class MessageMapper:
    def map(data: PowerdogData) -> [BrokerMessage]:
        """
        Map the WatchdogDataType and WatchdogDataValue to MQTT topics and payloads:

        - topic = powerdog/L1/voltage       payload = float
        - topic = powerdog/L1/amperage      payload = float
        - topic = powerdog/L1/wattage       payload = float
        - topic = powerdog/L1/power_usage   payload = float
        - topic = powerdog/L1/error         payload = int
        - topic = powerdog/L2/voltage       payload = float
        - topic = powerdog/L2/amperage      payload = float
        - topic = powerdog/L2/wattage       payload = float
        - topic = powerdog/L2/power_usage   payload = float
        - topic = powerdog/L2/error         payload = int
        """
        result = []

        line_code = 'unk'
        if data.data_type == PowerdogDataType.LINE1.value or data.data_type == PowerdogDataType.LINE2.value:
            line_code = f'L{data.data_type}'

        result.append(BrokerMessage(topic=f'powerdog/{line_code}/voltage', payload=data.voltage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/amperage', payload=data.amperage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/wattage', payload=data.wattage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/power_usage', payload=data.power_usage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/error', payload=data.error))

        return result

class MessageLimiter:
    def __init__(self):
        # TODO: limit messages sent based on rules
        pass

class AsyncMessagerClient:
    """
    - Connect to MQTT broker using BrokerConfig
    - Send BrokerMessage's via publish_messages()
    - Subscribe to BrokerConfig topics

    AsyncioPahoClient auto-retries to connect on connection failures
    https://pypi.org/project/asyncio-paho/
    https://github.com/toreamun/asyncio-paho/tree/main
    """
    def __init__(self, config: BrokerConfig):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        self.connected_flag = asyncio.Event()
        self.mqtt_client = None

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
        self.logger.info(f'Subscribed topic = {message.topic}: {message.payload}')

    async def publish_messages(self, messages: [BrokerMessage]) -> None:
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.logger.debug(f'Publish messages = {messages}')
            for message in messages:
                await self.mqtt_client.asyncio_publish(topic=message.topic, payload=message.payload)
        else:
            self.update_disconnected(message='failed to publish messages')

    async def subscribe_all_powerdog(self) -> None:
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
            await self.subscribe_all_powerdog()
            await asyncio.Future() # wait forever
