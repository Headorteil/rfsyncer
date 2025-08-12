import logging
from multiprocessing import Semaphore
from multiprocessing.queues import Queue as QueueType
from shlex import quote
from typing import Any

from rfsyncer.commands.ping import ping
from rfsyncer.ssh.connector import Connector
from rfsyncer.util.config import RfsyncerConfig
from rfsyncer.util.consts import (
    ASKPASS_PATH,
    REMOTE_TEMP_DIR,
)
from rfsyncer.util.display import mp_log


def clear(
    config: RfsyncerConfig,
    semaphore: Semaphore,  # pyright: ignore[reportInvalidTypeForm, reportUnknownParameterType]
    queue: QueueType[Any],
    host: str,
    insecure: bool,
    **_: Any,  # noqa: ANN401
) -> Connector | None:
    connector = ping(
        config,
        semaphore,
        queue,
        host,
        insecure,
    )
    if not connector:
        return
    host_config: dict[str, Any] = connector.host_config  # pyright: ignore[reportAssignmentType]
    real_hostname = host_config["real_hostname"]
    user = host_config["user"]
    hostname = host_config["hostname"]
    print_infos = (queue, hostname, user, real_hostname)

    with semaphore:
        _, stderr = connector.exec(f"rm -rf {quote(str(REMOTE_TEMP_DIR))}")  # pyright: ignore[reportAssignmentType]
        if not stderr:
            mp_log(
                logging.INFO,
                *print_infos,
                "Temporary dir clear OK",
            )
        else:
            mp_log(
                logging.ERROR,
                *print_infos,
                "Temporary dir clear NOK : %s",
                stderr,
            )

        _, stderr = connector.exec(f"rm -rf {quote(str(ASKPASS_PATH))}")  # pyright: ignore[reportAssignmentType]
        if not stderr:
            mp_log(
                logging.INFO,
                *print_infos,
                "Askpass clear OK",
            )
        else:
            mp_log(
                logging.ERROR,
                *print_infos,
                "Askpass clear NOK : %s",
                stderr,
            )
