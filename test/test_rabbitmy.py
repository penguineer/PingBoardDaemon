""" Unit tests for the rabbitmq module """

from unittest import mock
import pytest

import os

# noinspection PyUnresolvedReferences
# noinspection PyPackageRequirements
from rabbitmq import AmqpConfiguration


@mock.patch.dict(os.environ, {}, clear=True)
def test_rabbitmq_env_no_host_config():
    with pytest.raises(ValueError) as e:
        AmqpConfiguration.from_environment()

    assert "Host configuration must be provided!" in str(e.value)


@mock.patch.dict(os.environ, {
    "AMQP_HOST": "localhost"
}, clear=True)
def test_rabbitmq_env_no_user_config():
    with pytest.raises(ValueError) as e:
        AmqpConfiguration.from_environment()

    assert "User configuration must be provided!" in str(e.value)


@mock.patch.dict(os.environ, {
    "AMQP_HOST": "localhost",
    "AMQP_USER": "user"
}, clear=True)
def test_rabbitmq_env_default_config():
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
def test_rabbitmq_env_declare_false_config():
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
def test_rabbitmq_env_all_config():
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
