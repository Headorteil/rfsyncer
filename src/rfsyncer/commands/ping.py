import logging
from multiprocessing import Semaphore
from multiprocessing.queues import Queue as QueueType
from typing import Any

from rfsyncer.ssh.connector import Connector
from rfsyncer.util.config import RfsyncerConfig
from rfsyncer.util.display import mp_log


def ping(
    queue: QueueType[Any],
    config: RfsyncerConfig,
    semaphore: Semaphore,  # pyright: ignore[reportInvalidTypeForm, reportUnknownParameterType]
    host: str,
    insecure: bool,
    sudo: bool = False,
    keep: bool = False,
    **_: Any,  # noqa: ANN401
) -> Connector | None:
    print_infos = (queue, host, None, None)
    try:
        with semaphore:
            ssh = Connector(config, insecure=insecure, sudo=sudo)
            ssh.connect(host)
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
                    *print_infos,
                    "Aborting target : Execution error (%s)",
                    stderr,
                )
                return None
            ssh.host_config["real_hostname"] = stdout
            print_infos = (
                queue,
                ssh.host_config["hostname"],
                ssh.host_config["user"],
                ssh.host_config["real_hostname"],
            )
            mp_log(  # pyright: ignore[reportArgumentType]
                logging.INFO,
                *print_infos,
                "Connectivity OK",
            )
            return ssh
    except Exception as e:  # noqa: BLE001
        mp_log(  # pyright: ignore[reportArgumentType]
            logging.ERROR,
            *print_infos,
            "Error : %s",
            str(e),
            stop=True,
        )
        return None
