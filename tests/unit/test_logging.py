"""Unit tests for usbip_lib.logging_setup module."""

import logging
import re
import sys

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

    def test_configures_shared_usbip_logger_without_duplicates(self):
        service = logging.getLogger("monitor_test")
        shared = logging.getLogger("usbip")
        original_service_state = (
            list(service.handlers),
            service.level,
            service.propagate,
        )
        original_shared_state = (
            list(shared.handlers),
            shared.level,
            shared.propagate,
        )
        try:
            service.handlers.clear()
            shared.handlers.clear()

            configured = setup_logging("debug", name="monitor_test")
            first_count = len(shared.handlers)
            setup_logging("info", name="monitor_test")

            assert first_count == 1
            assert len(shared.handlers) == 1
            assert shared.level == logging.INFO
            assert configured.propagate is False
            assert shared.propagate is False
            assert (
                shared.handlers[0].formatter._fmt
                == configured.handlers[0].formatter._fmt
            )
        finally:
            service.handlers[:] = original_service_state[0]
            service.setLevel(original_service_state[1])
            service.propagate = original_service_state[2]
            shared.handlers[:] = original_shared_state[0]
            shared.setLevel(original_shared_state[1])
            shared.propagate = original_shared_state[2]

    def test_adds_stdout_handler_while_preserving_unrelated_handlers(self):
        service = logging.getLogger("monitor_unrelated_test")
        shared = logging.getLogger("usbip")
        original_service_state = (
            list(service.handlers),
            service.level,
            service.propagate,
        )
        original_shared_state = (
            list(shared.handlers),
            shared.level,
            shared.propagate,
        )
        service_unrelated = logging.NullHandler()
        shared_unrelated = logging.NullHandler()
        try:
            service.handlers[:] = [service_unrelated]
            shared.handlers[:] = [shared_unrelated]

            setup_logging("debug", name="monitor_unrelated_test")
            setup_logging("warning", name="monitor_unrelated_test")

            for logger, unrelated in (
                (service, service_unrelated),
                (shared, shared_unrelated),
            ):
                stdout_handlers = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.StreamHandler)
                    and handler.stream is sys.stdout
                ]

                assert logger.handlers.count(unrelated) == 1
                assert len(logger.handlers) == 2
                assert len(stdout_handlers) == 1
                assert logger.level == logging.WARNING
                assert stdout_handlers[0].level == logging.WARNING
                assert unrelated.level == logging.WARNING
                assert logger.propagate is False
                assert stdout_handlers[0].formatter is not None
                assert stdout_handlers[0].formatter._fmt == (
                    "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
                )
                assert stdout_handlers[0].formatter.datefmt == "%H:%M:%S"
        finally:
            service.handlers[:] = original_service_state[0]
            service.setLevel(original_service_state[1])
            service.propagate = original_service_state[2]
            shared.handlers[:] = original_shared_state[0]
            shared.setLevel(original_shared_state[1])
            shared.propagate = original_shared_state[2]

    def test_output_format(self, capsys):
        logger = setup_logging("info", name="test_fmt")
        logger.info("Hello world")
        captured = capsys.readouterr()
        assert re.search(r"^\d{2}:\d{2}:\d{2} ", captured.out)
        assert "[test_fmt]" in captured.out
        assert "INFO" in captured.out
        assert "Hello world" in captured.out

    def test_formatter_uses_hh_mm_ss_datefmt(self):
        logger = setup_logging("info", name="test_datefmt")
        formatter = logger.handlers[0].formatter
        assert formatter is not None
        assert formatter.datefmt == "%H:%M:%S"

    def test_unknown_level_defaults_to_info(self):
        logger = setup_logging("nonexistent_level", name="test_unknown")
        assert logger.level == logging.INFO
