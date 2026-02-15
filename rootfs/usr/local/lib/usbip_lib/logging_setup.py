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
    logger.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        # Update existing handler levels
        for h in logger.handlers:
            h.setLevel(level)

    return logger
