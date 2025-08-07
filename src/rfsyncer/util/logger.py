import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from rfsyncer.util.exceptions import HandledError


def get_logger(console: Console, level: int, debug: bool) -> logging.Logger:
    logger = logging.getLogger("rfsyncer")
    logger.setLevel(logging.DEBUG)
    handler = RichHandler(
        show_path=debug,
        rich_tracebacks=debug,
        console=console,
        omit_repeated_times=False,
        tracebacks_show_locals=debug,
    )
    logger.propagate = False
    logger.addHandler(handler)

    match level:
        case 0:
            handler.setLevel(60)
        case 1:
            handler.setLevel(logging.WARNING)
        case 2:
            handler.setLevel(logging.INFO)
        case 3:
            handler.setLevel(logging.DEBUG)
        case _:
            errmsg = "Invalid logging level"
            raise HandledError(errmsg)

    return logger


def add_file_handler(logger: logging.Logger, file: Path) -> None:
    file_handler = RotatingFileHandler(file, "a", 1000000, 10)
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter("{asctime:<23} {levelname:<8} {message}", style="{")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def get_null_logger() -> logging.Logger:
    logger = logging.getLogger("rfsyncer")
    logger.addHandler(logging.NullHandler())
    return logger
