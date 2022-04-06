"""RabbitMQ management classes"""

import os
import json

import pika
from pika.adapters.tornado_connection import TornadoConnection
import tornado.ioloop

from typing import Callable, Optional, List

import logging

LOGGER = logging.getLogger(__name__)


class AmqpConfiguration(object):
    """Configuration data for the AMQP communication"""

    DEFAULT_EXCHANGE = "pingboard"
    DEFAULT_RK_STATUS = "status"
    DEFAULT_RK_KEY = ['1.key', '2.key', '3.key', '4.key']
    DEFAULT_QU_CONFIGURATION = "pingboard-configuration"

    @staticmethod
    def from_environment():
        host = os.getenv('AMQP_HOST', None)
        user = os.getenv('AMQP_USER', None)
        passwd = os.getenv('AMQP_PASS', None)

        exchange = os.getenv('AMQP_EXCHANGE', AmqpConfiguration.DEFAULT_EXCHANGE)
        rk_status = os.getenv('AMQP_RK_STATUS', AmqpConfiguration.DEFAULT_RK_STATUS)
        rk_key = [""] * 4
        for i in range(0, 4):
            rk_key[i] = os.getenv('AMQP_RK_KEY_{}'.format(1), AmqpConfiguration.DEFAULT_RK_KEY[i])
        qu_config = os.getenv('AMQP_QU_CONFIG', AmqpConfiguration.DEFAULT_QU_CONFIGURATION)

        return AmqpConfiguration(host, user, passwd,
                                 exchange, rk_status, rk_key, qu_config)

    def __init__(self,
                 amqp_host: str,
                 amqp_user: str,
                 amqp_passwd: Optional[str] = None,
                 exchange: Optional[str] = DEFAULT_EXCHANGE,
                 rk_status: Optional[str] = DEFAULT_RK_STATUS,
                 rk_key: Optional[List[str]] = None,
                 qu_config: Optional[str] = DEFAULT_QU_CONFIGURATION):

        if not amqp_host:
            raise ValueError("Host configuration must be provided!")
        if not amqp_user:
            raise ValueError("User configuration must be provided!")

        self._credentials = pika.credentials.PlainCredentials(amqp_user, amqp_passwd)
        self._params = pika.ConnectionParameters(host=amqp_host,
                                                 credentials=self._credentials)

        if not rk_status:
            raise ValueError("Routing key for status must be provided!")
        if (None in rk_key) or ("" in rk_key):
            raise ValueError("Routing keys for key presses must not be empty!")
        if not qu_config:
            raise ValueError("Queue name for configuration must be provided!")

        self._exchange = exchange
        self._rk_status = rk_status
        self._rk_key = rk_key or AmqpConfiguration.DEFAULT_RK_KEY
        self._qu_config = qu_config

    def host(self) -> str:
        return self._params.host

    def user(self) -> str:
        return self._credentials.username

    def connection_parameters(self) -> pika.ConnectionParameters:
        return self._params

    def exchange(self) -> str:
        return self._exchange

    def rk_status(self) -> str:
        return self._rk_status

    def rk_key(self, idx: int) -> str:
        return self._rk_key[idx]

    def qu_config(self) -> str:
        return self._qu_config


class RabbitMQConnector(object):
    """Connector for RabbitMQ using the Tornado IOLoop"""

    def __init__(self, amqp_cfg: AmqpConfiguration,
                 ioloop: Optional[tornado.ioloop.IOLoop] = None):
        if amqp_cfg is None:
            raise ValueError("AMQP configuration must be provided!")
        self._amqp_cfg = amqp_cfg

        self._ioloop = ioloop
        self._terminating = None

        self._connection = None
        self._channel = None

        self._configuration_callback = None

    def setup(self):
        self._connection = self._connect()

    def stop(self):
        LOGGER.info("Terminating RabbitMQ consumer")
        self._terminating = True

    def set_configuration_callback(self, callback: Callable[[json], bool]):
        self._configuration_callback = callback

    def publish_status(self, status: json):
        self._publish(self._amqp_cfg.rk_status(), status)

    def publish_keypress(self, idx: int):
        self._publish(self._amqp_cfg.rk_key(idx),
                      {
                          "key": int(idx)
                      })

    def _connect(self):
        LOGGER.info("Connecting to %s@%s", self._amqp_cfg.user(), self._amqp_cfg.host())

        return TornadoConnection(parameters=self._amqp_cfg.connection_parameters(),
                                 custom_ioloop=self._ioloop,
                                 on_open_callback=self._on_connection_open,
                                 on_open_error_callback=None,
                                 on_close_callback=None)

    def _reconnect(self):
        if not self._terminating:

            self._connection = self._connect()

    def _on_connection_open(self, _connection):
        LOGGER.info("Connection to %s opened", self._amqp_cfg.host())
        self._connection.add_on_close_callback(self._on_connection_closed)

        self._connection.channel(on_open_callback=self._on_channel_open)

    def _on_connection_closed(self, _connection, reason):
        if not self._terminating:
            LOGGER.warning("Connection closed unexpectedly, reopening in 5 seconds: %s", reason)
            self._channel = None
            self._connection.ioloop.call_later(5, self._reconnect)

    def _on_channel_open(self, channel):
        self._channel = channel
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=self._amqp_cfg.qu_config(),
                              on_message_callback=self._on_configuration_callback)

        LOGGER.info("Configuration channel open")

    def _on_channel_closed(self, channel, reason):
        LOGGER.warning("Channel %i has been closed unexpectedly: %s", channel, reason)

        # Something went wrong.
        # Close the connection and let the connector rebuild
        if self._connection:
            self._connection.close()

    def _on_configuration_callback(self, channel, method, _properties, body):
        ack = True

        if self._configuration_callback:
            try:
                cfg = json.loads(body.decode('utf-8'))
                if self._configuration_callback:
                    ack = self._configuration_callback(cfg)
            except json.decoder.JSONDecodeError as e:
                LOGGER.warning("Could not decode configuration snippet: %s", str(e))
                self._publish(self._amqp_cfg.rk_status(),
                              {"error": {
                                  "message": "Invalid JSON received for configuration",
                                  "details": str(e),
                                  "original": body.decode('utf-8')
                              }})

        if ack:
            channel.basic_ack(delivery_tag=method.delivery_tag)

    def _publish(self, rk, body):
        # TODO enable correlation keys
        if self._channel:
            self._channel.basic_publish(exchange=self._amqp_cfg.exchange(),
                                        routing_key=rk,
                                        body=json.dumps(body),
                                        )
        else:
            LOGGER.warning("Message to %s has been discarded because a channel was not available!", rk)
