""" Unit tests for the rabbitmq module """
import logging
from unittest import mock
import pytest

from typing import Optional, Callable, Any

import os
import gc
import weakref

from pika.adapters.tornado_connection import TornadoConnection

# noinspection PyUnresolvedReferences
# noinspection PyPackageRequirements
from rabbitmq import AmqpConfiguration, RabbitMQConnector


class TestAmqpConfiguration:
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_rabbitmq_env_no_host_config(self):
        with pytest.raises(ValueError) as e:
            AmqpConfiguration.from_environment()

        assert "Host configuration must be provided!" in str(e.value)

    @mock.patch.dict(os.environ, {
        "AMQP_HOST": "localhost"
    }, clear=True)
    def test_rabbitmq_env_no_user_config(self):
        with pytest.raises(ValueError) as e:
            AmqpConfiguration.from_environment()

        assert "User configuration must be provided!" in str(e.value)

    @mock.patch.dict(os.environ, {
        "AMQP_HOST": "localhost",
        "AMQP_USER": "user"
    }, clear=True)
    def test_rabbitmq_env_default_config(self):
        cfg = AmqpConfiguration.from_environment()

        # These two came from the environment
        assert cfg.host() == "localhost"
        assert cfg.user() == "user"

        # These come from the defaults
        assert cfg.connection_parameters().credentials.password is None
        assert cfg.exchange() == "pingboard"
        assert cfg.rk_status() == "status"
        for i in range(1, 5):
            assert cfg.rk_key(i-1) == "{}.key".format(i)
        assert cfg.rk_config() == "pingboard-configuration"
        assert cfg.qu_config() == "pingboard-configuration"
        assert cfg.declare() is False

    @mock.patch.dict(os.environ, {
        "AMQP_HOST": "localhost",
        "AMQP_USER": "user",
        "AMQP_DECLARE": "false"
    }, clear=True)
    def test_rabbitmq_env_declare_false_config(self):
        cfg = AmqpConfiguration.from_environment()

        assert cfg.declare() is False

    @mock.patch.dict(os.environ, {
        "AMQP_HOST": "localhost",
        "AMQP_USER": "user",
        "AMQP_PASS": "UkVBRE1F",  # base64 encoding for "README"
        "AMQP_EXCHANGE": "cust_1",
        "AMQP_RK_STATUS": "cust_2",
        "AMQP_RK_KEY_1": "cust_3_1",
        "AMQP_RK_KEY_2": "cust_3_2",
        "AMQP_RK_KEY_3": "cust_3_3",
        "AMQP_RK_KEY_4": "cust_3_4",
        "AMQP_RK_CONFIG": "cust_4",
        "AMQP_QU_CONFIG": "cust_5",
        "AMQP_DECLARE": "true"
    }, clear=True)
    def test_rabbitmq_env_all_config(self):
        cfg = AmqpConfiguration.from_environment()

        assert cfg.host() == "localhost"
        assert cfg.user() == "user"

        # Password has been base64 encoded
        assert cfg.connection_parameters().credentials.password == b"README"
        assert cfg.exchange() == "cust_1"
        assert cfg.rk_status() == "cust_2"
        for i in range(1, 5):
            assert cfg.rk_key(i-1) == "cust_3_{}".format(i)
        assert cfg.rk_config() == "cust_4"
        assert cfg.qu_config() == "cust_5"
        assert cfg.declare() is True


class SpyConfigurationCallback:
    def __init__(self, retval: bool):
        self._retval = retval
        self.called = False
        self.payload = None

    def callback(self, payload: str) -> bool:
        self.called = True
        self.payload = payload
        return self._retval


class SpyConfigurationProvider:
    def __init__(self, cfg: Optional[str]):
        self._cfg = cfg
        self.called = False

    def callback(self):
        self.called = True
        return self._cfg


def setup_tornado_connection_mock(tornado_connection_mock, exception=None):
    def side_effect(parameters,
                    custom_ioloop,
                    on_open_callback,
                    on_open_error_callback,
                    on_close_callback):
        tornado_connection_mock._params = {
            "parameters": parameters,
            "custom_ioloop": custom_ioloop,
            "on_open_callback": on_open_callback,
            "on_open_error_callback": on_open_error_callback,
            "on_close_callback": on_close_callback
        }

        if exception:
            raise exception

    tornado_connection_mock.side_effect = side_effect


class SpyTornadoIOLoopMock:
    def __init__(self):
        self.calls = list()

    def call_later(
        self, delay: float, callback: Callable[..., None], *_args: Any, **_kwargs: Any
    ) -> object:
        self.calls.append((delay, callback))
        # we never use the return value
        return None


