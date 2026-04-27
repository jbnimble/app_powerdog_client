import random
import time
import logging
import argparse
import json
import sys

from paho.mqtt import client as mqtt_client
from paho.mqtt.enums import CallbackAPIVersion

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class miniMQTT:
    """A lightweight MQTT client wrapper for connecting, publishing, and managing the network loop.

    This class handles MQTT connection setup, publish requests, and background loop control with
    basic exception handling and logging.
    """

    def __init__(self, broker, port, client_id, username, password):
        """Initialize the MQTT client and attempt to connect to the broker.

        Args:
            broker (str): MQTT broker hostname or IP address.
            port (int): MQTT broker port.
            client_id (str): Unique client identifier.
            username (str): Username for broker authentication.
            password (str): Password for broker authentication.
        """
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.username = username
        self.password = password
        self.client = None
        try:
            self.client = self.connect_mqtt()
            if self.client is None:
                raise ConnectionError("Failed to establish MQTT connection")
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            raise
        
    def connect_mqtt(self):
        """Create and connect the MQTT client to the configured broker.

        Returns:
            mqtt_client.Client | None: The connected MQTT client instance, or None if connection fails.
        """
        def on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                logger.info("Connected to MQTT Broker!")
            else:
                logger.warning(f"Failed to connect, return code {rc}")

        try:
            client = mqtt_client.Client(CallbackAPIVersion.VERSION2, client_id=self.client_id)
            client.username_pw_set(self.username, self.password)
            client.on_connect = on_connect
            client.connect(self.broker, self.port)
            return client
        except Exception as e:
            logger.error(f"Connection attempt failed: {e}")
            return None

    def publish(self, topic=None, msg=None):
        """Publish a message to the specified MQTT topic.

        Args:
            topic (str): Destination MQTT topic.
            msg (str): Message payload to publish.

        Returns:
            bool: True if the publish request succeeded, False otherwise.
        """
        if self.client is None:
            logger.error("Cannot publish: client not connected")
            return False
        try:
            result = self.client.publish(topic, msg)
            status = result[0]
            if status == 0:
                logger.info(f"Sent `{msg}` to topic `{topic}`")
                return True
            else:
                logger.warning(f"Failed to send message to topic {topic}, status: {status}")
                return False
        except Exception as e:
            logger.error(f"Publish failed: {e}")
            return False

    def run_once(self, topic=None):
        """Start the MQTT loop, publish a single message, and stop the loop.

        This method is a convenience wrapper that manages the network loop while sending a
        single publish message.

        Args:
            topic (str): Destination MQTT topic.
        """
        try:
            self.start_loop()
            self.publish(topic)
        except Exception as e:
            logger.error(f"Run failed: {e}")
        finally:
            self.stop_loop()
        
    def start_loop(self):
        """Start the MQTT network loop in a background thread."""
        if self.client is None:
            logger.error("Cannot start loop: client not connected")
            return
        try:
            self.client.loop_start()
            logger.info("MQTT loop started")
        except Exception as e:
            logger.error(f"Failed to start loop: {e}")
            
    def stop_loop(self):
        """Stop the MQTT network loop and cleanly end background processing."""
        if self.client is None:
            return
        try:
            self.client.loop_stop()
            logger.info("MQTT loop stopped")
        except Exception as e:
            logger.error(f"Failed to stop loop: {e}")    
        



def main():
    arg_parser = argparse.ArgumentParser(description='miniMQTTpulisher')
    arg_parser.add_argument('--broker', required=True, help='MQTT broker IP or hostname')
    arg_parser.add_argument('--port', type=int, required=True, help='MQTT broker port')
    arg_parser.add_argument('--username', required=True, help='Username for broker connection')
    arg_parser.add_argument('--password', required=True, help='Password for broker connection')
    args = arg_parser.parse_args()

    try:
        client_id = f'publish-{random.randint(0, 1000)}'
        mqtt_client = miniMQTT(args.broker, args.port, client_id, args.username, args.password)
        mqtt_client.start_loop()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                topic = data["topic"]
                value = data["value"]
                mqtt_client.publish(topic, value)
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse line: {e}")
        
        
    except KeyboardInterrupt:
        print('Program interrupted by user (Ctrl+C). Shutting down')
        
    mqtt_client.stop_loop()

        

if __name__ == '__main__':
    main()        


    
    
    