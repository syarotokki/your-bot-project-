import discord
from discord import app_commands
from discord.ext import commands
import requests
import json
import os
import asyncio
from flask import Flask
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"

intents = discord.Intents.default()
client = commands.Bot(command_prefix="!", intents=intents)
tree = client.tree

# FlaskサーバーでRender維持
app = Flask("")

@app.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

# 設定読み書き
def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({}, f)
    with open(CONFIG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

# YouTube動画取得
def get_latest_videos(channel_id, max_results=1):
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults={max_results}"
    response = requests.get(url).json()
    return response.get("items", [])

# 通知ループ
async def check_for_new_videos():
    await client.wait_until_ready()
    sent_video_ids = set()
    while not client.is_closed():
        config = load_config()
        for guild_id, channels in config.items():
            for yt_channel_id, data in channels.items():
                discord_channel_id = data["discord_channel_id"]
                videos = get_latest_videos(yt_channel_id, 1)
                if not videos:
                    continue
                video = videos[0]
                video_id = video["id"].get("videoId")
                if not video_id or video_id in sent_video_ids:
                    continue

                is_live = video["snippet"].get("liveBroadcastContent") == "live"
                title = video["snippet"]["title"]
                url = f"https://www.youtube.com/watch?v={video_id}"

                try:
                    channel = client.get_channel(int(discord_channel_id))
                    if channel:
                        if is_live:
                            await channel.send(f"🔴 ライブ配信が始まりました！\n**{title}**\n{url}")
                        else:
                            await channel.send(f"📺 新しい動画が公開されました！\n**{title}**\n{url}")
                        sent_video_ids.add(video_id)
                except Exception as e:
                    print(f"送信エラー: {e}")

        await asyncio.sleep(300)  # 5分おき

# --- Slash コマンド ---

@tree.command(name="subscribe", description="YouTubeチャンネルを通知対象に登録")
@app_commands.describe(channel_id="YouTubeのチャンネルID", discord_channel="通知先チャンネル")
async def subscribe(interaction: discord.Interaction, channel_id: str, discord_channel: discord.TextChannel):
    await interaction.response.defer()
    config = load_config()
    guild_id = str(interaction.guild.id)
    if guild_id not in config:
        config[guild_id] = {}
    config[guild_id][channel_id] = {"discord_channel_id": str(discord_channel.id)}
    save_config(config)
    await interaction.followup.send(f"✅ 登録しました：`{channel_id}` → {discord_channel.mention}")

@tree.command(name="unsubscribe", description="登録解除")
@app_commands.describe(channel_id="解除するYouTubeチャンネルのID")
async def unsubscribe(interaction: discord.Interaction, channel_id: str):
    await interaction.response.defer()
    config = load_config()
    guild_id = str(interaction.guild.id)
    if guild_id in config and channel_id in config[guild_id]:
        del config[guild_id][channel_id]
        save_config(config)
        await interaction.followup.send(f"✅ 解除しました：`{channel_id}`")
    else:
        await interaction.followup.send("⚠️ 登録が見つかりませんでした。")

@tree.command(name="list_subscriptions", description="現在の登録一覧を表示")
async def list_subscriptions(interaction: discord.Interaction):
    config = load_config()
    guild_id = str(interaction.guild.id)
    if guild_id in config and config[guild_id]:
        message = "**登録チャンネル一覧：**\n"
        for yt_id, data in config[guild_id].items():
            ch_id = data["discord_channel_id"]
            message += f"- `{yt_id}` → <#{ch_id}>\n"
    else:
        message = "登録はありません。"
    await interaction.response.send_message(message)

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
    videos = get_latest_videos(channel_id, 50)

    count = 0
    for video in reversed(videos):
        video_id = video["id"].get("videoId")
        if not video_id:
            continue
        is_live = video["snippet"].get("liveBroadcastContent") == "live"
        title = video["snippet"]["title"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            if is_live:
                await channel.send(f"🔴 ライブ配信が始まりました！（過去分）\n**{title}**\n{url}")
            else:
                await channel.send(f"📺 過去動画：**{title}**\n{url}")
            count += 1
        except Exception as e:
            print(f"送信失敗: {e}")

    await interaction.followup.send(f"✅ {count} 件の動画を通知しました。")

# --- 起動処理 ---

@client.event
async def on_ready():
    print(f"✅ Bot is ready. Logged in as {client.user}")
    await tree.sync()
    client.loop.create_task(check_for_new_videos())

client.run(DISCORD_TOKEN)
