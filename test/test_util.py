"""Unit tests for the util module"""

#import logging
#from unittest import mock
import pytest

import util

@pytest.mark.parametrize("val", ["y", "yes", "t", "true", "on", "1", "Y", "YES", "True"])
def test_strtobool_true(val):
    assert util.strtobool(val) is True

@pytest.mark.parametrize("val", ["n", "no", "f", "false", "off", "0", "N", "NO", "False"])
def test_strtobool_false(val):
    assert util.strtobool(val) is False

def test_strtobool_invalid():
    with pytest.raises(ValueError):
        util.strtobool("maybe")
