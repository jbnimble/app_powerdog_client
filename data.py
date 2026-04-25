from enum import Enum
import json

class WatchdogDataError(Enum):
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

class WatchdogDataType(Enum):
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

class WatchdogDataValue:
    """
    The data is a 20 byte hex string, with the following patterns:
    5245534554.............................. resetting
    72656c6179206f6e........................ relay on
    ..................................000000 check point line 1, previous data was line 1
    ..................................010101 check point line 2, previous data was line 2
    010320vvvvvvvvaaaaaaaawwwwwwwwppppppppee > data line (v=volts, a=amps, w=watts, p=power, e=error)
    """
    def __init__(self, raw_data: str):
        self.raw_data = raw_data
        self.data_type = None
        self.voltage = None
        self.amperage = None
        self.wattage = None
        self.power_usage = None
        self.error = WatchdogDataError.NONE
        self.decode()

    def decode(self):
        index_06 = 6
        index_14 = 14
        index_22 = 22
        index_30 = 30
        index_34 = 34
        index_38 = 38
        index_40 = 40

        if self.raw_data.startswith('72656c6179206f6e'):
            self.data_type = WatchdogDataType.RELAY
        if self.raw_data.startswith('5245534554'):
            self.data_type = WatchdogDataType.RESET
        if len(self.raw_data) == index_40:
            if not self.raw_data.startswith('010320') and self.raw_data[index_34:index_40] == '000000':
                self.data_type = WatchdogDataType.LINE1
            if not self.raw_data.startswith('010320') and self.raw_data[index_34:index_40] == '010101':
                self.data_type = WatchdogDataType.LINE2
            if self.raw_data.startswith('010320'):
                self.data_type = WatchdogDataType.DATA
                index_ranges = [('voltage',index_06,index_14), ('amperage',index_14,index_22), ('wattage',index_22,index_30), ('power_usage',index_30,index_38)]
                for attr_name,index_start,index_end in index_ranges:
                    data = int(self.raw_data[index_start:index_end], 16) / 10000.0
                    setattr(self, attr_name, data)

    def json_str(self) -> {}:
        data_type_value = self.data_type.value if self.data_type else None
        data = {'data': self.raw_data, 'data_type': data_type_value}
        if self.data_type == WatchdogDataType.DATA:
            error_value = self.error.value if self.error else None
            data = {'data': self.raw_data, 'data_type': data_type_value, 'voltage': self.voltage, 'amperage': self.amperage, 'wattage': self.wattage, 'power_usage': self.power_usage, 'error': error_value}
        return json.dumps(data)

    def __str__(self):
        data_type_value = self.data_type.value if self.data_type else None
        result = f'{self.__class__.__name__}(raw_data={self.raw_data},data_type={data_type_value})'
        if self.data_type == WatchdogDataType.DATA:
            error_value = self.error.value if self.error else None
            result = f'{self.__class__.__name__}(raw_data={self.raw_data},data_type={data_type_value},voltage={self.voltage},amperage={self.amperage},wattage={self.wattage},power_usage={self.power_usage},error={error_value})'
        return result
