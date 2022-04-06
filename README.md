# PingBoard Daemon

[![standard-readme compliant](https://img.shields.io/badge/standard--readme-OK-green.svg?style=flat-square)](https://github.com/RichardLitt/standard-readme)

> Daemon connecting the [PingBoard](https://github.com/PingTechGmbH/PingBoard) to [RabbitMQ](https://www.rabbitmq.com/)

![](pingboard.jpeg)

A daemon that connects to a [PingBoard](https://github.com/PingTechGmbH/PingBoard) (or similar macro keyboard), then sends key presses and accepts configuration via [RabbitMQ](https://www.rabbitmq.com/).
The main goal is to enable the PingBoard as an IoT input device and execute actions outside the USB host.


## Table of Contents

- [Usage](#usage)
- [API](#api)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Usage

Run via docker:

```bash
docker run --rm -p 8080:8080 mrtux/pingboard-daemon
```

### Configuration

Configuration is done using environment variables:
* `MANAGEMENT_PORT`: Port for the HTTP Management Service (default: 8080)
* `AMQP_HOST`: RabbitMQ host
* `AMQP_USER`: RabbitMQ user
* `AMQP_PASS`: RabbitMQ password (default: empty)
* `AMQP_EXCHANGE`: RabbitMQ Exchange name (default: `pingboard`)
* `AMQP_RK_STATUS`: RabbitMQ routing key for status information (default: `status`)
* `AMQP_RK_KEY_1`: RabbitMQ routing key for key 1 press (default: `1.key`)
* `AMQP_RK_KEY_2`: RabbitMQ routing key for key 2 press (default: `2.key`)
* `AMQP_RK_KEY_3`: RabbitMQ routing key for key 3 press (default: `3.key`)
* `AMQP_RK_KEY_4`: RabbitMQ routing key for key 4 press (default: `4.key`)
* `AMQP_QU_CONFIG`: RabbitMQ queue for configuration updates (default: `pingboard-configuration`)

## API

tbd

## Maintainers

* [@penguineer](https://github.com/penguineer)

## Contributing

PRs are welcome!

If possible, please stick to the following guidelines:
* Keep PRs reasonably small and their scope limited to a feature or module within the code.
* If a large change is planned, it is best to open a feature request issue first, then link subsequent PRs to this issue, so that the PRs move the code towards the intended feature.

Small note: If editing the README, please conform to the [standard-readme](https://github.com/RichardLitt/standard-readme) specification.

## License

MIT © 2022 Stefan Haun and contributors
