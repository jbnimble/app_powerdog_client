from asyncio import Queue
import logging
from typing import Any

class EventData:
    def __init__(self, name: str, data: Any = None):
        self._name = name
        self._data = data

    @property
    def name(self) -> str:
        return self._name

    @property
    def data(self) -> Any:
        return self._data

    def __str__(self) -> str:
        if self._data:
            return f'{{"type": "EventData", "name": "{self._name}", "data": "{self._data}"}}'
        else:
            return f'{{"type": "EventData", "name": "{self._name}"}}'

class EventQueue:
    def __init__(self):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self._queue = Queue()

    async def put(self, event_data: EventData) -> None:
        await self._queue.put(event_data)

    async def get(self) -> EventData:
        return await self._queue.get()
