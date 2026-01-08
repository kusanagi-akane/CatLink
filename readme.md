# CatLink

一個輕量、框架無關的 Lavalink v3/v4 客戶端，專為 discord.py 設計。

## 特點

- 支援 Lavalink v3 和 v4
- 內建播放佇列管理
- 單曲循環支援
- 音量控制 (0-1000%)
- 進度搜尋 (Seek)
- 事件系統 (track_start, track_end 等)
- 與 discord.py 無縫整合

## 安裝

```bash
pip install -e ./CatLink
```

或直接在 `requirements.txt` 中加入：
```
-e ./CatLink
```

## 依賴

- Python >= 3.9
- aiohttp
- websockets
- discord.py >= 2.0

## 快速開始

### 1. 初始化客戶端

```python
import discord
from discord.ext import commands
from CatLink import LavalinkClient, LavalinkVoiceClient

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

@bot.event
async def on_ready():
    bot.lavalink = LavalinkClient(
        bot=bot,
        host="localhost",      # Lavalink 伺服器地址
        port=2333,             # Lavalink 伺服器端口
        password="youshallnotpass",  # Lavalink 密碼
        user_id=bot.user.id,
        version=4              # Lavalink 版本 (3 或 4)
    )
    await bot.lavalink.connect()
    print(f"{bot.user} 已上線！")
```

### 2. 播放音樂

```python
@bot.command()
async def play(ctx, *, query: str):
    # 加入語音頻道
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect(cls=LavalinkVoiceClient)
    
    # 搜尋並播放
    track = await bot.lavalink.load_track(query, source="ytsearch")
    if track:
        player = bot.lavalink.get_player(ctx.guild.id)
        await player.play(track)
        await ctx.send(f"🎵 正在播放: {track.title}")
```

### 3. 基本控制

```python
@bot.command()
async def skip(ctx):
    player = bot.lavalink.get_player(ctx.guild.id)
    await player.skip()

@bot.command()
async def pause(ctx):
    player = bot.lavalink.get_player(ctx.guild.id)
    await player.pause()

@bot.command()
async def resume(ctx):
    player = bot.lavalink.get_player(ctx.guild.id)
    await player.resume()

@bot.command()
async def stop(ctx):
    player = bot.lavalink.get_player(ctx.guild.id)
    await player.stop()
    if ctx.voice_client:
        await ctx.voice_client.disconnect()

@bot.command()
async def volume(ctx, vol: int):
    player = bot.lavalink.get_player(ctx.guild.id)
    await player.set_volume(vol)

@bot.command()
async def loop(ctx):
    player = bot.lavalink.get_player(ctx.guild.id)
    player.loop = not player.loop
    await ctx.send(f"🔁 循環: {'開啟' if player.loop else '關閉'}")
```

## Player API

| 方法 | 說明 |
|------|------|
| `play(track, replace=False)` | 播放或加入佇列 |
| `skip()` | 跳過當前歌曲 |
| `stop()` | 停止播放並清空佇列 |
| `pause()` | 暫停播放 |
| `resume()` | 恢復播放 |
| `set_volume(volume)` | 設定音量 (0-1000) |
| `seek(position_ms)` | 跳轉到指定位置 |

| 屬性 | 說明 |
|------|------|
| `current` | 當前播放的曲目 |
| `queue` | 播放佇列 (deque) |
| `is_playing` | 是否正在播放 |
| `paused` | 是否暫停中 |
| `volume` | 當前音量 |
| `position` | 當前播放位置 (ms) |
| `loop` | 是否單曲循環 |

## 事件系統

```python
@bot.lavalink.on("track_start")
async def on_track_start(event):
    print(f"開始播放: {event.track.title}")

@bot.lavalink.on("track_end")
async def on_track_end(event):
    print(f"播放結束: {event.reason}")

@bot.lavalink.on("player_update")
async def on_player_update(event):
    print(f"位置更新: {event.state.get('position')}ms")
```

