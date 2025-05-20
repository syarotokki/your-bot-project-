import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask
import requests
import json
import os
import threading

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CONFIG_FILE = "config.json"

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.decoder.JSONDecodeError):
        return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def fetch_channel_videos(channel_id, max_results=50):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "channelId": channel_id,
        "part": "snippet",
        "order": "date",
        "maxResults": max_results
    }
    response = requests.get(url, params=params)
    data = response.json()
    if "items" not in data:
        return []
    return data["items"]

def extract_video_info(item):
    kind = item["id"]["kind"]
    video_id = item["id"].get("videoId") or item["id"].get("playlistId")
    snippet = item["snippet"]
    title = snippet["title"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    timestamp = snippet["publishedAt"]
    return {
        "kind": kind,
        "video_id": video_id,
        "title": title,
        "url": url,
        "timestamp": timestamp
    }

@tree.command(name="subscribe", description="YouTubeチャンネルの通知を登録します")
@app_commands.describe(channel_id="YouTubeのチャンネルID", notify_channel="通知を送るDiscordチャンネル")
async def subscribe(interaction: discord.Interaction, channel_id: str, notify_channel: discord.TextChannel):
    config = load_config()
    guild_id = str(interaction.guild.id)

    config[guild_id] = {
        "channel_id": channel_id,
        "notify_channel_id": str(notify_channel.id),
        "latest_video_id": ""
    }

    save_config(config)
    await interaction.response.send_message(
        f"✅ 登録が完了しました！\n通知チャンネル: {notify_channel.mention}\nYouTubeチャンネルID: `{channel_id}`",
        ephemeral=True
    )

@tree.command(name="notify_latest", description="その時点で最新の動画を通知します")
async def notify_latest(interaction: discord.Interaction):
    config = load_config()
    guild_id = str(interaction.guild.id)

    if guild_id not in config:
        await interaction.response.send_message("❌ まずは `/subscribe` で登録してください。", ephemeral=True)
        return

    channel_id = config[guild_id]["channel_id"]
    notify_channel_id = int(config[guild_id]["notify_channel_id"])
    items = fetch_channel_videos(channel_id, max_results=1)

    if not items:
        await interaction.response.send_message("⚠️ 動画が取得できませんでした。", ephemeral=True)
        return

    video = extract_video_info(items[0])
    notify_channel = client.get_channel(notify_channel_id)

    if video["kind"] == "youtube#video":
        if "ライブ" in video["title"] or "LIVE" in video["title"]:
            msg = f"🔴 ライブ配信が始まりました！\n**{video['title']}**\n{video['url']}"
        else:
            msg = f"📢 新しい動画が投稿されました！\n**{video['title']}**\n{video['url']}"
        await notify_channel.send(msg)
        config[guild_id]["latest_video_id"] = video["video_id"]
        save_config(config)
        await interaction.response.send_message("✅ 通知を送信しました。", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 動画以外の投稿でした。", ephemeral=True)

@tree.command(name="notify_past", description="過去の動画をすべて通知します")
async def notify_past(interaction: discord.Interaction):
    config = load_config()
    guild_id = str(interaction.guild.id)

    if guild_id not in config:
        await interaction.response.send_message("❌ まずは `/subscribe` で登録してください。", ephemeral=True)
        return

    await interaction.response.send_message("📡 過去の動画を取得しています...", ephemeral=True)

    channel_id = config[guild_id]["channel_id"]
    notify_channel_id = int(config[guild_id]["notify_channel_id"])
    notify_channel = client.get_channel(notify_channel_id)

    items = fetch_channel_videos(channel_id, max_results=50)
    if not items:
        await notify_channel.send("⚠️ 過去動画が見つかりませんでした。")
        return

    notified = 0
    for item in reversed(items):
        video = extract_video_info(item)
        if video["kind"] != "youtube#video":
            continue

        if "ライブ" in video["title"] or "LIVE" in video["title"]:
            msg = f"🔴 ライブ配信がありました！\n**{video['title']}**\n{video['url']}"
        else:
            msg = f"📺 過去の動画：\n**{video['title']}**\n{video['url']}"

        await notify_channel.send(msg)
        notified += 1

    await interaction.followup.send(f"✅ {notified}件の動画を通知しました。", ephemeral=True)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    try:
        synced = await tree.sync()
        print(f"🌐 Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

# Flask用サーバー起動
threading.Thread(target=run_flask).start()

# Discordボット起動
client.run(DISCORD_TOKEN)
