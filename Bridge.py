############################################################################################################################
#
#  ████████╗███████╗ █████╗ ███╗   ███╗███████╗██████╗ ███████╗ █████╗ ██╗  ██╗      ██╗    ██╗  
#  ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║██╔════╝██╔══██╗██╔════╝██╔══██╗██║ ██╔╝     ██╔╝    ╚██╗ 
#     ██║   █████╗  ███████║██╔████╔██║███████╗██████╔╝█████╗  ███████║█████╔╝     ██╔╝█████╗╚██╗
#     ██║   ██╔══╝  ██╔══██║██║╚██╔╝██║╚════██║██╔═══╝ ██╔══╝  ██╔══██║██╔═██╗     ╚██╗╚════╝██╔╝
#     ██║   ███████╗██║  ██║██║ ╚═╝ ██║███████║██║     ███████╗██║  ██║██║  ██╗     ╚██╗    ██╔╝ 
#     ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚═╝     ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝      ╚═╝    ╚═╝            
#                                                                                                   
#  ██████╗ ██╗███████╗ ██████╗ ██████╗ ██████╗ ██████╗     ██████╗ ██████╗ ██╗██████╗  ██████╗ ███████╗
#  ██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔══██╗██╔══██╗    ██╔══██╗██╔══██╗██║██╔══██╗██╔════╝ ██╔════╝
#  ██║  ██║██║███████╗██║     ██║   ██║██████╔╝██║  ██║    ██████╔╝██████╔╝██║██║  ██║██║  ███╗█████╗  
#  ██║  ██║██║╚════██║██║     ██║   ██║██╔══██╗██║  ██║    ██╔══██╗██╔══██╗██║██║  ██║██║   ██║██╔══╝  
#  ██████╔╝██║███████║╚██████╗╚██████╔╝██║  ██║██████╔╝    ██████╔╝██║  ██║██║██████╔╝╚██████╔╝███████╗
#  ╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝     ╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝ ╚══════╝
#
# Detailed Description:
# This script connects to TeamSpeak via ServerQuery and to Discord via a Discord Bot to mirror channel text messages
# in real time. It strips TeamSpeak BBCode before sending to Discord and shortens Discord CDN attachment URLs for
# cleaner TeamSpeak messages. The bridge features automatic reconnection, anti-loop protection, and safe message
# formatting to preserve readability across platforms.
#
# Core Features:
# • Bidirectional relay: TeamSpeak ↔ Discord channel text messages
# • Uses TeamSpeak ServerQuery and Discord bot
# • BBCode stripping for TeamSpeak → Discord messages for clean formatting
# • Discord attachment URL shortening for TeamSpeak display (images/videos/audio)
# • Conservative escaping for TS3 special characters to avoid formatting issues
# • Anti-loop protection so the bot does not relay its own messages
# • Auto-reconnection with backoff and graceful shutdown handling
# • Simple configuration via .env (host, ports, credentials, channel IDs, nickname)
#
# Important Note:
# Ensure your .env file is secured and not committed to source control. This bridge relays channel text messages
# only; it is not a moderation tool. TeamSpeak ServerQuery permissions must allow login, event registration, and
# sending channel text messages. Use an appropriate nickname and avoid running multiple instances on the same server.
#
# TeamSpeak-Discord Bridge v1.00
# Bidirectional TeamSpeak ↔ Discord channel text bridge
# Created by: https://github.com/xa-io
# Last Updated: 2025-09-28 22:17:44
#
# ## Release Notes ##
# v1.00 - Initial release
############################################################################################################################

import os
import re
import time
import queue
import signal
import logging
import asyncio
import threading
from typing import Optional
import discord
import aiohttp
from dotenv import load_dotenv
import ts3

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# -----------------------------
# TS3 Escaping helpers
# (matches TeamSpeak ServerQuery rules)
# -----------------------------
_TS_DECODE_MAP = {
    r"\s": " ",
    r"\/": "/",
    r"\p": "|",
    r"\a": "\a",
    r"\b": "\b",
    r"\f": "\f",
    r"\n": "\n",
    r"\r": "\r",
    r"\t": "\t",
    r"\v": "\v",
    r"\\": "\\",
}
_TS_DECODE_REGEX = re.compile(r"(\\s|\\/|\\p|\\a|\\b|\\f|\\n|\\r|\\t|\\v|\\\\)")

