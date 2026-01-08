import discord
import logging
import asyncio
from typing import Dict, Optional, List, Callable, Any
from collections import defaultdict
from .rest import RestClient
from .node import Node
from .player import Player

_log = logging.getLogger(__name__)

class LavalinkClient:
    def __init__(self, bot: discord.Client, host: str, port: int, password: str, user_id: int, version: int = 4):
        self.bot = bot
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
        self.rest = RestClient(host, port, password, user_id, secure=False, version=version)
        self.node = Node(self.rest, self._dispatch, host, port, password, user_id, secure=False, version=version)
        self.players: Dict[int, Player] = {}
        
        self.bot.add_listener(self._handle_socket_response, 'on_socket_response')
        self.bot.add_listener(self._on_voice_state_update_event, 'on_voice_state_update')
        
        _log.info("Lavalink Client Initialized")
        self.on("track_end")(self._on_track_end)
        self.on("player_update")(self._on_player_update)

    async def _on_voice_state_update_event(self, member, before, after):
        if member.id != self.bot.user.id:
            return
        guild_id = member.guild.id
        if after.channel is not None:
            self.bot.loop.create_task(self._maybe_push_voice_update(guild_id))
        else:
            if guild_id in self.node.voice_states:
                del self.node.voice_states[guild_id]

    async def _handle_socket_response(self, payload: dict):
        if not payload: return
        t = payload.get("t")
        d = payload.get("d")

        if t == "VOICE_SERVER_UPDATE":
            guild_id = int(d["guild_id"])
            endpoint = d["endpoint"]
            if endpoint and ":" in endpoint:
                endpoint = endpoint.split(":")[0]
            

            voice = self.node.get_voice(guild_id)
            voice.token = d["token"]
            voice.endpoint = endpoint
            self.bot.loop.create_task(self._maybe_push_voice_update(guild_id))
            
        elif t == "VOICE_STATE_UPDATE":
            if self.bot.user and int(d["user_id"]) == self.bot.user.id:
                guild_id = int(d["guild_id"])
                voice = self.node.get_voice(guild_id)
                voice.session_id = d["session_id"]
                self.bot.loop.create_task(self._maybe_push_voice_update(guild_id))

 
    def on(self, event_name: str):
        def decorator(func):
            self._listeners[event_name].append(func)
            return func
        return decorator

    async def _dispatch(self, event_name: str, event: Any):
        for cb in self._listeners[event_name]:
            try: await cb(event)
            except: pass

    async def _on_track_end(self, event):
        if event.guild_id in self.players:
            await self.players[event.guild_id].handle_track_end(event.reason)

    async def _on_player_update(self, event):
        gid = int(getattr(event, 'guild_id', 0) or 0)
        if gid in self.players:
            state = getattr(event, 'state', {}) or {}
            pos = state.get('position') or state.get('time') or 0
            try:
                self.players[gid].position = int(pos)
            except Exception:
                self.players[gid].position = 0

    def get_player(self, guild_id: int) -> Player:
        if guild_id not in self.players:
            self.players[guild_id] = Player(guild_id, self.node)
        return self.players[guild_id]

    async def _maybe_push_voice_update(self, guild_id: int):
        voice = self.node.get_voice(guild_id)
        if not voice.ready():
            return
        ready = await self.node.wait_ready(timeout=8.0)
        if not ready:
            _log.warning(f"[Voice] session_id not ready, skipping sync (guild={guild_id})")
            return
        status = await self.node.update_voice(guild_id)
        if status not in (None, True, 200, 204):
            _log.warning(f"[Voice] update_voice returned {status} (guild={guild_id})")
    async def connect(self):
        await self.node.connect()

    async def load_track(self, query: str, source: str = "spsearch"):
        if not query.startswith(("http", "https")):
            query = f"{source}:{query}"
        tracks = await self.rest.load_tracks(query)
        return tracks[0] if tracks else None

    async def search_tracks(self, query: str, source: str = "ytsearch", limit: int = 10):
        if not query.startswith(("http", "https")):
            query = f"{source}:{query}"
        tracks = await self.rest.load_tracks(query)
        return tracks[:limit] if tracks else []
