#!/usr/bin/env python

"""Main application"""

import os
import tornado.ioloop

import service
import rabbitmq

import logging

LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -15s %(lineno) -5d: %(message)s'
LOGGER = logging.getLogger(__name__)


def main():
    # Setup logging
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    # Service Configuration
    management_port = os.getenv('MGMT_PORT', 8080)
    amqp_cfg = rabbitmq.AmqpConfiguration.from_environment()

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
    service.HealthHandler.add_health_provider('git-version', git_health_provider)

    # RabbitMQ
    amqp = rabbitmq.RabbitMQConnector(amqp_cfg, ioloop)
    amqp.setup()
    guard.add_termination_handler(amqp.stop)

    # Run
    LOGGER.info("Starting ioloop")
    while not guard.is_terminated():
        try:
            ioloop.start()
        except KeyboardInterrupt:
            LOGGER.info("Keyboard interrupt")
            guard.terminate()

    # Teardown
    LOGGER.info("Service terminated")


if __name__ == "__main__":
    main()
