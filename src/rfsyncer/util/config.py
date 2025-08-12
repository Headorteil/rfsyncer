import json
import os
from logging import Logger
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment
from yaml import safe_load

from rfsyncer.util.consts import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE,
)
from rfsyncer.util.exceptions import HandledError


class RfsyncerConfig:
    def __init__(self, logger: Logger, config_path: Path, flag: str) -> None:
        self.config_path = config_path.resolve()
        self.__logger = logger

        self.log_file = DEFAULT_LOG_FILE
        self.hosts = {}
        self.general = {}
        if flag:
            self.flag = json.loads(flag)
        else:
            self.flag = {}
        load_dotenv()
        self.env = os.environ

        if (
            self.config_path != DEFAULT_CONFIG_FILE.resolve()
            and not self.config_path.is_file()
        ):
            errmsg = "Config file is not default and does not exist"
            raise HandledError(errmsg)

    def init_config(self) -> None:
        """Return the config."""

        if self.config_path.is_file():
            env = Environment()  # noqa: S701
            template = env.from_string(self.config_path.read_text())
            template_out = template.render(env=self.env, flag=self.flag)

            raw_config = safe_load(template_out)
            if raw_config is not None:
                if raw_config.get("log_file"):
                    self.log_file = Path(raw_config["log_file"])
                if raw_config.get("hosts"):
                    self.hosts = raw_config["hosts"]
                if raw_config.get("general"):
                    if "flag" in raw_config["general"]:
                        errmsg = "flag is a reserved section of general "
                        "in config, don't use it"
                        raise HandledError(errmsg)
                    if "env" in raw_config["general"]:
                        errmsg = "env is a reserved section of general "
                        "in config, don't use it"
                        raise HandledError(errmsg)
                    self.general = raw_config["general"]

        self.general["flag"] = self.flag
        self.general["env"] = self.env

        if self.log_file.parent == DEFAULT_LOG_DIR and not DEFAULT_LOG_DIR.is_dir():
            self.__logger.info("Creating default logs dir -> %s", DEFAULT_LOG_DIR)
            DEFAULT_LOG_DIR.mkdir(parents=True)
        if not DEFAULT_LOG_DIR.is_dir():
            errmsg = "Log file is not default and its parent dir doesn't exist"
            raise HandledError(errmsg)
