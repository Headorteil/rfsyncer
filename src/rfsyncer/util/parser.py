import re


def parse_ssh_host(uri: str) -> dict[str, str | int]:
    match = re.search(
        r"^(?:(?P<user>.*?)@)?(?P<host>.*?)(?::(?P<port>\d+))?$",
        uri,
    )
    to_return = {"hostname": match.group("host")}
    port = match.group("port")
    user = match.group("user")
    if port:
        to_return["port"] = int(port)
    if user:
        to_return["user"] = user
    return to_return
