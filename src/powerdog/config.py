import configparser

from powerdog.data import PowerdogConfig, BrokerConfig, ClientConfig

class Configuration:
    """
    Expects an INI file of the format:

    [POWERDOG]
    address = str
    service = str
    [BROKER]
    host = str
    port = str
    user = str
    pass = str
    subscribe_topics = comma separated str
    [CLIENT]
    log_level = str
    """
    def __init__(self, config_file: str):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)

    """
    Parse INI file, and return PowerdogConfig
    raises NoOptionError and NoSectionError if missing required parts of config
    """
    def powerdog(self) -> PowerdogConfig:
        result = PowerdogConfig()

        # POWERDOG > address is required
        section_key = 'POWERDOG'
        if  section_key in self.config:
            result.address = self.config[section_key].get('address', fallback=result.address)
            result.service = self.config[section_key].get('service', fallback=result.service)
            result.limit_voltage_range = self.config[section_key].getfloat('limit_voltage_range', fallback=result.limit_voltage_range)
            result.limit_amperage_range = self.config[section_key].getfloat('limit_amperage_range', fallback=result.limit_amperage_range)
            result.limit_wattage_range = self.config[section_key].getfloat('limit_wattage_range', fallback=result.limit_wattage_range)
            result.limit_quiet_sec = self.config[section_key].getfloat('limit_quiet_sec', fallback=result.limit_quiet_sec)
            result.device_meta_path = self.config[section_key].get('device_meta_path', fallback=result.device_meta_path)

        return result

    def broker(self) -> BrokerConfig:
        result = BrokerConfig()

        # BROKER section required
        section_key = 'BROKER'
        if section_key in self.config:
            result.broker_host = self.config[section_key].get('host', fallback=result.broker_host)
            result.broker_port = self.config[section_key].getint('port', fallback=result.broker_port)
            result.broker_user = self.config[section_key].get('user', fallback=result.broker_user)
            result.broker_pass = self.config[section_key].get('pass', fallback=result.broker_pass)
            if 'subscribe_topics' in self.config[section_key] and len(self.config[section_key].get('subscribe_topics')) > 0:
                topics = self.config[section_key].get('subscribe_topics')
                result.subscribe_topics = topics.split(',')
        if not result.subscribe_topics:
            result.subscribe_topics = []

        return result

    def client(self) -> ClientConfig:
        result = ClientConfig()

        section_key = 'CLIENT'
        if section_key in self.config:
            result.log_level = self.config[section_key].get('log_level', fallback='INFO')

        return result
