"""Pingboard handling"""

import json
import weakref

import evdev
import tornado.ioloop
import serial.tools.list_ports

from typing import Optional, List

import logging

LOGGER = logging.getLogger(__name__)


class PingboardKeyParser(object):
    """Parse key press events and call handler if triggered"""
    MODIFIER_CODE = 125
    KEYS = [88, 87, 68, 67]

    def __init__(self,
                 callback):
        self._modifier = False
        self._callback = weakref.WeakMethod(callback)

    def process(self, code: int, enabled: bool):
        if code == PingboardKeyParser.MODIFIER_CODE:
            self._modifier = enabled
            return None

        if code not in PingboardKeyParser.KEYS:
            LOGGER.warning("Unknown Pingboard key code: %s", code)

        key = PingboardKeyParser.KEYS.index(code) + 1

        if self._modifier and enabled:
            if self._callback is not None:
                self._callback()(key)


class PingboardEvDev(object):
    """Listen to Pingboard via evdev"""
    @staticmethod
    def find_pingboard_evdev() -> Optional[evdev.InputDevice]:
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        candidates = list(filter(lambda d: (d.name == "Arduino LLC Arduino Micro") and
                                           (d.info.vendor == 0x2341) and
                                           (d.info.product == 0x8037),
                                 devices))
        if candidates:
            dev = candidates[0]
            return dev
        else:
            return None

    def __init__(self,
                 parser: PingboardKeyParser,
                 ioloop: tornado.ioloop.IOLoop):
        self._dev = None
        self._ioloop = ioloop

        self._parser = parser

        self._acquire_callbacks = list()

    def setup(self):
        self._acquire_evdev()

    def stop(self):
        pass

    def add_on_acquire_callback(self, callback):
        _cb = weakref.WeakMethod(callback)
        self._acquire_callbacks.append(_cb)

    def _on_acquire(self):
        for cb in self._acquire_callbacks:
            if cb() is not None:
                cb()()

    def _acquire_evdev(self):
        self._dev = PingboardEvDev.find_pingboard_evdev()
        if self._dev:
            LOGGER.info("Found Pingboard event device %s", self._dev)
            self._dev.grab()
            self._ioloop.add_callback(self._listen)
            self._on_acquire()
        else:
            LOGGER.error("Could not acquire the event device, will try again in 5 seconds")
            self._ioloop.call_later(5, self._acquire_evdev)

    async def _listen(self):
        try:
            async for ev in self._dev.async_read_loop():
                self._process_event(ev)
        except OSError as e:
            LOGGER.warning("OSError in evdev loop: %s", str(e))

        # Got out of this loop somehow -> restart
        self._acquire_evdev()

    def _process_event(self, event):
        if event.type == evdev.ecodes.EV_KEY:
            self._ioloop.add_callback(self._parser.process, event.code, bool(event.value))


class PingboardKeyState(object):
    """Store the configuration state for a single Pingboard key"""
    BLINK_MODE = ('SINGLE', 'SHORT', 'LONG', 'OFF')

    def __init__(self):
        self.color = [0] * 3
        self.blink_mode = 'OFF'
        self.blink_color = [0] * 3

    def as_key_configuration(self, idx: int) -> dict:
        return {
            "idx": idx,
            "color": self.color
        }

    def as_blink_configuration(self, idx: int) -> dict:
        return {
            "idx": idx,
            "mode": self.blink_mode,
            "color": self.blink_color
        }


class PingboardState(object):
    """Store the Pingboard configuration state"""
    def __init__(self):
        # Create four different instances of PingboardKeyState
        self.keys = [PingboardKeyState(),
                     PingboardKeyState(),
                     PingboardKeyState(),
                     PingboardKeyState()]
        self.brightness = 255

    def as_configuration(self) -> dict:
        return {
            "configuration": {
                "brightness": self.brightness,
                "keys": [key.as_key_configuration(idx + 1) for idx, key in enumerate(self.keys)],
                "blink": [key.as_blink_configuration(idx + 1) for idx, key in enumerate(self.keys)]
            },
        }


