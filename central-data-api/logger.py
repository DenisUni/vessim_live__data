import logging
import os
from datetime import datetime
from typing import Optional

from utilities import load_config

# This pre-logger is only used for error messages before full initialization
pre_formatter = logging.Formatter("%(asctime)s %(levelname)s CONFIG: %(message)s")
pre_handler = logging.StreamHandler()
pre_handler.setFormatter(pre_formatter)
pre_logger = logging.getLogger(__name__)
pre_logger.addHandler(pre_handler)


def convert_log_level(string):
    log_levels = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL
    }
    if string.lower() in log_levels:
        return log_levels[string.lower()]
    else:
        pre_logger.error(f"KeyError: {string} is not a valid logging level")
        pre_logger.error(f"Valid levels are: DEBUG, INFO, WARNING, ERROR, CRITICAL")
        raise KeyError


def setup_logger(name: str, display_name: str = None, app_config: Optional[dict] = None) -> logging.Logger:
    """Creates a configured logger that writes to a dated file and console."""
    if not app_config:
        try:
            app_config, _ = load_config()
        except Exception:
            app_config = {}

    if display_name is None:
        display_name = name

    log_level_file = convert_log_level(app_config.get("log_level_file", "INFO"))
    log_level_console = convert_log_level(app_config.get("log_level_console", "INFO"))
    log_folder = app_config.get("log_folder", "logs")

    os.makedirs(log_folder, exist_ok=True)
    log_filename = os.path.join(log_folder, datetime.now().strftime("%Y-%m-%d.log"))

    logger = logging.getLogger(name)

    # Remove all existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    # Create a formatter for this logger
    formatter = logging.Formatter(
        f'%(asctime)s,%(msecs)03d %(levelname)s {display_name}: %(message)s',
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Create a console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level_console)
    console_handler.setFormatter(formatter)

    # Create file handler
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(log_level_file)
    file_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    # Set level (DEBUG for maximum detail, filtering via handler level)
    logger.setLevel(logging.DEBUG)

    # Stop propagation (prevents duplicate logs from the root logger)
    logger.propagate = False

    return logger

