"""Logging configuration for USB/IP s6 scripts.

Maps Home Assistant log levels to Python logging levels and configures
output to stdout so s6-overlay captures it.
"""

import logging
import sys

# Home Assistant → Python logging level mapping
# 'notice' maps to INFO (Python has no NOTICE level)
HA_LOG_LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}

_SETUP_HANDLER_MARKER = "_usbip_logging_setup_handler"


def _configure_logger(logger: logging.Logger, level: int) -> None:
    """Configure one logger for s6 stdout without duplicate handlers."""
    logger.setLevel(level)
    logger.propagate = False

    owned_handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, _SETUP_HANDLER_MARKER, False) is True
    ]
    if owned_handlers:
        owned_handler = owned_handlers[0]
        for duplicate in owned_handlers[1:]:
            logger.removeHandler(duplicate)
            duplicate.close()
    else:
        owned_handler = logging.StreamHandler(sys.stdout)
        setattr(owned_handler, _SETUP_HANDLER_MARKER, True)
        logger.addHandler(owned_handler)

    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    owned_handler.setFormatter(formatter)

    for handler in logger.handlers:
        handler.setLevel(level)


def setup_logging(level_name: str = "info", name: str = "usbip") -> logging.Logger:
    """Configure and return a logger for s6 scripts.

    Args:
        level_name: HA log level string (trace/debug/info/notice/warning/error/fatal).
        name: Logger name (used as prefix in log output).

    Returns:
        Configured logger instance.
    """
    level = HA_LOG_LEVELS.get(level_name.lower(), logging.INFO)
    logger = logging.getLogger(name)
    _configure_logger(logger, level)
    _configure_logger(logging.getLogger("usbip"), level)

    return logger
