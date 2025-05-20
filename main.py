import os
import json
import asyncio
import discord
import requests
from discord.ext import tasks
from discord import app_commands
from flask import Flask
from threading import Thread
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CONFIG_FILE = "config.json"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# =============================
# Flask (for Render uptime)
# =============================
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

# =============================
# Config Load/Save
# =============================
def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({}, f)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

config = load_config()

# =============================
# YouTube Fetch Logic
# =============================
def fetch_latest_videos(channel_id):
    url = (
        f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}"
        f"&channelId={channel_id}&part=snippet,id&order=date&maxResults=5"
    )
    response = requests.get(url).json()
    return response.get("items", [])

def is_live_video(video):
    return video["snippet"].get("liveBroadcastContent") == "live"

def get_video_url(video):
    return f"https://www.youtube.com/watch?v={video['id']['videoId']}"

# =============================
# Background Task
# =============================
@tasks.loop(minutes=5)
async def check_new_videos():
    for channel_id, data in config.items():
        videos = fetch_latest_videos(channel_id)
        if not videos:
            continue

        latest_video = videos[0]
        video_id = latest_video["id"].get("videoId")
        if not video_id or video_id == data.get("last_video_id"):
            continue  # No new video

        discord_channel_id = data["discord_channel_id"]
        discord_channel = client.get_channel(discord_channel_id)
        if not discord_channel:
            continue

        video_url = get_video_url(latest_video)
        title = latest_video["snippet"]["title"]
        is_live = is_live_video(latest_video)
        published = latest_video["snippet"]["publishedAt"]
        time = datetime.fromisoformat(published.replace("Z", "+00:00")).strftime("%Y/%m/%d %H:%M")

        if is_live:
            message = f"🔴 **ライブ配信が始まりました！**\n**{title}**\n開始時刻：{time}\n{video_url}"
        else:
            message = f"🎬 **新しい動画が投稿されました！**\n**{title}**\n{video_url}"

        await discord_channel.send(message)
        config[channel_id]["last_video_id"] = video_id
        save_config(config)

# =============================
# Commands
# =============================
@tree.command(name="subscribe", description="YouTubeチャンネルを登録して通知を開始します。")
@app_commands.describe(channel_id="YouTubeのチャンネルID", discord_channel="通知先のDiscordチャンネル")
async def subscribe(interaction: discord.Interaction, channel_id: str, discord_channel: discord.TextChannel):
    config[channel_id] = {
        "discord_channel_id": discord_channel.id,
        "last_video_id": config.get(channel_id, {}).get("last_video_id")
    }
    save_config(config)
    await interaction.response.send_message(f"✅ 登録しました：{channel_id} → {discord_channel.mention}")

@tree.command(name="unsubscribe", description="登録したYouTubeチャンネルの通知を解除します。")
@app_commands.describe(channel_id="YouTubeのチャンネルID")
async def unsubscribe(interaction: discord.Interaction, channel_id: str):
    if channel_id in config:
        del config[channel_id]
        save_config(config)
        await interaction.response.send_message(f"✅ 登録解除しました：{channel_id}")
    else:
        await interaction.response.send_message("⚠️ そのチャンネルは登録されていません。")

@tree.command(name="list_subscriptions", description="登録中のチャンネルを一覧表示します。")
async def list_subscriptions(interaction: discord.Interaction):
    if not config:
        await interaction.response.send_message("📭 登録されているチャンネルはありません。")
        return
    msg = "**📋 現在登録されているチャンネル：**\n"
    for cid, data in config.items():
        msg += f"- {cid} → <#{data['discord_channel_id']}>\n"
    await interaction.response.send_message(msg)

@tree.command(name="notify_past", description="過去の動画や配信を一括で通知します。")
@app_commands.describe(channel_id="YouTubeのチャンネルID")
async def notify_past(interaction: discord.Interaction, channel_id: str):
    data = config.get(channel_id)
    if not data:
        await interaction.response.send_message("⚠️ このチャンネルは登録されていません。")
        return

    channel = client.get_channel(data["discord_channel_id"])
    if not channel:
        await interaction.response.send_message("⚠️ 通知先チャンネルが見つかりません。")
        return

    videos = fetch_latest_videos(channel_id)
    if not videos:
        await interaction.response.send_message("動画が見つかりませんでした。")
        return

    for video in reversed(videos):
        if "videoId" not in video["id"]:
            continue
        video_url = get_video_url(video)
        title = video["snippet"]["title"]
        is_live = is_live_video(video)
        published = video["snippet"]["publishedAt"]
        time = datetime.fromisoformat(published.replace("Z", "+00:00")).strftime("%Y/%m/%d %H:%M")

        if is_live:
            message = f"🔴 **ライブ配信が始まりました！**\n**{title}**\n開始時刻：{time}\n{video_url}"
        else:
            message = f"🎬 **過去動画：**\n**{title}**\n{video_url}"
        await channel.send(message)

    await interaction.response.send_message("✅ 過去の投稿を通知しました。")

@tree.command(name="help", description="コマンド一覧と使い方を表示します。")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📘 YouTube通知Bot コマンド一覧",
        description="YouTubeの新着動画・ライブ配信をDiscordで通知するボットです。",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="/subscribe <channel_id> <discord_channel>",
        value="指定したチャンネルを登録して通知を開始します。\n🎬 通常動画 / 🔴 ライブ配信対応",
        inline=False
    )
    embed.add_field(
        name="/unsubscribe <channel_id>",
        value="通知を解除します。",
        inline=False
    )
    embed.add_field(
        name="/list_subscriptions",
        value="現在登録中のチャンネルを一覧表示します。",
        inline=False
    )
    embed.add_field(
        name="/notify_past <channel_id>",
        value="過去の投稿を一括で通知します（最大約50件）。",
        inline=False
    )
    embed.add_field(
        name="/help",
        value="このヘルプメッセージを表示します。",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =============================
# 起動処理
# =============================
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    check_new_videos.start()

client.run(DISCORD_TOKEN)
