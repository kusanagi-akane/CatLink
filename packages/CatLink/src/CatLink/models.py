from dataclasses import dataclass
from typing import Optional

@dataclass(slots=True)
class Track:
    encoded: str
    title: str
    author: str
    length: int
    uri: str
    identifier: str
    is_seekable: bool = True
    is_stream: bool = False
