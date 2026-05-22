import logging
import time

from powerdog.data import PowerdogData, PowerdogDataType, PowerdogConfig

class PowerdogDecoder:
    """
    Decode the notify service data

    5245534554                               response for "RESEt" command
    72656c6179206f6e                         response for "RELAY ON" command
    ..................................000000 check point line 1, previous data was line 1
    ..................................010101 check point line 2, previous data was line 2
    010320vvvvvvvvaaaaaaaawwwwwwwwppppppppee > data line (v=volts, a=amps, w=watts, p=power, e=error)
    """

    def decode(raw_data: str) -> PowerdogData:
        """ Expects a hex string, decodes the values and outputs a PowerdogData """
        result = PowerdogData()
        result.raw_data = raw_data

        index_06 = 6
        index_14 = 14
        index_22 = 22
        index_30 = 30
        index_34 = 34
        index_38 = 38
        index_40 = 40

        if raw_data and raw_data.startswith('72656c6179206f6e'):
            result.data_type = PowerdogDataType.RELAY.value
        if raw_data and raw_data.startswith('5245534554'):
            result.data_type = PowerdogDataType.RESET.value
        if raw_data and len(raw_data) == index_40:
            if not raw_data.startswith('010320') and raw_data[index_34:index_40] == '000000':
                result.data_type = PowerdogDataType.LINE1.value
            if not raw_data.startswith('010320') and raw_data[index_34:index_40] == '010101':
                result.data_type = PowerdogDataType.LINE2.value
            if raw_data.startswith('010320'):
                result.data_type = PowerdogDataType.DATA.value
                index_ranges = [('voltage',index_06,index_14), ('amperage',index_14,index_22), ('wattage',index_22,index_30), ('power_usage',index_30,index_38)]
                for attr_name,index_start,index_end in index_ranges:
                    data = int(raw_data[index_start:index_end], 16) / 10000.0
                    setattr(result, attr_name, data)
                result.error = int(raw_data[index_38:index_40], 16)

        return result

class DataLimiter:
    """
    Send data when any of the following is true:

    - no last data sent
    - no last time
    - limit_quiet_sec <= 0.0
    - last line data was > limit_quiet_sec ago
    - limit_voltage_range > 0.0 and line voltage is limit_voltage_range greater or less than last voltage data
    - limit_amperage_range > 0.0 and line amperage is limit_amperage_range greater or less than last amperage data
    - limit_wattage_range > 0.0 and line wattage is limit_wattage_range greater or less than last wattage data
    - line data error changed from last error
    """
    def __init__(self, config: PowerdogConfig):
        self.config = config
        self.last_line1: PowerdogData | None = None
        self.time_line1: int | None = None
        self.last_line2: PowerdogData | None = None
        self.time_line2: int | None = None
        self.now: float | None = None

    def check(self, data: PowerdogData) -> bool:
        result = False
        self.now = time.time()

        if data.data_type == PowerdogDataType.LINE1.value:
            result = self.check_data(self.last_line1, self.time_line1, data)
        if data.data_type == PowerdogDataType.LINE2.value:
            result = self.check_data(self.last_line2, self.time_line2, data)

        if data.data_type == PowerdogDataType.LINE1.value and result:
            self.last_line1 = data
            self.time_line1 = time.time()
        if data.data_type == PowerdogDataType.LINE2.value and result:
            self.last_line2 = data
            self.time_line2 = time.time()

        return result

    def check_data(self, last_data: PowerdogData, last_time: float, data: PowerdogData) -> bool:
        result = False
        if not last_data or not last_time:
            result = True # no previous data
        elif self.config.limit_quiet_sec <= 0.0 or self.now - self.config.limit_quiet_sec > last_time:
            result = True # no quiet limit or quiet limit reached
        elif last_data.error != data.error:
            result = True # error state changed
        elif self.config.limit_voltage_range > 0.0 and self.check_bounds(last_data.voltage, data.voltage, self.config.limit_voltage_range):
            result = True # voltage range exceeded
        elif self.config.limit_amperage_range > 0.0 and self.check_bounds(last_data.amperage, data.amperage, self.config.limit_amperage_range):
            result = True # amperage range exceeded
        elif self.config.limit_wattage_range > 0.0 and self.check_bounds(last_data.wattage, data.wattage, self.config.limit_wattage_range):
            result = True # wattage range exceeded
        return result

    def check_bounds(self, prev_value: float, curr_value: float, range_value: float) -> bool:
        result = False
        if curr_value < prev_value - range_value or curr_value > prev_value + range_value:
            result = True
        return result

class PowerdogMessageMonitor:
    def __init__(self, wait_sec: int = 300):
        self.logger: Logger = logging.getLogger(self.__class__.__name__)
        self.wait_sec = wait_sec
        self.last_cleared = time.time()
        self.message_tracker = {}

    def on_message(self, message_type: str) -> None:
        if message_type not in self.message_tracker:
            self.logger.info(f'Tracking {message_type} messages')
            self.message_tracker[message_type] = 1
        else:
            self.message_tracker[message_type] = self.message_tracker[message_type] + 1
        if time.time() - self.wait_sec > self.last_cleared:
            for key,val in self.message_tracker.items():
                self.logger.info(f'{val} {key} messages sent in the last {self.wait_sec} seconds')
                self.message_tracker[key] = 0
            self.last_cleared = time.time()
