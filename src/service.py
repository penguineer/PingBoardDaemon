"""Service Management classes"""

import signal
import platform
import asyncio

import tornado.ioloop
import tornado.netutil
import tornado.httpserver

from abc import ABCMeta
import tornado.web

import os
import subprocess
from datetime import datetime
import isodate
import weakref

import json

from typing import Callable, Union, Optional, Any

import logging
LOGGER = logging.getLogger(__name__)


def platform_setup() -> None:
    """Platform-specific setup, especially for asyncio."""
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class TerminationGuard(object):
    """Guard the ioloop for termination signals and call clean-up handlers"""

    def __init__(self, ioloop: Optional[tornado.ioloop.IOLoop] = None):
        self._signal_received = False
        self._handlers = list()
        self._ioloop = ioloop

        signal.signal(signal.SIGTERM, self._on_signal)
        tornado.ioloop.PeriodicCallback(self._stop_on_signal, 1000).start()

    def is_terminated(self) -> bool:
        """Indicate if the termination signal has been received"""

        return self._signal_received

    def terminate(self) -> None:
        """Explicit trigger for the termination signal"""

        self._on_signal(signal.SIGTERM, None)

    def add_termination_handler(self, handler: Callable[[None], Any]) -> None:
        """Add a clean-up handler to call when the guard terminates"""

        if handler is not None:
            self._handlers.append(handler)

    def _on_signal(self, sig, _frame):
        LOGGER.info("%s received, stopping server" % sig)
        if not self._signal_received:
            for hnd in self._handlers:
                hnd()
        self._signal_received = True

    def _stop_on_signal(self):
        if self._signal_received and self._ioloop:
            self._ioloop.stop()
            LOGGER.info("IOLoop stopped")


class HealthProvider(object):
    """Interface class for health information providers"""
    def get_health(self) -> tuple[Union[None, str, dict], bool]:
        """Get additional health information and the provider's health status"""

        pass


class GitHealthProvider(HealthProvider):
    """Provide information about the git reference for the health endpoint"""

    # noinspection PyAttributeOutsideInit
    def __init__(self, gitversion_file: Optional[str] = 'git-version.txt'):
        self.git_version = self._load_git_version(gitversion_file)

    def get_health(self) -> tuple[Optional[str], bool]:
        """Return the git revision; status is always healthy"""
        return self.git_version, True

    @staticmethod
    def _load_git_version(gitversion_file):
        v = None

        # try file git-version.txt first
        if os.path.exists(gitversion_file):
            with open(gitversion_file) as f:
                v = f.readline().strip()

        # if not available, try git
        if v is None:
            LOGGER.info("%s not found, trying git call", str(gitversion_file))
            try:
                v = subprocess.check_output(["git", "describe", "--always", "--dirty"],
                                            cwd=os.path.dirname(__file__)).strip().decode()
            except subprocess.CalledProcessError as e:
                LOGGER.warning("Checking git version lead to non-null return code: %s", e.returncode)

        if v:
            LOGGER.info("Git version is %s", str(v))
        else:
            LOGGER.info("Git version could not be determined.")

        return v


class HealthHandler(tornado.web.RequestHandler, metaclass=ABCMeta):
    """Provide a health endpoint for the service API"""

    startup_timestamp = datetime.now()
    """Store the timestamp of service start"""

    health_providers = weakref.WeakValueDictionary()
    """Weak references to the health information providers"""

    RESERVED_KEYS = ('api-version', 'timestamp', 'uptime')
    """Do not use these keys for additional health providers!"""

    @classmethod
    def add_health_provider(cls, key: str, provider: HealthProvider) -> None:
        """Add a health provider"""

        if key in cls.RESERVED_KEYS:
            raise ValueError("Key must not be in RESERVED_KEYS!")

        if key in cls.health_providers.keys():
            raise KeyError("Key is already registered!")

        if provider is None:
            del cls.health_providers[key]
        else:
            cls.health_providers[key] = provider

    # noinspection PyAttributeOutsideInit
    def initialize(self):
        pass

    def get(self):
        health = dict()
        health['api-version'] = 'v0'

        health['timestamp'] = isodate.datetime_isoformat(datetime.now())
        health['uptime'] = isodate.duration_isoformat(datetime.now() - HealthHandler.startup_timestamp)

        healthy = True

        # Call the health handlers
        for key in HealthHandler.health_providers:
            provider = HealthHandler.health_providers[key]
            if provider is None:
                del HealthHandler.health_providers[key]

            info, status = provider.get_health()
            if info is not None:
                health[key] = info
            healthy = healthy and status

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(health, indent=4))
        self.set_status(200 if healthy else 500)


class Oas3Handler(tornado.web.RequestHandler, metaclass=ABCMeta):
    """Return the OAS3 spec for the service endpoint"""

    def get(self):
        self.set_header("Content-Type", "text/plain")
        # The following is the proposed content type,
        # but browsers like Firefox try to download instead of displaying the content
        # self.set_header("Content-Type", "text/vnd.yml")
        with open('OAS3.yml', 'r') as f:
            oas3 = f.read()
            self.write(oas3)
        self.finish()


class ServiceMgmtEndpoint(object):
    """Open a Tornado HTTP server for the service management API"""

    def __init__(self, listen_port: Optional[int] = 8080):
        if not isinstance(listen_port, int):
            raise ValueError("Server port must be an integer value!")

        self._listen_port = listen_port
        self._server = None

    def setup(self) -> None:
        """Setup the server (does not start ioloop)"""
        sockets = tornado.netutil.bind_sockets(self._listen_port, '')
        server = tornado.httpserver.HTTPServer(ServiceMgmtEndpoint._make_app())
        server.add_sockets(sockets)

        port = None

        for s in sockets:
            LOGGER.info('Listening on %s, port %d' % s.getsockname()[:2])
            if port is None:
                port = s.getsockname()[1]

    def stop(self) -> None:
        """Stop the server, if available"""
        if self._server:
            self._server.stop()

    @staticmethod
    def _make_app() -> tornado.web.Application:
        version_path = r"/v[0-9]"
        return tornado.web.Application([
            (version_path + r"/health", HealthHandler),
            (version_path + r"/oas3", Oas3Handler),
        ])
