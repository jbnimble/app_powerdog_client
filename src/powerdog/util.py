from powerdog.data import PowerdogModelType, GattData, PowerdogData, PowerdogDataError, PowerdogDataType, BrokerMessage

class PowerdogUtil:
    def bytearray_to_ascii(data: bytearray) -> str:
        result = data
        try:
            result = bytearray.fromhex(data.hex()).decode(encoding='ascii').replace('\u0000', '')
        except:
            pass
        return result

    def get_model_type(name: str) -> PowerdogModelType | None:
        """ The BLE device name starts with `PMS` for single line and `PMD` for double line data """
        result = None
        if name and name.startswith('PMS'):
            result = PowerdogModelType.SINGLE
        if name and name.startswith('PMD'):
            result = PowerdogModelType.DOUBLE
        return result

    def get_gatt_data_value(desc: str, gatt_data: [GattData]) -> str:
        result = ''
        for data in gatt_data:
            if data and data.description == desc:
                result = data.data_ascii
                break
        return result

    def get_broker_messages(data: PowerdogData) -> [BrokerMessage]:
        """
        Map the WatchdogDataType and WatchdogDataValue to MQTT topics and payloads:

        - topic = powerdog/L1/voltage       payload = float
        - topic = powerdog/L1/amperage      payload = float
        - topic = powerdog/L1/wattage       payload = float
        - topic = powerdog/L1/power_usage   payload = float
        - topic = powerdog/L1/error_code    payload = int
        - topic = powerdog/L1/error_status  payload = str
        - topic = powerdog/L2/voltage       payload = float
        - topic = powerdog/L2/amperage      payload = float
        - topic = powerdog/L2/wattage       payload = float
        - topic = powerdog/L2/power_usage   payload = float
        - topic = powerdog/L2/error_code    payload = int
        - topic = powerdog/L2/error_status  payload = str
        """
        result = []

        line_code = 'unk'
        if data.data_type == PowerdogDataType.LINE1.value or data.data_type == PowerdogDataType.LINE2.value:
            line_code = f'L{data.data_type}'

        result.append(BrokerMessage(topic=f'powerdog/{line_code}/voltage', payload=data.voltage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/amperage', payload=data.amperage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/wattage', payload=data.wattage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/power_usage', payload=data.power_usage))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/error_code', payload=data.error))
        result.append(BrokerMessage(topic=f'powerdog/{line_code}/error_status', payload=PowerdogUtil.get_error_status(data=data)))

        return result


    def get_error_status(data: PowerdogData) -> str:
        """
        Map the error code and data to textual error descriptions
        Add unsafe/high/low context for voltage errors
        """
        result = 'OK'
        if PowerdogDataError.VOLTAGE_1.value == data.error:
            desc = 'low' if data.voltage < 104.0 else 'unsafe'
            desc = 'high' if data.voltage > 132.0 else desc
            result = f'E{data.error}: Line1 {desc} voltage'
        elif PowerdogDataError.VOLTAGE_2.value == data.error:
            desc = 'low' if data.voltage < 104.0 else 'unsafe'
            desc = 'high' if data.voltage > 132.0 else desc
            result = f'E{data.error}: Line2 {desc} voltage'
        elif PowerdogDataError.CURRENT_OVER_1.value == data.error:
            result = f'E{data.error}: Line1 over current'
        elif PowerdogDataError.CURRENT_OVER_2.value == data.error:
            result = f'E{data.error}: Line2 over current'
        elif PowerdogDataError.NEUTRAL_REVERSED_1.value == data.error:
            result = f'E{data.error}: Line1 neutral/hot reversed'
        elif PowerdogDataError.NEUTRAL_REVERSED_2.value == data.error:
            result = f'E{data.error}: Line1 neutral/hot reversed'
        elif PowerdogDataError.GROUND_MISSING.value == data.error:
            result = f'E{data.error}: missing ground'
        elif PowerdogDataError.NEUTRAL_MISSING.value == data.error:
            result = f'E{data.error}: missing neutral'
        elif PowerdogDataError.SURGE_REPLACE.value == data.error:
            result = 'E9: replace surge protection board'
        return result
