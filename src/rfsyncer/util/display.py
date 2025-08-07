import pydoc
from logging import Logger
from typing import Any

from rich.console import Console
from rich.pager import Pager
from rich.progress import Progress

from rfsyncer.util.consts import PROGRESS_WIDGETS
from rfsyncer.util.logger import get_null_logger


class LessPager(Pager):
    def _pager(self, content: str) -> None:
        pydoc.pipepager(content, "less -S +g -R")

    def show(self, content: str) -> None:
        self._pager(content)


class Display:
    def __init__(
        self,
        logger: Logger | None,
        console: Console | None,
        display: bool,
        pager: bool,
        debug: bool,
        live: bool,
    ) -> None:
        display_logger = get_null_logger() if logger is None else logger
        if console is None:
            display_console = Console(quiet=True)
            display_live_console = display_console
        else:
            display_console = console
            display_live_console = display_console if live else Console(quiet=True)

        self.progress = Progress(
            *PROGRESS_WIDGETS,
            transient=True,
            console=display_live_console,
        )

        self.logger = display_logger
        self.console = display_console
        self.display = display
        self.pager = pager
        self.debug = debug
        self.live = live

    def print_page(self, obj: Any) -> None:  # noqa: ANN401
        if not self.display:
            return
        pager_console = Console(width=1000)
        tab_width = (
            sum(obj._calculate_column_widths(pager_console, pager_console.options))  # noqa: SLF001
            + obj._extra_width  # noqa: SLF001
        )
        too_large = tab_width > self.console.options.max_width
        if self.pager and too_large:
            self.logger.info("Table too large, printing it in less")
            with pager_console.pager(styles=True, pager=LessPager()):
                pager_console.print(obj)
        else:
            obj.expand = True
            if too_large:
                self.console.print(
                    'Table too large, you should enable pager with "rfsyncer -P"',
                )
            self.console.print(obj)
