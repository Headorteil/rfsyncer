import logging
from multiprocessing import Semaphore
from multiprocessing.queues import Queue as QueueType
from typing import Any

from rfsyncer.ssh.connector import Connector
from rfsyncer.util.config import RfsyncerConfig
from rfsyncer.util.display import mp_log
from rfsyncer.util.exceptions import HandledError


def ping(
    config: RfsyncerConfig,
    semaphore: Semaphore,  # pyright: ignore[reportInvalidTypeForm, reportUnknownParameterType]
    queue: QueueType[Any],
    host: str,
    insecure: bool,
    sudo: bool = False,
    keep: bool = False,
    **_: Any,  # noqa: ANN401
) -> Connector | None:
    with semaphore:
        ssh = Connector(config, insecure=insecure, sudo=sudo)
        try:
            ssh.connect(host)
        except HandledError as e:
            mp_log(
                logging.ERROR,
                queue,
                ssh.host_config["hostname"],  # pyright: ignore[reportArgumentType]
                ssh.host_config["user"],  # pyright: ignore[reportArgumentType]
                None,
                "Aborting target : %s",
                e,
            )
            return None
        if ssh.host_config["sudo"]:
            try:
                ssh.set_askpass()
                stdout, stderr = ssh.exec("hostname")
            finally:
                if not keep:
                    ssh.del_askpass()
        else:
            stdout, stderr = ssh.exec("hostname")

        if stderr:
            mp_log(
                logging.ERROR,
                queue,
                ssh.host_config["hostname"],  # pyright: ignore[reportArgumentType]
                ssh.host_config["user"],  # pyright: ignore[reportArgumentType]
                None,
                "Aborting target : Execution error (%s)",
                stderr,
            )
            return None
        ssh.host_config["real_hostname"] = stdout
        mp_log(
            logging.INFO,
            queue,
            ssh.host_config["hostname"],  # pyright: ignore[reportArgumentType]
            ssh.host_config["user"],  # pyright: ignore[reportArgumentType]
            ssh.host_config["real_hostname"],  # pyright: ignore[reportArgumentType]
            "Connectivity OK",
        )
        return ssh
