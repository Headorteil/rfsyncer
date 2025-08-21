import importlib
from enum import StrEnum, auto
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer
from paramiko.config import SSHConfig
from rich.console import Console

from rfsyncer.syncer import Syncer
from rfsyncer.util.config import RfsyncerConfig
from rfsyncer.util.consts import DEFAULT_CONFIG_FILE
from rfsyncer.util.exceptions import HandledError
from rfsyncer.util.logger import add_file_handler, get_logger

app = typer.Typer(
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Rfsyncer by Headorteil 😎",
    no_args_is_help=True,
)


def __version_callback(value: bool) -> None:
    if value:
        version = importlib.metadata.version("rfsyncer")  # pyright: ignore[reportAttributeAccessIssue]
        print(version)  # noqa: T201
        raise typer.Exit


class Color(StrEnum):
    STANDARD = auto()
    TRUECOLOR = auto()
    AUTO = auto()
    NONE = auto()
    COLOR_256 = "256"


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Config path (or - for stdin)",
        ),
    ] = DEFAULT_CONFIG_FILE,
    dotenv_file: Annotated[
        Path,
        typer.Option(
            "--dotenv",
            "-e",
            file_okay=True,
            readable=True,
            resolve_path=True,
            help="Dotenv path",
        ),
    ] = Path(".env"),
    verbosity: Annotated[
        int,
        typer.Option(
            "--verbosity-level",
            "-v",
            rich_help_panel="Display",
            min=0,
            max=3,
            help="Change the logs verbosity",
        ),
    ] = 2,
    log_to_file: Annotated[
        bool,
        typer.Option(
            "--log-to-file/--no-log-to-file",
            rich_help_panel="Display",
            help="Enable file logging (path defined in config)",
        ),
    ] = True,
    processes: Annotated[
        int,
        typer.Option(
            "--processes",
            "-p",
            help="Number of processes to pop",
        ),
    ] = 4,
    flag: Annotated[
        str,
        typer.Option(
            "--flag",
            "-f",
            help="json to pass to templating engines",
        ),
    ] = "",
    display: Annotated[
        bool,
        typer.Option(
            "--display/--no-display",
            " /-D",
            rich_help_panel="Display",
            help="Display things that are not logs nor live like tables or diffs",
        ),
    ] = True,
    pager: Annotated[
        bool,
        typer.Option(
            "--pager/--no-pager",
            "-P",
            rich_help_panel="Display",
            help="Display tables in less",
        ),
    ] = False,
    live: Annotated[
        bool,
        typer.Option(
            "--live/--no-live",
            "-l/-L",
            rich_help_panel="Display",
            help="Display live objects like progress bars",
        ),
    ] = True,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug/--no-debug",
            "-d",
            rich_help_panel="Display",
            help="Use max verbosity and print file infos with logs",
        ),
    ] = False,
    color: Annotated[
        Color,
        typer.Option(
            "--color",
            rich_help_panel="Display",
            help="Color system",
        ),
    ] = Color.AUTO,
    version: Annotated[  # noqa: ARG001
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=__version_callback,
            is_eager=True,
            help="Print the tool version",
        ),
    ] = False,
) -> None:
    """Set variables for all subcommands and run TUI if no command is provided."""
    if color is Color.NONE:
        console = Console(no_color=True)
    else:
        console = Console(color_system=color)  # pyright: ignore[reportArgumentType]

    if debug:
        verbosity = 3

    logger = get_logger(console, verbosity, debug)

    try:
        config = RfsyncerConfig(logger, config_path, flag, dotenv_file)
        config.init_config()
    except HandledError as e:
        logger.critical(e)
        raise typer.Exit(code=1) from e
    except Exception as e:
        logger.critical("Can't parse config file -> %s", e)
        raise typer.Exit(code=1) from e

    if log_to_file:
        add_file_handler(logger, config.log_file)

    try:
        syncer = Syncer(
            config,
            console=console,
            display=display,
            pager=pager,
            live=live,
            logger=logger,  # pyright: ignore[reportCallIssue]
            debug=debug,
            processes=processes,
        )
    except Exception as e:
        logger.critical(e)
        raise typer.Exit(code=1) from e

    ctx.obj = SimpleNamespace(
        logger=logger,
        syncer=syncer,
    )


