import aiohttp
import logging
import asyncio
import socket
import sys
from typing import Optional, List, Dict, Any, Union
from .models import Track

_log = logging.getLogger(__name__)


DEFAULT_TIMEOUT = aiohttp.ClientTimeout(
    total=30,
    connect=10,
    sock_connect=10,
    sock_read=20
)

class RestClient:
    def __init__(self, host: str, port: int, password: str, user_id: int, secure: bool = False, version: int = 4):
        protocol = "https" if secure else "http"
        self.version = version
        if version == 4:
            self.base = f"{protocol}://{host}:{port}/v4"
        else:
            self.base = f"{protocol}://{host}:{port}"
        self.headers = {
            "Authorization": password,
            "User-Id": str(user_id),
            "Client-Name": "lavalink_simple",
            "Content-Type": "application/json"
        }
        self.session: Optional[aiohttp.ClientSession] = None
        self.session_id: Optional[str] = None

    async def start(self):
        if self.session is None:
            family = socket.AF_INET if sys.platform == 'win32' else socket.AF_UNSPEC
            conn = aiohttp.TCPConnector(
                family=family, 
                limit=10,              
                ttl_dns_cache=300,
                force_close=False,
                enable_cleanup_closed=True,
                keepalive_timeout=30
            )
            self.session = aiohttp.ClientSession(
                headers=self.headers, 
                connector=conn,
                timeout=DEFAULT_TIMEOUT
            )

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def update_session(self, resuming: bool = True, timeout: int = 60):
        if not self.session_id: return
        try:
            async with self.session.patch(
                f"{self.base}/sessions/{self.session_id}",
                json={"resuming": resuming, "timeout": timeout},
            ) as resp:
                await resp.text()
                if resp.status != 200:
                    _log.warning(f"Failed to update session: {resp.status}")
        except Exception as e:
            _log.error(f"Error updating session: {e}")

    async def load_tracks(self, identifier: str) -> List[Track]:
        url = f"{self.base}/loadtracks"
        _log.info(f"[REST] Searching: {identifier}")
        
        try:
            async with self.session.get(
                url,
                params={"identifier": identifier},
                timeout=aiohttp.ClientTimeout(total=45, connect=20, sock_read=30)
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    _log.error(f"Load tracks failed: {resp.status}")
                    return []
        except Exception as e:
            _log.error(f"[REST] Search error: {e}")
            return []

        raw_tracks = []
        if self.version == 4:
            if isinstance(data, list):
                raw_tracks = data
            else:
                load_type = data.get("loadType")
                ddata = data.get("data")
                if load_type in ("track", "short"):
                    if isinstance(ddata, list):
                        raw_tracks = ddata
                    elif ddata is not None:
                        raw_tracks = [ddata]
                elif load_type in ("playlist", "search"):
                    if isinstance(ddata, dict):
                        raw_tracks = ddata.get("tracks", ddata)
                    elif isinstance(ddata, list):
                        raw_tracks = ddata
                    else:
                        raw_tracks = []
                else:
                    raw_tracks = []
        else:
            raw_tracks = data.get("tracks", [])

        tracks = []
        for t in raw_tracks:
            info = t.get("info", t)
            encoded_str = t.get("encoded", t.get("track"))
            tracks.append(
                Track(
                    encoded=encoded_str,
                    title=info.get("title", "Unknown"),
                    author=info.get("author", "Unknown"),
                    length=info.get("length", 0),
                    uri=info.get("uri", ""),
                    identifier=info.get("identifier", "")
                )
            )
        return tracks

    async def update_player(self, guild_id: int, encoded_track: Optional[str] = None, no_replace: bool = False, volume: int = None, paused: bool = None, voice: dict = None, position: int = None):
        if not self.session_id: return None
            
        payload = {}
        if encoded_track is not None:
            if encoded_track == "STOP": payload["track"] = {"encoded": None}
            else: payload["track"] = {"encoded": encoded_track}
        if volume is not None: payload["volume"] = volume
        if paused is not None: payload["paused"] = paused
        if voice is not None: payload["voice"] = voice
        if position is not None: payload["position"] = position
        
        params = {}
        if no_replace and "track" in payload: params["noReplace"] = "true"
        

        max_attempts = 5 if voice else 3
        timeout_cfg = aiohttp.ClientTimeout(total=10, connect=5, sock_read=8) if voice else aiohttp.ClientTimeout(total=20, connect=10, sock_read=15)
        
        for attempt in range(max_attempts):
            try:
                async with self.session.patch(
                    f"{self.base}/sessions/{self.session_id}/players/{guild_id}",
                    json=payload,
                    params=params,
                    timeout=timeout_cfg
                ) as resp:
                    text = await resp.text()
                    
                    if voice:
                        _log.info(f"[REST] Atomic Play succeeded (HTTP {resp.status})")
                    if resp.status not in (200, 204):
                        _log.warning(f"[REST] update_player returned {resp.status}, body={text[:200]}")
                    return resp.status
            except Exception as e:
                retry_delay = 0.1 if voice else 0.2
                if attempt < max_attempts - 1:
                    _log.debug(f"[REST] Attempt {attempt+1} failed, retrying in {retry_delay}s: {e}")
                    await asyncio.sleep(retry_delay)
                else:
                    if voice: _log.error(f"[REST] Voice update failed after {max_attempts} attempts: {e}")
                    return None

    async def update_voice(self, guild_id: int, voice_data: dict):
        return await self.update_player(guild_id, voice=voice_data)
