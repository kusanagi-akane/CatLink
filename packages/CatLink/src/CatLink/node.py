import asyncio
import logging
from typing import Optional, Callable, Dict, Any, Union
from .voice import VoiceState
from .websocket import LavalinkWebSocket
from .events import *
from .models import Track

_log = logging.getLogger(__name__)

class Node:
    def __init__(
        self, 
        rest, 
        dispatch: Callable, 
        host: str, 
        port: int, 
        password: str, 
        user_id: int, 
        secure: bool = False,
        version: int = 4
    ):
        self.rest = rest
        self.dispatch = dispatch
        self.host = host
        self.port = port
        self.password = password
        self.user_id = user_id
        self.secure = secure
        self.version = version

        self.voice_states: Dict[int, VoiceState] = {}
        self.ws: Optional[LavalinkWebSocket] = None
        self.stats: Dict[str, Any] = {}

    @property
    def base_uri(self) -> str:
        protocol = "https" if self.secure else "http"
        return f"{protocol}://{self.host}:{self.port}"

    def get_voice(self, guild_id: int) -> VoiceState:
        return self.voice_states.setdefault(guild_id, VoiceState())

    async def connect(self):
        _log.info(f"Connecting to Node {self.host}:{self.port} (Version: {self.version})...")
        await self.rest.start()
        self.ws = LavalinkWebSocket(
            self.host,
            self.port,
            self.password,
            self.user_id,
            None, 
            self._handle_payload,
            self.secure,
            self.version
        )
        asyncio.create_task(self.ws.connect())

    async def wait_ready(self, timeout: float = 10.0) -> bool:
        if self.version != 4:
            return True
        waited = 0.0
        while self.rest.session_id is None and waited < timeout:
            await asyncio.sleep(0.1)
            waited += 0.1
        return self.rest.session_id is not None

    async def update_voice(self, guild_id: int, session_id: str = None, token: str = None, endpoint: str = None):
        voice = self.get_voice(guild_id)
 
        if session_id: voice.session_id = session_id
        if token: voice.token = token
        if endpoint: voice.endpoint = endpoint
        if not voice.ready():
            return None


        if self.version == 4:
            return await self.rest.update_voice(
                guild_id,
                {
                    "sessionId": voice.session_id,
                    "token": voice.token,
                    "endpoint": voice.endpoint,
                },
            )
        else:
            await self.ws.send({
                "op": "voiceUpdate",
                "guildId": str(guild_id),
                "sessionId": voice.session_id,
                "event": {
                    "token": voice.token,
                    "endpoint": voice.endpoint,
                }
            })
            return True

    async def play(self, guild_id: int, track: Union[Track, str, None], replace: bool = True):
        encoded = track.encoded if isinstance(track, Track) else track
        
        if self.version == 4:
            ready = await self.wait_ready(timeout=8.0)
            if not ready:
                _log.warning("[Node] Waiting for session_id timed out, cancelling play request")
                return
            val = encoded if encoded else "STOP"
            voice_payload = None
            voice = self.get_voice(guild_id)
            if voice.ready():
                voice_payload = {
                    "sessionId": voice.session_id,
                    "token": voice.token,
                    "endpoint": voice.endpoint
                }
                _log.info(f"[Node] Executing Atomic Play (with Voice credentials)")
            
            status = await self.rest.update_player(
                guild_id, 
                encoded_track=val, 
                no_replace=not replace,
                voice=voice_payload
            )
            if status not in (200, 204):
                _log.warning(f"[Node] update_player returned {status}, may not have played successfully")
        else:
            if not encoded:
                await self.stop(guild_id)
            else:
                await self.ws.send({
                    "op": "play",
                    "guildId": str(guild_id),
                    "track": encoded,
                    "noReplace": not replace
                })

    async def stop(self, guild_id: int):
        if self.version == 4:
            status = await self.rest.update_player(guild_id, encoded_track="STOP")
            if status and status not in (200, 204):
                _log.warning(f"[Node] stop returned {status}")
        else:
            await self.ws.send({"op": "stop", "guildId": str(guild_id)})

    async def set_volume(self, guild_id: int, volume: int):
        if self.version == 4:
            await self.rest.update_player(guild_id, volume=volume)
        else:
            await self.ws.send({"op": "volume", "guildId": str(guild_id), "volume": volume})

    async def set_paused(self, guild_id: int, paused: bool):
        if self.version == 4:
            await self.rest.update_player(guild_id, paused=paused)
        else:
            await self.ws.send({"op": "pause", "guildId": str(guild_id), "pause": paused})

    async def seek(self, guild_id: int, position_ms: int):

        if self.version == 4:
            try:
                await self.rest.update_player(guild_id, encoded_track=None, no_replace=False, volume=None, paused=None, voice=None)  # 先保留連線熱身
            except Exception:
                pass
            await self.rest.update_player(guild_id)
        else:
            await self.ws.send({"op": "seek", "guildId": str(guild_id), "position": position_ms})

    async def _handle_payload(self, payload: dict):
        op = payload.get("op")
        if op == "stats":
            self.stats = payload
        elif op == "playerUpdate":
            try:
                guild_id = int(payload.get("guildId", 0))
            except Exception:
                guild_id = 0
            state = payload.get("state", {})
            await self.dispatch("player_update", PlayerUpdateEvent(guild_id=guild_id, state=state))
        elif op == "event":
            await self._handle_event(payload)
        elif op == "ready":
            session_id = payload.get("sessionId")
            _log.info(f"Lavalink Ready! Session ID: {session_id}")
            if self.version == 4 and session_id:
                self.rest.session_id = session_id
                await self.rest.update_session(resuming=True)

    async def _handle_event(self, payload: dict):
        event_type = payload.get("type")
        guild_id = int(payload.get("guildId", 0))
        event = None
        if event_type == "TrackStartEvent":
            event = TrackStartEvent(guild_id=guild_id, track=payload.get("track"))
            await self.dispatch("track_start", event)
        elif event_type == "TrackEndEvent":
            event = TrackEndEvent(guild_id=guild_id, track=payload.get("track"), reason=payload.get("reason"))
            await self.dispatch("track_end", event)
        elif event_type == "TrackExceptionEvent":
            event = TrackExceptionEvent(guild_id=guild_id, track=payload.get("track"), exception=payload.get("exception"))
            await self.dispatch("track_exception", event)
        elif event_type == "TrackStuckEvent":
            event = TrackStuckEvent(guild_id=guild_id, track=payload.get("track"), threshold_ms=payload.get("thresholdMs"))
            await self.dispatch("track_stuck", event)
        elif event_type == "WebSocketClosedEvent":
            event = WebSocketClosedEvent(guild_id=guild_id, code=payload.get("code"), reason=payload.get("reason"), by_remote=payload.get("byRemote"))
            await self.dispatch("websocket_closed", event)
