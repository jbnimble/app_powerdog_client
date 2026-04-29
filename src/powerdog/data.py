from dataclasses import dataclass
from enum import Enum

@dataclass
class PowerdogConfig:
    address: str = None
    service: str = None

@dataclass
class BrokerConfig:
    broker_host: str = None
    broker_port: int = -1
    broker_user: str = None
    broker_pass: str = None
    subscribe_topics = None

@dataclass
class ClientConfig:
    log_level: str = None

@dataclass
class PowerdogData:
    data_type: int = None
    voltage: float = None
    amperage: float = None
    wattage: float = None
    power_usage: float = None
    error: int = None

@dataclass
class BrokerMessage:
    topic: str
    payload: str

class PowerdogDataError(Enum):
    """
    Data error codes are the last two bytes of the 20 byte hex data line
    00 no error code
    01 line1 voltage error (104 > voltage > 132)
    02 line2 voltage error (104 > voltage > 132)
    03 line1 over current, exceeded amp rating
    04 line2 over current, exceeded amp rating
    05 line1 neutral reversed
    06 line2 neutral reversed
    07 missing ground
    08 neutral missing
    09 surge absorption capacity low, replace surge protector
    """
    NONE = 0
    VOLTAGE_1 = 1
    VOLTAGE_2 = 2
    CURRENT_OVER_1 = 3
    CURRENT_OVER_2 = 4
    NEUTRAL_REVERSED_1 = 5
    NEUTRAL_REVERSED_2 = 6
    GROUND_MISSING = 7
    NEUTRAL_MISSING = 8
    SURGE_REPLACE = 9

class PowerdogDataType(Enum):
    """
    Three types of data values:
    - DATA, has voltage/amperage/watts/power/error values
    - LINE1, indicates the previously received data value was for LINE1
    - LINE2, indicates the previously received data value was for LINE2
    - RELAY, relay ON
    - RESET, resetting
    30Amp devices only use LINE1
    50Amp devices use both LINE1 and LINE2
    """
    DATA = 0
    LINE1 = 1
    LINE2 = 2
    RELAY = 3
    RESET = 4