def ts_decode(value: str) -> str:
    return _TS_DECODE_REGEX.sub(lambda m: _TS_DECODE_MAP.get(m.group(0), m.group(0)), value)

def ts_encode(value: str) -> str:
    # Escape backslashes first, then everything else
    value = value.replace("\\", r"\\")
    value = value.replace(" ", r"\s")
    value = value.replace("/", r"\/")
    value = value.replace("|", r"\p")
    value = value.replace("\a", r"\a")
    value = value.replace("\b", r"\b")
    value = value.replace("\f", r"\f")
    value = value.replace("\n", r"\n")
    value = value.replace("\r", r"\r")
    value = value.replace("\t", r"\t")
    value = value.replace("\v", r"\v")
    return value

# -----------------------------
# Environment
# -----------------------------
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

TS3_HOST = os.getenv("TS3_HOST", "127.0.0.1")
TS3_VOICE_PORT = int(os.getenv("TS3_VOICE_PORT", "9987"))
TS3_QUERY_PORT = int(os.getenv("TS3_QUERY_PORT", "10011"))
TS3_USER = os.getenv("TS3_SERVERQUERY_USERNAME", "")
TS3_PASS = os.getenv("TS3_SERVERQUERY_PASSWORD", "")
TS3_CHANNEL_ID = int(os.getenv("TS3_CHANNEL_ID", "0"))
TS3_NICKNAME = os.getenv("TS3_NICKNAME", "Bridge")

# Optional webhook logger configuration
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").strip().lower() in ("1", "true", "yes", "y", "on")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

if not DISCORD_TOKEN or not DISCORD_CHANNEL_ID or not TS3_HOST or not TS3_USER or not TS3_PASS or not TS3_CHANNEL_ID:
    raise SystemExit("Missing required .env values. Please fill all required fields.")

# -----------------------------
# Cross-bridge queues
# -----------------------------
# Discord -> TS3 (thread-safe)
discord_to_ts_queue: "queue.Queue[str]" = queue.Queue()

# TS3 -> Discord (use asyncio-safe handoff)
ts_to_discord_queue: "asyncio.Queue[str]" = asyncio.Queue()

# Graceful shutdown flag
stop_event = threading.Event()

# Webhook client (initialized in async_main if enabled)
aiohttp_session: Optional[aiohttp.ClientSession] = None
webhook: Optional[discord.Webhook] = None

