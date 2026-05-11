import importlib.metadata as meta

from powerdog.data import GattData, DiscoveryPayload, PowerdogModelType
from powerdog.util import PowerdogUtil

# MQTT Discovery with Home Assistant
# https://www.home-assistant.io/integrations/mqtt
# Example discovery payload https://github.com/home-assistant/core/blob/dev/homeassistant/components/mqtt/schemas.py#L197
# Platform > sensor https://www.home-assistant.io/integrations/sensor/
# {
#     'device': {
#         'identifiers': ['MY_UNIQUE_ID'], # unique id's that identify the device
#         'name': 'MY_UNIQUE_NAME',
#         'model': '', # device model
#         'model_id': '', # device model identifier
#         'manufacturer': '', # device manufacturer
#         'serial_number': '',
#         'sw_version': '', # device firmware version
#         'hw_version': '', # device hardware version
#         'connections': [], # list of tuple for device connections to outside world, ex: [['bluetooth','AA:BB:CC:DD:EE:FF']]
#     },
#     'origin': {
#         'name': 'origin application name',
#         'sw_version': 'origin application software version',
#         'support_url': 'origin application support URL',
#     },
#     'components': {
#         'my_component_1': {
#             'platform': 'sensor', # required, homeassistant/components/mqtt/const.py SUPPORTED_COMPONENTS
#             'unique_id': 'my_component_1',
#             'device_class': '', # SensorDeviceClass https://github.com/home-assistant/core/blob/dev/homeassistant/components/sensor/const.py#L90
#             'state_class': '', # SensorStateClass
#             'entity_category': '', # EntityCategory
#             'unit_of_measurement': '',
#             'state_topic': 'my/sensor/attribute',
#         },
#     },
#     'qos': 2,
#     'encoding': 'utf-8',
#     'enabled_by_default': True, # default=True
#     'command_topic': 'my/sensor/command/set',
#     'availability': [
#         {
#             'topic': 'my/sensor/status',
#         }
#     ],
# }

