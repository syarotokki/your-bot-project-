import discord
from discord.ext import commands, tasks
import requests
import json
import os
from flask import Flask

# Botの設定
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
app = Flask(__name__)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

CONFIG_FILE = "config.json"
LAST_IDS_FILE = "last_ids.json"

config = {}
last_video_ids = {}

# FlaskでRenderをスリープさせない
@app.route("/")
def home():
    return "Bot is running!"

# JSONファイルの読み書き
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

# 起動時処理
@bot.event
async def on_ready():
    global config, last_video_ids
    config = load_json(CONFIG_FILE)
    last_video_ids = load_json(LAST_IDS_FILE)
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    check_new_videos.start()

# スラッシュコマンド: /subscribe
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
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(
        f"✅ 通知設定完了！\nYouTubeチャンネルID: `{youtube_channel_id}`\n通知先: {notify_channel.mention}",
        ephemeral=True
    )

# /list_settings コマンド
@bot.tree.command(name="list_settings", description="現在の通知設定を表示する")
async def list_settings(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    if guild_id in config:
        data = config[guild_id]
        await interaction.response.send_message(
            f"📌 現在の設定:\nYouTubeチャンネルID: `{data['channel_id']}`\n通知先: <#{data['notify_channel']}>",
            ephemeral=True
        )
    else:
        await interaction.response.send_message("❌ このサーバーには設定がありません。", ephemeral=True)

# /notify_past コマンド
@bot.tree.command(name="notify_past", description="過去の動画を一括通知する")
async def notify_past(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    if guild_id not in config:
        await interaction.response.send_message("❌ このサーバーには設定がありません。", ephemeral=True)
        return

    await interaction.response.send_message("🔍 過去動画を取得中...", ephemeral=True)

    channel_id = config[guild_id]["channel_id"]
    notify_channel = bot.get_channel(config[guild_id]["notify_channel"])
    videos = get_latest_videos(channel_id, count=5)

    for video in reversed(videos):
        msg = build_video_message(video)
        await notify_channel.send(msg)

    await interaction.followup.send("✅ 過去の動画を通知しました。", ephemeral=True)

# 動画情報の取得（複数件）
def get_latest_videos(channel_id, count=1):
    url = (
        f"https://www.googleapis.com/youtube/v3/search"
        f"?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id"
        f"&order=date&maxResults={count}"
    )
    response = requests.get(url).json()
    items = response.get("items", [])
    videos = []

    for item in items:
        if item["id"]["kind"] == "youtube#video":
            video = {
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "is_live": "live" in item["snippet"]["title"].lower()
            }
            videos.append(video)
    return videos

# 通知文を作成
def build_video_message(video):
    if video["is_live"]:
        return f"🔴 **ライブ配信が始まりました！**\n{video['title']}\nhttps://www.youtube.com/watch?v={video['video_id']}"
    else:
        return f"🎥 **新しい動画が公開されました！**\n{video['title']}\nhttps://www.youtube.com/watch?v={video['video_id']}"

# 定期チェック
@tasks.loop(minutes=5)
async def check_new_videos():
    for guild_id, settings in config.items():
        channel_id = settings["channel_id"]
        notify_channel_id = settings["notify_channel"]
        try:
            latest = get_latest_videos(channel_id, count=1)[0]
            if last_video_ids.get(guild_id) != latest["video_id"]:
                last_video_ids[guild_id] = latest["video_id"]
                save_json(LAST_IDS_FILE, last_video_ids)
                channel = bot.get_channel(notify_channel_id)
                if channel:
                    await channel.send(build_video_message(latest))
        except Exception as e:
            print(f"[エラー] Guild {guild_id}: {e}")

# Flask起動（Render用）
if __name__ == "__main__":
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()
    bot.run(DISCORD_TOKEN)
