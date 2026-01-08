import discord
import config
import logging
from discord.ext import commands
from CatLink import LavalinkClient

logging.basicConfig(level=logging.INFO)

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix="!", 
            intents=intents,
            application_id=config.APPLICATION_ID
        )
        self.lavalink: LavalinkClient = None

    async def setup_hook(self):
        self.lavalink = LavalinkClient(
            self,
            host=config.LAVALINK_HOST,
            port=config.LAVALINK_PORT,
            password=config.LAVALINK_PASSWORD,
            user_id=self.application_id,
            version=4 #lavalink version
        )
        try:
            await self.load_extension("cogs.music")
            print("[Music] cogs.music Loaded successfully.")
        except Exception as e:
            print(f"[Music] Error loading cogs.music: {e}")
        await self.tree.sync() 
        print("[INFO] Command tree synced.")

    async def on_ready(self):
        print(f"Login in: {self.user} (ID: {self.user.id})")
        
        self.lavalink.node.user_id = self.user.id
        if hasattr(self.lavalink, "rest") and hasattr(self.lavalink.rest, "headers"):
            self.lavalink.rest.headers["User-Id"] = str(self.user.id)
        

        await self.lavalink.connect()
        print("Lavalink connecteing...")

if __name__ == "__main__":
    bot = MusicBot()
    bot.run(config.TOKEN)
