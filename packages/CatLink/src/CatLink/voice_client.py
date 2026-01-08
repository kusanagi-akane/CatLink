import asyncio
import logging
from typing import Optional, TYPE_CHECKING

import discord
from discord import VoiceProtocol

if TYPE_CHECKING:
    from .client import LavalinkClient

_log = logging.getLogger(__name__)


class LavalinkVoiceClient(VoiceProtocol):
    """
    一個假的VoiceClient，負責：
    1. 發送 VOICE_STATE_UPDATE 到 Discord Gateway（告訴 Discord 我要插入了）
    2. 把憑證幹給 LavalinkClient
    3. 不建立真正的語音 WebSocket（讓 Lavalink抽插）
    """
    def __init__(self, client: discord.Client, channel: discord.VoiceChannel):
        self.client = client
        self.channel = channel
        self._guild = channel.guild
        self._connected = asyncio.Event()
        self._session_id: Optional[str] = None
        self._token: Optional[str] = None
        self._endpoint: Optional[str] = None

    @property
    def guild(self):
        return self._guild
    
    def _get_lavalink(self) -> Optional["LavalinkClient"]:
        return getattr(self.client, 'lavalink', None)

    async def on_voice_server_update(self, data: dict):
        self._token = data.get("token")
        endpoint = data.get("endpoint")
        if endpoint and ":" in endpoint:
            endpoint = endpoint.split(":")[0]
        self._endpoint = endpoint
        
        _log.info(f"[LavalinkVC] VOICE_SERVER_UPDATE: endpoint={endpoint}")
        

        lavalink = self._get_lavalink()
        if lavalink and self._token and self._endpoint:
            voice = lavalink.node.get_voice(self._guild.id)
            voice.token = self._token
            voice.endpoint = self._endpoint
            _log.info(f"[LavalinkVC] Updated token/endpoint to Node")
        
        self._connected.set()

    async def on_voice_state_update(self, data: dict):
        channel_id = data.get("channel_id")
        session_id = data.get("session_id")
        
        if channel_id is None:
            _log.info(f"[LavalinkVC] Left voice channel")
            self._connected.clear()
            await self.disconnect(force=True)
        else:
            self._session_id = session_id
            _log.info(f"[LavalinkVC] VOICE_STATE_UPDATE: channel={channel_id}, session={session_id}")
            lavalink = self._get_lavalink()
            if lavalink and session_id:
                voice = lavalink.node.get_voice(self._guild.id)
                voice.session_id = session_id
                _log.info(f"[LavalinkVC] Updated session_id to Node")

    async def connect(self, *, timeout: float = 30.0, reconnect: bool = True, self_deaf: bool = False, self_mute: bool = False) -> None:
        _log.info(f"[LavalinkVC] Joining voice channel {self.channel.id}...")
        await self._guild.change_voice_state(
            channel=self.channel,
            self_mute=self_mute,
            self_deaf=self_deaf
        )
        
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            _log.info(f"[LavalinkVC] Joined voice channel {self.channel.id}")
        except asyncio.TimeoutError:
            _log.warning(f"[LavalinkVC] Join voice channel timeout")
            raise discord.errors.ConnectionClosed(None, None, 4006)

    async def disconnect(self, *, force: bool = False) -> None:
        _log.info(f"[LavalinkVC] Leaving voice channel...")
        try:
            await self._guild.change_voice_state(channel=None)
        except Exception as e:
            if not force:
                raise
            _log.warning(f"[LavalinkVC] Error leaving voice channel: {e}")
        finally:
            self._connected.clear()
            self.cleanup()

    def cleanup(self) -> None:
        pass

    async def move_to(self, channel: Optional[discord.VoiceChannel]) -> None:
        if channel is None:
            await self.disconnect()
        else:
            self.channel = channel
            await self._guild.change_voice_state(channel=channel)
            _log.info(f"[LavalinkVC] Moved to voice channel {channel.id}")

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()
