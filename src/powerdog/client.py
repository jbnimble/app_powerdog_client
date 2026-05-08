#!/usr/bin/env python

import argparse
import asyncio
from asyncio import TaskGroup
import logging

from powerdog.pd import AsyncServiceNotifier, AsyncDeviceInterrogator
from powerdog.mq import AsyncBrokerClient
from powerdog.config import Configuration
from powerdog.data import PowerdogData, PowerdogConfig, BrokerConfig, ClientConfig, BrokerMessage
from powerdog.util import PowerdogUtil

class PowerdogMqttBridge:
    def __init__(self, pd_config: PowerdogConfig, br_config: BrokerConfig, cl_config: ClientConfig):
        self.pd_config = pd_config
        self.br_config = br_config
        self.cl_config = cl_config
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.sender = None
        self.notifier = None

    async def on_data_ready(self, data: PowerdogData):
        if self.sender:
            await self.sender.publish_messages(PowerdogUtil.get_broker_messages(data))
            self.logger.info('published data messages')
        else:
            self.logger.debug(f'MQTT not connected failed to send {data}')

    async def on_publish(self, messages: [BrokerMessage]) -> None:
        if self.sender:
            await self.sender.publish_messages(messages)
        else:
            self.logger.debug(f'MQTT not connected failed to send {message}')

    async def on_publish_discovery(self) -> None:
        if self.notifier:
            await self.notifier.publish_discovery()
        else:
            self.logger.warning('Notifer not available for discovery publish')

    async def execute(self):
        async with TaskGroup() as group:
            self.notifier = AsyncServiceNotifier(config=self.pd_config, on_data_callback=self.on_data_ready, on_publish_callback=self.on_publish)
            group.create_task(self.notifier.execute())
            self.sender = AsyncBrokerClient(config=self.br_config, async_publish_discovery_callback=self.on_publish_discovery)
            group.create_task(self.sender.execute())

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
        # this changes the global log level
        logging.basicConfig(format=logging_format, level=logging.getLevelNamesMapping()[cl_config.log_level], datefmt=logging_datefmt)
        logging.getLogger('bleak').setLevel(logging.INFO) # bleak is very verbose
    else:
        logging.basicConfig(format=logging_format, level=logging.INFO, datefmt=logging_datefmt) # default to INFO

    try:
        asyncio.run(PowerdogMqttBridge(pd_config=pd_config, br_config=br_config, cl_config=cl_config).execute())
    except KeyboardInterrupt:
        print('Program interrupted by user (Ctrl+C). Shutting down')

if __name__ == '__main__':
    main()