class PingboardSerial:
    """Write to the Pingboard via the serial console"""
    @staticmethod
    def find_arduino_port():
        ports = list(serial.tools.list_ports.comports())
        candidates = list(filter(lambda p: p.description == "Arduino Micro", ports))

        if candidates:
            port = candidates[0]
            LOGGER.info("Found Pingboard arduino serial port at %s", port)
            return port
        else:
            LOGGER.warning("Pingboard arduino serial port could not be found!")
            return None

    def __init__(self):
        self._port = None
        self.scan_port()

    def scan_port(self):
        self._port = PingboardSerial.find_arduino_port()

    def brightness(self, brightness: int) -> bool:
        command = "DIM {:03d}\n".format(brightness)

        return self._write(command)

    def key_color(self, idx: int, color: List[int]) -> bool:
        command = "COL {0:1d} {1:03d} {2:03d} {3:03d}\n".format(idx,
                                                                color[0],
                                                                color[1],
                                                                color[2])

        return self._write(command)

    def key_blink(self, idx: int, mode: str, color: List[int]) -> bool:
        command = "BLNK {:1d} {} {:03d} {:03d} {:03d}\n".format(idx,
                                                                mode,
                                                                color[0],
                                                                color[1],
                                                                color[2])
        return self._write(command)

    def _write(self, command: str) -> bool:
        ok = False
        retries = 3

        while self._port and retries and not ok:
            try:
                retries -= 1

                ser = serial.Serial(self._port.device, 115200, timeout=1)
                ser.write(command.encode())
                res = ser.readline().decode()
                ser.flush()
                ser.close()

                ok = res == "OK\n"
            except serial.SerialException as e:
                LOGGER.error("Serial exception while writing to Pingboard: %s", str(e))
                self.scan_port()

        if not ok:
            LOGGER.error("Failure when writing to Pingboard, command was: %s", command)

        return ok


class PingboardConfiguration(object):
    """Handle Pingboard configuration requests"""
    def __init__(self, pb_serial: PingboardSerial):
        self._serial = pb_serial

        # State object will be created when the first configuration comes in.
        # This way we won't push dummy configuration to the board.
        self._state = None

        self._cfg_handlers = {
            "brightness": self._cfg_brightness,
            "keys": self._cfg_keys,
            "blink": self._cfg_blink
        }

    def push_config(self):
        if self._state is None:
            return None

        self._brightness(self._state.brightness)
        for idx in range(1, 5):
            key = self._state.keys[idx - 1]
            self._key_color(idx, key.color)
            self._key_blink(idx, key.blink_mode, key.blink_color)

    def on_configuration(self, cfg: json):
        if self._state is None:
            self._state = PingboardState()

        configuration = cfg.get("configuration", dict())
        for key, value in configuration.items():
            try:
                self._cfg_handlers[key](value)
            except Exception as e:
                LOGGER.error("Invalid configuration snippet: %s", str(e))

    def get_configuration(self) -> dict:
        return self._state.as_configuration()

    def _cfg_brightness(self, brightness):
        if brightness is not None:
            self._brightness(brightness)

    def _cfg_keys(self, keys):
        for key in keys or dict():
            idx = key['idx']
            color = key['color']
            self._key_color(idx, color)

    def _cfg_blink(self, blinks):
        for blink in blinks or dict():
            idx = blink['idx']
            color = blink['color']
            mode = blink['mode']
            self._key_blink(idx, mode, color)

    def _brightness(self, brightness: int) -> bool:
        self._state.brightness = brightness

        return self._serial.brightness(brightness)

    def _key_color(self, idx: int, color: List[int]) -> bool:
        self._state.keys[idx - 1].color = color

        return self._serial.key_color(idx, color)

    def _key_blink(self, idx: int, mode: str, color: List[int]) -> bool:
        if mode not in PingboardKeyState.BLINK_MODE:
            raise ValueError("Blink mode must be one of %s, was:", PingboardKeyState.BLINK_MODE, mode)

        ok = self._serial.key_blink(idx, mode, color)

        # Store single blink as 'OFF' event, if written successfully, so that it is not repeated
        self._state.keys[idx - 1].blink_mode = 'OFF' if mode == 'SINGLE' and ok else mode
        self._state.keys[idx - 1].blink_color = color

        return ok
