""" Unit tests for the rabbitmq module """

import logging
from unittest import mock
import pytest

import weakref

import serial.tools.list_ports

from pingboard import PingboardKeyParser, PingboardKeyState, PingboardState, PingboardSerial, PingboardConfiguration


class KeyCallback(object):
    def __init__(self):
        self.called = False
        self.key = None

    def callback(self, key):
        self.called = True
        self.key = key


class TestPingboardKeyParser:
    MODIFIER_CODE = 125
    KEYS = [88, 87, 68, 67]

    def cb(self, _key):
        pass

    def test_setup_no_callback(self):
        with pytest.raises(ValueError) as e:
            PingboardKeyParser(callback=None)

        assert "Callback must be provided!" in str(e.value)

    def test_setup_callback(self):
        cb = KeyCallback()
        p = PingboardKeyParser(callback=cb.callback)

        assert not p._modifier
        assert p._callback == weakref.WeakMethod(cb.callback)

    def test_modifier_key(self):
        cb = KeyCallback()
        p = PingboardKeyParser(callback=cb.callback)

        # modifier should not be enabled
        assert not p._modifier

        # user has pushed the modifier
        p.process(TestPingboardKeyParser.MODIFIER_CODE, enabled=True)
        assert p._modifier

        # user has released the modifier
        p.process(TestPingboardKeyParser.MODIFIER_CODE, enabled=False)
        assert not p._modifier

    def test_known_keys(self):
        for idx, key in enumerate(TestPingboardKeyParser.KEYS, start=1):
            cb = KeyCallback()
            p = PingboardKeyParser(callback=cb.callback)

            # keypress without modifier
            p.process(key, enabled=True)
            # should not have called callback
            assert not cb.called
            # and not enabled
            assert not p._modifier

            # push the modifier
            p.process(TestPingboardKeyParser.MODIFIER_CODE, enabled=True)
            assert not cb.called
            assert p._modifier

            # push the key
            p.process(key, enabled=True)
            assert cb.called
            assert cb.key == idx
            assert p._modifier

            cb.called = False
            # release the key
            p.process(key, enabled=False)
            assert not cb.called
            assert p._modifier

            # release the modifier
            p.process(TestPingboardKeyParser.MODIFIER_CODE, enabled=False)
            assert not cb.called
            assert not p._modifier

    def test_unknown_key(self, caplog):
        cb = KeyCallback()
        p = PingboardKeyParser(callback=cb.callback)

        p.process(1, enabled=True)

        assert len(caplog.records) == 1
        assert caplog.records[-1].message == \
               "Unknown Pingboard key code: 1"


class TestPingboardKeyState:
    def test_init(self):
        st = PingboardKeyState()

        assert st.color == [0, 0, 0]
        assert st.blink_mode == "OFF"
        assert st.blink_color == [0, 0, 0]

    def test_configuration_json(self):
        colors = [[0] * 3, [255] * 3, [255, 128, 0]]

        for color in colors:
            for blink_mode in PingboardKeyState.BLINK_MODE:
                for blink_color in colors:
                    st = PingboardKeyState()
                    st.color = color
                    st.blink_mode = blink_mode
                    st.blink_color = blink_color

                    # assert that values are equal to settings
                    assert st.color == color
                    assert st.blink_mode == blink_mode
                    assert st.blink_color == blink_color

                    for idx in range(0, 4):
                        assert st.as_key_configuration(idx) == {
                            "idx": idx,
                            "color": color
                        }

                        assert st.as_blink_configuration(idx) == {
                            "idx": idx,
                            "mode": blink_mode,
                            "color": blink_color
                        }

    def test_equals(self):
        st1 = PingboardKeyState()
        st2 = PingboardKeyState()

        assert st1 == st2

    def test_not_equals(self):
        # unequal color
        st1 = PingboardKeyState()
        st2 = PingboardKeyState()
        st2.color = [1] * 3
        assert not (st1 == st2)
        assert st1 != st2

        # unequal blink mode
        st1 = PingboardKeyState()
        st2 = PingboardKeyState()
        st2.blink_mode = "ON"
        assert not (st1 == st2)
        assert st1 != st2

        # unequal blink color
        st1 = PingboardKeyState()
        st2 = PingboardKeyState()
        st2.blink_color = [1] * 3
        assert not (st1 == st2)
        assert st1 != st2

    def test_not_equals_others(self):
        assert not (PingboardKeyState() == "")


class TestPingboardState:
    def test_init(self):
        st = PingboardState()

        assert st.keys == [PingboardKeyState()] * 4
        assert st.brightness == 255

    def test_as_configuration(self):
        st = PingboardState()

        assert st.as_configuration() == {
            'configuration': {
                'blink': [{'color': [0, 0, 0], 'idx': 1, 'mode': 'OFF'},
                          {'color': [0, 0, 0], 'idx': 2, 'mode': 'OFF'},
                          {'color': [0, 0, 0], 'idx': 3, 'mode': 'OFF'},
                          {'color': [0, 0, 0], 'idx': 4, 'mode': 'OFF'}],
                'brightness': 255,
                'keys': [{'color': [0, 0, 0], 'idx': 1},
                         {'color': [0, 0, 0], 'idx': 2},
                         {'color': [0, 0, 0], 'idx': 3},
                         {'color': [0, 0, 0], 'idx': 4}]
            }
        }

    def test_equals(self):
        st1 = PingboardState()
        st2 = PingboardState()

        assert st1 == st2

    def test_not_equals(self):
        st1 = PingboardState()
        st2 = PingboardState()
        st2.brightness = 128

        assert not (st1 == st2)
        assert st1 != st2

    def test_not_equals_others(self):
        assert not (PingboardState() == "")


