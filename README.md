# YouTube通知Discordボット

このボットは、指定したYouTubeチャンネルの最新動画やライブ配信をDiscordに自動で通知します。

## 🔧 機能
- `/subscribe <channel_id> <discord_channel>`：通知登録
- `/unsubscribe <channel_id>`：登録解除
- `/list_subscriptions`：登録一覧確認
- `/notify_past <channel_id>`：過去動画通知
- `/help`：ヘルプ表示

## 🖥️ 使用技術
- Python + discord.py
- YouTube Data API v3
- Flask + UptimeRobot + Render（無料24時間稼働）

## 📦 必要な環境変数（.env に設定）
