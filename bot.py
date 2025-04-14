import os
import re
import time
import logging
import tempfile
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, CallbackQueryHandler,
    CallbackContext, Filters, ConversationHandler
)

from config import TELEGRAM_TOKEN, MAX_VIDEO_SIZE_MB, MAX_MERGE_VIDEOS
from downloader import VideoDownloader
from video_processor import VideoProcessor
from file_uploader import FileUploader

# Setup logging
logger = logging.getLogger(__name__)

# Conversation states
AWAITING_LINKS, PROCESSING = range(2)

# Dictionary to store video URLs for each user
user_videos = {}


class VideoMergeBot:
    """Telegram bot for downloading and merging videos."""
    
    def __init__(self):
        self.downloader = VideoDownloader()
        self.processor = VideoProcessor()
        self.file_uploader = FileUploader()
        self.updater = Updater(token=TELEGRAM_TOKEN)
        self.dispatcher = self.updater.dispatcher
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Set up the bot command handlers."""
        # Command handlers
        self.dispatcher.add_handler(CommandHandler("start", self.start_command))
        self.dispatcher.add_handler(CommandHandler("help", self.help_command))
        
        # Conversation handler for video merging process
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("merge", self.merge_command)],
            states={
                AWAITING_LINKS: [
                    MessageHandler(Filters.text & ~Filters.command, self.receive_links),
                    CallbackQueryHandler(self.button_callback)
                ],
                PROCESSING: [
                    CallbackQueryHandler(self.button_callback)
                ]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_command)]
        )
        self.dispatcher.add_handler(conv_handler)
        
        # Error handler
        self.dispatcher.add_error_handler(self.error_handler)
    
    def start_command(self, update: Update, context: CallbackContext):
        """Handle the /start command."""
        user = update.effective_user
        update.message.reply_html(
            f"👋 Hello, {user.mention_html()}!\n\n"
            f"I'm a Video Merger Bot. I can download videos from links you send me "
            f"and merge them into a single video file of any size.\n\n"
            f"I'll upload the merged video to a file hosting service and provide you with a download link. "
            f"This allows handling files larger than Telegram's 50MB limit.\n\n"
            f"To get started, use the /merge command to begin adding video links."
        )
    
    def help_command(self, update: Update, context: CallbackContext):
        """Handle the /help command."""
        help_text = (
            "🎬 *Video Merger Bot Help* 🎬\n\n"
            "*Commands:*\n"
            "• /start - Start the bot\n"
            "• /merge - Begin a new video merging process\n"
            "• /cancel - Cancel the current operation\n"
            "• /help - Show this help message\n\n"
            
            "*How to use:*\n"
            "1. Send /merge to start a new merging process\n"
            "2. Send video links one by one or multiple links in one message\n"
            "3. Press 'Done' when you've added all your videos\n"
            "4. Wait for processing to complete (you'll see progress updates)\n"
            "5. Get a download link for your merged video!\n\n"
            
            "*Features:*\n"
            "• Progress tracking for downloads, transcoding, merging and uploading\n"
            "• Support for videos of any size (up to 10GB per video)\n"
            "• Upload to multiple file hosting services with fallbacks\n"
            "• Detailed status updates throughout the process\n\n"
            
            "*Supported video sources:*\n"
            "YouTube, Vimeo, Twitter/X, Instagram, Facebook, and direct video links\n\n"
            
            "*Limitations:*\n"
            f"• Maximum {MAX_MERGE_VIDEOS} videos per merge\n"
            f"• Each video should be under {MAX_VIDEO_SIZE_MB/1024:.0f}GB\n"
            "• Processing may take some time depending on video length and quality\n"
            "• File hosting links may expire after some time"
        )
        
        update.message.reply_markdown(help_text)
    
    def merge_command(self, update: Update, context: CallbackContext):
        """Start the video merging process."""
        user_id = update.effective_user.id
        
        # Clear any previous videos for this user
        user_videos[user_id] = []
        
        keyboard = [
            [InlineKeyboardButton("Done", callback_data="done")],
            [InlineKeyboardButton("Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            "Send me the links to the videos you want to merge.\n\n"
            "You can send multiple links (one per line) or send them one at a time.\n"
            "When you're done adding videos, press the 'Done' button.",
            reply_markup=reply_markup
        )
        
        return AWAITING_LINKS
    
    def receive_links(self, update: Update, context: CallbackContext):
        """Process incoming video links."""
        user_id = update.effective_user.id
        text = update.message.text
        
        # Initialize user's video list if doesn't exist
        if user_id not in user_videos:
            user_videos[user_id] = []
        
        # Extract URLs from text
        urls = self._extract_urls(text)
        
        if not urls:
            update.message.reply_text(
                "❌ No valid URLs found in your message. Please send valid video links."
            )
            return AWAITING_LINKS
        
        # Check if adding these would exceed the maximum
        if len(user_videos[user_id]) + len(urls) > MAX_MERGE_VIDEOS:
            update.message.reply_text(
                f"❌ You can only merge up to {MAX_MERGE_VIDEOS} videos at once. "
                f"You've already added {len(user_videos[user_id])} videos."
            )
            return AWAITING_LINKS
        
        # Add the URLs to the user's list
        user_videos[user_id].extend(urls)
        
        # Provide feedback
        added_count = len(urls)
        total_count = len(user_videos[user_id])
        
        keyboard = [
            [InlineKeyboardButton("Done", callback_data="done")],
            [InlineKeyboardButton("Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            f"✅ Added {added_count} video link{'s' if added_count > 1 else ''}.\n"
            f"Total: {total_count} video{'s' if total_count > 1 else ''}.\n\n"
            f"Send more links or press 'Done' to start merging.",
            reply_markup=reply_markup
        )
        
        return AWAITING_LINKS
    
    def button_callback(self, update: Update, context: CallbackContext):
        """Handle button callbacks."""
        query = update.callback_query
        query.answer()
        
        user_id = query.from_user.id
        
        if query.data == "cancel":
            # Clear user data
            if user_id in user_videos:
                del user_videos[user_id]
            
            query.edit_message_text("Operation canceled.")
            return ConversationHandler.END
        
        elif query.data == "done":
            # Check if the user has added any videos
            if user_id not in user_videos or not user_videos[user_id]:
                query.edit_message_text(
                    "❌ You haven't added any videos. Operation canceled."
                )
                return ConversationHandler.END
            
            # Start processing
            query.edit_message_text(
                f"🔄 Processing {len(user_videos[user_id])} videos. This may take some time..."
            )
            
            # Process videos
            return self.process_videos(update, context, user_id)
    
    def process_videos(self, update: Update, context: CallbackContext, user_id: int):
        """Process and merge the videos."""
        query = update.callback_query
        urls = user_videos[user_id]
        downloaded_paths = []
        transcoded_paths = []
        
        try:
            # Progress updates
            progress_message = context.bot.send_message(
                chat_id=user_id,
                text="🔄 Starting download and processing..."
            )
            
            # Download each video
            for i, url in enumerate(urls):
                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=progress_message.message_id,
                    text=f"⬇️ Downloading video {i+1}/{len(urls)}...\nURL: {url[:30]}..."
                )
                
                try:
                    # Define a download progress callback
                    def download_progress_callback(bytes_downloaded, total_bytes, percentage, speed_kbps, eta_seconds, status):
                        # Only update every 10% to avoid too many messages
                        if percentage % 10 == 0:
                            try:
                                eta_text = f"{eta_seconds // 60}m {eta_seconds % 60}s" if eta_seconds else "calculating..."
                                
                                context.bot.edit_message_text(
                                    chat_id=user_id,
                                    message_id=progress_message.message_id,
                                    text=f"⬇️ Downloading video {i+1}/{len(urls)}... {percentage}%\n"
                                         f"Speed: {speed_kbps/1024:.1f} MB/s, ETA: {eta_text}\n"
                                         f"URL: {url[:30]}..."
                                )
                            except Exception:
                                # Ignore errors from message rate limiting
                                pass
                    
                    # Download with progress tracking
                    video_path = self.downloader.download_video(url, download_progress_callback)
                    downloaded_paths.append(video_path)
                    
                    # Check file size
                    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
                    logger.info(f"Downloaded video {i+1}: {video_path} ({file_size_mb:.2f} MB)")
                    
                    if file_size_mb > MAX_VIDEO_SIZE_MB:
                        raise ValueError(f"Video {i+1} is too large ({file_size_mb:.2f} MB > {MAX_VIDEO_SIZE_MB} MB)")
                    
                except Exception as e:
                    logger.error(f"Error downloading video {i+1}: {e}")
                    context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=progress_message.message_id,
                        text=f"❌ Error downloading video {i+1}: {str(e)}\n\nOperation canceled."
                    )
                    # Clean up any downloaded files
                    for path in downloaded_paths:
                        if os.path.exists(path):
                            os.remove(path)
                    
                    return ConversationHandler.END
            
            # Transcode videos for compatibility
            transcoded_paths = []
            for i, video_path in enumerate(downloaded_paths):
                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=progress_message.message_id,
                    text=f"🔄 Transcoding video {i+1}/{len(downloaded_paths)}..."
                )
                
                try:
                    # Define a transcode progress callback
                    def transcode_progress_callback(progress, operation_type, message, details):
                        # Only update every 10% to avoid too many messages
                        if progress % 10 == 0:
                            try:
                                context.bot.edit_message_text(
                                    chat_id=user_id,
                                    message_id=progress_message.message_id,
                                    text=f"🔄 Transcoding video {i+1}/{len(downloaded_paths)}... {progress}%\n{message}"
                                )
                            except Exception:
                                # Ignore errors from message rate limiting
                                pass
                    
                    transcoded_path = self.processor.transcode_video(video_path, None, transcode_progress_callback)
                    transcoded_paths.append(transcoded_path)
                except Exception as e:
                    logger.error(f"Error transcoding video {i+1}: {e}")
                    context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=progress_message.message_id,
                        text=f"❌ Error transcoding video {i+1}: {str(e)}\n\nOperation canceled."
                    )
                    # Clean up
                    self.processor.cleanup_temp_files(downloaded_paths + transcoded_paths)
                    return ConversationHandler.END
            
            # Merge videos
            context.bot.edit_message_text(
                chat_id=user_id,
                message_id=progress_message.message_id,
                text="🔄 Merging videos... This may take a while."
            )
            
            try:
                # Define a progress callback for the merge operation
                def merge_progress_callback(progress, operation_type, message, details):
                    # Only update every 5% to avoid too many messages
                    if progress % 5 == 0:
                        try:
                            context.bot.edit_message_text(
                                chat_id=user_id,
                                message_id=progress_message.message_id,
                                text=f"🔄 Merging videos... {progress}%\n{message}"
                            )
                        except Exception:
                            # Ignore errors from message rate limiting
                            pass
                
                output_filename = f"merged_video_{user_id}_{int(time.time())}.mp4"
                merged_path = self.processor.merge_videos(transcoded_paths, output_filename, merge_progress_callback)
                
                # Upload the merged video to file hosting services
                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=progress_message.message_id,
                    text="✅ Merging complete! Uploading the video to file hosting services..."
                )
                
                # Get the file size
                file_size_mb = os.path.getsize(merged_path) / (1024 * 1024)
                
                # Define a progress callback for the upload
                def upload_progress_callback(service_index, service_name, service_progress, overall_progress):
                    # Only update every 10% to avoid too many messages
                    if service_progress % 10 == 0:
                        try:
                            context.bot.edit_message_text(
                                chat_id=user_id,
                                message_id=progress_message.message_id,
                                text=f"📤 Uploading to {service_name}... {service_progress}% complete"
                            )
                        except Exception:
                            # Ignore errors from message rate limiting
                            pass
                
                # Try to upload the file to hosting services
                upload_result = self.file_uploader.upload_file(
                    merged_path, 
                    max_attempts=5, 
                    progress_callback=upload_progress_callback
                )
                
                if upload_result.get('success'):
                    # Success - send download link to user
                    file_url = upload_result.get('url')
                    service_name = upload_result.get('service_name')
                    
                    success_message = (
                        f"✅ Your merged video ({file_size_mb:.2f}MB) has been processed successfully!\n\n"
                        f"📥 Download from: {service_name}\n"
                        f"{file_url}\n\n"
                        f"⚠️ This link may expire after some time depending on the service.\n\n"
                        f"The video contains {len(transcoded_paths)} merged videos."
                    )
                    
                    context.bot.send_message(
                        chat_id=user_id,
                        text=success_message,
                        disable_web_page_preview=False  # Allow link preview
                    )
                else:
                    # Failed to upload - try Telegram if small enough
                    error = upload_result.get('error', 'Unknown error')
                    logger.error(f"Failed to upload to file hosting services: {error}")
                    
                    # For small files, try sending directly through Telegram as fallback
                    if file_size_mb <= 50:  # Telegram bot API limit is 50MB
                        context.bot.send_message(
                            chat_id=user_id,
                            text=f"⚠️ Failed to upload to file hosting services. Sending directly through Telegram..."
                        )
                        
                        with open(merged_path, 'rb') as video_file:
                            context.bot.send_video(
                                chat_id=user_id,
                                video=video_file,
                                caption=f"✅ Here's your merged video! ({file_size_mb:.2f}MB)"
                            )
                    else:
                        # File too large for Telegram and upload failed
                        context.bot.send_message(
                            chat_id=user_id,
                            text=f"❌ Failed to upload the merged video to file hosting services, and the file "
                                 f"is too large ({file_size_mb:.2f}MB) to send through Telegram.\n\n"
                                 f"Error: {error}\n\n"
                                 f"Please try again with fewer or shorter videos."
                        )
                
                # Clean up
                self.processor.cleanup_temp_files(downloaded_paths + transcoded_paths + [merged_path])
                
                # Clear user data
                del user_videos[user_id]
                
                context.bot.send_message(
                    chat_id=user_id,
                    text="✅ All done! You can start a new merging process with /merge."
                )
                
            except Exception as e:
                logger.error(f"Error merging videos: {e}")
                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=progress_message.message_id,
                    text=f"❌ Error merging videos: {str(e)}\n\nOperation canceled."
                )
                # Clean up
                self.processor.cleanup_temp_files(downloaded_paths + transcoded_paths)
        
        except Exception as e:
            logger.error(f"Unexpected error in process_videos: {e}")
            context.bot.send_message(
                chat_id=user_id,
                text=f"❌ An unexpected error occurred: {str(e)}\n\nOperation canceled."
            )
            # Clean up any files
            for path in downloaded_paths + transcoded_paths:
                if os.path.exists(path):
                    os.remove(path)
        
        return ConversationHandler.END
    
    def cancel_command(self, update: Update, context: CallbackContext):
        """Cancel the current operation."""
        user_id = update.effective_user.id
        
        # Clear user data
        if user_id in user_videos:
            del user_videos[user_id]
        
        update.message.reply_text("Operation canceled.")
        return ConversationHandler.END
    
    def error_handler(self, update: object, context: CallbackContext):
        """Handle errors in the dispatcher."""
        logger.error(f"Update {update} caused error {context.error}")
        
        # Send error message to user if possible
        if update and hasattr(update, 'effective_chat'):
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ An error occurred: {str(context.error)}\n\nPlease try again or contact the bot administrator."
            )
    
    def _extract_urls(self, text):
        """Extract URLs from text."""
        url_pattern = r'https?://[^\s]+'
        return re.findall(url_pattern, text)
    
    def run(self):
        """Run the bot."""
        try:
            self.updater.start_polling()
            # When running in a thread, we can't use idle() which relies on signal handling
            # So we use a simple loop instead
            import threading
            if threading.current_thread() is not threading.main_thread():
                import time
                while True:
                    time.sleep(1)
            else:
                self.updater.idle()
        except Exception as e:
            logger.error(f"Error in bot.run(): {e}")
            # Don't raise the exception further to keep the thread alive


if __name__ == "__main__":
    bot = VideoMergeBot()
    bot.run()
