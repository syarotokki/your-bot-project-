import discord
from discord.ext import commands, tasks
from flask import Flask
import threading
import requests
import json
import os

# Flaskアプリ（Render無料プランのスリープ防止用）
app = Flask(__name__)
@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# Discord Bot 初期設定
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CONFIG_FILE = "config.json"
config = {}
last_video_ids = {}

# 設定ファイルの読み込み・保存
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Bot起動時処理
@bot.event
async def on_ready():
    global config
    config = load_config()
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")
    check_new_videos.start()

# スラッシュコマンド：/subscribe
@tree.command(name="subscribe", description="YouTubeチャンネルの通知設定をする")
@discord.app_commands.describe(
    youtube_channel_id="通知するYouTubeチャンネルのID",
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

# 最新動画取得（動画ID・タイトル・種別）
def get_latest_video(channel_id):
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
    publish_time = video["snippet"]["publishedAt"]

    # 動画の詳細情報でライブ判定
    details_url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?key={YOUTUBE_API_KEY}&id={video_id}&part=snippet,liveStreamingDetails"
    )
    details = requests.get(details_url).json()
    kind = "video"
    if "liveStreamingDetails" in details["items"][0]:
        kind = "live"
    return video_id, title, kind

# 定期タスク：新着チェック
@tasks.loop(minutes=5)
async def check_new_videos():
    for guild_id, settings in config.items():
        channel_id = settings["channel_id"]
        notify_channel_id = settings["notify_channel"]
        try:
            video_id, title, kind = get_latest_video(channel_id)
            if last_video_ids.get(guild_id) != video_id:
                last_video_ids[guild_id] = video_id
                channel = bot.get_channel(notify_channel_id)
                if channel:
                    if kind == "live":
                        msg = f"🔴 **ライブ配信が始まりました！**\n**{title}**\nhttps://www.youtube.com/watch?v={video_id}"
                    else:
                        msg = f"🎥 **新しい動画が公開されました！**\n**{title}**\nhttps://www.youtube.com/watch?v={video_id}"
                    await channel.send(msg)
        except Exception as e:
            print(f"[エラー] Guild {guild_id}: {e}")

# Flask起動スレッド
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(DISCORD_TOKEN)
