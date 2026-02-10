"""Unit tests for usbip_lib.logging_setup module."""

import logging

import pytest

from usbip_lib.logging_setup import HA_LOG_LEVELS, setup_logging


class TestSetupLogging:
    @pytest.mark.parametrize(
        "ha_level,py_level",
        [
            ("trace", logging.DEBUG),
            ("debug", logging.DEBUG),
            ("info", logging.INFO),
            ("notice", logging.INFO),
            ("warning", logging.WARNING),
            ("error", logging.ERROR),
            ("fatal", logging.CRITICAL),
        ],
    )
    def test_level_mapping(self, ha_level, py_level):
        logger = setup_logging(ha_level, name=f"test_{ha_level}")
        assert logger.level == py_level

    def test_returns_logger(self):
        logger = setup_logging("info", name="test_returns")
        assert isinstance(logger, logging.Logger)

    def test_has_handler(self):
        logger = setup_logging("info", name="test_handler")
        assert len(logger.handlers) >= 1

    def test_no_duplicate_handlers(self):
        name = "test_no_dup"
        logger = setup_logging("info", name=name)
        count1 = len(logger.handlers)
        logger = setup_logging("debug", name=name)
        count2 = len(logger.handlers)
        assert count1 == count2

    def test_output_format(self, capsys):
        logger = setup_logging("info", name="test_fmt")
        logger.info("Hello world")
        captured = capsys.readouterr()
        assert "[test_fmt]" in captured.out
        assert "INFO" in captured.out
        assert "Hello world" in captured.out

    def test_unknown_level_defaults_to_info(self):
        logger = setup_logging("nonexistent_level", name="test_unknown")
        assert logger.level == logging.INFO
