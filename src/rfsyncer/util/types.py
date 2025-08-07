from enum import StrEnum, auto


class FileFuture(StrEnum):
    CREATE = auto()
    UPDATE = auto()
    KEEP = auto()
    NA = "n/a"
    ERROR = auto()


CREATE_COLOR = "green"
UPDATE_COLOR = "orange3"
KEEP_COLOR = "chartreuse1"
NA_COLOR = "grey53"
ERROR_COLOR = "red"


def map_file_color(future: FileFuture) -> str:
    match future:
        case FileFuture.CREATE:
            return CREATE_COLOR
        case FileFuture.UPDATE:
            return UPDATE_COLOR
        case FileFuture.KEEP:
            return KEEP_COLOR
        case FileFuture.NA:
            return NA_COLOR
        case FileFuture.ERROR:
            return ERROR_COLOR