# -----------------------------
# TeamSpeak 3 Thread
# -----------------------------
class TS3BridgeThread(threading.Thread):
    def __init__(self,
                 host: str,
                 query_port: int,
                 voice_port: int,
                 user: str,
                 password: str,
                 channel_id: int,
                 nickname: str,
                 loop: asyncio.AbstractEventLoop):
        super().__init__(daemon=True)
        self.host = host
        self.query_port = query_port
        self.voice_port = voice_port
        self.user = user
        self.password = password
        self.channel_id = channel_id
        self.nickname = nickname
        self.loop = loop
        self.clid: Optional[int] = None  # ServerQuery client id after whoami
        self.username_cache = {}  # Cache client ID -> username mappings
        self.ts3conn = None  # Store connection for cleanup

    def strip_bbcode(self, text: str) -> str:
        """Strip common BBCode tags from TeamSpeak messages for Discord display."""
        import re
        
        # Remove URL tags more carefully: [URL]link[/URL] or [url]link[/url] -> link
        # Handle both cases: [URL]link[/URL] and [URL=link]text[/URL]
        # Also handle incomplete/broken URL tags like [URL]https://
        text = re.sub(r'\[URL\]([^[]*)\[/URL\]', r'\1', text, flags=re.IGNORECASE)
        text = re.sub(r'\[URL=[^]]*\]([^[]*)\[/URL\]', r'\1', text, flags=re.IGNORECASE)
        # Handle incomplete URL tags (just opening tag)
        text = re.sub(r'\[URL\]([^[]*?)$', r'\1', text, flags=re.IGNORECASE)
        text = re.sub(r'\[URL\]', '', text, flags=re.IGNORECASE)
        
        # Remove other common BBCode tags
        bbcode_patterns = [
            r'\[/?[Bb]\]',          # Bold: [b]text[/b] -> text
            r'\[/?[Ii]\]',          # Italic: [i]text[/i] -> text  
            r'\[/?[Uu]\]',          # Underline: [u]text[/u] -> text (but not URL)
            r'\[/?[Ss]\]',          # Strikethrough: [s]text[/s] -> text
            r'\[/?[Cc][Oo][Dd][Ee]\]',  # Code: [code]text[/code] -> text
            r'\[[Cc][Oo][Ll][Oo][Rr]=[^]]*\]',  # Color start: [color=#ff0000] -> (removed)
            r'\[/[Cc][Oo][Ll][Oo][Rr]\]',       # Color end: [/color] -> (removed)
            r'\[[Ss][Ii][Zz][Ee]=[^]]*\]',      # Size start: [size=12] -> (removed) 
            r'\[/[Ss][Ii][Zz][Ee]\]',           # Size end: [/size] -> (removed)
        ]
        
        for pattern in bbcode_patterns:
            text = re.sub(pattern, '', text)
        
        return text.strip()

    def cleanup_connection(self):
        """Gracefully logout from TeamSpeak ServerQuery"""
        if self.ts3conn:
            try:
                logging.info("[TS3] Logging out from ServerQuery...")
                self.ts3conn.logout()
                logging.info("[TS3] Successfully logged out from ServerQuery")
            except Exception as logout_error:
                logging.warning(f"[TS3] Error during logout: {logout_error}")
            finally:
                self.ts3conn = None

    def transform_urls_for_discord(self, text: str) -> str:
        """Transform URLs from TeamSpeak messages for better Discord embeds."""
        import re
        
        # Define URL transformations for better Discord embeds
        url_transformations = [
            # Twitter/X.com transformations
            (r'https?://(www\.)?x\.com/', 'https://fixupx.com/'),
            (r'https?://(www\.)?twitter\.com/', 'https://fxtwitter.com/'),
            
            # Reddit transformation  
            # (r'https?://(www\.)?reddit\.com/', 'https://rxddit.com/'),
            
            # TikTok transformation
            # (r'https?://(www\.)?tiktok\.com/', 'https://vxtiktok.com/'),
            
            # Instagram transformation
            # (r'https?://(www\.)?instagram\.com/', 'https://ddinstagram.com/'),
        ]
        
        original_text = text
        
        # Apply each transformation
        for pattern, replacement in url_transformations:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        # Log URL transformations if any were made
        if text != original_text:
            logging.info(f"[TS3] URL transformation - Original: {original_text}")
            logging.info(f"[TS3] URL transformation - Transformed: {text}")
        
        return text


    def run(self):
        backoff = 2
        while not stop_event.is_set():
            try:
                logging.info(f"[TS3] Connecting to {self.host}:{self.query_port} ...")
                with ts3.query.TS3Connection(self.host, self.query_port) as ts3conn:
                    self.ts3conn = ts3conn  # Store connection reference for cleanup
                    # login, select server, set nickname
                    ts3conn.login(
                        client_login_name=self.user,
                        client_login_password=self.password
                    )
                    ts3conn.use(port=self.voice_port)
                    
                    # Try to kick any existing "Bridge" client to free up the nickname
                    try:
                        clients = ts3conn.clientlist()
                        logging.info(f"[TS3] Checking {len(clients.parsed)} clients for existing '{self.nickname}' connections...")
                        
                        for client in clients.parsed:
                            client_nickname = ts_decode(client.get('client_nickname', ''))
                            client_type = client.get('client_type', '1')  # 0 = regular client, 1 = ServerQuery
                            client_id = client.get('clid')
                            
                            logging.info(f"[TS3] Client check - ID: {client_id}, Name: '{client_nickname}', Type: {client_type}")
                            
                            # Kick regular clients (type 0) with our nickname, or any client with exactly our nickname
                            if client_nickname == self.nickname:
                                logging.info(f"[TS3] Found existing '{self.nickname}' client (clid={client_id}, type={client_type}), attempting to kick...")
                                try:
                                    # Try different kick reasons
                                    ts3conn.clientkick(clid=client_id, reasonid=5, reasonmsg="Bridge bot reconnecting")
                                    logging.info(f"[TS3] Successfully kicked client {client_id}")
                                    time.sleep(2)  # Wait longer for disconnect
                                except Exception as kick_error:
                                    logging.warning(f"[TS3] Could not kick existing client {client_id}: {kick_error}")
                                    # Try poke then kick
                                    try:
                                        ts3conn.clientpoke(clid=client_id, msg="Bridge bot needs this nickname")
                                        time.sleep(1)
                                        ts3conn.clientkick(clid=client_id, reasonid=4, reasonmsg="Nickname required")
                                    except Exception as poke_kick_error:
                                        logging.warning(f"[TS3] Poke+kick also failed: {poke_kick_error}")
                    except Exception as client_list_error:
                        logging.warning(f"[TS3] Could not check for existing clients: {client_list_error}")
                    
                    # Try to set the primary nickname with patient retry (wait for disconnections)
                    nickname_set = False
                    max_attempts = 3  # More attempts
                    
                    for attempt in range(max_attempts):
                        try:
                            ts3conn.clientupdate(client_nickname=self.nickname)
                            logging.info(f"[TS3] Successfully set nickname: {self.nickname}")
                            nickname_set = True
                            break
                        except Exception as nick_error:
                            if "513" in str(nick_error):  # nickname in use
                                wait_time = min(3 + attempt, 8)  # Progressive wait: 3s, 4s, 5s... up to 8s
                                logging.warning(f"[TS3] Nickname '{self.nickname}' still in use (attempt {attempt + 1}/{max_attempts}), waiting {wait_time}s...")
                                time.sleep(wait_time)
                                continue
                            else:
                                raise nick_error
                    
                    # Only use minimal fallback if absolutely necessary (after 10 attempts)
                    if not nickname_set:
                        logging.error(f"[TS3] Could not secure '{self.nickname}' after {max_attempts} attempts!")
                        # Try one simple numbered fallback as last resort
                        fallback_nick = f"{self.nickname}_{int(time.time() % 100)}"
                        try:
                            ts3conn.clientupdate(client_nickname=fallback_nick)
                            self.nickname = fallback_nick
                            logging.warning(f"[TS3] Using emergency fallback nickname: {fallback_nick}")
                            nickname_set = True
                        except Exception as fallback_error:
                            logging.error(f"[TS3] Even fallback nickname failed: {fallback_error}")
                            raise Exception("Could not set any nickname - all attempts failed")
                    
                    if not nickname_set:
                        raise Exception("Could not set any nickname - all attempts failed")
                    whoami = ts3conn.whoami()
                    self.clid = int(whoami.parsed[0].get("client_id", "0"))
                    logging.info(f"[TS3] Logged in. clid={self.clid}")

                    # register for channel text messages
                    try:
                        ts3conn.servernotifyregister(event="textchannel", schandlerid=0)
                        logging.info(f"[TS3] Registered for textchannel notifications on cid={self.channel_id}")
                    except Exception as notify_error:
                        # Try alternative registration method
                        logging.warning(f"[TS3] Primary notification registration failed: {notify_error}")
                        try:
                            ts3conn.servernotifyregister(event="textchannel")
                            logging.info(f"[TS3] Registered for textchannel notifications (fallback method)")
                        except Exception as fallback_error:
                            logging.error(f"[TS3] Both notification registration methods failed: {fallback_error}")
                            raise fallback_error

                    last_keepalive = time.time()
                    last_nickname_check = time.time()
                    original_nickname = os.getenv('TS3_NICKNAME', 'Bridge')  # Store original for comparison
                    using_fallback = (self.nickname != original_nickname)

                    while not stop_event.is_set():
                        # Relay Discord -> TS3
                        try:
                            msg = discord_to_ts_queue.get_nowait()
                        except queue.Empty:
                            msg = None

                        if msg:
                            # Send to TS channel - message format is "username: message"
                            # Only encode special TS3 characters, be more conservative with encoding
                            safe_msg = msg.replace("\\", "\\\\").replace("|", "\\p").replace("\n", "\\n").replace("\r", "\\r")
                            ts3conn.sendtextmessage(
                                targetmode=2,  # channel
                                target=self.channel_id,
                                msg=safe_msg
                            )
                            logging.info(f"[TS3] Sent message to channel: {msg[:50]}...")

                        # Wait for TS3 events with short timeout to keep loop responsive
                        try:
                            event = ts3conn.wait_for_event(timeout=0.2)
                        except ts3.query.TS3TimeoutError:
                            event = None

                        if event and event.event == "notifytextmessage":
                            data = event.parsed[0]
                            
                            # invokerid is numeric id of the sender (ServerQuery-side)
                            invokerid = int(data.get("invokerid", "0"))
                            
                            # DOUBLE CHECKER USERNAME RESOLUTION SYSTEM
                            invokername = None
                            
                            # FIRST CHECK: Try event data fields
                            possible_names = [
                                data.get("invokername", ""),
                                data.get("invokernickname", ""), 
                                data.get("client_nickname", "")
                            ]
                            
                            for name_field in possible_names:
                                if name_field:
                                    decoded_name = ts_decode(str(name_field)).strip()
                                    if decoded_name and decoded_name != "":
                                        invokername = decoded_name
                                        break
                            
                            # SECOND CHECK: Cache lookup if we have this client ID cached
                            if not invokername and invokerid > 0 and invokerid in self.username_cache:
                                invokername = self.username_cache[invokerid]
                                logging.info(f"[TS3] Retrieved username from cache: '{invokername}'")
                            
                            # THIRD CHECK: Direct clientinfo lookup (most reliable)
                            if not invokername and invokerid > 0:
                                try:
                                    logging.info(f"[TS3] Event data missing username, querying clientinfo for ID {invokerid}")
                                    client_info = ts3conn.clientinfo(clid=invokerid)
                                    if client_info and client_info.parsed and len(client_info.parsed) > 0:
                                        client_nickname = client_info.parsed[0].get('client_nickname', '')
                                        if client_nickname:
                                            invokername = ts_decode(client_nickname).strip()
                                            # Cache this result for future use
                                            self.username_cache[invokerid] = invokername
                                            logging.info(f"[TS3] Retrieved and cached username via clientinfo: '{invokername}'")
                                        else:
                                            # If clientinfo fails but we have a cached name, use it
                                            if invokerid in self.username_cache:
                                                invokername = self.username_cache[invokerid]
                                                logging.info(f"[TS3] clientinfo empty, using cached username: '{invokername}'")
                                            else:
                                                logging.warning(f"[TS3] clientinfo returned empty client_nickname for ID {invokerid}")
                                    else:
                                        # If clientinfo returns no data but we have cache, use it
                                        if invokerid in self.username_cache:
                                            invokername = self.username_cache[invokerid]
                                            logging.info(f"[TS3] clientinfo no data, using cached username: '{invokername}'")
                                        else:
                                            logging.warning(f"[TS3] clientinfo returned no data for ID {invokerid}")
                                except Exception as client_lookup_error:
                                    # If lookup fails but we have cache, use it
                                    if invokerid in self.username_cache:
                                        invokername = self.username_cache[invokerid]
                                        logging.info(f"[TS3] clientinfo failed, using cached username: '{invokername}'")
                                    else:
                                        logging.error(f"[TS3] clientinfo lookup failed for ID {invokerid}: {client_lookup_error}")
                            
                            # FINAL FALLBACK: Should never happen now
                            if not invokername:
                                invokername = f"Client_{invokerid}"  # More descriptive than "Unknown"
                                logging.error(f"[TS3] ALL USERNAME RESOLUTION METHODS FAILED!")
                                logging.error(f"[TS3] Event data: {data}")
                                logging.error(f"[TS3] Using fallback: {invokername}")
                            
                            raw_msg = ts_decode(data.get("msg", ""))
                            
                            logging.info(f"[TS3] Extracted - ID: {invokerid}, Name: '{invokername}', Message: '{raw_msg}'")

                            # Ignore our own ServerQuery messages
                            if self.clid and invokerid == self.clid:
                                # logging.info(f"[TS3] Ignoring our own message (clid={self.clid})")
                                continue

                            # Build display for Discord - bold username only
                            clean = raw_msg.replace("\r", " ").replace("\n", " ").strip()
                            
                            # Strip BBCode formatting for Discord
                            clean = self.strip_bbcode(clean)
                            
                            # Transform URLs for better Discord embeds (TeamSpeak → Discord only)
                            clean = self.transform_urls_for_discord(clean)
                            
                            bridged = f"**{invokername}**: {clean}"
                            # Handoff to discord loop
                            asyncio.run_coroutine_threadsafe(ts_to_discord_queue.put(bridged), self.loop)

                        # Keepalive (avoid idle timeouts on some hosts)
                        if time.time() - last_keepalive > 45:
                            try:
                                ts3conn.version()
                            except Exception:
                                # If keepalive fails, break to reconnect
                                logging.warning("[TS3] Keepalive failed; reconnecting.")
                                break
                            last_keepalive = time.time()

                    # End inner loop; reconnect if not stopping
                    if stop_event.is_set():
                        self.cleanup_connection()
                        break

            except Exception as e:
                logging.error(f"[TS3] Connection error: {e}")
                self.cleanup_connection()

            # Reconnect backoff
            if stop_event.is_set():
                break
            logging.info(f"[TS3] Reconnecting in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

# -----------------------------
# Discord Bot
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True  # required to read message text
client = discord.Client(intents=intents)

discord_channel: Optional[discord.TextChannel] = None

@client.event
async def on_ready():
    global discord_channel
    discord_channel = client.get_channel(DISCORD_CHANNEL_ID)
    if discord_channel is None:
        # Fallback fetch if not in cache
        discord_channel = await client.fetch_channel(DISCORD_CHANNEL_ID)
    logging.info(f"[Discord] Logged in as {client.user} | Bridging channel #{discord_channel} ({discord_channel.id})")

    # Start background consumer for TS -> Discord
    client.loop.create_task(relay_ts_to_discord())
    if USE_WEBHOOK and webhook is not None:
        logging.info("[Webhook] Webhook logging is enabled.")

async def relay_ts_to_discord():
    """Reads messages from TS and posts to the Discord channel."""
    assert discord_channel is not None
    while not client.is_closed():
        try:
            bridged = await ts_to_discord_queue.get()
            if bridged and discord_channel:
                await discord_channel.send(bridged)
                # Also send to webhook if enabled
                if webhook is not None:
                    try:
                        await webhook.send(bridged)
                    except Exception as we:
                        logging.warning(f"[Webhook] Failed to send TS message: {we}")
                logging.info("[Discord] Posted message from TS.")
        except Exception as e:
            logging.error(f"[Discord] Error posting TS message: {e}")
            await asyncio.sleep(1)

def shorten_discord_attachments(content: str) -> str:
    """Shorten Discord CDN attachment URLs for better TeamSpeak display."""
    import re
    
    # Define file extensions for different media types
    image_extensions = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg', 'tiff', 'tif', 'ico', 'heic', 'heif', 'jfif']
    video_extensions = ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', 'm4v', '3gp', 'ogv', 'mpg', 'mpeg', 'mp2', 'mpe', 'mpv', 'm2v']
    audio_extensions = ['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'wma', 'opus']
    
    # Create regex patterns for different file types with capture groups for the full URL
    image_pattern = r'(https?://cdn\.discordapp\.com/[^)\s]*\.(?:' + '|'.join(image_extensions) + r')(?:\?[^)\s]*)?)'
    video_pattern = r'(https?://cdn\.discordapp\.com/[^)\s]*\.(?:' + '|'.join(video_extensions) + r')(?:\?[^)\s]*)?)'
    audio_pattern = r'(https?://cdn\.discordapp\.com/[^)\s]*\.(?:' + '|'.join(audio_extensions) + r')(?:\?[^)\s]*)?)'
    
    # Replace image URLs with BBCode wrapped links
    content = re.sub(image_pattern, r'[URL=\1]Click to show image[/URL]', content, flags=re.IGNORECASE)
    
    # Replace video URLs with BBCode wrapped links
    content = re.sub(video_pattern, r'[URL=\1]Click to download video[/URL]', content, flags=re.IGNORECASE)
    
    # Replace audio URLs with BBCode wrapped links
    content = re.sub(audio_pattern, r'[URL=\1]Click to download audio[/URL]', content, flags=re.IGNORECASE)
    
    return content

@client.event
async def on_message(message: discord.Message):
    """Listen to the selected Discord channel and relay to TS3."""
    # Only relay the target channel
    if message.channel.id != DISCORD_CHANNEL_ID:
        return
    # Avoid loops: ignore our own bot posts
    if message.author.id == client.user.id:
        return
    # Avoid relaying webhook-originated messages (prevents loops if webhook targets same channel)
    if message.webhook_id is not None:
        return

    # Build content
    parts = []
    if message.content:
        parts.append(message.content.strip())

    # Include attachment URLs (optional but helpful)
    for att in message.attachments:
        parts.append(f"({att.url})")

    if not parts:
        return  # nothing meaningful to send

    # Build raw content once
    raw_content = " ".join(p.replace("\n", " ").strip() for p in parts).strip()
    
    # For TeamSpeak: ALWAYS shorten Discord CDN attachment URLs to clickable text
    content_for_ts = shorten_discord_attachments(raw_content)
    
    # For webhook: preserve original Discord formatting (raw links)
    content_for_webhook = raw_content
    
    display_name = message.author.display_name
    
    # To TeamSpeak
    bridged = f"{display_name}: {content_for_ts}"
    # Hand off to TS thread (thread-safe queue)
    discord_to_ts_queue.put(bridged)
    logging.info(f"[Bridge] Queued Discord -> TS message: {display_name}")
    # Also send to webhook if enabled
    if webhook is not None:
        try:
            # To webhook (Discord) with original content preserved
            bold_bridged = f"**{display_name}**: {content_for_webhook}"
            await webhook.send(bold_bridged)
        except Exception as we:
            logging.warning(f"[Webhook] Failed to send Discord message: {we}")

async def async_main():
    # Get current event loop or create new one
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Start TS thread using the discord event loop
    ts_thread = TS3BridgeThread(
        host=TS3_HOST,
        query_port=TS3_QUERY_PORT,
        voice_port=TS3_VOICE_PORT,
        user=TS3_USER,
        password=TS3_PASS,
        channel_id=TS3_CHANNEL_ID,
        nickname=TS3_NICKNAME,
        loop=loop,
    )
    ts_thread.start()

    # Graceful shutdown handlers with TeamSpeak cleanup
    def _stop(*_):
        logging.info("Stopping bridge...")
        stop_event.set()
        # Give the TS thread a moment to cleanup
        if ts_thread and ts_thread.is_alive():
            logging.info("Waiting for TeamSpeak thread to cleanup...")
            ts_thread.cleanup_connection()
            ts_thread.join(timeout=3)  # Wait max 3 seconds for cleanup

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Initialize webhook if enabled
    global aiohttp_session, webhook
    if USE_WEBHOOK and DISCORD_WEBHOOK_URL:
        try:
            aiohttp_session = aiohttp.ClientSession()
            webhook = discord.Webhook.from_url(DISCORD_WEBHOOK_URL, session=aiohttp_session)
            logging.info("[Webhook] Initialized webhook client.")
        except Exception as e:
            logging.error(f"[Webhook] Initialization failed: {e}")
            webhook = None

    # Run Discord bot (blocks)
    try:
        await client.start(DISCORD_TOKEN)
    finally:
        # Cleanup webhook session if created
        if aiohttp_session is not None and not aiohttp_session.closed:
            await aiohttp_session.close()

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logging.info("Shutdown requested by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