## 搜尋來源

```python
# YouTube 搜尋
track = await bot.lavalink.load_track("never gonna give you up", source="ytsearch")

# Spotify 搜尋 (需要 LavaSrc 插件)
track = await bot.lavalink.load_track("never gonna give you up", source="spsearch")

# 直接 URL
track = await bot.lavalink.load_track("https://youtube.com/watch?v=...")

# 多結果搜尋
tracks = await bot.lavalink.search_tracks("query", source="ytsearch", limit=10)
```

## 專案結構

```
CatLink/
├── src/
│   └── CatLink/
│       ├── __init__.py      # 匯出 LavalinkClient, LavalinkVoiceClient
│       ├── client.py        # 主客戶端
│       ├── player.py        # 播放器與佇列管理
│       ├── node.py          # Lavalink 節點連線
│       ├── rest.py          # REST API 客戶端
│       ├── websocket.py     # WebSocket 連線
│       ├── voice_client.py  # Discord 語音協議
│       ├── voice.py         # 語音狀態管理
│       ├── models.py        # 資料模型 (Track 等)
│       ├── events.py        # 事件定義
│       └── errors.py        # 錯誤定義
└── pyproject.toml
```

## 授權

由 kusanagi_akane 開發
---

# SimpleBot - 音樂機器人範例

基於 CatLink 的完整 Discord 音樂機器人，支援 Slash Commands 和 Components V2 UI。

## 🎵 功能

- `/play <query>` - 播放音樂（支援搜尋或 URL）
- `/skip` - 跳過當前歌曲
- `/stop` - 停止播放並離開頻道
- `/pause` - 暫停播放
- `/resume` - 恢復播放
- `/loop` - 切換單曲循環
- `/volume <0-1000>` - 調整音量
- `/nowplaying` - 顯示正在播放（含控制面板）
- `/queue` - 查看播放清單（Components V2 UI）
- `/setpanel` - 設定自動面板頻道

## 📦 安裝

1. 安裝依賴：
```bash
pip install -r requirements.txt
```

2. 設定 `config.py`：
```python
# config.py

TOKEN = "your_bot_token"           # Discord Bot Token
APPLICATION_ID = "your_app_id"     # Application ID

LAVALINK_HOST = "localhost"        # Lavalink 伺服器地址
LAVALINK_PORT = 2333               # Lavalink 伺服器端口
LAVALINK_PASSWORD = "youshallnotpass"  # Lavalink 密碼
```

3. 啟動機器人：
```bash
python main.py
```

## 📁 專案結構

```
SimpleBot/
├── main.py          # 機器人主程式
├── config.py        # 設定檔
└── cogs/
    └── music.py     # 音樂指令模組
```

## 🎛️ UI 元件

### 播放面板 (PlayerControlsView)
- ⏯ 暫停/播放
- ⏭ 跳過
- ⏹ 停止
- 🔉 -10 / 🔊 +10 音量控制
- 🔁 循環開關

### 播放清單 (QueueLayoutView)
使用 Discord Components V2：
- Container + TextDisplay 顯示佇列
- ActionRow + Select 選擇刪除歌曲
- ActionRow + Button 分頁控制

## ⚙️ 需求

- Python >= 3.10
- discord.py >= 2.6 (Components V2 支援)
- Lavalink Server v4
- CatLink 套件

## 🔧 Lavalink 設定

需要運行 Lavalink 伺服器，建議設定：

```yaml
# application.yml
server:
  port: 2333
  address: 0.0.0.0

lavalink:
  server:
    password: "youshallnotpass"
    sources:
      youtube: true
      soundcloud: true
    # 如需 Spotify，安裝 LavaSrc 插件
```

## 注意事項

1. **Lavalink v4** 推薦使用，v3 也支援但部分 API 不同
2. **LavaLink LavaSrc插件** 可支援 Spotify、Apple Music 等來源