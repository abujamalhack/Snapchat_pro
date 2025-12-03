#!/usr/bin/env python3
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.error import TelegramError

from config import config
from snap_api import SnapchatAPI
from downloader import DownloadManager
from watermark_remover import WatermarkRemover
from queue_manager import QueueManager
from rate_limiter import RateLimiter

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('snapbot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class SnapchatDownloaderBot:
    def __init__(self):
        self.application: Optional[Application] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.api: Optional[SnapchatAPI] = None
        self.downloader: Optional[DownloadManager] = None
        self.watermark_remover: Optional[WatermarkRemover] = None
        self.queue: Optional[QueueManager] = None
        self.rate_limiter: Optional[RateLimiter] = None
        
    async def initialize(self):
        """Initialize bot components."""
        import aiohttp
        
        # Create session
        self.session = aiohttp.ClientSession()
        
        # Initialize components
        self.api = SnapchatAPI(self.session)
        self.downloader = DownloadManager(self.session, max_workers=config.bot.concurrent_downloads)
        self.watermark_remover = WatermarkRemover()
        self.queue = QueueManager(max_concurrent=config.bot.concurrent_downloads)
        self.rate_limiter = RateLimiter(requests_per_minute=30)
        
        # Start queue manager
        await self.queue.start()
        
        # Create temp directory
        Path(config.bot.temp_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize Telegram bot
        self.application = Application.builder().token(config.bot.token).build()
        
        # Add handlers
        self._add_handlers()
        
    def _add_handlers(self):
        """Add all Telegram handlers."""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user = update.effective_user
        
        welcome_text = f"""
👻 *Snapchat Downloader Bot v3.0* 👻

Hey {user.first_name}! I can download Snapchat Stories and Spotlight videos without watermarks.

*Available Commands:*
• Send a Snapchat username (e.g., `username`)
• Send a profile URL
• Send a Spotlight video URL
• /stats - Check your usage

*Features:*
✅ No watermark
✅ High quality
✅ Fast downloads
✅ Batch downloads
✅ Rate limit: 30 requests/minute

*Note:* Only public content is supported.
        """
        
        keyboard = [
            [InlineKeyboardButton("📖 How to Use", callback_data="help")],
            [InlineKeyboardButton("🔧 Status", callback_data="status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = """
*How to Use:*

1. *Username Method:*
   Just send a Snapchat username (e.g., `champagnepapi`)

2. *URL Method:*
   Send a Snapchat profile URL:
   `https://www.snapchat.com/add/username`

3. *Spotlight Videos:*
   Send a Spotlight video URL:
   `https://www.snapchat.com/spotlight/video_id`

*Bot will:*
• Fetch all available public stories
• Download them without watermark
• Send them to you individually

*Limits:*
• Max 10 items per request
• 100MB file size limit
• 30 requests per minute
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        user_id = update.effective_user.id
        stats = self.rate_limiter.get_user_stats(user_id)
        
        stats_text = f"""
*Your Stats:*
• Requests this minute: {stats['requests_last_minute']}/{stats['limit']}
• Rate limit resets in: {stats['next_reset_in']:.0f} seconds
• Concurrent downloads: {config.bot.concurrent_downloads}
• Max file size: {config.bot.max_file_size // 1024 // 1024}MB
        """
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages."""
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # Check rate limit
        if not await self.rate_limiter.wait_if_needed(user_id):
            await update.message.reply_text("⏳ Rate limit exceeded. Please wait 1 minute.")
            return
        
        # Show typing indicator
        await update.message.chat.send_action(action="typing")
        
        try:
            # Determine content type
            if "snapchat.com/add/" in text.lower():
                # Profile URL
                username = self._extract_username(text)
                if username:
                    await self._process_username(update, username)
                else:
                    await update.message.reply_text("❌ Invalid URL format.")
            
            elif "snapchat.com/spotlight/" in text.lower():
                # Spotlight video
                video_id = self._extract_video_id(text)
                if video_id:
                    await self._process_spotlight(update, video_id)
                else:
                    await update.message.reply_text("❌ Invalid Spotlight URL.")
            
            elif self._looks_like_username(text):
                # Username
                await self._process_username(update, text)
            
            else:
                await update.message.reply_text("❌ Invalid input. Send a username or Snapchat URL.")
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    async def _process_username(self, update: Update, username: str):
        """Process username and download stories."""
        user_id = update.effective_user.id
        message = await update.message.reply_text(f"🔍 Fetching stories for @{username}...")
        
        try:
            # Get stories
            stories = await self.api.get_user_stories(username)
            
            if not stories:
                await message.edit_text(f"❌ No public stories found for @{username}")
                return
            
            await message.edit_text(f"✅ Found {len(stories)} items. Downloading...")
            
            # Download stories
            downloaded_files = await self.downloader.download_batch(stories, user_id)
            
            if not downloaded_files:
                await message.edit_text("❌ Failed to download any content.")
                return
            
            # Send files
            success_count = 0
            for filepath in downloaded_files:
                try:
                    if str(filepath).endswith(('.mp4', '.mov', '.avi')):
                        await update.message.reply_video(
                            video=open(filepath, 'rb'),
                            caption=f"@{username} - Downloaded via SnapBot"
                        )
                    else:
                        await update.message.reply_photo(
                            photo=open(filepath, 'rb'),
                            caption=f"@{username} - Downloaded via SnapBot"
                        )
                    success_count += 1
                    
                    # Clean up file
                    try:
                        filepath.unlink()
                    except:
                        pass
                        
                except Exception as e:
                    logger.error(f"Error sending file: {e}")
                    continue
            
            await message.edit_text(f"✅ Successfully downloaded {success_count}/{len(stories)} items.")
            
        except Exception as e:
            logger.error(f"Error processing username: {e}")
            await message.edit_text(f"❌ Error: {str(e)[:100]}")
    
    async def _process_spotlight(self, update: Update, video_id: str):
        """Process Spotlight video."""
        message = await update.message.reply_text("🔍 Fetching Spotlight video...")
        
        try:
            # Get video info
            video_data = await self.api.get_spotlight_video(video_id)
            
            if not video_data:
                await message.edit_text("❌ Video not found or is private.")
                return
            
            await message.edit_text("📥 Downloading video...")
            
            # Download video
            downloaded = await self.downloader.download_batch([video_data], update.effective_user.id)
            
            if not downloaded:
                await message.edit_text("❌ Failed to download video.")
                return
            
            # Send video
            filepath = downloaded[0]
            await update.message.reply_video(
                video=open(filepath, 'rb'),
                caption="🎥 Spotlight Video - Downloaded via SnapBot"
            )
            
            await message.edit_text("✅ Video downloaded successfully!")
            
            # Clean up
            try:
                filepath.unlink()
            except:
                pass
            
        except Exception as e:
            logger.error(f"Error processing spotlight: {e}")
            await message.edit_text(f"❌ Error: {str(e)[:100]}")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button presses."""
        query = update.callback_query
        await query.answer()
        
        if query.data == "help":
            await self.help_command(update, context)
        elif query.data == "status":
            await query.edit_message_text("✅ Bot is running normally.")
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors."""
        logger.error(f"Update {update} caused error {context.error}")
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    f"⚠️ An error occurred: {str(context.error)[:200]}"
                )
        except:
            pass
    
    def _extract_username(self, text: str) -> Optional[str]:
        """Extract username from URL."""
        import re
        patterns = [
            r'snapchat\.com/add/([a-zA-Z0-9_.-]+)',
            r'snapchat\.com/s/([a-zA-Z0-9_.-]+)',
            r'snapchat\.com/([a-zA-Z0-9_.-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    def _extract_video_id(self, text: str) -> Optional[str]:
        """Extract video ID from Spotlight URL."""
        import re
        patterns = [
            r'spotlight/([a-zA-Z0-9_-]+)',
            r'video/([a-zA-Z0-9_-]+)',
            r'v=([a-zA-Z0-9_-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    def _looks_like_username(self, text: str) -> bool:
        """Check if text looks like a Snapchat username."""
        import re
        pattern = r'^[a-zA-Z0-9_.-]{3,20}$'
        return bool(re.match(pattern, text))
    
    async def run(self):
        """Run the bot."""
        if not self.application:
            await self.initialize()
        
        logger.info("Starting bot...")
        await self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    async def cleanup(self):
        """Cleanup resources."""
        if self.session:
            await self.session.close()
        if self.queue:
            await self.queue.stop()

def main():
    """Main entry point."""
    bot = SnapchatDownloaderBot()
    
    try:
        # Run on asyncio event loop
        import asyncio
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    finally:
        # Cleanup
        import asyncio
        asyncio.run(bot.cleanup())

if __name__ == '__main__':
    main()