from multiprocessing.queues import Queue
from typing import Any

from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from rfsyncer.util.consts import (
    HOST_COLOR,
)


def mp_print(
    queue: Queue[Any],
    host: str,
    user: str,
    hostname: str,
    message: Text | Syntax | str,
    panel: bool = False,
    subtitle: Text | str = "",
) -> None:
    if panel:
        queue.put(
            {
                "type": "print",
                "text": Panel(
                    message,
                    subtitle=subtitle,
                    title=Text(f"{host} {user}@{hostname}", style=HOST_COLOR),
                ),
            },
        )
        return
    queue.put(
        {
            "type": "print",
            "text": Text.assemble(
                "[",
                (f"{host} {user}@{hostname}", HOST_COLOR),
                "] ",
            )
            + message,
        },
    )


def mp_log(
    level: int,
    queue: Queue[Any],
    host: str,
    user: str,
    hostname: str | None,
    message: str,
    *args: Any,  # noqa: ANN401
) -> None:
    if hostname:
        queue.put(
            {
                "type": "log",
                "level": level,
                "message": f"[%s %s@%s] {message}",
                "args": [host, user, hostname, *args],
            },
        )
        return
    queue.put(
        {
            "type": "log",
            "level": level,
            "message": f"[%s@%s] {message}",
            "args": [user, host, *args],
        },
    )
