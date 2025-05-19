import discord
from discord.ext import commands, tasks
import requests
import json
import os
from flask import Flask
from threading import Thread

# ==== Flask keep_alive サーバー ====
app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run).start()

# ==== Bot 設定 ====
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

CONFIG_FILE = "config.json"
config = {}
last_video_ids = {}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ==== YouTube 最新動画情報を取得（ライブ配信も対応） ====
def get_latest_video_info(channel_id):
    url = (
        f"https://www.googleapis.com/youtube/v3/search"
        f"?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id"
        f"&order=date&maxResults=1&type=video"
    )
    response = requests.get(url).json()
    if "items" not in response or not response["items"]:
        raise Exception("動画が見つかりません")
    video = response["items"][0]
    video_id = video["id"]["videoId"]
    title = video["snippet"]["title"]
    broadcast_type = video["snippet"].get("liveBroadcastContent", "none")
    return video_id, title, broadcast_type

# ==== Bot 起動時処理 ====
@bot.event
async def on_ready():
    global config
    config = load_config()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    check_new_videos.start()

# ==== スラッシュコマンド: /subscribe ====
@bot.tree.command(name="subscribe", description="YouTubeチャンネルの通知設定をする")
@discord.app_commands.describe(
    youtube_channel_id="通知したいYouTubeチャンネルのID",
    notify_channel="通知を送るDiscordチャンネル"
)
async def subscribe(interaction: discord.Interaction, youtube_channel_id: str, notify_channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    config[guild_id] = {
        "channel_id": youtube_channel_id,
        "notify_channel": notify_channel.id
    }
    save_config(config)
    await interaction.response.send_message(
        f"✅ 通知設定完了！\nYouTubeチャンネルID: `{youtube_channel_id}`\n通知先: {notify_channel.mention}",
        ephemeral=True
    )

# ==== スラッシュコマンド: /check_now（手動チェック） ====
@bot.tree.command(name="check_now", description="今すぐ新しい動画をチェックする")
async def check_now(interaction: discord.Interaction):
    await interaction.response.send_message("🔍 チェック中...", ephemeral=True)
    await run_check()

# ==== 通知チェック関数 ====
async def run_check():
    for guild_id, settings in config.items():
        channel_id = settings["channel_id"]
        notify_channel_id = settings["notify_channel"]
        try:
            video_id, title, broadcast_type = get_latest_video_info(channel_id)
            if last_video_ids.get(guild_id) != video_id:
                last_video_ids[guild_id] = video_id
                channel = bot.get_channel(notify_channel_id)
                if channel:
                    if broadcast_type == "live":
                        await channel.send(f"🔴 ライブ配信が開始されました！\n**{title}**\nhttps://www.youtube.com/watch?v={video_id}")
                    else:
                        await channel.send(f"🎥 新しい動画が公開されました！\n**{title}**\nhttps://www.youtube.com/watch?v={video_id}")
        except Exception as e:
            print(f"[エラー] Guild {guild_id}: {e}")

@tasks.loop(minutes=5)
async def check_new_videos():
    await run_check()

# ==== 起動処理 ====
if __name__ == "__main__":
    keep_alive()  # FlaskでHTTPサーバー起動（Render用）
    bot.run(DISCORD_TOKEN)
