import os
import json
import asyncio
import requests
import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask
from threading import Thread

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CONFIG_FILE = "config.json"
CHECK_INTERVAL = 300  # 5分

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ----- 設定読み書き -----

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
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults=1"
    res = requests.get(url)
    items = res.json().get("items")
    return items[0] if items else None

def get_past_videos(channel_id, max_results=10):
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults={max_results}"
    res = requests.get(url)
    return res.json().get("items", [])

def is_live_video(video):
    return video["snippet"].get("liveBroadcastContent") == "live"

# ----- コマンド -----

@tree.command(name="subscribe", description="YouTubeチャンネルの通知設定を登録")
@app_commands.describe(channel_id="YouTubeチャンネルのID", discord_channel="通知を送るDiscordチャンネル")
async def subscribe(interaction: discord.Interaction, channel_id: str, discord_channel: discord.TextChannel):
    await interaction.response.defer()
    config = load_config()
    guild_id = str(interaction.guild.id)

    if guild_id not in config:
        config[guild_id] = {}

    config[guild_id][channel_id] = {
        "discord_channel_id": str(discord_channel.id),
        "last_video_id": ""
    }

    save_config(config)
    await interaction.followup.send(f"✅ 登録しました！ 通知先: {discord_channel.mention}")

@tree.command(name="notify_latest", description="最新の動画またはライブ配信を即時通知")
@app_commands.describe(channel_id="YouTubeチャンネルのID")
async def notify_latest(interaction: discord.Interaction, channel_id: str):
    await interaction.response.defer()
    config = load_config()
    guild_id = str(interaction.guild.id)

    if guild_id not in config or channel_id not in config[guild_id]:
        await interaction.followup.send("⚠️ 登録が見つかりません。まず `/subscribe` を行ってください。")
        return

    latest_video = get_latest_video(channel_id)
    if not latest_video:
        await interaction.followup.send("⚠️ 最新動画が取得できませんでした。")
        return

    discord_channel_id = int(config[guild_id][channel_id]["discord_channel_id"])
    discord_channel = client.get_channel(discord_channel_id)

    video_id = latest_video["id"]["videoId"]
    title = latest_video["snippet"]["title"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    published = latest_video["snippet"]["publishedAt"]

    if is_live_video(latest_video):
        msg = f"🔴 **ライブ配信が始まりました！**\n📺 {title}\n🕒 {published}\n{url}"
    else:
        msg = f"📢 **新しい動画が投稿されました！**\n📺 {title}\n{url}"

    try:
        await discord_channel.send(msg)
        await interaction.followup.send("✅ 最新動画を通知しました。")
    except Exception as e:
        print(f"通知送信エラー: {e}")
        await interaction.followup.send("⚠️ 通知の送信に失敗しました。")

@tree.command(name="notify_past", description="過去の動画を一括通知（最新10件）")
@app_commands.describe(channel_id="YouTubeチャンネルのID")
async def notify_past(interaction: discord.Interaction, channel_id: str):
    await interaction.response.defer()
    config = load_config()
    guild_id = str(interaction.guild.id)

    if guild_id not in config or channel_id not in config[guild_id]:
        await interaction.followup.send("⚠️ 登録が見つかりません。")
        return

    videos = get_past_videos(channel_id)
    if not videos:
        await interaction.followup.send("⚠️ 動画が取得できませんでした。")
        return

    discord_channel_id = int(config[guild_id][channel_id]["discord_channel_id"])
    discord_channel = client.get_channel(discord_channel_id)

    for video in reversed(videos):
        video_id = video["id"].get("videoId")
        if not video_id:
            continue
        title = video["snippet"]["title"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        published = video["snippet"]["publishedAt"]

        if is_live_video(video):
            msg = f"🔴 **ライブ配信が始まりました！（過去）**\n📺 {title}\n🕒 {published}\n{url}"
        else:
            msg = f"📢 **過去の動画**\n📺 {title}\n{url}"
        await discord_channel.send(msg)

    await interaction.followup.send("✅ 過去の動画を通知しました。")

# ----- 自動チェックタスク -----

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_new_videos():
    await client.wait_until_ready()
    config = load_config()
    for guild_id, channels in config.items():
        for channel_id, data in channels.items():
            latest_video = get_latest_video(channel_id)
            if not latest_video:
                continue

            video_id = latest_video["id"].get("videoId")
            if not video_id or video_id == data.get("last_video_id"):
                continue  # すでに通知済み

            discord_channel = client.get_channel(int(data["discord_channel_id"]))
            title = latest_video["snippet"]["title"]
            url = f"https://www.youtube.com/watch?v={video_id}"
            published = latest_video["snippet"]["publishedAt"]

            if is_live_video(latest_video):
                msg = f"🔴 **ライブ配信が始まりました！**\n📺 {title}\n🕒 {published}\n{url}"
            else:
                msg = f"📢 **新しい動画が投稿されました！**\n📺 {title}\n{url}"

            await discord_channel.send(msg)
            data["last_video_id"] = video_id

    save_config(config)

# ----- 起動処理 -----

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    await tree.sync()
    check_new_videos.start()

if __name__ == "__main__":
    Thread(target=run_flask).start()
    client.run(DISCORD_TOKEN)
