import configparser

from data import PowerdogConfig, BrokerConfig, ClientConfig

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
        if 'POWERDOG' in self.config and 'address' in self.config['POWERDOG']:
            result.address = self.config['POWERDOG'].get('address')
        else:
            raise configparser.NoOptionError('address', 'POWERDOG')
        # POWERDOG > service is required
        if 'POWERDOG' in self.config and 'service' in self.config['POWERDOG']:
            result.service = self.config['POWERDOG'].get('service')
        else:
            raise configparser.NoOptionError('service', 'POWERDOG')

        return result

    def broker(self) -> BrokerConfig:
        result = BrokerConfig()

        # BROKER section required
        if 'BROKER' not in self.config:
            raise configparser.NoSectionError('BROKER')

        result.broker_host = self.config['BROKER'].get('host', fallback='localhost')
        result.broker_port = self.config['BROKER'].getint('port', fallback=1883)
        result.broker_user = self.config['BROKER'].get('user', fallback=None)
        result.broker_pass = self.config['BROKER'].get('pass', fallback=None)
        if 'subscribe_topics' in self.config['BROKER'] and len(self.config['BROKER'].get('subscribe_topics')) > 0:
            topics = self.config['BROKER'].get('subscribe_topics')
            result.subscribe_topics = topics.split(',')
        else:
            result.subscribe_topics = []

        return result

    def client(self) -> ClientConfig:
        result = ClientConfig()

        if 'CLIENT' not in self.config:
            raise configparser.NoSectionError('CLIENT')

        result.log_level = self.config['CLIENT'].get('log_level', fallback='INFO')

        return result
