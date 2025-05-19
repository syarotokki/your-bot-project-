import os
import json
import discord
import requests
import asyncio
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timezone
from flask import Flask
from threading import Thread

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CONFIG_FILE = "config.json"

# 永続サーバー維持のための Flask サーバー
app = Flask('')
@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run).start()

# 設定ファイル読み書き
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

config = load_config()

# YouTube API で最新動画を取得
def get_latest_videos(channel_id, max_results=10):
    url = (
        f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}"
        f"&channelId={channel_id}&part=snippet,id&order=date&maxResults={max_results}"
    )
    response = requests.get(url)
    if response.status_code != 200:
        return []

    data = response.json()
    videos = []
    for item in data.get("items", []):
        if item["id"]["kind"] in ["youtube#video", "youtube#liveBroadcast"]:
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            published_at = item["snippet"]["publishedAt"]
            is_live = "live" in title.lower() or item["snippet"].get("liveBroadcastContent") == "live"
            videos.append({
                "id": video_id,
                "title": title,
                "publishedAt": published_at,
                "is_live": is_live
            })
    return videos

# 通知タスク
@tasks.loop(minutes=5)
async def check_for_new_videos():
    for guild_id, guild_data in config.items():
        for channel_id in guild_data.get("subscriptions", []):
            videos = get_latest_videos(channel_id, max_results=1)
            if not videos:
                continue
            latest_video = videos[0]
            last_video_id = guild_data.get("last_video_ids", {}).get(channel_id)

            if latest_video["id"] != last_video_id:
                channel = client.get_channel(int(guild_data["notification_channel"]))
                if channel:
                    if latest_video["is_live"]:
                        await channel.send(
                            f"🔴 ライブ配信が始まりました: {latest_video['title']}\nhttps://youtu.be/{latest_video['id']}"
                        )
                    else:
                        await channel.send(
                            f"📹 新しい動画が投稿されました: {latest_video['title']}\nhttps://youtu.be/{latest_video['id']}"
                        )
                guild_data.setdefault("last_video_ids", {})[channel_id] = latest_video["id"]
    save_config(config)

@client.event
async def on_ready():
    await tree.sync()
    check_for_new_videos.start()
    print(f"Logged in as {client.user}")

# コマンド定義
@tree.command(name="subscribe", description="YouTubeチャンネルを通知対象として登録")
@app_commands.describe(channel_id="YouTubeのチャンネルID")
async def subscribe(interaction: discord.Interaction, channel_id: str):
    guild_id = str(interaction.guild.id)
    channel = interaction.channel

    if guild_id not in config:
        config[guild_id] = {"subscriptions": [], "notification_channel": str(channel.id), "last_video_ids": {}}

    if channel_id not in config[guild_id]["subscriptions"]:
        config[guild_id]["subscriptions"].append(channel_id)
        await interaction.response.send_message(f"✅ チャンネル {channel_id} を登録しました。")
    else:
        await interaction.response.send_message("⚠️ すでに登録されています。")
    config[guild_id]["notification_channel"] = str(channel.id)
    save_config(config)

@tree.command(name="notify_past", description="過去の動画をすべて通知")
async def notify_past(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    if guild_id not in config or not config[guild_id].get("subscriptions"):
        await interaction.response.send_message("⚠️ 登録されたチャンネルがありません。")
        return

    await interaction.response.send_message("🔄 過去の動画を確認しています。少々お待ちください。")
    for channel_id in config[guild_id]["subscriptions"]:
        videos = get_latest_videos(channel_id, max_results=10)
        if not videos:
            continue

        notify_channel = client.get_channel(int(config[guild_id]["notification_channel"]))
        for video in reversed(videos):
            if video["is_live"]:
                await notify_channel.send(f"🔴 過去のライブ配信: {video['title']}\nhttps://youtu.be/{video['id']}")
            else:
                await notify_channel.send(f"📹 過去の動画: {video['title']}\nhttps://youtu.be/{video['id']}")
        config[guild_id].setdefault("last_video_ids", {})[channel_id] = videos[0]["id"]
    save_config(config)

@tree.command(name="list_subscriptions", description="登録中のチャンネルを表示")
async def list_subscriptions(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    if guild_id not in config or not config[guild_id].get("subscriptions"):
        await interaction.response.send_message("⚠️ 登録されたチャンネルがありません。")
        return
    subs = config[guild_id]["subscriptions"]
    await interaction.response.send_message("📺 登録中のチャンネル:\n" + "\n".join(subs))

@tree.command(name="change_channel", description="通知先チャンネルを変更")
async def change_channel(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    if guild_id not in config:
        await interaction.response.send_message("⚠️ 登録情報が見つかりません。まずは /subscribe してください。")
        return
    config[guild_id]["notification_channel"] = str(interaction.channel.id)
    save_config(config)
    await interaction.response.send_message("✅ 通知先チャンネルをこのチャンネルに変更しました。")

@tree.command(name="force_notify", description="最新動画を即時通知")
async def force_notify(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    if guild_id not in config:
        await interaction.response.send_message("⚠️ 設定が存在しません。")
        return
    for channel_id in config[guild_id].get("subscriptions", []):
        videos = get_latest_videos(channel_id, max_results=1)
        if not videos:
            continue
        latest_video = videos[0]
        notify_channel = client.get_channel(int(config[guild_id]["notification_channel"]))
        if latest_video["is_live"]:
            await notify_channel.send(f"🔴 ライブ配信が始まりました: {latest_video['title']}\nhttps://youtu.be/{latest_video['id']}")
        else:
            await notify_channel.send(f"📹 新しい動画: {latest_video['title']}\nhttps://youtu.be/{latest_video['id']}")
        config[guild_id].setdefault("last_video_ids", {})[channel_id] = latest_video["id"]
    save_config(config)
    await interaction.response.send_message("✅ 強制通知を完了しました。")

@tree.command(name="reset_all_subscriptions", description="登録を全削除（管理者専用）")
async def reset_all(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ このコマンドは管理者のみ実行できます。")
        return
    guild_id = str(interaction.guild.id)
    config[guild_id] = {"subscriptions": [], "notification_channel": str(interaction.channel.id), "last_video_ids": {}}
    save_config(config)
    await interaction.response.send_message("🗑️ 登録をすべて削除しました。")

@tree.command(name="help", description="コマンドの使い方を表示")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**利用できるコマンド一覧：**\n"
        "/subscribe - YouTubeチャンネルを通知対象として登録\n"
        "/list_subscriptions - 登録中のチャンネルを表示\n"
        "/check_latest - 指定チャンネルの最新動画を確認\n"
        "/force_notify - 登録チャンネルの最新動画を即時通知\n"
        "/notify_past - 過去の動画をすべて通知\n"
        "/change_channel - 通知先チャンネルを変更\n"
        "/reset_all_subscriptions - 登録を全削除（管理者専用）\n"
        "/help - このヘルプを表示"
    )
    await interaction.response.send_message(help_text)

client.run(os.getenv("DISCORD_TOKEN"))
