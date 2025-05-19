import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import requests
import asyncio
from datetime import datetime
from keep_alive import keep_alive

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

CONFIG_FILE = "config.json"

# config.json を読み込む（存在しない場合は初期化）
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        json.dump({}, f)

with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHECK_INTERVAL = 300  # 秒

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def fetch_videos(channel_id, max_results=50):
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults={max_results}"
    response = requests.get(url)
    if response.status_code != 200:
        return []
    data = response.json()
    return data.get("items", [])

def get_video_info(item):
    video_id = item["id"].get("videoId")
    if not video_id:
        return None

    is_live = item["snippet"].get("liveBroadcastContent") == "live"
    title = item["snippet"]["title"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    published = item["snippet"]["publishedAt"]
    return {
        "video_id": video_id,
        "title": title,
        "url": url,
        "is_live": is_live,
        "published": published
    }

@tree.command(name="subscribe", description="YouTubeチャンネルを登録して通知を受け取る")
@app_commands.describe(channel_id="YouTubeのチャンネルID")
async def subscribe(interaction: discord.Interaction, channel_id: str):
    guild_id = str(interaction.guild_id)
    channel = interaction.channel

    config[guild_id] = {
        "channel_id": channel_id,
        "notify_channel": channel.id,
        "notified_ids": []
    }
    save_config()

    await interaction.response.send_message(f"✅ 登録完了！チャンネルID: `{channel_id}`", ephemeral=True)

@tree.command(name="notify_past", description="過去のすべての動画を通知する")
async def notify_past(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    if guild_id not in config:
        await interaction.response.send_message("⚠️ このサーバーではまだ /subscribe されていません。", ephemeral=True)
        return

    data = config[guild_id]
    items = fetch_videos(data["channel_id"], max_results=50)
    notify_channel = bot.get_channel(data["notify_channel"])

    notified_ids = set(data.get("notified_ids", []))
    new_ids = []

    for item in reversed(items):  # 古い順に通知
        info = get_video_info(item)
        if info and info["video_id"] not in notified_ids:
            msg = f"🎥 過去の動画: [{info['title']}]({info['url']})"
            await notify_channel.send(msg)
            new_ids.append(info["video_id"])

    data["notified_ids"].extend(new_ids)
    save_config()
    await interaction.response.send_message(f"✅ {len(new_ids)} 件の動画を通知しました。", ephemeral=True)

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_for_new_videos():
    for guild_id, data in config.items():
        items = fetch_videos(data["channel_id"], max_results=1)
        if not items:
            continue

        info = get_video_info(items[0])
        if not info:
            continue

        notified_ids = data.get("notified_ids", [])
        if info["video_id"] in notified_ids:
            continue

        # 新着動画判定：公開時間がチェック間隔以内 or リストに入っていない
        published_time = datetime.strptime(info["published"], "%Y-%m-%dT%H:%M:%SZ")
        now = datetime.utcnow()
        if (now - published_time).total_seconds() > 3600:
            continue  # 1時間以上前の動画はスキップ（再起動時の誤通知防止）

        channel = bot.get_channel(data["notify_channel"])
        if channel:
            if info["is_live"]:
                msg = f"🔴 ライブ配信が始まりました: [{info['title']}]({info['url']})"
            else:
                msg = f"🎬 新しい動画が投稿されました: [{info['title']}]({info['url']})"
            await channel.send(msg)

        data["notified_ids"].append(info["video_id"])
        save_config()

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    await tree.sync()
    check_for_new_videos.start()

# 起動部分
if __name__ == "__main__":
    keep_alive()  # Flaskで生存確認用サーバー起動
    print("✅ Flaskサーバー起動完了")
    try:
        bot.run(os.getenv("DISCORD_TOKEN"))
    except Exception as e:
        print(f"❌ Bot起動失敗: {e}")

