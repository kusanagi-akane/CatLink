from dataclasses import dataclass
from typing import Dict, Any, Optional
from .models import Track

@dataclass(slots=True)
class TrackStartEvent:
    guild_id: int
    track: Dict[str, Any]

@dataclass(slots=True)
class TrackEndEvent:
    guild_id: int
    reason: str
    track: Dict[str, Any]

@dataclass(slots=True)
class TrackExceptionEvent:
    guild_id: int
    track: Dict[str, Any]
    exception: Dict[str, Any]

@dataclass(slots=True)
class TrackStuckEvent:
    guild_id: int
    track: Dict[str, Any]
    threshold_ms: int

@dataclass(slots=True)
class WebSocketClosedEvent:
    guild_id: int
    code: int
    reason: str
    by_remote: bool

@dataclass(slots=True)
class PlayerUpdateEvent:
    guild_id: int
    state: Dict[str, Any]
