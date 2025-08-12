from pathlib import Path

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

PROGRESS_WIDGETS = [
    SpinnerColumn("arc"),
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    MofNCompleteColumn(),
    TimeElapsedColumn(),
]

DEFAULT_TOOL_DIR = Path.home().resolve() / ".rfsyncer"
DEFAULT_CONFIG_FILE = Path("./config.yml")
APP_PATH = Path(__file__).parent.parent

DEFAULT_LOG_DIR = DEFAULT_TOOL_DIR / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "rfsyncer.log"

HOST_COLOR = "steel_blue3"

RFSYNCER_PREFIX = "rfsyncer"
REMOTE_TEMP_DIR = Path("/tmp/rfsyncer")
BUF_SIZE = 65536
MAX_DIFF_SIZE = 10_000_000
DEFAULT_FILE_CONFIG = {"enabled": True, "name": None}

ASKPASS_PATH = Path("/tmp/rfsyncer_askpass.sh")
