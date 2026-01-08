import asyncio
import json
import logging
import sys
import aiohttp

_log = logging.getLogger(__name__)


WS_TIMEOUT = aiohttp.ClientTimeout(
    total=None, 
    connect=15,
    sock_connect=10,
    sock_read=None
)

class LavalinkWebSocket:
    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        user_id: int,
        session_id: str,
        handler,
        secure: bool = False,
        version: int = 4
    ):
        protocol = "wss" if secure else "ws"
        if version == 4:
            self.uri = f"{protocol}://{host}:{port}/v4/websocket"
        else:
            self.uri = f"{protocol}://{host}:{port}/v3/websocket"

        self.headers = {
            "Authorization": password,
            "User-Id": str(user_id),
            "Client-Name": "lavalink_simple",
        }
        
        if version == 4 and session_id:
            self.headers["Session-Id"] = session_id
            
        self.handler = handler
        self._running = True
        self.ws = None
        self.session = None

    async def connect(self):
        import socket
        family = socket.AF_INET if sys.platform == 'win32' else socket.AF_UNSPEC
        conn = aiohttp.TCPConnector(
            family=family,
            limit=5,
            ttl_dns_cache=300,
            enable_cleanup_closed=True
        )
        self.session = aiohttp.ClientSession(connector=conn, timeout=WS_TIMEOUT)
        
        while self._running:
            try:
                _log.info(f"Connecting to WS: {self.uri}")
                async with self.session.ws_connect(
                    self.uri, 
                    headers=self.headers, 
                    heartbeat=15.0, 
                    timeout=15.0, 
                    receive_timeout=None 
                ) as ws:
                    self.ws = ws
                    _log.info("WebSocket connected!")
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                await self.handler(json.loads(msg.data))
                            except Exception as e:
                                _log.error(f"Error handling WS message: {e}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            _log.warning(f"WebSocket closed: {msg}")
                            break
                            
            except Exception as e:
                _log.error(f"[Lavalink WS] reconnecting in 5s: {e}")
                await asyncio.sleep(5)
        
        if self.session:
            await self.session.close()

    async def send(self, payload: dict):
        if self.ws and not self.ws.closed:
            await self.ws.send_json(payload)
        else:
            _log.warning("WebSocket is not connected, dropping payload")

    def close(self):
        self._running = False