class MockPort(object):
    def __init__(self, description, device):
        self.description = description
        self.device = device

    def __str__(self):
        return self.device


def setup_serial_write_mock(serial_mock, result=True):
    def write(command):
        serial_mock.command = command
        return result

    serial_mock.side_effect = write


class TestPingboardSerial:
    def test_init_with_pingboard(self, caplog):
        with caplog.at_level(logging.INFO):
            with mock.patch.object(serial.tools.list_ports, 'comports') as ports_mock:
                arduino_port = MockPort("Arduino Micro", "/dev/mock")
                ports_mock.return_value = [
                    MockPort("foo1", None),
                    arduino_port,
                    MockPort("foo2", None)
                ]

                ser = PingboardSerial()

                assert ser._port == arduino_port

                assert len(caplog.records) == 1
                assert caplog.records[-1].message == \
                       "Found Pingboard arduino serial port at /dev/mock"

                status, healthy = ser.get_health()
                assert healthy
                assert status == {
                    'healthy': True,
                    'name': 'Arduino Micro',
                    'path': '/dev/mock'
                }

    def test_init_without_pingboard(self, caplog):
        with caplog.at_level(logging.INFO):
            with mock.patch.object(serial.tools.list_ports, 'comports') as ports_mock:
                ports_mock.return_value = [
                    MockPort("foo1", None),
                    MockPort("foo2", None)
                ]

                ser = PingboardSerial()

                assert ser._port is None

                assert len(caplog.records) == 1
                assert caplog.records[-1].message == \
                       "Pingboard arduino serial port could not be found!"

                status, healthy = ser.get_health()
                assert not healthy
                assert status == {
                    'healthy': False
                }

    @staticmethod
    def create_serial():
        with mock.patch.object(serial.tools.list_ports, 'comports') as ports_mock:
            ports_mock.return_value = [
                MockPort("Arduino Micro", "/dev/mock")
            ]
            return PingboardSerial()

    def test_brightness(self):
        with mock.patch.object(PingboardSerial, '_write') as serial_mock:
            setup_serial_write_mock(serial_mock)

            ser = TestPingboardSerial.create_serial()

            assert ser.brightness(0)
            assert serial_mock.command == "DIM 000\n"

            assert ser.brightness(12)
            assert serial_mock.command == "DIM 012\n"

            assert ser.brightness(128)
            assert serial_mock.command == "DIM 128\n"

            assert ser.brightness(255)
            assert serial_mock.command == "DIM 255\n"

            with pytest.raises(TypeError):
                ser.brightness(None)  # type: ignore

    def test_key_color(self):
        with mock.patch.object(PingboardSerial, '_write') as serial_mock:
            setup_serial_write_mock(serial_mock)

            ser = TestPingboardSerial.create_serial()

            assert ser.key_color(1, [0, 0, 0])
            assert serial_mock.command == "COL 1 000 000 000\n"

            # TODO should be an exception
            assert ser.key_color(5, [128, 56, 0])
            assert serial_mock.command == "COL 5 128 056 000\n"

            with pytest.raises(IndexError):
                ser.key_color(1, [128, 56])

    def test_key_blink(self):
        with mock.patch.object(PingboardSerial, '_write') as serial_mock:
            setup_serial_write_mock(serial_mock)

            ser = TestPingboardSerial.create_serial()

            assert ser.key_blink(1, "OFF", [0, 0, 0])
            assert serial_mock.command == "BLNK 1 OFF 000 000 000\n"

            # TODO should be an exception
            assert ser.key_blink(1, None, [0, 0, 0])  # type: ignore
            assert serial_mock.command == "BLNK 1 None 000 000 000\n"

            # TODO should be an exception
            assert ser.key_blink(1, "Something", [0, 0, 0])  # type: ignore
            assert serial_mock.command == "BLNK 1 Something 000 000 000\n"

            # TODO should be an exception
            assert ser.key_blink(5, "SINGLE", [128, 56, 0])
            assert serial_mock.command == "BLNK 5 SINGLE 128 056 000\n"

            with pytest.raises(IndexError):
                ser.key_blink(1, "ON", [128, 56])

    # TODO test write with serial mock


class MockPingboardSerial(PingboardSerial):
    def __init__(self):
        super().__init__()

        self.commands = list()
        self.write_result = True

    def scan_port(self):
        self._port = MockPort("Arduino Micro", "/dev/mock")

    def _write(self, command: str) -> bool:
        self.commands.append(command)

        return self.write_result


