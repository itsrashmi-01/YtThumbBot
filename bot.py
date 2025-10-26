import os
import re
import logging
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
FORCE_CHANNEL = os.environ.get("FORCE_CHANNEL")
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL"))
ADMINS = [int(admin) for admin in os.environ.get("ADMINS", "").split(",")]
BOT_NAME = os.environ.get("BOT_NAME", "YT Thumbnail Downloader")
START_IMAGE = os.environ.get("START_IMAGE", "https://telegra.ph/file/1b2df9f3014633f679544.jpg")

# --- Initialize Logging ---
logging.basicConfig(level=logging.INFO)

# --- Initialize MongoDB ---
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client.get_database("youtube_thumbnail_bot")
    user_collection = db.get_collection("users")
    logging.info("Successfully connected to MongoDB.")
except Exception as e:
    logging.error(f"Error connecting to MongoDB: {e}")
    mongo_client = None

# --- Initialize Pyrogram Client ---
app = Client("thumbnail_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Helper Functions ---

def get_video_id(url):
    """Extracts YouTube video ID from various URL formats."""
    regex = r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    return match.group(1) if match else None

async def is_user_subscribed(user_id):
    """Checks if a user is a member of the force subscribe channel."""
    try:
        await app.get_chat_member(chat_id=FORCE_CHANNEL, user_id=user_id)
        return True
    except Exception:
        return False

async def add_user_to_db(message: Message):
    """Adds or updates user information in the database."""
    if not mongo_client:
        return
    user_id = message.from_user.id
    if not user_collection.find_one({"user_id": user_id}):
        user_data = {
            "user_id": user_id,
            "username": message.from_user.username or "N/A",
            "first_name": message.from_user.first_name,
            "join_date": datetime.utcnow(),
            "usage_count": 0,
        }
        user_collection.insert_one(user_data)
        # Log new user to the log channel
        await app.send_message(
            LOG_CHANNEL,
            f"**✨ New User Alert ✨**\n\n"
            f"**User Name:** {message.from_user.first_name}\n"
            f"**User ID:** `{user_id}`\n"
            f"**Username:** @{message.from_user.username}\n"
            f"**Bot Name:** {BOT_NAME}"
        )

# --- Command Handlers ---

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """Handles the /start command."""
    await add_user_to_db(message)

    welcome_text = (
        f"**👋 Hello, {message.from_user.first_name}!**\n\n"
        f"I am the **{BOT_NAME}**, your reliable assistant for downloading YouTube video thumbnails.\n\n"
        "Simply send me any YouTube video link to get started!"
    )
    
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💡 About Bot", callback_data="about_bot"), InlineKeyboardButton("📢 Updates Channel", url="https://t.me/BotClusters")],
            [InlineKeyboardButton("🛠️ More Tools", callback_data="more_tools"), InlineKeyboardButton("🤝 Support", url="https://t.me/BC_Support")],
        ]
    )
    
    await message.reply_photo(
        photo=START_IMAGE,
        caption=welcome_text,
        reply_markup=keyboard
    )

@app.on_message(filters.text & ~filters.command("start"))
async def handle_youtube_url(client, message: Message):
    """Handles YouTube URL messages."""
    user_id = message.from_user.id
    
    # --- Force Subscribe Check ---
    if not await is_user_subscribed(user_id):
        join_link = (await app.get_chat(FORCE_CHANNEL)).invite_link
        if not join_link:
            # Fallback in case invite link isn't fetchable
            join_link = f"https://t.me/{FORCE_CHANNEL}"

        await message.reply_text(
            "**⚠️ Access Denied!**\n\n"
            "To use this bot, you must join our updates channel. This helps us keep you updated on new features and important announcements.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("➡️ Join Channel", url=join_link)],
                    [InlineKeyboardButton("✅ I Have Joined", callback_data="check_subscribe")]
                ]
            )
        )
        return

    # --- URL Validation and Thumbnail Generation ---
    video_id = get_video_id(message.text)
    
    if not video_id:
        await message.reply_text("❌ **Invalid URL!** Please send a valid YouTube video link.")
        return

    sd_thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    hd_thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

    caption = f"🖼️ Thumbnails for **{video_id}**"
    
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📥 Download SD", url=sd_thumbnail_url),
                InlineKeyboardButton("📥 Download HD", url=hd_thumbnail_url)
            ]
        ]
    )

    try:
        # Send HD first, as it's the most requested
        await message.reply_photo(photo=hd_thumbnail_url, caption=caption, reply_markup=keyboard)
    except Exception:
        try:
            # Fallback to SD if HD isn't available
            await message.reply_photo(photo=sd_thumbnail_url, caption=caption, reply_markup=keyboard)
        except Exception as e:
            await message.reply_text("Could not fetch the thumbnail. Please check the video link.")
            logging.error(f"Error fetching thumbnail for {video_id}: {e}")

    # Update usage count
    if mongo_client:
        user_collection.update_one({"user_id": user_id}, {"$inc": {"usage_count": 1}})


# --- Callback Query Handlers ---

@app.on_callback_query()
async def callback_query_handler(client, callback_query):
    """Handles all callback queries."""
    data = callback_query.data
    
    if data == "about_bot":
        await callback_query.message.edit_caption(
            caption="**About This Bot**\n\n"
                    "This bot is designed to help you quickly download high-quality thumbnails from any YouTube video.\n\n"
                    "**Features:**\n"
                    "✅ HD & SD Quality\n"
                    "✅ Fast & Reliable\n"
                    "✅ Easy to Use\n\n"
                    "Powered by [BotClusters](https://t.me/BotClusters).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]])
        )
    
    elif data == "more_tools":
        await callback_query.message.edit_caption(
            caption="**Discover More Tools**\n\n"
                    "Explore our collection of other useful bots and tools designed to make your life easier!\n\n"
                    "Visit our main channel to see what else we have to offer.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 Explore Bots", url="https://t.me/BotClusters")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_to_start")]
            ])
        )
        
    elif data == "back_to_start":
        welcome_text = (
            f"**👋 Hello, {callback_query.from_user.first_name}!**\n\n"
            f"I am the **{BOT_NAME}**, your reliable assistant for downloading YouTube video thumbnails.\n\n"
            "Simply send me any YouTube video link to get started!"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("💡 About Bot", callback_data="about_bot"), InlineKeyboardButton("📢 Updates Channel", url="https://t.me/BotClusters")],
                [InlineKeyboardButton("🛠️ More Tools", callback_data="more_tools"), InlineKeyboardButton("🤝 Support", url="https://t.me/BC_Support")],
            ]
        )
        await callback_query.message.edit_caption(caption=welcome_text, reply_markup=keyboard)

    elif data == "check_subscribe":
        if await is_user_subscribed(callback_query.from_user.id):
            await callback_query.answer("Thank you for joining! You can now use the bot.", show_alert=True)
            await callback_query.message.delete()
        else:
            await callback_query.answer("You have not joined the channel yet. Please join to continue.", show_alert=True)
            
    await callback_query.answer()


# --- Main Execution ---

if __name__ == "__main__":
    logging.info(f"{BOT_NAME} - Bot starting...")
    app.run()
    print("Bot started successfully on Koyeb 🚀")