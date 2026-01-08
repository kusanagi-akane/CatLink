import asyncio
import logging
from collections import deque
from typing import Optional
from .models import Track
from .node import Node

_log = logging.getLogger(__name__)

class Player:
    def __init__(self, guild_id: int, node: Node):
        self.guild_id = guild_id
        self.node = node
        self.queue: deque[Track] = deque()
        self.current: Optional[Track] = None
        self.loop: bool = False
        self.paused: bool = False
        self.volume: int = 100
        self.position: int = 0

    @property
    def is_playing(self) -> bool:
        return self.current is not None

    async def play(self, track: Track, replace: bool = False):
        if replace or not self.is_playing:
            await self._perform_play(track)
        else:
            self.queue.append(track)

    async def _perform_play(self, track: Track):
        self.current = track
        self.paused = False
        self.position = 0
        voice = self.node.get_voice(self.guild_id)
        if not voice.ready():
            _log.info(f"[Player] Waiting for voice credentials (Max 4s)...")
            for _ in range(40):
                if voice.ready():
                    break
                await asyncio.sleep(0.1)
        
        if voice.ready():
            _log.info(f"[Player] Voice credentials ready, preparing to send Atomic Play Request")
            try:
                await self.node.update_voice(self.guild_id)
            except Exception as e:
                _log.warning(f"[Player] Pre-sync voice failed: {e}")
        else:
            _log.warning(f"[Player] Waiting for voice credentials timed out, attempting to play without credentials (may fail)")
        await self.node.play(self.guild_id, track)

    async def stop(self):
        self.queue.clear()
        self.current = None
        self.paused = False
        self.position = 0
        await self.node.stop(self.guild_id)

    async def handle_track_end(self, reason: str):
        prev = self.current
        self.current = None
        self.paused = False
        self.position = 0
        if reason == "replaced":
            return
        if reason == "finished" or reason == "loadFailed":
            if self.loop and prev:
                await self._perform_play(prev)
                return
            if self.queue:
                next_track = self.queue.popleft()
                await self._perform_play(next_track)

    async def skip(self):
        if self.queue:
            next_track = self.queue.popleft()
            self.current = next_track
            self.position = 0
            await self.node.play(self.guild_id, next_track, replace=True)
        else:
            self.current = None
            await self.node.stop(self.guild_id)

    async def set_volume(self, volume: int):
        v = max(0, min(1000, int(volume)))
        await self.node.set_volume(self.guild_id, v)
        self.volume = v

    async def pause(self):
        await self.node.set_paused(self.guild_id, True)
        self.paused = True

    async def resume(self):
        await self.node.set_paused(self.guild_id, False)
        self.paused = False

    async def seek(self, position_ms: int):
        await self.node.rest.update_player(self.guild_id, position=position_ms)
        self.position = int(position_ms)
