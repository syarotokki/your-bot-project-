import os
import json
import asyncio
import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask
from threading import Thread
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
config_file = "config.json"

app = Flask(__name__)

# --- Flask server for keep-alive ---
@app.route("/")
def home():
    return "Bot is alive!"

def keep_alive():
    Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

# --- Utility Functions ---
def load_config():
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)

def fetch_latest_video(channel_id, api_key):
    url = (
        f"https://www.googleapis.com/youtube/v3/search?key={api_key}"
        f"&channelId={channel_id}&part=snippet,id&order=date&maxResults=1"
    )
    res = requests.get(url).json()
    if "items" not in res or not res["items"]:
        return None
    item = res["items"][0]
    if item["id"]["kind"] == "youtube#video":
        return {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "is_live": False,
        }
    elif item["id"]["kind"] == "youtube#liveBroadcast":
        return {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "is_live": True,
        }
    return None

# --- Slash Command ---
@bot.tree.command(name="subscribe", description="YouTubeチャンネルを登録して通知")
@app_commands.describe(youtube_channel_id="YouTubeのチャンネルID", notify_channel="通知先チャンネル")
async def subscribe(interaction: discord.Interaction, youtube_channel_id: str, notify_channel: discord.TextChannel):
    config = load_config()
    guild_id = str(interaction.guild.id)
    config[guild_id] = {
        "youtube_channel_id": youtube_channel_id,
        "notify_channel_id": notify_channel.id,
        "last_video_id": ""
    }
    save_config(config)
    await interaction.response.send_message("✅ 登録完了！最新動画をチェックします。")

# --- Background Task ---
@tasks.loop(minutes=5)
async def check_new_videos():
    await bot.wait_until_ready()
    config = load_config()
    api_key = os.getenv("YOUTUBE_API_KEY")
    for guild_id, data in config.items():
        youtube_channel_id = data["youtube_channel_id"]
        notify_channel_id = data["notify_channel_id"]
        last_video_id = data.get("last_video_id", "")

        video = fetch_latest_video(youtube_channel_id, api_key)
        if video and video["video_id"] != last_video_id:
            channel = bot.get_channel(notify_channel_id)
            if channel:
                if video["is_live"]:
                    embed = discord.Embed(
                        title="🔴 ライブ配信が始まりました！",
                        description=f"[{video['title']}](https://youtu.be/{video['video_id']})\n開始時刻: {video['published_at']}",
                        color=discord.Color.red()
                    )
                else:
                    embed = discord.Embed(
                        title="📢 新しい動画が投稿されました！",
                        description=f"[{video['title']}](https://youtu.be/{video['video_id']})",
                        color=discord.Color.blue()
                    )
                await channel.send(embed=embed)
                config[guild_id]["last_video_id"] = video["video_id"]
    save_config(config)

# --- 起動処理 ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Botとしてログインしました: {bot.user}")
    check_new_videos.start()

# --- 実行部 ---
if __name__ == "__main__":
    keep_alive()
    print("✅ Flaskサーバー起動完了")

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN が取得できません。Render の環境変数を確認してください。")
    else:
        try:
            print("🟢 Bot 起動を試みます...")
            bot.run(token)
        except Exception as e:
            print(f"❌ Bot起動失敗: {e}")
