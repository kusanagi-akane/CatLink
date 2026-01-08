import asyncio
import logging
import discord
import CatLink
from discord import app_commands
from discord.ext import commands
from discord.ui import LayoutView, Container, Section, TextDisplay, ActionRow
from CatLink import LavalinkClient, LavalinkVoiceClient
from CatLink.models import Track
from typing import List

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._log = logging.getLogger(__name__)
        self._np_channel: dict[int, int] = {}
        self._last_track_id: dict[int, str] = {}
        self._suppress_next_post: set[int] = set()
        self._panel_message: dict[int, discord.Message] = {}
        self._update_tasks: dict[int, asyncio.Task] = {}
        self._panel_track_id: dict[int, str] = {}
        try:
            self.bot.lavalink.on("track_start")(self._on_track_start)
        except Exception:
            pass

    @property
    def lavalink(self) -> LavalinkClient:
        return self.bot.lavalink

    def create_embed(self, title: str, description: str, color=discord.Color.blue()):
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="Powered by CatLink")
        return embed

    async def _disable_old_panel(self, guild_id: int):
        msg = self._panel_message.get(guild_id)
        if not msg:
            return
        try:
            view = PlayerControlsView(self.bot, guild_id)
            for child in view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            await msg.edit(view=view)
        except Exception:
            pass

    def _format_time(self, ms: int) -> str:
        ms = max(0, int(ms or 0))
        s = ms // 1000
        h = s // 3600
        m = (s % 3600) // 60
        s = s % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _progress_line(self, pos_ms: int, total_ms: int, width: int = 20) -> str:
        total_ms = max(1, int(total_ms or 1))
        pos_ms = max(0, min(int(pos_ms or 0), total_ms))
        ratio = pos_ms / total_ms
        cursor = int(ratio * width)
        cursor = min(max(0, cursor), width)
        left = "▬" * max(0, cursor - 1)
        knob = "🔘"
        right = "▬" * max(0, width - cursor)
        bar = f"{left}{knob}{right}"
        return f"{self._format_time(pos_ms)} ┃{bar}┃ {self._format_time(total_ms)}"

    def _build_nowplaying_embed(self, guild_id: int) -> discord.Embed | None:
        player = self.lavalink.get_player(guild_id)
        track = getattr(player, 'current', None)
        if not track:
            return None
        pos = getattr(player, 'position', 0)
        total = getattr(track, 'length', 0) or 0
        line = self._progress_line(pos, total)
        status = "⏸️ 暫停中" if getattr(player, 'paused', False) else "▶️ 播放中"
        color = discord.Color.orange() if player.paused else discord.Color.green()
        embed = self.create_embed("🎶 正在播放", f"[{track.title}]({track.uri})\n{status}\n{line}", color)
        embed.add_field(name="歌手", value=track.author, inline=True)
        try:
            vol = getattr(player, 'volume', 100) or 100
            loop_on = '開' if getattr(player, 'loop', False) else '關'
            qlen = len(getattr(player, 'queue', []) or [])
            info = f"音量: {vol}%\n循環: {loop_on}\n待播: {qlen} 首"
            embed.add_field(name="狀態", value=info, inline=True)
        except Exception:
            pass
        try:
            ident = getattr(track, 'identifier', None)
            uri = getattr(track, 'uri', '') or ''
            if ident and ("youtube" in uri or "youtu.be" in uri or len(str(ident)) == 11):
                embed.set_thumbnail(url=f"https://img.youtube.com/vi/{ident}/mqdefault.jpg")
        except Exception:
            pass
        return embed

    def _ensure_updater(self, guild_id: int):
        if guild_id in self._update_tasks and not self._update_tasks[guild_id].done():
            return
        self._update_tasks[guild_id] = asyncio.create_task(self._updater_loop(guild_id))

    def _find_fallback_text_channel(self, guild_id: int) -> int | None:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        for ch in guild.text_channels:
            perms = ch.permissions_for(guild.me)
            if perms and perms.send_messages:
                return ch.id
        return None

    async def _updater_loop(self, guild_id: int):
        try:
            while True:
                await asyncio.sleep(3)
                player = self.lavalink.get_player(guild_id)
                if not getattr(player, 'current', None):
                    break
                current_id = getattr(getattr(player, 'current', None), 'identifier', None)
                bound_id = self._panel_track_id.get(guild_id)
                if bound_id and current_id and current_id != bound_id:
                    break
                msg = self._panel_message.get(guild_id)
                if not msg:
                    continue
                embed = self._build_nowplaying_embed(guild_id)
                if not embed:
                    break
                try:
                    await msg.edit(embed=embed)
                except Exception:
                    try:
                        ch = msg.channel or self.bot.get_channel(msg.channel.id)
                        real = await ch.fetch_message(msg.id)
                        self._panel_message[guild_id] = real
                        await real.edit(embed=embed)
                    except Exception:
                        break
        finally:
            task = self._update_tasks.get(guild_id)
            if task:
                self._update_tasks.pop(guild_id, None)

    @app_commands.command(name="play", description="播放音樂(根據你的岩漿插件件)")
    @app_commands.describe(query="歌曲名稱或網址")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        if not interaction.user.voice:
            return await interaction.followup.send(
                embed=self.create_embed("❌ 錯誤", "請先加入語音頻道！", discord.Color.red())
            )

        target_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        try:
            if not vc:
                await target_channel.connect(cls=LavalinkVoiceClient, self_deaf=True)
                await asyncio.sleep(0.5)
            elif vc.channel != target_channel:
                await vc.move_to(target_channel)
        except Exception as e:
            return await interaction.followup.send(f"無法加入/移動語音頻道: {e}")

        is_url = query.startswith(("http://", "https://"))
        if is_url:
            track = await self.lavalink.load_track(query, source="ytsearch")
            if not track:
                return await interaction.followup.send(
                    embed=self.create_embed("🔍 找不到歌曲", f"無法載入 `{query}`。", discord.Color.orange())
                )
            player = self.lavalink.get_player(interaction.guild_id)
            await player.play(track)

            playing_now = getattr(player, 'current', None) is track
            if playing_now:
                await self._disable_old_panel(interaction.guild_id)
                embed = self._build_nowplaying_embed(interaction.guild_id) or self.create_embed("🎶 開始播放", f"[{track.title}]({track.uri})", discord.Color.green())
                view = PlayerControlsView(self.bot, interaction.guild_id)
                msg = await interaction.followup.send(embed=embed, view=view)
            else:
                pos = len(self.lavalink.get_player(interaction.guild_id).queue)
                embed = self.create_embed("✅ 已加入隊列", f"[{track.title}]({track.uri})\n目前排第 {pos} 首")
                embed.add_field(name="歌手", value=track.author, inline=True)
                try:
                    if getattr(track, 'identifier', None):
                        embed.set_thumbnail(url=f"https://img.youtube.com/vi/{track.identifier}/mqdefault.jpg")
                except Exception:
                    pass
                msg = await interaction.followup.send(embed=embed)
            self._np_channel[interaction.guild_id] = interaction.channel_id
            if playing_now:
                try:
                    sent = await interaction.original_response()
                    self._panel_message[interaction.guild_id] = sent
                    cur = getattr(self.lavalink.get_player(interaction.guild_id), 'current', None)
                    if cur and getattr(cur, 'identifier', None):
                        self._panel_track_id[interaction.guild_id] = cur.identifier
                    self._ensure_updater(interaction.guild_id)
                except Exception:
                    pass
            if not player.queue:
                if hasattr(track, 'identifier') and track.identifier:
                    self._last_track_id[interaction.guild_id] = track.identifier
                self._suppress_next_post.add(interaction.guild_id)
            return msg


        results: List[Track] = await self.lavalink.search_tracks(query, source="ytsearch", limit=10)
        if not results:
            return await interaction.followup.send(
                embed=self.create_embed("🔍 找不到歌曲", f"找不到關於 `{query}` 的結果。", discord.Color.orange())
            )

        select_view = TrackSelectView(self.bot, results)
        return await interaction.followup.send(
            embed=self.create_embed("🔎 請選擇歌曲", f"為 `{query}` 找到 {len(results)} 筆結果，請從下拉選單中選擇。"),
            view=select_view,
            ephemeral=True
        )

    @app_commands.command(name="skip", description="跳過當前歌曲")
    async def skip(self, interaction: discord.Interaction):
        player = self.lavalink.get_player(interaction.guild_id)
        if not player.is_playing and not player.queue:
            return await interaction.response.send_message("現在沒有在播放或待播的歌曲。", ephemeral=True)

        await player.skip()
        await interaction.response.send_message(
            embed=self.create_embed("⏭️ 跳過", "已跳過當前歌曲。", discord.Color.gold())
        )

    @app_commands.command(name="stop", description="停止播放並清空隊列")
    async def stop(self, interaction: discord.Interaction):
        player = self.lavalink.get_player(interaction.guild_id)
        
        await player.stop()
        player.queue.clear()
        

        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
        self._panel_message.pop(interaction.guild_id, None)
        self._panel_track_id.pop(interaction.guild_id, None)
        task = self._update_tasks.get(interaction.guild_id)
        if task:
            task.cancel()
            self._update_tasks.pop(interaction.guild_id, None)
            
        await interaction.response.send_message(
            embed=self.create_embed("⏹️ 停止", "已停止播放並斷開連線。", discord.Color.red())
        )

    @app_commands.command(name="pause", description="暫停播放")
    async def pause(self, interaction: discord.Interaction):
        player = self.lavalink.get_player(interaction.guild_id)
        await player.pause()
        await interaction.response.send_message("⏸️ 已暫停。", ephemeral=True)

    @app_commands.command(name="resume", description="恢復播放")
    async def resume(self, interaction: discord.Interaction):
        player = self.lavalink.get_player(interaction.guild_id)
        await player.resume()
        await interaction.response.send_message("▶️ 已恢復。", ephemeral=True)

    @app_commands.command(name="loop", description="切換單曲循環")
    async def loop(self, interaction: discord.Interaction):
        player = self.lavalink.get_player(interaction.guild_id)
        player.loop = not getattr(player, 'loop', False)
        await interaction.response.send_message(f"🔁 單曲循環：{'開啟' if player.loop else '關閉'}", ephemeral=True)

    @app_commands.command(name="nowplaying", description="顯示現在播放並附控制")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.lavalink.get_player(interaction.guild_id)
        if not player.current:
            return await interaction.response.send_message("目前沒有播放。", ephemeral=True)
        embed = self._build_nowplaying_embed(interaction.guild_id)
        if not embed:
            return await interaction.response.send_message("目前沒有播放。", ephemeral=True)
        view = PlayerControlsView(self.bot, interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view)
        try:
            msg = await interaction.original_response()
            self._panel_message[interaction.guild_id] = msg
            cur = getattr(self.lavalink.get_player(interaction.guild_id), 'current', None)
            if cur and getattr(cur, 'identifier', None):
                self._panel_track_id[interaction.guild_id] = cur.identifier
            self._ensure_updater(interaction.guild_id)
        except Exception:
            pass

    @app_commands.command(name="queue", description="查看播放清單")
    async def queue(self, interaction: discord.Interaction):
        player = self.lavalink.get_player(interaction.guild_id)
        if not player.queue and not player.current:
            return await interaction.response.send_message("播放清單是空的。", ephemeral=True)

        view = QueueLayoutView(self.bot, interaction.guild_id)
        await interaction.response.send_message(view=view)

    @app_commands.command(name="volume", description="調整音量 (0-1000)")
    async def volume(self, interaction: discord.Interaction, level: int):
        player = self.lavalink.get_player(interaction.guild_id)
        if level < 0 or level > 1000:
            return await interaction.response.send_message("音量必須在 0 到 1000 之間。", ephemeral=True)

        await player.set_volume(level)
        
        await interaction.response.send_message(f"🔊 音量已設定為 {level}%")


    async def _on_track_start(self, event):
        try:
            guild_id = int(event.guild_id)
        except Exception:
            return
        if guild_id in self._suppress_next_post:
            self._log.info(f"[NP] suppress once for guild={guild_id}")
            self._suppress_next_post.discard(guild_id)
            return

        channel_id = self._np_channel.get(guild_id)
        if not channel_id:
            self._log.info(f"[NP] no channel recorded for guild={guild_id}, skip")
            return

        player = self.lavalink.get_player(guild_id)
        track = getattr(player, 'current', None)
        if not track:
            self._log.info(f"[NP] no current track for guild={guild_id}, skip")
            return

        new_id = getattr(track, 'identifier', None)
        prev_id = self._last_track_id.get(guild_id)
        if new_id and prev_id and new_id == prev_id:
            self._log.info(f"[NP] same track as last (loop); guild={guild_id}, track={new_id}")
            return
        if new_id:
            self._last_track_id[guild_id] = new_id
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                self._log.warning(f"[NP] cannot fetch channel {channel_id} for guild={guild_id}")
                return

        await self._disable_old_panel(guild_id)
        await self._disable_old_panel(guild_id)
        embed = self._build_nowplaying_embed(guild_id) or self.create_embed("🎶 開始播放", f"[{track.title}]({track.uri})", discord.Color.green())
        if embed and not embed.fields:
            embed.add_field(name="歌手", value=track.author, inline=True)
        view = PlayerControlsView(self.bot, guild_id)
        try:
            msg = await channel.send(embed=embed, view=view)
            self._panel_message[guild_id] = msg
            if getattr(track, 'identifier', None):
                self._panel_track_id[guild_id] = track.identifier
            self._ensure_updater(guild_id)
            self._log.info(f"[NP] posted now-playing panel to channel={channel_id} guild={guild_id}")
        except Exception as e:
            self._log.warning(f"[NP] failed to send panel: {e}")

    @app_commands.command(name="setpanel", description="設定自動面板貼文頻道為目前頻道")
    async def setpanel(self, interaction: discord.Interaction):
        self._np_channel[interaction.guild_id] = interaction.channel_id
        await interaction.response.send_message("✅ 已設定自動面板頻道為本頻道。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))


class PlayerControlsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self._apply_state()

    def _player(self, interaction: discord.Interaction | None = None):
        gid = interaction.guild_id if interaction else self.guild_id
        return self.bot.lavalink.get_player(gid)

    def _apply_state(self):
        try:
            player = self._player()
            loop_on = getattr(player, 'loop', False)
        except Exception:
            loop_on = False
        for child in self.children:
            if isinstance(child, discord.ui.Button) and (child.label or '').startswith("🔁"):
                child.label = f"🔁 循環：{'開' if loop_on else '關'}"
                child.style = discord.ButtonStyle.success if loop_on else discord.ButtonStyle.secondary
                break

    @discord.ui.button(label="⏯ 暫停/播放", style=discord.ButtonStyle.primary)
    async def toggle_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._player(interaction)
        if getattr(player, 'paused', False):
            await player.resume()
        else:
            await player.pause()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="⏭ 跳過", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._player(interaction)
        await player.skip()
        await interaction.response.defer()

    @discord.ui.button(label="⏹ 停止", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._player(interaction)
        await player.stop()
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
        await interaction.response.defer()

    @discord.ui.button(label="🔉 -10", style=discord.ButtonStyle.secondary)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._player(interaction)
        cur = getattr(player, 'volume', 100) or 100
        await player.set_volume(max(0, cur - 10))
        await interaction.response.defer()

    @discord.ui.button(label="🔊 +10", style=discord.ButtonStyle.secondary)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._player(interaction)
        cur = getattr(player, 'volume', 100) or 100
        await player.set_volume(min(1000, cur + 10))
        await interaction.response.defer()

    @discord.ui.button(label="🔁 循環：關", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._player(interaction)
        player.loop = not getattr(player, 'loop', False)
        self._apply_state()
        await interaction.response.edit_message(view=self)


class TrackSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, tracks: List[Track]):
        self.bot = bot
        self.tracks = tracks
        options = []
        for idx, t in enumerate(tracks[:25]):
            label = (t.title or "Unknown")[:90]
            desc = (t.author or "")[:90]
            options.append(discord.SelectOption(label=label, description=desc, value=str(idx)))
        super().__init__(placeholder="選擇要播放的歌曲", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            index = int(self.values[0])
        except:
            return await interaction.response.send_message("選擇無效。", ephemeral=True)

        track = self.tracks[index]
        player = self.bot.lavalink.get_player(interaction.guild_id)
        await player.play(track)

        player_now = self.bot.lavalink.get_player(interaction.guild_id)
        playing_now = getattr(player_now, 'current', None) is track

        cog = self.bot.get_cog("MusicCog")
        if playing_now:
            if isinstance(cog, MusicCog):
                await cog._disable_old_panel(interaction.guild_id)
                embed = cog._build_nowplaying_embed(interaction.guild_id) or discord.Embed(title="🎶 開始播放", description=f"[{track.title}]({track.uri})", color=discord.Color.green())
            else:
                embed = discord.Embed(title="🎶 開始播放", description=f"[{track.title}]({track.uri})", color=discord.Color.green())
            view = PlayerControlsView(self.bot, interaction.guild_id)
            sent = await interaction.channel.send(embed=embed, view=view)
        else:
            pos = len(self.bot.lavalink.get_player(interaction.guild_id).queue)
            embed = discord.Embed(title="✅ 已加入隊列", description=f"[{track.title}]({track.uri})\n目前排第 {pos} 首", color=discord.Color.blurple())
            embed.add_field(name="歌手", value=track.author, inline=True)
            try:
                if getattr(track, 'identifier', None):
                    embed.set_thumbnail(url=f"https://img.youtube.com/vi/{track.identifier}/mqdefault.jpg")
            except Exception:
                pass
            sent = await interaction.channel.send(embed=embed)


        if isinstance(cog, MusicCog):
            cog._np_channel[interaction.guild_id] = interaction.channel_id
            if playing_now:
                cog._panel_message[interaction.guild_id] = sent
                if hasattr(track, 'identifier') and track.identifier:
                    cog._panel_track_id[interaction.guild_id] = track.identifier
                cog._ensure_updater(interaction.guild_id)
            try:
                player_now = self.bot.lavalink.get_player(interaction.guild_id)
                if getattr(player_now, 'current', None) is track:
                    if hasattr(track, 'identifier') and track.identifier:
                        cog._last_track_id[interaction.guild_id] = track.identifier
                    cog._suppress_next_post.add(interaction.guild_id)
            except Exception:
                pass


        self.disabled = True
        notice = "已開始播放。" if playing_now else "已加入隊列。"
        await interaction.response.edit_message(content=f"已選擇曲目，{notice}", view=self.view)


class TrackSelectView(discord.ui.View):
    def __init__(self, bot: commands.Bot, tracks: List[Track], timeout: float | None = 60):
        super().__init__(timeout=timeout)
        self.add_item(TrackSelect(bot, tracks))
#傻逼組件v2實作
class QueueContainer(discord.ui.Select):
    def __init__(self, parent: "QueueLayoutView", tracks: list[Track], start_index: int):
        self._parent_view = parent
        options = []
        for idx, t in enumerate(tracks, start=start_index + 1):
            title = (t.title or "Unknown")[:90]
            tlen = parent._fmt_time(getattr(t, "length", 0))
            options.append(discord.SelectOption(label=f"{idx}. {title}", description=tlen, value=str(idx)))
        placeholder = "選擇要刪除的歌曲" if options else "沒有可刪的曲目"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, disabled=not options, row=0)

    async def callback(self, interaction: discord.Interaction):
        if not self.values:
            return
        try:
            index = int(self.values[0])
        except ValueError:
            return await interaction.response.send_message("選擇無效。", ephemeral=True)
        await self._parent_view.remove_track(interaction, index)


class QueueLayoutView(LayoutView):
    def __init__(self, bot: commands.Bot, guild_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.page = max(0, page)
        self.per_page = 8
        snap = self._snapshot()
        self._build_layout(snap)

    def _player(self):
        return self.bot.lavalink.get_player(self.guild_id)

    def _fmt_time(self, ms: int) -> str:
        ms = max(0, int(ms or 0))
        s = ms // 1000
        h = s // 3600
        m = (s % 3600) // 60
        s = s % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _snapshot(self) -> dict:
        player = self._player()
        queue_list = list(player.queue)
        total = len(queue_list)
        page_count = max(1, (total + self.per_page - 1) // self.per_page)
        self.page = max(0, min(self.page, page_count - 1))
        start = self.page * self.per_page
        end = min(start + self.per_page, total)
        shown = queue_list[start:end]
        return {"player": player, "queue": queue_list, "total": total, "shown": shown, "start": start, "page_count": page_count}

    def _build_text_block(self, snap: dict) -> str:
        player = snap["player"]
        total = snap["total"]
        shown = snap["shown"]
        start = snap["start"]

        lines = []
        if getattr(player, "current", None):
            cur_len = self._fmt_time(getattr(player.current, "length", 0))
            lines.append(f"**正在播放**\n{player.current.title} | {cur_len}\n")

        if total > 0:
            lines.append(f"🎶 **{total} 首歌曲在佇列中**\n")

        if shown:
            lines.append("**下一首：**")
            for i, t in enumerate(shown, start=start + 1):
                tlen = self._fmt_time(getattr(t, "length", 0))
                lines.append(f"`{i}.` {t.title} ({tlen})")

        if not lines:
            lines.append("佇列目前為空。")

        return "\n".join(lines)

    def build_embed(self, snap: dict | None = None) -> discord.Embed:
        snap = snap or self._snapshot()
        pc = snap["page_count"]
        desc = self._build_text_block(snap)
        embed = discord.Embed(title="🎵 播放清單", description=desc, color=discord.Color.blurple())
        embed.set_footer(text=f"第 {self.page + 1}/{pc} 頁")
        return embed

    def _build_layout(self, snap: dict):
        self.clear_items()

        main_container = Container()


        main_container.add_item(TextDisplay(content=self._build_text_block(snap)))

        if snap["shown"]:
            select_row = ActionRow()
            select_row.add_item(QueueContainer(self, snap["shown"], snap["start"]))
            main_container.add_item(select_row)

        pc = snap["page_count"]
        prev_btn = discord.ui.Button(label="<", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        page_btn = discord.ui.Button(label=f"{self.page + 1}/{pc}", style=discord.ButtonStyle.primary, disabled=True)
        next_btn = discord.ui.Button(label=">", style=discord.ButtonStyle.secondary, disabled=self.page >= pc - 1)

        async def prev_cb(interaction: discord.Interaction):
            if self.page > 0:
                self.page -= 1
            await self.refresh(interaction)

        async def next_cb(interaction: discord.Interaction):
            if self.page < pc - 1:
                self.page += 1
            await self.refresh(interaction)

        prev_btn.callback = prev_cb
        next_btn.callback = next_cb

        nav_row = ActionRow()
        nav_row.add_item(prev_btn)
        nav_row.add_item(page_btn)
        nav_row.add_item(next_btn)
        main_container.add_item(nav_row)

        self.add_item(main_container)

    async def refresh(self, interaction: discord.Interaction):
        snap = self._snapshot()
        self._build_layout(snap)
        try:
            await interaction.response.edit_message(view=self)
        except discord.InteractionResponded:
            await interaction.message.edit(view=self)

    async def remove_track(self, interaction: discord.Interaction, index: int):
        player = self._player()
        queue_list = list(player.queue)
        removed = False
        target = None
        if 1 <= index <= len(queue_list):
            target = queue_list[index - 1]
        if target is not None:
            try:
                player.queue.remove(target)
                removed = True
            except Exception:
                removed = False

        snap = self._snapshot()
        self._build_layout(snap)
        try:
            await interaction.response.edit_message(view=self)
        except discord.InteractionResponded:
            await interaction.message.edit(view=self)