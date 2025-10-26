import os
import re
import logging
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from pyrogram.errors import UserNotParticipant
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment variables (loaded from .env or Koyeb env)
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")  # e.g., @channelusername or channel ID
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "0"))
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(',') if x.strip()]
START_IMAGE = os.getenv("START_IMAGE", "https://telegra.ph/file/9b1f6c9c5ff0f6a507d9e.jpg")
BOT_NAME = os.getenv("BOT_NAME", "YouTube Thumbnail Downloader Bot")

if not BOT_TOKEN or API_ID == 0 or not API_HASH or not MONGO_URI:
    logger.error("Missing essential environment variables. Please check .env or Koyeb configuration.")
    raise SystemExit(1)

# MongoDB setup
mongo = MongoClient(MONGO_URI)
db = mongo.get_database("ytthumbbot")
users_col = db["users"]
logs_col = db["logs"]

# Pyrogram client
app = Client("yt_thumb_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# Utilities
def now_str():
    return datetime.utcnow().strftime("%d %b %Y, %I:%M %p (UTC)")

YOUTUBE_REGEX = re.compile(r"(?:https?://)?(?:www\.)?(?:m\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})")

def extract_video_id(text: str):
    m = YOUTUBE_REGEX.search(text)
    if m:
        return m.group(1)
    # fallback query param
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(text)
        qs = parse_qs(parsed.query)
        if 'v' in qs:
            return qs['v'][0]
    except Exception:
        pass
    return None

def thumb_urls(video_id: str):
    return {
        'maxres': f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg',
        'hq': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
        'sd': f'https://img.youtube.com/vi/{video_id}/sddefault.jpg',
        'mq': f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg',
        'default': f'https://img.youtube.com/vi/{video_id}/default.jpg',
    }

async def is_subscribed(client: Client, user_id: int) -> bool:
    if not FORCE_CHANNEL:
        return True
    try:
        member = await client.get_chat_member(FORCE_CHANNEL, user_id)
        return member.status not in ('left','kicked')
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.warning("Failed to check subscription: %s - allowing by default.", e)
        return True

async def send_log_new_user(client: Client, user) -> None:
    try:
        text = ("🆕 New User Started the Bot\n\n"
                f"👤 Name: [{user.first_name}](tg://user?id={user.id})\n"
                f"🆔 User ID: `{user.id}`\n"
                f"⏰ Joined: {now_str()}\n"
                f"🤖 From: {BOT_NAME}")
        if LOG_CHANNEL:
            await client.send_message(LOG_CHANNEL, text, parse_mode='markdown')
    except Exception as e:
        logger.warning("Could not send log message: %s", e)


def start_keyboard():
    buttons = [
        [InlineKeyboardButton('🧾 About Bot', callback_data='about_bot'), InlineKeyboardButton('🆕 Updates', url=f'https://t.me/{FORCE_CHANNEL.replace('@','')}' if FORCE_CHANNEL else 'https://t.me/')],
        [InlineKeyboardButton('⚙️ More Tools', callback_data='more_tools'), InlineKeyboardButton('💬 Support', url='https://t.me/your_support_group')]
    ]
    return InlineKeyboardMarkup(buttons)

def force_keyboard():
    buttons = [
        [InlineKeyboardButton('🔔 Join Channel', url=f'https://t.me/{FORCE_CHANNEL.replace('@','')}')],
        [InlineKeyboardButton('✅ I Joined', callback_data='check_sub')]
    ]
    return InlineKeyboardMarkup(buttons)

def thumbnail_keyboard(video_url: str, video_id: str):
    urls = thumb_urls(video_id)
    buttons = [
        [InlineKeyboardButton('🖼 HD (maxres)', url=urls['maxres'])],
        [InlineKeyboardButton('📷 SD (hq)', url=urls['hq'])],
        [InlineKeyboardButton('🔗 Open Video', url=video_url)]
    ]
    return InlineKeyboardMarkup(buttons)

# Handlers
@app.on_message(filters.private & filters.command('start'))
async def cmd_start(client, message):
    user = message.from_user
    # save user
    if not users_col.find_one({'user_id': user.id}):
        users_col.insert_one({
            'user_id': user.id,
            'username': user.username or '',
            'first_name': user.first_name or '',
            'join_date': datetime.utcnow(),
            'usage_count': 0,
            'is_banned': False
        })
        await send_log_new_user(client, user)
    else:
        users_col.update_one({'user_id': user.id}, {'$set': {'last_active': datetime.utcnow()}})

    caption = (f"👋 Hey [{user.first_name}](tg://user?id={user.id}),\n\n"
               f"Welcome to *{BOT_NAME}* 🎉\n"
               "I can fetch *HD / SD / 4K YouTube Thumbnails* instantly!\n\n"
               "📸 Just send any YouTube video link below.\n")

    try:
        await client.send_photo(chat_id=message.chat.id, photo=START_IMAGE, caption=caption, parse_mode='markdown', reply_markup=start_keyboard())
    except Exception as e:
        logger.warning("Failed sending start image: %s", e)
        await client.send_message(chat_id=message.chat.id, text=caption, parse_mode='markdown', reply_markup=start_keyboard())

@app.on_callback_query()
async def callbacks(client, callback_query):
    data = callback_query.data
    user = callback_query.from_user

    if data == 'about_bot':
        text = (f"🤖 *About {BOT_NAME}*\n\n"
                "I fetch thumbnails from YouTube videos.\n"
                "Built with Pyrogram & MongoDB. Hosted on Koyeb.\n")
        await callback_query.answer()
        await client.send_message(user.id, text, parse_mode='markdown')

    elif data == 'more_tools':
        text = "🧩 *More Tools (Coming Soon)*\n\n- YouTube Shorts Saver\n- Channel Logo Downloader\n- Premium Features\n"
        await callback_query.answer()
        await client.send_message(user.id, text, parse_mode='markdown')

    elif data == 'check_sub':
        await callback_query.answer('Checking subscription...', show_alert=False)
        ok = await is_subscribed(client, user.id)
        if ok:
            users_col.update_one({'user_id': user.id}, {'$set': {'force_subscribed': True}}, upsert=True)
            await client.send_message(user.id, '✅ Thanks for joining. Now send me a YouTube link.')
        else:
            await client.send_message(user.id, '❌ You are not a member yet. Please join the channel and try again.')

@app.on_message(filters.private & filters.regex(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/'))
async def handle_youtube(client, message):
    user = message.from_user
    text = message.text.strip()

    # ban check
    u = users_col.find_one({'user_id': user.id})
    if u and u.get('is_banned'):
        return await message.reply_text('You are banned from using this bot.')

    # force sub
    if not await is_subscribed(client, user.id):
        return await message.reply_text('⚠️ To use this bot, please join our update channel first!', reply_markup=force_keyboard())

    vid = extract_video_id(text)
    if not vid:
        return await message.reply_text('❌ Invalid YouTube link!')

    urls = thumb_urls(vid)
    users_col.update_one({'user_id': user.id}, {'$inc': {'usage_count': 1}, '$set': {'last_active': datetime.utcnow()}}, upsert=True)
    logs_col.insert_one({'user_id': user.id, 'video_id': vid, 'time': datetime.utcnow(), 'bot_name': BOT_NAME})

    # send thumbnail (try maxres then fallback)
    try:
        await client.send_photo(chat_id=message.chat.id, photo=urls['maxres'], caption=f'Thumbnail for https://youtu.be/{vid}', reply_markup=thumbnail_keyboard(text, vid))
    except Exception:
        await client.send_photo(chat_id=message.chat.id, photo=urls['hq'], caption=f'Thumbnail for https://youtu.be/{vid}', reply_markup=thumbnail_keyboard(text, vid))

# Admin command: /stats
@app.on_message(filters.private & filters.command('stats') & filters.user(*ADMINS) if ADMINS else filters.private & filters.command('stats'))
async def cmd_stats(client, message):
    total_users = users_col.count_documents({})
    total_logs = logs_col.count_documents({})
    await message.reply_text(f'📊 Total Users: {total_users}\n📝 Total Actions Logged: {total_logs}')

if __name__ == '__main__':
    logger.info('Starting bot...')
    app.run()
