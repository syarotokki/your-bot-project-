import os
import json
import asyncio
import discord
import requests
from discord import app_commands
from discord.ext import tasks
from flask import Flask
from threading import Thread

# --- 定数 ---
CONFIG_FILE = 'config.json'
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# --- Flask Keep-Alive ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run).start()

# --- Bot初期化 ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- 設定ロード ---
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)

config = load_config()

# --- 最新動画取得 ---
def get_latest_video(channel_id):
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults=1"
    response = requests.get(url)
    data = response.json()
    if 'items' not in data or not data['items']:
        return None
    video = data['items'][0]
    video_id = video['id'].get('videoId')
    if not video_id:
        return None
    return {
        'video_id': video_id,
        'title': video['snippet']['title'],
        'published_at': video['snippet']['publishedAt'],
        'url': f"https://www.youtube.com/watch?v={video_id}"
    }

# --- 通知ループ ---
@tasks.loop(minutes=5)
async def check_new_videos():
    for guild_id, entry in config.items():
        channel_id = entry['discord_channel_id']
        yt_channel_id = entry['youtube_channel_id']
        latest = get_latest_video(yt_channel_id)
        if not latest:
            continue
        if latest['video_id'] == entry.get('last_video_id'):
            continue
        channel = client.get_channel(int(channel_id))
        if channel:
            await channel.send(f"新しい動画が投稿されました！\n**{latest['title']}**\n{latest['url']}")
            config[guild_id]['last_video_id'] = latest['video_id']
            save_config(config)

# --- コマンド ---
@tree.command(name="subscribe", description="YouTubeチャンネルを通知対象として登録")
@app_commands.describe(youtube_channel_id="YouTubeのチャンネルID", channel="通知を送るDiscordチャンネル")
async def subscribe(interaction: discord.Interaction, youtube_channel_id: str, channel: discord.TextChannel):
    config[str(interaction.guild_id)] = {
        "youtube_channel_id": youtube_channel_id,
        "discord_channel_id": str(channel.id),
        "last_video_id": ""
    }
    save_config(config)
    await interaction.response.send_message("登録が完了しました！")

@tree.command(name="list_subscriptions", description="現在登録されているYouTubeチャンネルを表示")
async def list_subscriptions(interaction: discord.Interaction):
    entry = config.get(str(interaction.guild_id))
    if not entry:
        await interaction.response.send_message("登録はありません。")
    else:
        await interaction.response.send_message(f"登録中のチャンネルID: {entry['youtube_channel_id']}\n通知チャンネル: <#{entry['discord_channel_id']}>")

@tree.command(name="check_latest", description="指定したYouTubeチャンネルの最新動画を確認")
@app_commands.describe(youtube_channel_id="YouTubeのチャンネルID")
async def check_latest(interaction: discord.Interaction, youtube_channel_id: str):
    latest = get_latest_video(youtube_channel_id)
    if not latest:
        await interaction.response.send_message("動画が見つかりませんでした。")
    else:
        await interaction.response.send_message(f"最新動画: **{latest['title']}**\n{latest['url']}")

@tree.command(name="force_notify", description="全登録チャンネルの最新動画を即座に通知")
async def force_notify(interaction: discord.Interaction):
    for guild_id, entry in config.items():
        channel = client.get_channel(int(entry['discord_channel_id']))
        latest = get_latest_video(entry['youtube_channel_id'])
        if not latest:
            continue
        await channel.send(f"(手動通知) 新しい動画！**{latest['title']}**\n{latest['url']}")
        config[guild_id]['last_video_id'] = latest['video_id']
    save_config(config)
    await interaction.response.send_message("全チャンネルに通知を送信しました。")

@tree.command(name="change_channel", description="通知先のDiscordチャンネルを変更")
@app_commands.describe(channel="新しい通知先チャンネル")
async def change_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    if guild_id in config:
        config[guild_id]['discord_channel_id'] = str(channel.id)
        save_config(config)
        await interaction.response.send_message("通知チャンネルを変更しました。")
    else:
        await interaction.response.send_message("まだ登録されていません。まず /subscribe してください。")

@tree.command(name="reset_all_subscriptions", description="全登録を削除（管理者専用）")
async def reset_all(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        config.clear()
        save_config(config)
        await interaction.response.send_message("すべての登録を削除しました。")
    else:
        await interaction.response.send_message("管理者のみ使用できます。")

@tree.command(name="help", description="コマンドの使い方を表示")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message("""
**利用可能なコマンド一覧**

/subscribe - YouTubeチャンネルと通知チャンネルを登録
/list_subscriptions - 登録済みのチャンネル情報を表示
/check_latest - 任意のチャンネルの最新動画を確認
/force_notify - 全登録チャンネルの最新動画を即通知
/change_channel - 通知先チャンネルを変更
/reset_all_subscriptions - 全登録を削除（管理者専用）
/help - このメッセージを表示
""")

# --- 起動処理 ---
@client.event
async def on_ready():
    await tree.sync()
    check_new_videos.start()
    print(f'Logged in as {client.user}')

keep_alive()
client.run(DISCORD_TOKEN)