class TestMockPingboardSerial:
    def test_init(self):
        serial_mock = MockPingboardSerial()
        assert serial_mock._port is not None

    def test_write(self):
        serial_mock = MockPingboardSerial()

        assert serial_mock.commands == []

        serial_mock._write("foo")
        assert serial_mock.commands == ["foo"]

        serial_mock._write("bar")
        assert serial_mock.commands == ["foo", "bar"]


class TestPingboardConfiguration:
    def test_empty_init(self):
        with pytest.raises(ValueError) as e:
            PingboardConfiguration(None)  # type: ignore

        assert "Must provide a pingboard serial handler!" in str(e.value)

    def test_init(self):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        assert cfg._serial == serial_mock
        assert cfg._state is None
        assert cfg._cfg_handlers == {
            "brightness": cfg._cfg_brightness,
            "keys": cfg._cfg_keys,
            "blink": cfg._cfg_blink
        }

    def test_push_empty_config(self):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        cfg.push_config()

        assert serial_mock.commands == []

    def test_on_configuration_none(self):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        with pytest.raises(ValueError) as e:
            cfg.on_configuration(None)

        assert "Configuration must be provided!" in str(e.value)

    def test_on_configuration_missing_structure(self, caplog):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        cfg.on_configuration({})

        assert cfg._state is None
        assert serial_mock.commands == []

        assert len(caplog.records) == 1
        assert caplog.records[-1].message == \
               "Could not find configuration part in snippet!"

    def test_on_configuration_invalid_key(self, caplog):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        cfg.on_configuration({"configuration": {
            "brightness": 0,
            "foo": 1,
            "keys": [
                {
                    "idx": 1,
                    "color": [
                        255,
                        255,
                        255
                    ]
                }]
        }})

        st = PingboardState()
        st.brightness = 0
        st.keys[0].color = [255]*3
        assert cfg._state == st

        assert serial_mock.commands == [
            'DIM 000\n',
            'COL 1 255 255 255\n'
        ]

        assert len(caplog.records) == 1
        assert caplog.records[-1].message == \
               "Invalid configuration snippet: 'foo'"

    def test_on_configuration_only_invalid(self, caplog):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        cfg.on_configuration({"configuration": {
            "foo": 1,
        }})

        assert cfg._state is None
        assert serial_mock.commands == []

        assert len(caplog.records) == 1
        assert caplog.records[-1].message == \
               "Invalid configuration snippet: 'foo'"

    def test_on_configuration_generic(self):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        st = PingboardState()

        cfg.on_configuration(st.as_configuration())

        assert cfg._state == st

        assert serial_mock.commands == [
            'DIM 255\n',
            'COL 1 000 000 000\n',
            'COL 2 000 000 000\n',
            'COL 3 000 000 000\n',
            'COL 4 000 000 000\n',
            'BLNK 1 OFF 000 000 000\n',
            'BLNK 2 OFF 000 000 000\n',
            'BLNK 3 OFF 000 000 000\n',
            'BLNK 4 OFF 000 000 000\n'
        ]

    def test_on_configuration_all(self):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        st = PingboardState()
        st.brightness = 1
        st.keys[1].color = [2, 3, 4]
        st.keys[2].blink_mode = "SINGLE"
        st.keys[2].blink_color = [128] * 3
        st.keys[3].blink_mode = "SHORT"

        cfg.on_configuration(st.as_configuration())

        # Single blink should be stored as off
        st.keys[2].blink_mode = "OFF"
        assert cfg._state == st
        
        assert serial_mock.commands == [
            'DIM 001\n',
            'COL 1 000 000 000\n',
            'COL 2 002 003 004\n',
            'COL 3 000 000 000\n',
            'COL 4 000 000 000\n',
            'BLNK 1 OFF 000 000 000\n',
            'BLNK 2 OFF 000 000 000\n',
            'BLNK 3 SINGLE 128 128 128\n',
            'BLNK 4 SHORT 000 000 000\n'
        ]

    def test_get_configuration_empty(self):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        assert cfg.get_configuration() == PingboardState().as_configuration()

    def test_get_configuration_value(self):
        serial_mock = MockPingboardSerial()
        cfg = PingboardConfiguration(serial_mock)

        cfg._cfg_brightness(123)
        # test only this because all values should come via on_configuration

        assert cfg.get_configuration() == {
            'configuration': {'blink': [{'color': [0, 0, 0], 'idx': 1, 'mode': 'OFF'},
                                        {'color': [0, 0, 0], 'idx': 2, 'mode': 'OFF'},
                                        {'color': [0, 0, 0], 'idx': 3, 'mode': 'OFF'},
                                        {'color': [0, 0, 0], 'idx': 4, 'mode': 'OFF'}],
                              'brightness': 123,
                              'keys': [{'color': [0, 0, 0], 'idx': 1},
                                       {'color': [0, 0, 0], 'idx': 2},
                                       {'color': [0, 0, 0], 'idx': 3},
                                       {'color': [0, 0, 0], 'idx': 4}]}
        }
