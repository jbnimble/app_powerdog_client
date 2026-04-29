#!/usr/bin/env python

import argparse
import asyncio
from asyncio import TaskGroup
import logging

from powerdog.pd import AsyncServiceNotifier
from powerdog.mq import AsyncMessagerClient

from powerdog.config import Configuration
from powerdog.data import PowerdogData, PowerdogConfig, BrokerConfig, ClientConfig
from powerdog.mq import MessageMapper

class PowerdogMqttBridge:
    def __init__(self, pd_config: PowerdogConfig, br_config: BrokerConfig, cl_config: ClientConfig):
        self.pd_config = pd_config
        self.br_config = br_config
        self.cl_config = cl_config
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.sender = None

    async def on_data_ready(self, data: PowerdogData):
        if self.sender:
            await self.sender.publish_messages(MessageMapper.map(data))
        else:
            self.logger.debug(f'MQTT not connected line={line} value={value}')

    async def execute(self):
        async with TaskGroup() as group:
            notifier = AsyncServiceNotifier(config=self.pd_config, on_data_callback=self.on_data_ready)
            group.create_task(notifier.execute())
            self.sender = AsyncMessagerClient(config=self.br_config)
            group.create_task(self.sender.execute())

def main():
    arg_parser = argparse.ArgumentParser(description='Powerdog Client')
    arg_parser.add_argument('--config-file', help='INI style configuration file', default='config.ini')
    args = arg_parser.parse_args()

    config = Configuration(config_file=args.config_file)
    pd_config = config.powerdog()
    br_config = config.broker()
    cl_config = config.client()

    if cl_config.log_level in logging.getLevelNamesMapping():
        # this changes the global log level
        logging.basicConfig(level=logging.getLevelNamesMapping()[cl_config.log_level])
    else:
        logging.basicConfig(level=logging.INFO) # default to INFO

    try:
        asyncio.run(PowerdogMqttBridge(pd_config=pd_config, br_config=br_config, cl_config=cl_config).execute())
    except KeyboardInterrupt:
        print('Program interrupted by user (Ctrl+C). Shutting down')

if __name__ == '__main__':
    main()
