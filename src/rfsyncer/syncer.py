import signal
import time
from collections.abc import Callable
from copy import deepcopy
from logging import Logger
from multiprocessing import Manager, Process, Queue, Semaphore
from multiprocessing.managers import DictProxy
from multiprocessing.queues import Queue as QueueType
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from rfsyncer.commands.clear import clear
from rfsyncer.commands.diff import diff_proxy
from rfsyncer.commands.ping import ping
from rfsyncer.util.config import RfsyncerConfig
from rfsyncer.util.consts import (
    HOST_COLOR,
)
from rfsyncer.util.display import Display
from rfsyncer.util.types import FileFuture, map_file_color


class Syncer:
    def __init__(
        self,
        config: RfsyncerConfig,
        console: Console | None = None,
        display: bool = True,
        live: bool = True,
        pager: bool = False,
        logger: Logger | None = None,
        debug: bool = False,
        processes: int = 4,
    ) -> None:
        self.config = config
        self.display = Display(logger, console, display, pager, debug, live)
        self.semaphore = Semaphore(processes)
        self.stop = False
        self.default_hosts = []
        for host, host_dict in self.config.hosts.items():
            if host_dict.get("enabled", True):
                self.default_hosts.append(host)

    def queue_loop(self, queue: QueueType[Any]) -> None:
        elem = queue.get()
        match elem["type"]:
            case "log":
                self.display.logger.log(
                    elem["level"],
                    elem["message"],
                    *elem["args"],
                )
                if elem["exception"]:
                    self.stop = True
                    if self.display.debug:
                        self.display.console.print(elem["exception"])
            case "print":
                printable = elem["text"]
                if isinstance(printable, Panel) and not self.display.display:
                    to_print = Text("[")
                    to_print.append_text(printable.title)  # pyright: ignore[reportArgumentType]
                    to_print.append("] ")
                    to_print.append_text(printable.subtitle)  # pyright: ignore[reportArgumentType]
                    self.display.console.print(to_print)
                    return
                self.display.console.print(elem["text"])
            case _:
                raise NotImplementedError

    def run_tasks(
        self,
        task_desc: str,
        func: Callable[..., Any],
        args_list: list[tuple[Any, ...]] | None = None,
        kwargs_list: list[dict[str, Any]] | None = None,
    ) -> DictProxy[str, Any] | None:
        processes: list[Process] = []

        if args_list and not kwargs_list:
            kwargs_list = [{}] * len(args_list)
        if kwargs_list and not args_list:
            args_list = [()] * len(kwargs_list)

        def handler(_: Any, __: Any) -> None:  # noqa: ANN401
            self.stop = True

        signal.signal(signal.SIGINT, handler)

        with self.display.progress:
            global_task = self.display.progress.add_task(
                f"[blue]{task_desc}[/blue]",
                total=len(args_list),  # pyright: ignore[reportArgumentType]
            )
            with Manager() as manager:
                progress_ = manager.dict()
                queue = Queue()
                return_dict = manager.dict()

                for args, kwargs in zip(args_list, kwargs_list, strict=True):  # pyright: ignore[reportArgumentType]
                    host_task = self.display.progress.add_task(
                        "",
                        visible=False,
                    )
                    file_task = self.display.progress.add_task(
                        "",
                        visible=False,
                    )
                    processes.append(
                        Process(
                            target=func,
                            args=(
                                queue,
                                self.config,
                                self.semaphore,
                                *args,
                            ),
                            kwargs={
                                "progress": progress_,
                                "task": host_task,
                                "file_task": file_task,
                                "return_dict": return_dict,
                                **kwargs,
                            },
                        ),
                    )
                    processes[-1].start()

                while (
                    n_finished := sum([not process.is_alive() for process in processes])
                ) < len(processes):
                    while not queue.empty():
                        self.queue_loop(queue)

                    if self.stop:
                        self.display.logger.error("Terminate processes")
                        self.display.progress.remove_task(
                            global_task,
                        )
                        for task_id in progress_:
                            self.display.progress.remove_task(
                                task_id,
                            )
                        for process in processes:
                            process.terminate()
                        for _ in range(200):
                            if sum([process.is_alive() for process in processes]) == 0:
                                return None
                            time.sleep(0.01)
                        self.display.logger.error("Killing processes")
                        for process in processes:
                            process.kill()
                        for _ in range(100):
                            if sum([process.is_alive() for process in processes]) == 0:
                                return None
                            time.sleep(0.01)
                        return None

                    self.display.progress.update(
                        global_task,
                        completed=n_finished,
                    )
                    for task_id, update_data in progress_.items():
                        latest = update_data["progress"]
                        total = update_data["total"]
                        description = update_data["description"]
                        self.display.progress.update(
                            task_id,
                            description=description,
                            completed=latest,
                            total=total,
                            visible=latest < total,
                        )
                    time.sleep(0.1)

                # Just to be sure
                for process in processes:
                    process.join()

                while not queue.empty():
                    self.queue_loop(queue)

                to_return = deepcopy(return_dict)

        return to_return

    def ping(
        self, hosts: list[str], insecure: bool = False, sudo: bool = False
    ) -> None:
        if not hosts:
            hosts = self.default_hosts
        self.run_tasks(
            "Testing connectivity",
            ping,
            args_list=[(host, insecure) for host in hosts],
            kwargs_list=[{"sudo": sudo}] * len(hosts),
        )

    def clear(
        self,
        hosts: list[str],
        insecure: bool = False,
    ) -> None:
        if not hosts:
            hosts = self.default_hosts
        self.run_tasks(
            "Clearing all hosts",
            clear,
            args_list=[(host, insecure) for host in hosts],
        )

    def diff(
        self,
        hosts: list[str],
        root: Path,
        insecure: bool = False,
        sudo: bool = False,
        keep: bool = False,
        upload: bool = False,
        install: bool = False,
    ) -> None:
        if not hosts:
            hosts = self.default_hosts
        values = self.run_tasks(
            "Runing on all hosts",
            diff_proxy,
            args_list=[(host, insecure, root) for host in hosts],
            kwargs_list=[
                {"sudo": sudo, "keep": keep, "upload": upload, "install": install}
            ]
            * len(hosts),
        )
        if not values:
            return
        table = Table(title="Files by hosts")
        table.add_column("file", justify="center", no_wrap=True)
        paths = set()
        for host in hosts:
            if host not in values:
                table.add_column(
                    Text(host, style=map_file_color(FileFuture.ERROR)),
                    justify="center",
                    no_wrap=True,
                )
                continue
            host_vals = values[host]
            host_str = Text.assemble(
                "[",
                (
                    f"{host_vals['hostname']} "
                    f"{host_vals['user']}@{host_vals['real_hostname']}",
                    HOST_COLOR,
                ),
                "]",
            )
            table.add_column(host_str, justify="center", no_wrap=True)
            for path in host_vals["paths"].values():
                paths.add(path["r_path"])
        path_list = sorted(paths)
        for r_path in path_list:
            to_add = [str(r_path)]
            for host in hosts:
                if host not in values:
                    to_add.append(
                        Text(FileFuture.ERROR, style=map_file_color(FileFuture.ERROR))  # pyright: ignore[reportArgumentType]
                    )
                    continue
                paths = values[host]["paths"]
                for path in paths.values():
                    if r_path == path["r_path"]:
                        to_add.append(
                            Text(  # pyright: ignore[reportArgumentType]
                                str(path["future"]),
                                style=map_file_color(path["future"]),
                            )
                        )
                        break
                else:
                    to_add.append(
                        Text(FileFuture.NA, style=map_file_color(FileFuture.NA))  # pyright: ignore[reportArgumentType]
                    )
            table.add_row(*to_add)
        self.display.print_page(table)
