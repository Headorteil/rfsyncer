import contextlib
import logging
from copy import deepcopy
from multiprocessing import Semaphore
from multiprocessing.managers import DictProxy
from multiprocessing.queues import Queue as QueueType
from pathlib import Path
from shlex import quote
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

import yaml
from jinja2 import Environment, FileSystemLoader
from rich.console import Group
from rich.progress import TaskID
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text
from rich.traceback import Traceback

from rfsyncer.commands.ping import ping
from rfsyncer.util.config import RfsyncerConfig
from rfsyncer.util.consts import (
    DEFAULT_FILE_CONFIG,
    HOST_COLOR,
    MAX_DIFF_SIZE,
    REMOTE_TEMP_DIR,
    RFSYNCER_PREFIX,
)
from rfsyncer.util.display import mp_log, mp_print
from rfsyncer.util.exceptions import HandledError
from rfsyncer.util.hash import hash_
from rfsyncer.util.types import FileFuture, map_file_color

if TYPE_CHECKING:
    from paramiko.sftp_client import SFTPClient


def diff_proxy(queue: QueueType[Any], *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
    diff = DiffApp(queue, *args, **kwargs)
    diff()


class DiffApp:
    def __init__(
        self,
        queue: QueueType[Any],
        config: RfsyncerConfig,
        semaphore: Semaphore,  # pyright: ignore[reportInvalidTypeForm, reportUnknownParameterType]
        host: str,
        insecure: bool,
        root: Path,
        sudo: bool = False,
        keep: bool = False,
        upload: bool = False,
        install: bool = False,
        progress: DictProxy[Any, Any] | None = None,
        task: TaskID | None = None,
        file_task: TaskID | None = None,
        return_dict: DictProxy[str, Any] | None = None,
    ) -> None:
        self.semaphore = semaphore
        self.return_dict = return_dict
        self.queue = queue

        self.config = config
        self.general_config = config.general

        self.host = host
        self.insecure = insecure
        self.sudo = sudo
        self.root = root

        self.keep = keep
        self.upload = upload
        self.install = install

        self.progress = progress
        self.task = task
        self.file_task = file_task

        self.jinja_env = Environment(  # noqa: S701
            loader=FileSystemLoader(self.root.parent), keep_trailing_newline=True
        )
        self.hook = {}
        self.print_infos = (
            self.queue,
            self.host,
            None,
            None,
        )

    def connect(self) -> None:
        self.connector = ping(
            self.queue,
            self.config,
            self.semaphore,
            self.host,
            self.insecure,
            sudo=self.sudo,
            keep=True,
        )

        if not self.connector:
            return

        self.sftp: SFTPClient = self.connector.sftp  # pyright: ignore[reportAssignmentType, reportAttributeAccessIssue]
        self.host_config: dict[str, Any] = self.connector.host_config  # pyright: ignore[reportAssignmentType, reportAttributeAccessIssue]
        self.sudo = self.host_config["sudo"]

        self.real_hostname = self.host_config["real_hostname"]
        self.user = self.host_config["user"]
        self.hostname = self.host_config["hostname"]

        self.print_infos = (
            self.queue,
            self.hostname,
            self.user,
            self.real_hostname,
        )
        self.host_log = f"{self.hostname} {self.user}@{self.real_hostname}"
        self.host_log_colored = (self.host_log, HOST_COLOR)

    def pre_hooks(self, local_tmpdir: str) -> dict[str, dict[str, str]]:
        to_return = {}

        hooks = self.general_config.get("pre_hooks", [])
        hooks += self.host_config.get("pre_hooks", [])

        env = Environment()  # noqa: S701
        tmpdir_path = Path(local_tmpdir)
        for hook in hooks:
            hook_path = Path(hook.get("path"))
            hook_name = hook.get("name")
            if not hook_path or not hook_name:
                errmsg = "Evry hook must have a 'path' and 'name' field"
                raise HandledError(errmsg)

            template = env.from_string(Path(hook_path).read_text())
            template_out = template.render(
                host=self.host_config, general=self.general_config
            )

            local_hook = tmpdir_path / hook_path.name
            local_hook.write_text(template_out)
            remote_hook = REMOTE_TEMP_DIR / hook_path.name

            mp_log(
                logging.INFO,
                *self.print_infos,
                "Uploading pre hook %s",
                hook_name,
            )

            def callback(transferred: int, total: int) -> None:
                self.progress[self.file_task] = {
                    "progress": transferred,
                    "total": total,
                    "description": Text.assemble(
                        "[",
                        self.host_log_colored,
                        f"] Uploading pre hook {hook_name}",  # noqa: B023
                    ),
                }

            self.sftp.put(
                str(local_hook),
                str(remote_hook),
                callback=callback,
            )

            stdout, stderr = self.connector.exec(f"sh {quote(str(remote_hook))}")
            to_return[hook_name] = {"stdout": stdout, "stderr": stderr}
            mp_print(  # pyright: ignore[reportArgumentType]
                *self.print_infos,
                Group(
                    Syntax(
                        template_out,
                        "bash",
                        line_numbers=True,
                        word_wrap=True,
                    ),
                    Rule(title="Results"),
                    Syntax(
                        f"Stdout :\n{stdout}\nStderr :\n{stderr}",
                        "text",
                        line_numbers=True,
                        word_wrap=True,
                    ),
                ),
                panel=True,
                subtitle=f"Pre hook {hook_name}",
            )
        return to_return

    def post_hooks(self, local_tmpdir: str, return_paths: dict[str, Any]) -> None:
        hooks = self.general_config.get("post_hooks", [])
        hooks += self.host_config.get("post_hooks", [])

        paths = {}
        for l_path, path_dict in return_paths.items():
            paths[str(l_path)] = {
                "remote_path": str(path_dict["r_path"]),
                "state": str(path_dict["future"]),
            }

        env = Environment()  # noqa: S701
        tmpdir_path = Path(local_tmpdir)
        for hook in hooks:
            hook_path = Path(hook.get("path"))
            hook_name = hook.get("name")
            if not hook_path or not hook_name:
                errmsg = "Evry hook must have a 'path' and 'name' field"
                raise HandledError(errmsg)

            template = env.from_string(Path(hook_path).read_text())
            template_out = template.render(
                host=self.host_config,
                general=self.general_config,
                hook=self.hook,
                paths=paths,
            )

            if not self.install:
                mp_print(  # pyright: ignore[reportArgumentType]
                    *self.print_infos,
                    Syntax(
                        template_out,
                        "bash",
                        line_numbers=True,
                        word_wrap=True,
                    ),
                    panel=True,
                    subtitle=f"Post hook {hook_name}",
                )
                continue

            local_hook = tmpdir_path / hook_path.name
            local_hook.write_text(template_out)
            remote_hook = REMOTE_TEMP_DIR / hook_path.name

            mp_log(
                logging.INFO,
                *self.print_infos,
                "Uploading post hook %s",
                hook_name,
            )

            def callback(transferred: int, total: int) -> None:
                self.progress[self.file_task] = {
                    "progress": transferred,
                    "total": total,
                    "description": Text.assemble(
                        "[",
                        self.host_log_colored,
                        f"] Uploading post hook {hook_name}",  # noqa: B023
                    ),
                }

            self.sftp.put(
                str(local_hook),
                str(remote_hook),
                callback=callback,
            )

            stdout, stderr = self.connector.exec(f"sh {quote(str(remote_hook))}")
            mp_print(  # pyright: ignore[reportArgumentType]
                *self.print_infos,
                Group(
                    Syntax(
                        template_out,
                        "bash",
                        line_numbers=True,
                        word_wrap=True,
                    ),
                    Rule(title="Results"),
                    Syntax(
                        f"Stdout :\n{stdout}\nStderr :\n{stderr}",
                        "text",
                        line_numbers=True,
                        word_wrap=True,
                    ),
                ),
                panel=True,
                subtitle=f"Results for post hook {hook_name}",
            )

    def __call__(self) -> None:
        try:
            self.connect()
            if not self.connector:
                return

            tree = {}
            self.gen_files(Path(), tree)
            self.task_total = len(tree) + 1

            mp_log(
                logging.DEBUG,
                *self.print_infos,
                "Host config %s",
                self.host_config,
            )

            return_paths = {}

            with contextlib.suppress(IOError):
                self.sftp.mkdir(str(REMOTE_TEMP_DIR))

            with TemporaryDirectory(
                prefix=f"rfsyncer_{self.hostname}_"
            ) as local_tmpdir:
                self.hook = self.pre_hooks(local_tmpdir)
                for i, (path, path_dict) in enumerate(tree.items()):
                    return_paths[path] = self.diff_file(i, path_dict, local_tmpdir)
                self.post_hooks(local_tmpdir, return_paths)

            self.return_dict[self.host] = {
                "real_hostname": self.real_hostname,
                "hostname": self.hostname,
                "user": self.user,
                "paths": return_paths,
            }
        except Exception as e:  # noqa: BLE001
            mp_log(
                logging.ERROR,
                *self.print_infos,
                str(e),
                exception=Traceback(show_locals=True),
            )
        finally:
            if not self.keep:
                with contextlib.suppress(Exception):
                    self.connector.exec(f"rm -rf {quote(str(REMOTE_TEMP_DIR))}")
                with contextlib.suppress(Exception):
                    self.connector.del_askpass()

            with contextlib.suppress(Exception):
                self.progress[self.task] = {
                    "progress": self.task_total,
                    "total": self.task_total,
                    "description": Text.assemble(
                        "[",
                        self.host_log_colored,
                        "]",
                    ),
                }

    def diff_file(
        self, index: int, path_dict: dict[str, Any], local_tmpdir: str
    ) -> dict[str, Any]:
        file_mode = path_dict["mode"]
        file_config = path_dict["config"]

        if file_config.get("templating") == "j2":
            real_local_path = path_dict["l_path"]
            template = self.jinja_env.get_template(str(real_local_path))
            template_out = template.render(
                host=self.host_config,
                general=self.general_config,
                hook=self.hook,
            )
            local_path = Path(local_tmpdir) / real_local_path.name
            local_path.write_text(template_out)
        else:
            local_path = path_dict["l_path"]
        dest_path = path_dict["r_path"]

        l_hash = None
        if local_path.is_symlink():
            l_type = "symbolic link"
            l_link = local_path.readlink()
        elif local_path.is_dir():
            l_type = "directory"
        elif local_path.is_file():
            l_type = "regular file"
            l_size = local_path.stat().st_size
        else:
            raise NotImplementedError

        with self.semaphore:
            self.progress[self.task] = {
                "progress": index + 1,
                "total": self.task_total,
                "description": Text.assemble(
                    "[",
                    self.host_log_colored,
                    f"] Syncing {dest_path}",
                ),
            }

            mp_log(
                logging.DEBUG,
                *self.print_infos,
                "File dict %s",
                path_dict,
            )

            try:
                r_size, r_type = self.connector.stat(dest_path)
            except PermissionError:
                future = FileFuture.ERROR
                mp_log(
                    logging.WARNING,
                    *self.print_infos,
                    "You do not have sufficient rights to read %s",
                    dest_path,
                )
                return {"r_path": dest_path, "future": future}
            except FileNotFoundError:
                if l_type == "directory":
                    future = FileFuture.CREATE
                    if not self.install:
                        mp_print(  # pyright: ignore[reportArgumentType]
                            *self.print_infos,
                            Text.assemble(
                                "directory ",
                                (str(dest_path), "bold"),
                                " will be ",
                                ("created", f"{map_file_color(future)} bold"),
                            ),
                        )
                    try:
                        self.install_dir(
                            dest_path,
                            file_mode,
                        )
                    except HandledError:
                        return {"r_path": dest_path, "future": FileFuture.ERROR}
                    return {"r_path": dest_path, "future": future}
                if l_type == "symbolic link":
                    future = FileFuture.CREATE
                    if not self.install:
                        mp_print(  # pyright: ignore[reportArgumentType]
                            *self.print_infos,
                            Text.assemble(
                                "symbolic link ",
                                (str(dest_path), "bold"),
                                " will be ",
                                ("created", f"{map_file_color(future)} bold"),
                            ),
                        )
                    try:
                        self.install_symbolic_link(
                            dest_path,
                            l_link,  # pyright: ignore[reportPossiblyUnboundVariable]
                            future,
                        )
                    except HandledError:
                        return {"r_path": dest_path, "future": FileFuture.ERROR}
                    return {"r_path": dest_path, "future": future}
                if l_size > MAX_DIFF_SIZE:  # pyright: ignore[reportPossiblyUnboundVariable]
                    future = FileFuture.CREATE
                    mp_log(
                        logging.DEBUG,
                        *self.print_infos,
                        "file %s it is too heavy, so it won't be displayed",
                        dest_path,
                    )
                    try:
                        self.upload_and_install_file(
                            local_path,
                            l_hash,
                            l_size,  # pyright: ignore[reportPossiblyUnboundVariable]
                            dest_path,
                            index + 1,
                            file_mode,
                            future,
                            forced=True,
                        )
                    except HandledError:
                        return {"r_path": dest_path, "future": FileFuture.ERROR}
                    return {"r_path": dest_path, "future": future}
                try:
                    local_content = local_path.read_text()
                except UnicodeDecodeError:
                    future = FileFuture.CREATE
                    if not self.install:
                        mp_print(  # pyright: ignore[reportArgumentType]
                            *self.print_infos,
                            Text.assemble(
                                "file (binary) ",
                                (str(dest_path), "bold"),
                                " will be ",
                                ("created", f"{map_file_color(future)} bold"),
                            ),
                        )
                    try:
                        self.upload_and_install_file(
                            local_path,
                            l_hash,
                            l_size,  # pyright: ignore[reportPossiblyUnboundVariable]
                            dest_path,
                            index + 1,
                            file_mode,
                            future,
                            forced=True,
                        )
                    except HandledError:
                        return {"r_path": dest_path, "future": FileFuture.ERROR}
                    return {"r_path": dest_path, "future": future}
                if local_content:
                    future = FileFuture.CREATE
                    if self.install:
                        subtitle = Text.assemble(
                            (str(dest_path), "bold"),
                        )
                    else:
                        subtitle = Text.assemble(
                            "file ",
                            (str(dest_path), "bold"),
                            " will be ",
                            ("created", f"{map_file_color(future)} bold"),
                        )
                    mp_print(  # pyright: ignore[reportArgumentType]
                        *self.print_infos,
                        Syntax(
                            local_content,
                            Syntax.guess_lexer(local_path),
                            line_numbers=True,
                            word_wrap=True,
                        ),
                        panel=True,
                        subtitle=subtitle,
                    )
                    try:
                        self.upload_and_install_file(
                            local_path,
                            l_hash,
                            l_size,  # pyright: ignore[reportPossiblyUnboundVariable]
                            dest_path,
                            index + 1,
                            file_mode,
                            future,
                            forced=True,
                        )
                    except HandledError:
                        return {"r_path": dest_path, "future": FileFuture.ERROR}
                    return {"r_path": dest_path, "future": future}
                future = FileFuture.CREATE
                if not self.install:
                    mp_print(  # pyright: ignore[reportArgumentType]
                        *self.print_infos,
                        Text.assemble(
                            "file (empty) ",
                            (str(dest_path), "bold"),
                            " will be ",
                            ("created", f"{map_file_color(future)} bold"),
                        ),
                    )
                try:
                    self.upload_and_install_file(
                        None,
                        None,
                        None,
                        dest_path,
                        index + 1,
                        file_mode,
                        future,
                        forced=True,
                    )
                except HandledError:
                    return {"r_path": dest_path, "future": FileFuture.ERROR}
                return {"r_path": dest_path, "future": future}

            mp_log(
                logging.DEBUG,
                *self.print_infos,
                "%s %s already exist",
                l_type,
                dest_path,
            )

            if r_type != l_type:
                future = FileFuture.ERROR
                mp_log(
                    logging.WARNING,
                    *self.print_infos,
                    "Remote %s is a %s but local is a %s, will not update remote",
                    dest_path,
                    r_type,
                    l_type,
                )
                return {"r_path": dest_path, "future": future}

            if l_type == "directory":
                future = FileFuture.KEEP
                return {"r_path": dest_path, "future": future}

            if l_type == "symbolic link":
                r_link, stderr = self.connector.exec(
                    f"readlink {quote(str(dest_path))}"
                )
                if stderr:
                    future = FileFuture.ERROR
                    mp_log(
                        logging.ERROR,
                        *self.print_infos,
                        "%s",
                        stderr,
                    )
                    return {"r_path": dest_path, "future": future}

                if r_link == str(l_link):  # pyright: ignore[reportPossiblyUnboundVariable]
                    future = FileFuture.KEEP
                    mp_log(
                        logging.INFO,
                        *self.print_infos,
                        "symbolic link %s is the same on remote",
                        dest_path,
                    )
                    return {"r_path": dest_path, "future": future}

                future = FileFuture.UPDATE
                if self.install:
                    subtitle = Text.assemble(
                        (str(dest_path), "bold"),
                    )
                else:
                    subtitle = Text.assemble(
                        "symbolic link ",
                        (str(dest_path), "bold"),
                        " will be ",
                        ("updated", f"{map_file_color(future)} bold"),
                    )
                mp_print(  # pyright: ignore[reportArgumentType]
                    *self.print_infos,
                    Syntax(
                        f"< {r_link}\n---\n> {l_link}",  # pyright: ignore[reportPossiblyUnboundVariable]
                        "diff",
                        line_numbers=True,
                        word_wrap=True,
                    ),
                    panel=True,
                    subtitle=subtitle,
                )
                self.install_symbolic_link(dest_path, l_link, future)  # pyright: ignore[reportPossiblyUnboundVariable]
                return {"r_path": dest_path, "future": future}

            if r_size == l_size:  # pyright: ignore[reportPossiblyUnboundVariable]
                self.progress[self.task] = {
                    "progress": index + 1,
                    "total": self.task_total,
                    "description": Text.assemble(
                        "[",
                        self.host_log_colored,
                        f"] Hashing remote {dest_path}",
                    ),
                }
                try:
                    r_hash = self.connector.hash_file(dest_path)
                except HandledError as e:
                    future = FileFuture.ERROR
                    mp_log(
                        logging.ERROR,
                        *self.print_infos,
                        "%s",
                        e,
                    )
                    return {"r_path": dest_path, "future": future}
                self.progress[self.task] = {
                    "progress": index + 1,
                    "total": self.task_total,
                    "description": Text.assemble(
                        "[",
                        self.host_log_colored,
                        f"] Syncing {dest_path}",
                    ),
                }
                l_hash = self.hash_and_log(
                    local_path,
                    index + 1,
                    dest_path,
                )
                if r_hash != l_hash and l_size > MAX_DIFF_SIZE:  # pyright: ignore[reportPossiblyUnboundVariable]
                    future = FileFuture.UPDATE
                    mp_log(
                        logging.DEBUG,
                        *self.print_infos,
                        "file %s do not have the same hash, "
                        "but it is too heavy, so diff "
                        "won't be displayed",
                        dest_path,
                    )
                    if not self.install:
                        mp_print(  # pyright: ignore[reportArgumentType]
                            *self.print_infos,
                            Text.assemble(
                                "file ",
                                (str(dest_path), "bold"),
                                " will be ",
                                ("modified", f"{map_file_color(future)} bold"),
                            ),
                        )
                    try:
                        self.upload_and_install_file(
                            local_path,
                            l_hash,
                            l_size,  # pyright: ignore[reportPossiblyUnboundVariable]
                            dest_path,
                            index + 1,
                            file_mode,
                            future,
                            forced=True,
                        )
                    except HandledError:
                        return {"r_path": dest_path, "future": FileFuture.ERROR}
                    return {"r_path": dest_path, "future": future}
                if r_hash == l_hash:
                    future = FileFuture.KEEP
                    mp_log(
                        logging.INFO,
                        *self.print_infos,
                        "file %s is the same on remote",
                        dest_path,
                    )
                    return {"r_path": dest_path, "future": future}
                mp_log(
                    logging.DEBUG,
                    *self.print_infos,
                    "file %s do not have the same hash, it has to be uploaded",
                    dest_path,
                )
            else:
                if l_size > MAX_DIFF_SIZE:  # pyright: ignore[reportPossiblyUnboundVariable]
                    future = FileFuture.UPDATE
                    mp_log(
                        logging.DEBUG,
                        *self.print_infos,
                        "file %s do not have the same size, "
                        "but it is too heavy, so diff "
                        "won't be displayed",
                        dest_path,
                    )
                    if not self.install:
                        mp_print(  # pyright: ignore[reportArgumentType]
                            *self.print_infos,
                            Text.assemble(
                                "file ",
                                (str(dest_path), "bold"),
                                " will be ",
                                ("modified", f"{map_file_color(future)} bold"),
                            ),
                        )
                    try:
                        self.upload_and_install_file(
                            local_path,
                            l_hash,
                            l_size,  # pyright: ignore[reportPossiblyUnboundVariable]
                            dest_path,
                            index + 1,
                            file_mode,
                            future,
                            forced=True,
                        )
                    except HandledError:
                        return {"r_path": dest_path, "future": FileFuture.ERROR}
                    return {"r_path": dest_path, "future": future}
                mp_log(
                    logging.DEBUG,
                    *self.print_infos,
                    "file %s is not the same size, it has to be uploaded",
                    dest_path,
                )

            future = FileFuture.UPDATE

            if not l_hash:
                l_hash = self.hash_and_log(
                    local_path,
                    index + 1,
                    dest_path,
                )

            try:
                diff = self.upload_and_install_file(
                    local_path,
                    l_hash,
                    l_size,  # pyright: ignore[reportPossiblyUnboundVariable]
                    dest_path,
                    index + 1,
                    file_mode,
                    future,
                    do_upload=True,
                    do_diff=True,
                )
            except HandledError:
                return {"r_path": dest_path, "future": FileFuture.ERROR}

            if self.install:
                subtitle = Text.assemble(
                    (str(dest_path), "bold"),
                )
            else:
                subtitle = Text.assemble(
                    "file ",
                    (str(dest_path), "bold"),
                    " will be ",
                    ("updated", f"{map_file_color(future)} bold"),
                )
            mp_print(  # pyright: ignore[reportArgumentType]
                *self.print_infos,
                Syntax(diff, "diff", line_numbers=True, word_wrap=True),
                panel=True,
                subtitle=subtitle,
            )

            return {"r_path": dest_path, "future": future}

    def gen_files(
        self,
        root: Path,
        tree: dict[Path, dict[str, Any]],
    ) -> None:
        l_file = self.root / root

        if not (l_file.is_dir() or l_file.is_file() or l_file.is_symlink()):
            raise NotImplementedError

        r_parent = tree[root.parent]["r_path"] if root.parent in tree else Path("/")
        l_parent = root.parent if root.parent in tree else Path()
        file_config = deepcopy(DEFAULT_FILE_CONFIG)
        name = root.name

        if root != Path():
            if root.suffix == f".{RFSYNCER_PREFIX}":
                return
            conf_file = l_file.parent / f"{l_file.name}.{RFSYNCER_PREFIX}"
            if conf_file.is_file():
                template = self.jinja_env.get_template(str(conf_file))
                template_out = template.render(
                    host=self.host_config,
                    general=self.general_config,
                    hook=self.hook,
                )
                file_config.update(yaml.safe_load(template_out))

        if not file_config["enabled"]:
            return

        if file_config["name"]:
            name = file_config["name"]

        tree[l_parent / root.name] = {
            "r_path": r_parent / name,  # pyright: ignore[reportOperatorIssue]
            "l_path": l_file,
            "mode": oct(l_file.stat(follow_symlinks=False).st_mode)[-4:],
            "config": file_config,
        }

        if l_file.is_file() or l_file.is_symlink():
            return
        for file in l_file.iterdir():
            self.gen_files(
                file.relative_to(self.root),
                tree,
            )

    def upload_file(
        self,
        local_path: Path,
        l_hash: str | None,
        l_size: int,
        dest_path: Path,
        current_advancement: int,
        forced: bool = False,
    ) -> Path:
        if not l_hash:
            l_hash = self.hash_and_log(
                local_path,
                current_advancement,
                dest_path,
            )

        temp_dest_path = REMOTE_TEMP_DIR / l_hash

        with contextlib.suppress(Exception):
            tmp_listdir = self.sftp.listdir(str(REMOTE_TEMP_DIR))
            if l_hash in tmp_listdir:
                r_size = self.sftp.stat(str(temp_dest_path)).st_size
                if r_size == l_size:
                    r_hash = self.connector.hash_file(temp_dest_path)
                    if r_hash == l_hash:
                        mp_log(
                            logging.DEBUG,
                            *self.print_infos,
                            "File %s (%s) is already in remote "
                            "rsfsyncer path, not uploading",
                            dest_path,
                            l_hash,
                        )
                        return temp_dest_path
                self.sftp.remove(str(temp_dest_path))

        if forced and not self.install:
            mp_log(
                logging.INFO,
                *self.print_infos,
                "Force upload mode, uploading file %s",
                dest_path,
            )
        else:
            mp_log(
                logging.INFO,
                *self.print_infos,
                "Uploading file %s",
                dest_path,
            )

        def callback(transferred: int, total: int) -> None:
            self.progress[self.file_task] = {
                "progress": transferred,
                "total": total,
                "description": Text.assemble(
                    "[",
                    self.host_log_colored,
                    f"] Uploading {dest_path}",
                ),
            }

        self.sftp.put(
            str(local_path),
            str(temp_dest_path),
            callback=callback,
        )
        return temp_dest_path

    def hash_and_log(
        self,
        local_path: Path,
        current_advancement: int,
        dest_path: Path,
    ) -> str:
        self.progress[self.task] = {
            "progress": current_advancement,
            "total": self.task_total,
            "description": Text.assemble(
                "[",
                self.host_log_colored,
                f"] Hashing {dest_path}",
            ),
        }
        l_hash = hash_(local_path)
        self.progress[self.task] = {
            "progress": current_advancement,
            "total": self.task_total,
            "description": Text.assemble(
                "[",
                self.host_log_colored,
                f"] Syncing {dest_path}",
            ),
        }
        return l_hash

    def upload_and_install_file(
        self,
        local_path: Path | None,
        l_hash: str | None,
        l_size: int | None,
        dest_path: Path,
        current_advancement: int,
        file_mode: str,
        future: FileFuture,
        do_upload: bool = False,
        do_diff: bool = False,
        forced: bool = False,
    ) -> str:
        diff = ""

        if local_path and (self.upload or self.install or do_upload):
            source_path = self.upload_file(
                local_path,
                l_hash,
                l_size,  # pyright: ignore[reportArgumentType]
                dest_path,
                current_advancement,
                forced=forced,
            )
        if not local_path:
            source_path = Path("/dev/null")

        if do_diff:
            diff = self.connector.diff_file(dest_path, l_hash)  # pyright: ignore[reportArgumentType]

        if self.install:
            _, stderr = self.connector.exec(
                f"install -m{file_mode} {quote(str(source_path))} "  # pyright: ignore[reportPossiblyUnboundVariable]
                f"{quote(str(dest_path))}"
            )
            if stderr:
                mp_log(
                    logging.WARNING,
                    *self.print_infos,
                    "file %s was not created : %s",
                    dest_path,
                    stderr,
                )
                raise HandledError(stderr)
            match future:
                case FileFuture.CREATE:
                    state = "created"
                case FileFuture.UPDATE:
                    state = "updated"
                case _:
                    raise NotImplementedError

            mp_print(  # pyright: ignore[reportArgumentType]
                *self.print_infos,
                Text.assemble(
                    "file ",
                    (str(dest_path), "bold"),
                    " ",
                    (state, f"{map_file_color(future)} bold"),
                ),
            )
        return diff

    def install_dir(
        self,
        dest_path: Path,
        file_mode: str,
    ) -> None:
        if self.install:
            _, stderr = self.connector.exec(
                f"install -m{file_mode} -d {quote(str(dest_path))}"
            )
            if stderr:
                mp_log(
                    logging.WARNING,
                    *self.print_infos,
                    "directory %s was not created : %s",
                    dest_path,
                    stderr,
                )
                raise HandledError(stderr)
            mp_print(  # pyright: ignore[reportArgumentType]
                *self.print_infos,
                Text.assemble(
                    "directory ",
                    (str(dest_path), "bold"),
                    " ",
                    ("created", f"{map_file_color(FileFuture.CREATE)} bold"),
                ),
            )

    def install_symbolic_link(
        self,
        dest_path: Path,
        link_to: Path,
        future: FileFuture,
    ) -> None:
        if self.install:
            _, stderr = self.connector.exec(
                f"ln -f -s {quote(str(link_to))} {quote(str(dest_path))}"
            )
            if stderr:
                mp_log(
                    logging.WARNING,
                    *self.print_infos,
                    "symbolic link %s was not created : %s",
                    dest_path,
                    stderr,
                )
                raise HandledError(stderr)
            match future:
                case FileFuture.CREATE:
                    state = "created"
                case FileFuture.UPDATE:
                    state = "updated"
                case _:
                    raise NotImplementedError

            mp_print(  # pyright: ignore[reportArgumentType]
                *self.print_infos,
                Text.assemble(
                    "symbolic link ",
                    (str(dest_path), "bold"),
                    " ",
                    (state, f"{map_file_color(future)} bold"),
                ),
            )