class MqttDiscovery:
    """ Generate the Home Assistant MQTT integration's discovery payload """
    def __init__(self, device_name: str = None, device_address: str = None, gatt_data: [GattData] = None):
        self.device_name = device_name
        self.device_address = device_address
        self.gatt_data = gatt_data

    def get_payload(self) -> DiscoveryPayload:
        result = DiscoveryPayload()

        origin_name = 'powerdog'
        device_name = self.device_name.strip()
        device_model = device_name.split(' ')[0].strip() + device_name.split(' ')[-1].strip()
        device_addr = self.device_address

        fw_version = PowerdogUtil.get_gatt_data_value('Firmware Revision String', self.gatt_data)
        sw_version = PowerdogUtil.get_gatt_data_value('Software Revision String', self.gatt_data)
        manufacturer = PowerdogUtil.get_gatt_data_value('Manufacturer Name String', self.gatt_data)

        result.command_topic = 'powerdog/set'
        # device, see frontend > ha-device-info-card.ts
        result.device = {
            'name': device_name,
            'identifiers': [device_name, device_addr],
            'model': device_model,
            'model_id': PowerdogUtil.get_gatt_data_value('Model Number String', self.gatt_data),
            'manufacturer': f'Powerdog and BLE@{manufacturer}',
            'serial_number': PowerdogUtil.get_gatt_data_value('Serial Number String', self.gatt_data),
            'sw_version': f'Powerdog version {meta.version(origin_name)}',
            'hw_version': f'BLE firmware {fw_version}, BLE software {sw_version}',
            'connections': [['bluetooth', device_addr]],
        }
        # origin
        result.origin = {
            'name': origin_name,
            'sw_version': meta.version(origin_name),
            'support_url': 'https://github.com/jbnimble/app_powerdog_client',
        }
        # availability
        result.availability = []
        result.availability.append({
            'topic': 'powerdog/status',
        })
        # components
        result.components = self.components()

        return result

    def components(self) -> {}:
        result = {
            'powerdog_line1_voltage': {
                'unique_id': 'powerdog_line1_voltage',
                'name': 'L1 Voltage',
                'platform': 'sensor',
                'device_class': 'voltage',
                'unit_of_measurement': 'V',
                'state_class': 'measurement',
                'suggested_display_precision': 2,
                'state_topic': 'powerdog/L1/voltage',
            },
            'powerdog_line1_amperage': {
                'unique_id': 'powerdog_line1_amperage',
                'name': 'L1 Amperage',
                'platform': 'sensor',
                'device_class': 'current',
                'unit_of_measurement': 'A',
                'state_class': 'measurement',
                'suggested_display_precision': 2,
                'state_topic': 'powerdog/L1/amperage',
            },
            'powerdog_line1_wattage': {
                'unique_id': 'powerdog_line1_wattage',
                'name': 'L1 Wattage',
                'platform': 'sensor',
                'device_class': 'power',
                'unit_of_measurement': 'W',
                'state_class': 'measurement',
                'suggested_display_precision': 2,
                'state_topic': 'powerdog/L1/wattage',
            },
            'powerdog_line1_power_usage': {
                'unique_id': 'powerdog_line1_power_usage',
                'name': 'L1 Usage',
                'platform': 'sensor',
                'device_class': 'energy',
                'unit_of_measurement': 'Wh',
                'state_class': 'total_increasing',
                'suggested_display_precision': 2,
                'state_topic': 'powerdog/L1/power_usage',
            },
            'powerdog_line1_error_code': {
                'unique_id': 'powerdog_line1_error_code',
                'name': 'L1 Code',
                'platform': 'sensor',
                'state_topic': 'powerdog/L1/error_code',
            },
            'powerdog_line1_error_status': {
                'unique_id': 'powerdog_line1_error_status',
                'name': 'L1 Error',
                'platform': 'sensor',
                'state_topic': 'powerdog/L1/error_status',
            },
        }

        if PowerdogUtil.get_model_type(name=self.device_name) == PowerdogModelType.DOUBLE:
            line2_result = {
                'powerdog_line2_voltage': {
                    'unique_id': 'powerdog_line2_voltage',
                    'name': 'L2 Voltage',
                    'platform': 'sensor',
                    'device_class': 'voltage',
                    'unit_of_measurement': 'V',
                    'state_class': 'measurement',
                    'suggested_display_precision': 2,
                    'state_topic': 'powerdog/L2/voltage',
                },
                'powerdog_line2_amperage': {
                    'unique_id': 'powerdog_line2_amperage',
                    'name': 'L2 Amperage',
                    'platform': 'sensor',
                    'device_class': 'current',
                    'unit_of_measurement': 'A',
                    'state_class': 'measurement',
                    'suggested_display_precision': 2,
                    'state_topic': 'powerdog/L2/amperage',
                },
                'powerdog_line2_wattage': {
                    'unique_id': 'powerdog_line2_wattage',
                    'name': 'L2 Wattage',
                    'platform': 'sensor',
                    'device_class': 'power',
                    'unit_of_measurement': 'W',
                    'state_class': 'measurement',
                    'suggested_display_precision': 2,
                    'state_topic': 'powerdog/L2/wattage',
                },
                'powerdog_line2_power_usage': {
                    'unique_id': 'powerdog_line2_power_usage',
                    'name': 'L2 Usage',
                    'platform': 'sensor',
                    'device_class': 'energy',
                    'unit_of_measurement': 'Wh',
                    'state_class': 'total_increasing',
                    'suggested_display_precision': 2,
                    'state_topic': 'powerdog/L2/power_usage',
                },
                'powerdog_line2_error_code': {
                    'unique_id': 'powerdog_line2_error_code',
                    'name': 'L2 Code',
                    'platform': 'sensor',
                    'state_topic': 'powerdog/L2/error_code',
                },
                'powerdog_line2_error_status': {
                    'unique_id': 'powerdog_line2_error_status',
                    'name': 'L2 Error',
                    'platform': 'sensor',
                    'state_topic': 'powerdog/L2/error_status',
                },
            }
            result.update(line2_result)
        return result

