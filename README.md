# PingBoard Daemon

[![standard-readme compliant](https://img.shields.io/badge/standard--readme-OK-green.svg?style=flat-square)](https://github.com/RichardLitt/standard-readme)
![PyTest](https://github.com/penguineer/PingBoardDaemon/actions/workflows/pytest.yml/badge.svg)
![Docker Image](https://github.com/penguineer/PingBoardDaemon/actions/workflows/docker-image.yml/badge.svg)

> Daemon connecting the [PingBoard](https://github.com/PingTechGmbH/PingBoard) to [RabbitMQ](https://www.rabbitmq.com/)

![](pingboard.jpeg)

A daemon that connects to a [PingBoard](https://github.com/PingTechGmbH/PingBoard) (or similar macro keyboard), then
sends key presses and accepts configuration via [RabbitMQ](https://www.rabbitmq.com/). The main goal is to enable the
PingBoard as an IoT input device and execute actions outside the USB host.

Features:
* Emits AMQP messages on Pingboard key press.
* Configures Pingboard (Brightness, Key LED colors, Blinking) with AMQP messages.
* Detects PingBoard via evdev and grabs it to prevent rogue inputs to other applications.
* Reconnects when connections to RabbitMQ or Pingboard are lost. Can also be started without Pingboard present.
* Current state is pushed to the configuration queue when finishing, so that it can be retrieved on the next run.
* Runs out of an unprivileged Docker container.

## Table of Contents

- [Usage](#usage)
- [API](#api)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Usage

### Run with Docker

Deployment via Docker is not trivial, as the daemon needs access to USB (evdev and serial).

With the configuration stored in a file `.env`, the daemon can be started as follows:

```bash
docker run --rm \
  -p 8080:8080 \
  --env-file .env \
  -v /dev:/dev \
  -v /run/udev:/run/udev:ro \
  --device-cgroup-rule='c 13:* rmw' \
  --device-cgroup-rule='c 166:* rmw' \
  mrtux/pingboard-daemon
```

### Configuration

Configuration is done using environment variables:

* `MANAGEMENT_PORT`: Port for the HTTP Management Service (default: 8080)
* `AMQP_HOST`: RabbitMQ host
* `AMQP_USER`: RabbitMQ user
* `AMQP_PASS`: Base64-encoded RabbitMQ password (default: empty)
* `AMQP_EXCHANGE`: RabbitMQ Exchange name (default: `pingboard`)
* `AMQP_RK_STATUS`: RabbitMQ routing key for status information (default: `status`)
* `AMQP_RK_KEY_1`: RabbitMQ routing key for key 1 press (default: `1.key`)
* `AMQP_RK_KEY_2`: RabbitMQ routing key for key 2 press (default: `2.key`)
* `AMQP_RK_KEY_3`: RabbitMQ routing key for key 3 press (default: `3.key`)
* `AMQP_RK_KEY_4`: RabbitMQ routing key for key 4 press (default: `4.key`)
* `AMQP_RK_CONFIG`: RabbitMQ routing key to retain configuration (default: `pingboard-configuration`)
* `AMQP_QU_CONFIG`: RabbitMQ queue for configuration updates (default: `pingboard-configuration`)
* `AMQP_DECLARE`: Declare exchange and channel with bind for configuration (default: `false`)

### Developing with PyCharm

When opening this project with [PyCharm](https://www.jetbrains.com/de-de/pycharm/), make sure to mark the source and
test source directories accordingly. Otherwise, PyCharm will not find the source modules in the tests.

The `test_service.py` module also needs to be run from the project root (not the test root).

## API

### RabbitMQ routing

The daemon expects a specific setup for RabbitMQ:

* All messages are sent to one single exchange.
* There are specific routing keys for status updates, key 1 to 4 presses and to retain the configuration during downtime.
* Configuration is received on a separate queue. Exchange and routing keys can be configured with the environment
  variables.

Unless `AMQP_DECLARE` is set to `true` the exchange, queues and bindings are not set up automatically, so RabbitMQ has
to be prepared accordingly. This allows to fine-tune the channel settings in the broker.
A declaration will only set up the exchange, a configuration channel and that channel's binding.
Routing for key and status messages is not relevant to this daemon and must be set up by the receiving agents or in the
broker.

To route multiple or all keys to the same queue, either create the respective bindings or set all routing keys to the
same value.

### Messages

All messages are encoded in the JSON format.

#### Key presses

The message for a key press is structured as follows:

```json
{
  "key": 1
}
```

The value can be a number between 1 and 4, depending on the key pressed.

#### Pingboard Configuration

Pingboard configuration, i.e. brightness, key colors and blinking, can be set with the following JSON:

```json
{
  "configuration": {
    "brightness": 255,
    "keys": [
      {
        "idx": 1,
        "color": [255, 255, 255]
      },
      {
        "idx": 2,
        "color": [0, 0, 0]
      },
      {
        "idx": 3,
        "color": [0, 0, 0]
      },
      {
        "idx": 4,
        "color": [0, 0, 0]
      }
    ],
    "blink": [
      {
        "idx": 1,
        "mode": "OFF",
        "color": [255, 0, 0]
      },
      {
        "idx": 2,
        "mode": "SINGLE",
        "color": [255, 0, 0]
      },
      {
        "idx": 3,
        "mode": "SHORT",
        "color": [255, 0, 0]
      },
      {
        "idx": 4,
        "mode": "LONG",
        "color": [255, 0, 0]
      }
    ]
  }
}
```

Fragmentation is accepted, following these rules:

* An arbitrary permutation of the top-level elements can be sent.
* `"keys"` and `"blink"` accept an arbitrary number of array elements. Arrays are processed in the order of elements,
  i.e. if a key is set twice in an array, the last setting will be stored.

If the Pingboard is available, all settings will be written in their order of appearance.

Please note that the key index is one-based.

On shutdown the daemon will push an the configuration to the queue to retain it during a downtime.
To avoid this behaviour set an empty routing key for the configuration.

### Health endpoint

The daemon features a health endpoint to check if all components are up and running.
While a certain amount of resilience is built into the handlers, an overall check routine using the Docker
health checks has been established.
The endpoint works similar to health endpoints expected for Microservices, e.g. in a Kubernetes runtime environment:
* HTTP status 200 is returned when the service is considered healthy.
* HTTP status 500 is returned when the service is considered unhealthy.
* Additional information can be found in the return message. Please refer to the [OAS3](src/OAS3.yml) for details.

The [Dockerfile](Dockerfile) sets the container up for a health check every 10s, otherwise sticks to the Docker defaults.

To expose the health endpoint, route port 8080 to a port that is suitable for the deployment environment.

## Maintainers

* Stefan Haun ([@penguineer](https://github.com/penguineer))

## Contributing

PRs are welcome!

If possible, please stick to the following guidelines:

* Keep PRs reasonably small and their scope limited to a feature or module within the code.
* If a large change is planned, it is best to open a feature request issue first, then link subsequent PRs to this
  issue, so that the PRs move the code towards the intended feature.

Small note: If editing the README, please conform to
the [standard-readme](https://github.com/RichardLitt/standard-readme) specification.

## License

[MIT](LICENSE.txt) © 2022-2023 Stefan Haun and contributors