@app.command("ping", help="Test connectivity to remote hosts")
def ping(
    ctx: typer.Context,
    hosts: Annotated[
        list[str] | None,
        typer.Option(
            "--hosts",
            help="Hosts",
            show_default="all hosts defined in the config file",
            autocompletion=SSHConfig.from_path(
                Path().home() / ".ssh/config",
            ).get_hostnames,
        ),
    ] = None,
    sudo: Annotated[
        bool,
        typer.Option(
            "--sudo/--no-sudo",
            "-s/-S",
            help="Exec commands with sudo",
        ),
    ] = False,
    insecure: Annotated[
        bool,
        typer.Option(
            "--insecure/--no-insecure",
            "-i/-I",
            help="Insecure mode : don't check host keys",
        ),
    ] = False,
) -> None:
    try:
        ctx.obj.syncer.ping(
            hosts,
            insecure=insecure,
            sudo=sudo,
        )
    except Exception as e:
        ctx.obj.logger.exception("Unhandled error")
        raise typer.Exit(code=1) from e


@app.command("install", help="Install local tree to remote hosts")
def install(
    ctx: typer.Context,
    root: Annotated[
        Path,
        typer.Option(
            "--root",
            "-r",
            help="Root path on wich make diff",
        ),
    ] = Path("./root"),
    hosts: Annotated[
        list[str] | None,
        typer.Option(
            "--hosts",
            show_default="all hosts defined in the config file",
            help="Hosts",
            autocompletion=SSHConfig.from_path(
                Path().home() / ".ssh/config",
            ).get_hostnames,
        ),
    ] = None,
    sudo: Annotated[
        bool,
        typer.Option(
            "--sudo/--no-sudo",
            "-s/-S",
            help="Exec commands with sudo",
        ),
    ] = False,
    insecure: Annotated[
        bool,
        typer.Option(
            "--insecure/--no-insecure",
            "-i/-I",
            help="Insecure mode : don't check host keys",
        ),
    ] = False,
    keep: Annotated[
        bool,
        typer.Option(
            "--keep/--no-keep",
            "-k/-K",
            help="Keep remote tmp dir",
        ),
    ] = False,
) -> None:
    try:
        ctx.obj.syncer.diff(
            hosts,
            root=root,
            insecure=insecure,
            sudo=sudo,
            keep=keep,
            install=True,
        )
    except Exception as e:
        ctx.obj.logger.exception("Unhandled error")
        raise typer.Exit(code=1) from e


@app.command("diff", help="Diff local tree with remote trees")
def diff(
    ctx: typer.Context,
    root: Annotated[
        Path,
        typer.Option(
            "--root",
            "-r",
            help="Root path on wich make diff",
        ),
    ] = Path("./root"),
    hosts: Annotated[
        list[str] | None,
        typer.Option(
            "--hosts",
            show_default="all hosts defined in the config file",
            help="Hosts",
            autocompletion=SSHConfig.from_path(
                Path().home() / ".ssh/config",
            ).get_hostnames,
        ),
    ] = None,
    sudo: Annotated[
        bool,
        typer.Option(
            "--sudo/--no-sudo",
            "-s/-S",
            help="Exec commands with sudo",
        ),
    ] = False,
    insecure: Annotated[
        bool,
        typer.Option(
            "--insecure/--no-insecure",
            "-i/-I",
            help="Insecure mode : don't check host keys",
        ),
    ] = False,
    keep: Annotated[
        bool,
        typer.Option(
            "--keep/--no-keep",
            "-k/-K",
            help="Keep remote tmp dir",
        ),
    ] = False,
    upload: Annotated[
        bool,
        typer.Option(
            "--force-upload/--no-force-upload",
            "-f/-F",
            help="Force upload to remote, may be useful with --keep",
        ),
    ] = False,
) -> None:
    try:
        ctx.obj.syncer.diff(
            hosts,
            root=root,
            insecure=insecure,
            sudo=sudo,
            keep=keep,
            upload=upload,
        )
    except Exception as e:
        ctx.obj.logger.exception("Unhandled error")
        raise typer.Exit(code=1) from e


@app.command("clear", help="Clear remote hosts of rfsyncer temporary files")
def clear(
    ctx: typer.Context,
    hosts: Annotated[
        list[str] | None,
        typer.Option(
            "--hosts",
            show_default="all hosts defined in the config file",
            help="Hosts",
            autocompletion=SSHConfig.from_path(
                Path().home() / ".ssh/config",
            ).get_hostnames,
        ),
    ] = None,
    insecure: Annotated[
        bool,
        typer.Option(
            "--insecure/--no-insecure",
            "-i/-I",
            help="Insecure mode : don't check host keys",
        ),
    ] = False,
) -> None:
    try:
        ctx.obj.syncer.clear(
            hosts,
            insecure=insecure,
        )
    except Exception as e:
        ctx.obj.logger.exception("Unhandled error")
        raise typer.Exit(code=1) from e
