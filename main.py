import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask
import requests
import os
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

CONFIG_FILE = "config.json"

# ----- Flask HTTP Server -----
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

# ----- Config Handling -----
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

# ----- YouTube API -----
def get_latest_video(channel_id):
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&order=date&part=snippet&type=video&maxResults=1"
    response = requests.get(url).json()
    items = response.get("items", [])
    if not items:
        return None
    return items[0]

def is_live_video(video):
    snippet = video.get("snippet", {})
    title = snippet.get("title", "").lower()
    return "ライブ" in title or "live" in title

def get_uploads_playlist_id(channel_id):
    url = f"https://www.googleapis.com/youtube/v3/channels?key={YOUTUBE_API_KEY}&id={channel_id}&part=contentDetails"
    response = requests.get(url).json()
    items = response.get("items")
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

def get_past_videos(channel_id, max_results=50):
    uploads_playlist_id = get_uploads_playlist_id(channel_id)
    if not uploads_playlist_id:
        return []

    videos = []
    next_page_token = None
    while len(videos) < max_results:
        url = f"https://www.googleapis.com/youtube/v3/playlistItems?key={YOUTUBE_API_KEY}&playlistId={uploads_playlist_id}&part=snippet&maxResults=50"
        if next_page_token:
            url += f"&pageToken={next_page_token}"
        response = requests.get(url).json()
        items = response.get("items", [])
        videos.extend(items)
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return videos[:max_results]

# ----- Commands -----
@tree.command(name="subscribe", description="通知チャンネルとYouTubeチャンネルIDを設定")
@app_commands.describe(channel_id="YouTubeチャンネルID", discord_channel="通知チャンネル")
async def subscribe(interaction: discord.Interaction, channel_id: str, discord_channel: discord.TextChannel):
    config = load_config()
    guild_id = str(interaction.guild.id)
    if guild_id not in config:
        config[guild_id] = {}
    config[guild_id][channel_id] = {
        "discord_channel_id": str(discord_channel.id),
        "last_video_id": ""
    }
    save_config(config)
    await interaction.response.send_message(f"✅ 登録しました: {channel_id} → {discord_channel.mention}")

@tree.command(name="notify_past", description="過去の動画を一括通知")
@app_commands.describe(channel_id="YouTubeチャンネルのID")
async def notify_past(interaction: discord.Interaction, channel_id: str):
    await interaction.response.defer()
    config = load_config()
    guild_id = str(interaction.guild.id)
    if guild_id not in config or channel_id not in config[guild_id]:
        await interaction.followup.send("⚠️ 登録が見つかりません。")
        return

    discord_channel_id = int(config[guild_id][channel_id]["discord_channel_id"])
    channel = client.get_channel(discord_channel_id)
    videos = get_past_videos(channel_id, 50)

    count = 0
    for video in reversed(videos):
        snippet = video["snippet"]
        video_id = snippet["resourceId"]["videoId"]
        title = snippet["title"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            await channel.send(f"📺 過去動画：**{title}**\n{url}")
            count += 1
        except Exception as e:
            print(f"送信失敗: {e}")

    await interaction.followup.send(f"✅ {count} 件の動画を通知しました。")

# ----- Periodic Check -----
@tasks.loop(minutes=5)
async def check_new_videos():
    await client.wait_until_ready()
    config = load_config()
    for guild_id, channels in config.items():
        for channel_id, data in channels.items():
            latest_video = get_latest_video(channel_id)
            if not latest_video:
                continue

            video_id = latest_video["id"]["videoId"]
            last_video_id = data.get("last_video_id")
            if video_id == last_video_id:
                continue

            data["last_video_id"] = video_id
            save_config(config)

            discord_channel = client.get_channel(int(data["discord_channel_id"]))
            title = latest_video["snippet"]["title"]
            url = f"https://www.youtube.com/watch?v={video_id}"
            published = latest_video["snippet"]["publishedAt"]

            if is_live_video(latest_video):
                msg = f"🔴 **ライブ配信が始まりました！**\n📺 {title}\n🕒 {published}\n{url}"
            else:
                msg = f"📢 **新しい動画が投稿されました！**\n📺 {title}\n{url}"

            try:
                await discord_channel.send(msg)
            except Exception as e:
                print(f"送信失敗: {e}")

# ----- Startup -----
@client.event
async def on_ready():
    await tree.sync()
    check_new_videos.start()
    print(f"Logged in as {client.user}")

# Flask for uptime
def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    import threading
    threading.Thread(target=run_flask).start()
    client.run(DISCORD_TOKEN)
