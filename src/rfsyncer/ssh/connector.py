import os
from io import BytesIO
from pathlib import Path
from shlex import quote
from socket import gaierror

from paramiko import AutoAddPolicy, SSHClient, SSHException
from paramiko.config import SSHConfig as ParamikoSSHConfig

from rfsyncer.util.config import RfsyncerConfig
from rfsyncer.util.consts import ASKPASS_PATH, REMOTE_TEMP_DIR
from rfsyncer.util.exceptions import HandledError
from rfsyncer.util.parser import parse_ssh_host


class Connector:
    def __init__(
        self, config: RfsyncerConfig, insecure: bool = False, sudo: bool = False
    ) -> None:
        self.client = SSHClient()
        if insecure:
            self.client.set_missing_host_key_policy(AutoAddPolicy)
        else:
            self.client.load_system_host_keys()

        self.ssh_config = None
        ssh_config = Path().home() / ".ssh/config"
        if ssh_config.is_file():
            self.ssh_config = ParamikoSSHConfig.from_path(ssh_config)

        self.sudo = sudo
        self.sftp = None
        self.global_config = config
        self.host_config = None

    def connect(self, host: str) -> None:
        parsed_host = {
            "port": 22,
            "sudo": self.sudo,
            "hostname": None,
            "user": os.getlogin(),
            "password": None,
            "identityfile": None,
        }
        if self.ssh_config and host in self.ssh_config.get_hostnames():
            parsed_host.update(self.ssh_config.lookup(host))
            if "port" in parsed_host:
                parsed_host["port"] = int(parsed_host["port"])  # pyright: ignore[reportArgumentType]
            config_host = host
        else:
            parsed_host.update(parse_ssh_host(host))
            config_host = parsed_host["hostname"]

        if host_config := self.global_config.hosts.get(config_host):
            parsed_host.update(host_config)

        self.host_config = parsed_host

        try:
            self.client.connect(
                parsed_host.get("hostname"),  # pyright: ignore[reportArgumentType]
                port=parsed_host.get("port"),  # pyright: ignore[reportArgumentType]
                username=parsed_host.get("user"),  # pyright: ignore[reportArgumentType]
                password=parsed_host.get("password"),  # pyright: ignore[reportArgumentType]
                key_filename=parsed_host.get("identityfile"),  # pyright: ignore[reportArgumentType]
            )
            self.sftp = self.client.open_sftp()
        except SSHException as e:
            errmsg = f"SSH error ({e})"
            raise HandledError(errmsg) from e
        except gaierror as e:
            errmsg = f"Could not resolve hostname ({e})"
            raise HandledError(errmsg) from e
        except OSError as e:
            errmsg = f"Could not connect ({e})"
            raise HandledError(errmsg) from e
        except EOFError as e:
            errmsg = f"EOF error ({e})"
            raise HandledError(errmsg) from e

    def set_askpass(self) -> None:
        self.sftp.putfo(
            BytesIO(b"#!/bin/sh\nprintf '%s\\n' \"$RFSYNCER_SUDO_PASSWORD\""),
            str(ASKPASS_PATH),
        )
        self.sftp.chmod(str(ASKPASS_PATH), 0o700)

    def del_askpass(self) -> None:
        self.sftp.remove(str(ASKPASS_PATH))

    def exec(self, command: str) -> tuple[str, str]:
        if self.host_config["sudo"]:
            return self.sudo_exec(command)

        _, stdout, stderr = self.client.exec_command(command)
        return (stdout.read().decode().strip(), stderr.read().decode().strip())

    def sudo_exec(self, command: str) -> tuple[str, str]:
        if self.host_config["password"]:
            _, stdout, stderr = self.client.exec_command(
                f"SUDO_ASKPASS={ASKPASS_PATH} "
                f"RFSYNCER_SUDO_PASSWORD={quote(self.host_config['password'])} "  # pyright: ignore[reportArgumentType]
                f"sudo -H -A -k {command}"
            )
        else:
            _, stdout, stderr = self.client.exec_command(f"sudo -H -n {command}")
        return (stdout.read().decode().strip(), stderr.read().decode().strip())

    def stat(self, file: Path) -> tuple[int, str]:
        stdout, stderr = self.exec(f'stat --printf="%s|%F" {quote(str(file))}')
        if stderr:
            if stderr.endswith("No such file or directory"):
                raise FileNotFoundError(stderr)
            if stderr.endswith("Permission denied"):
                raise PermissionError(stderr)
        size, ftype = stdout.split("|")
        if ftype == "regular empty file":
            ftype = "regular file"
        return int(size), ftype

    def hash_file(self, file: Path) -> str:
        stdout, stderr = self.exec(f"md5sum {quote(str(file))}")
        stdout_list = stdout.split(" ")
        if len(stdout_list) > 0 and len(stdout_list[0]) == 32:
            return stdout_list[0]
        errmsg = f"Could not hash file {file}, maybe you don't "
        f"have read rights on it ({stderr})"
        raise HandledError(errmsg)

    def diff_file(self, file: Path, hash_: str) -> str:
        src = REMOTE_TEMP_DIR / hash_
        stdout, stderr = self.exec(f"diff {quote(str(file))} {quote(str(src))}")
        if stderr:
            errmsg = f"Could not diff file {file}, maybe you don't "
            f"have read rights on it ({stderr})"
            raise HandledError(errmsg)
        return stdout
