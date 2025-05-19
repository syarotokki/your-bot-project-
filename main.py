import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
import json
import os
from keep_alive import keep_alive

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

CONFIG_FILE = "config.json"
config = {}
last_video_ids = {}

# 設定ファイルの読み書き
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# YouTube動画一覧を取得
def get_all_uploaded_videos(channel_id):
    url = (
        f"https://www.googleapis.com/youtube/v3/channels?part=contentDetails"
        f"&id={channel_id}&key={YOUTUBE_API_KEY}"
    )
    res = requests.get(url).json()
    uploads_id = res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    next_page_token = ""

    while True:
        playlist_url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems"
            f"?part=snippet&maxResults=50&playlistId={uploads_id}"
            f"&key={YOUTUBE_API_KEY}&pageToken={next_page_token}"
        )
        playlist_res = requests.get(playlist_url).json()
        for item in playlist_res["items"]:
            video_id = item["snippet"]["resourceId"]["videoId"]
            title = item["snippet"]["title"]
            videos.append((video_id, title))
        next_page_token = playlist_res.get("nextPageToken")
        if not next_page_token:
            break
    return videos

# 最新動画取得（動画 or ライブ）
def get_latest_video(channel_id):
    url = (
        f"https://www.googleapis.com/youtube/v3/search"
        f"?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id"
        f"&order=date&maxResults=1"
    )
    res = requests.get(url).json()
    if "items" not in res or not res["items"]:
        raise Exception("動画が見つかりません")
    item = res["items"][0]
    id_info = item["id"]

    if id_info["kind"] == "youtube#video":
        video_id = id_info["videoId"]
        title = item["snippet"]["title"]
        is_live = "[ライブ]" in title or "live" in title.lower()
        return video_id, title, is_live
    else:
        raise Exception("動画ではありません")

@bot.event
async def on_ready():
    global config
    config = load_config()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    check_new_videos.start()

@bot.tree.command(name="subscribe", description="YouTubeチャンネルの通知設定をする")
@app_commands.describe(
    youtube_channel_id="通知したいYouTubeチャンネルのID",
    notify_channel="通知を送るDiscordチャンネル"
)
async def subscribe(interaction: discord.Interaction, youtube_channel_id: str, notify_channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    config[guild_id] = {
        "channel_id": youtube_channel_id,
        "notify_channel": notify_channel.id
    }
    save_config(config)
    await interaction.response.send_message(
        f"✅ 通知設定完了！\nYouTubeチャンネルID: `{youtube_channel_id}`\n通知先: {notify_channel.mention}",
        ephemeral=True
    )

@bot.tree.command(name="notify_past", description="過去の動画をすべて通知する")
async def notify_past(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    if guild_id not in config:
        await interaction.response.send_message("⚠️ 先に `/subscribe` で通知設定してください。", ephemeral=True)
        return

    await interaction.response.send_message("🔍 過去動画を取得中です...", ephemeral=True)

    channel_id = config[guild_id]["channel_id"]
    notify_channel_id = config[guild_id]["notify_channel"]
    notify_channel = bot.get_channel(notify_channel_id)
    videos = get_all_uploaded_videos(channel_id)

    for video_id, title in reversed(videos):  # 古い順で送信
        await notify_channel.send(f"📺 **{title}**\nhttps://www.youtube.com/watch?v={video_id}")

@tasks.loop(minutes=5)
async def check_new_videos():
    for guild_id, settings in config.items():
        channel_id = settings["channel_id"]
        notify_channel_id = settings["notify_channel"]
        try:
            video_id, title, is_live = get_latest_video(channel_id)
            if last_video_ids.get(guild_id) != video_id:
                last_video_ids[guild_id] = video_id
                channel = bot.get_channel(notify_channel_id)
                if channel:
                    if is_live:
                        await channel.send(f"🔴 **ライブ配信が開始されました！**\n📺 {title}\nhttps://www.youtube.com/watch?v={video_id}")
                    else:
                        await channel.send(f"🎥 **新しい動画が公開されました！**\n📺 {title}\nhttps://www.youtube.com/watch?v={video_id}")
        except Exception as e:
            print(f"[エラー] Guild {guild_id}: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