class TestRabbitMQConnector:
    @staticmethod
    def _create_default_config():
        with mock.patch.dict(os.environ, {
            "AMQP_HOST": "localhost",
            "AMQP_USER": "user"
        }, clear=True):
            return AmqpConfiguration.from_environment()

    def test_no_config(self):
        with pytest.raises(ValueError) as e:
            RabbitMQConnector(None)

        assert "AMQP configuration must be provided!" in str(e.value)

    def test_initial_health(self):
        con = RabbitMQConnector(TestRabbitMQConnector._create_default_config())

        status, healthy = con.get_health()

        assert not healthy
        assert status == {
            "host": "localhost",
            "connection": "not established",
            "channel": "not established",
            "terminating": False,
            "healthy": False
        }

    def test_set_configuration_callback(self):
        con = RabbitMQConnector(TestRabbitMQConnector._create_default_config())

        con.set_configuration_callback(None)
        assert con._configuration_callback is None

        cb = SpyConfigurationCallback(False)
        con.set_configuration_callback(cb.callback)
        assert con._configuration_callback == cb.callback

    def test_set_configuration_provider(self):
        con = RabbitMQConnector(TestRabbitMQConnector._create_default_config())

        con.set_configuration_provider(None)
        assert con._configuration_provider is None

        prov = SpyConfigurationProvider(None)
        con.set_configuration_provider(prov.callback)
        prov_ref = weakref.WeakMethod(prov.callback)
        # We should get a weak reference to the callback method
        assert con._configuration_provider == prov_ref

        # test reference deletion
        del prov
        gc.collect()
        # noinspection PyCallingNonCallable
        assert con._configuration_provider() is None

    def test_unconnected_publish_status(self, caplog):
        con = RabbitMQConnector(TestRabbitMQConnector._create_default_config())
        con.publish_status("{}")

        assert caplog.records[-1].message == "Message to status has been discarded because a channel was not available!"

    def test_unconnected_publish_keypress(self, caplog):
        con = RabbitMQConnector(TestRabbitMQConnector._create_default_config())

        for idx in range(1, 4):
            con.publish_keypress(idx)
            assert caplog.records[-1].message == \
                   "Message to %d.key has been discarded because a channel was not available!" % idx

    def test_normal_connect(self, caplog):
        cfg = TestRabbitMQConnector._create_default_config()
        con = RabbitMQConnector(cfg)

        with caplog.at_level(logging.INFO):
            with mock.patch.object(TornadoConnection, '__init__') as tornado_mock:
                with mock.patch('pika.adapters.tornado_connection.TornadoConnection.ioloop',
                                new_callable=mock.PropertyMock):
                    setup_tornado_connection_mock(tornado_mock, exception=None)
                    con.setup()

                    assert caplog.records[-1].message == "Connecting to user@localhost"
                    assert tornado_mock._params == {
                        "parameters": cfg.connection_parameters(),
                        "custom_ioloop": None,
                        "on_open_callback": con._on_connection_open,
                        "on_open_error_callback": con._on_connection_error,
                        "on_close_callback": None
                    }

    def test_failed_connect_with_ioloop(self, caplog):
        cfg = TestRabbitMQConnector._create_default_config()
        ioloop = SpyTornadoIOLoopMock()
        con = RabbitMQConnector(cfg, ioloop=ioloop)

        with caplog.at_level(logging.INFO):
            with mock.patch.object(TornadoConnection, '__init__') as tornado_mock:
                setup_tornado_connection_mock(tornado_mock, exception=Exception("test"))
                con.setup()

                assert caplog.records[-1].message == \
                       "Error when connecting to RabbitMQ (will try again in 5 seconds: test"
                assert tornado_mock._params == {
                    "parameters": cfg.connection_parameters(),
                    "custom_ioloop": ioloop,
                    "on_open_callback": con._on_connection_open,
                    "on_open_error_callback": con._on_connection_error,
                    "on_close_callback": None
                }
                assert len(ioloop.calls) == 1
                assert ioloop.calls[0] == (5, con._reconnect)

    def test_failed_connect_without_ioloop(self, caplog):
        cfg = TestRabbitMQConnector._create_default_config()
        con = RabbitMQConnector(cfg, ioloop=None)

        with caplog.at_level(logging.INFO):
            with mock.patch.object(TornadoConnection, '__init__') as tornado_mock:
                with mock.patch('pika.adapters.tornado_connection.TornadoConnection.ioloop',
                                new_callable=mock.PropertyMock):
                    setup_tornado_connection_mock(tornado_mock, exception=Exception("test"))
                    con.setup()

                    assert caplog.records[-1].message == \
                           "IOLoop is not configured, will not retry!"
                    assert tornado_mock._params == {
                        "parameters": cfg.connection_parameters(),
                        "custom_ioloop": None,
                        "on_open_callback": con._on_connection_open,
                        "on_open_error_callback": con._on_connection_error,
                        "on_close_callback": None
                    }

    def test_close_unconnected_without_ioloop(self, caplog):
        cfg = TestRabbitMQConnector._create_default_config()
        con = RabbitMQConnector(cfg, ioloop=None)

        with caplog.at_level(logging.INFO):
            con.stop()

        assert len(caplog.records) == 1
        assert caplog.records[-1].message == \
               "Terminating RabbitMQ consumer"
