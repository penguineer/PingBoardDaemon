#!/usr/bin/env python

"""Main application"""
import os

import tornado.ioloop

import service
import rabbitmq
import pingboard

import logging

LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -15s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)


def main():
    # Setup logging
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    # Service Configuration
    management_port = os.getenv('MGMT_PORT', 8080)
    try:
        amqp_cfg = rabbitmq.AmqpConfiguration.from_environment()
    except ValueError as e:
        LOGGER.critical("Critical error reading AMQP config: %s", e)
        # It is still safe to just return here
        return

    # Setup ioloop
    service.platform_setup()
    ioloop = tornado.ioloop.IOLoop.current()
    guard = service.TerminationGuard(ioloop)

    # Setup Service Management endpoint
    mgmt_ep = service.ServiceMgmtEndpoint(listen_port=management_port)
    guard.add_termination_handler(mgmt_ep.stop)
    mgmt_ep.setup()

    # Health Provider map uses weak references, so make sure to store this instance in a variable
    git_health_provider = service.GitHealthProvider()
    service.HealthHandler.add_health_provider('git-version', git_health_provider.get_health)

    # Pingboard Configuration
    pb_serial = pingboard.PingboardSerial()
    pb_cfg = pingboard.PingboardConfiguration(pb_serial)

    # RabbitMQ
    amqp = rabbitmq.RabbitMQConnector(amqp_cfg, ioloop)
    guard.add_termination_handler(amqp.stop)
    amqp.set_configuration_callback(pb_cfg.on_configuration)
    amqp.set_configuration_provider(pb_cfg.get_configuration)
    amqp.setup()
    service.HealthHandler.add_health_provider('amqp', amqp.get_health)

    # Pingboard Input
    key_parser = pingboard.PingboardKeyParser(amqp.publish_keypress)
    pb_input = pingboard.PingboardEvDev(key_parser, ioloop)
    pb_input.add_on_acquire_callback(pb_serial.scan_port)
    pb_input.add_on_acquire_callback(pb_cfg.push_config)
    pb_input.setup()
    guard.add_termination_handler(pb_input.stop)

    # Run
    LOGGER.info("Starting ioloop")
    while not guard.is_terminated():
        try:
            ioloop.start()
        except KeyboardInterrupt:
            LOGGER.info("Keyboard interrupt")
            guard.terminate()

    # Restart ioloop for clean-up
    ioloop.start()

    # Teardown
    LOGGER.info("Service terminated")


if __name__ == "__main__":
    main()
