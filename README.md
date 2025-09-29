# TeamSpeak-Discord Bridge v1.00

Bidirectional bridge that relays text messages between a TeamSpeak 3 channel and a Discord channel.

## Overview
This script connects to TeamSpeak via ServerQuery and to Discord via a Discord Bot to mirror channel text messages
in real time. It strips TeamSpeak BBCode before sending to Discord and shortens Discord CDN attachment URLs for
cleaner TeamSpeak messages. The bridge features automatic reconnection, anti-loop protection, and safe message
formatting to preserve readability across platforms.

## Core Features
- **Bidirectional relay**: TeamSpeak ↔ Discord channel text messages
- **TeamSpeak ServerQuery + Discord bot** integration
- **BBCode stripping** for TS → Discord messages
- **Discord attachment URL shortening** for TS display (images/videos/audio)
- **Anti-loop protection** so the bot doesn’t echo itself
- **Auto-reconnection** with backoff and graceful shutdown
- **.env configuration** for host, ports, credentials, channel IDs, nickname

## Requirements
- Python 3.12+
- Packages: `discord.py`, `python-dotenv`, `ts3` (TeamSpeak ServerQuery library), `aiohttp` (for optional webhook)

```bash
pip install discord.py python-dotenv ts3 aiohttp
```

## Configuration
Create a `.env` file in the project folder with the following keys:

```ini
# Discord
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=123456789012345678

# TeamSpeak ServerQuery
TS3_HOST=127.0.0.1
TS3_VOICE_PORT=9987
TS3_QUERY_PORT=10011
TS3_SERVERQUERY_USERNAME=serveradmin
TS3_SERVERQUERY_PASSWORD=your_password
TS3_CHANNEL_ID=1
TS3_NICKNAME=Bridge

# [Webhook Logging] settings (optional)
USE_WEBHOOK=False
DISCORD_WEBHOOK_URL=xxxxxxxxxxxxxx
```

## Usage
```bash
python Bridge.py
```
When the bot logs in, it will bridge messages between the configured Discord channel and TeamSpeak channel.

## Notable Behavior
- TeamSpeak messages are cleaned: BBCode tags are stripped before posting to Discord.
- Discord CDN attachments are shortened for TeamSpeak display by `shorten_discord_attachments()` to avoid long URLs.
- The bridge ignores its own messages to prevent loops.
- When webhook logging is enabled, all TeamSpeak→Discord and Discord→TeamSpeak bridged messages are also sent to the configured webhook URL. Messages authored by webhooks are ignored to prevent loops.
- The script automatically reconnects on transient failures and shuts down gracefully on SIGINT/SIGTERM.

## Security Note
Keep `.env` out of source control. Ensure your TeamSpeak ServerQuery account has only the permissions required for login, event registration, and posting channel text messages.

## Versioning
- v1.00 — Initial release

Created by: https://github.com/xa-io  
Last Updated: 2025-09-28 22:00:58
