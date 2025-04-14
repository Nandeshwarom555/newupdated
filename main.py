import logging
import os
import threading
import time
import sys
from bot import VideoMergeBot
from app import app  # Import the Flask app
from config import logger, TELEGRAM_TOKEN, TEMP_DOWNLOAD_DIR, TEMP_OUTPUT_DIR

# Ensure required directories exist
for directory in [TEMP_DOWNLOAD_DIR, TEMP_OUTPUT_DIR]:
    if not os.path.exists(directory):
        logger.info(f"Creating directory: {directory}")
        os.makedirs(directory, exist_ok=True)

# For deployment (Koyeb), we run both the web app and bot in the same process
# For local development, we separate them to avoid conflicts:
# - "gunicorn main:application" runs the web app only
# - "python main.py" runs the bot only

# Check if we're running under Gunicorn (web server)
is_gunicorn = "gunicorn" in os.environ.get("SERVER_SOFTWARE", "")

# Check if we're running directly as a script (for the bot only)
is_script = __name__ == "__main__"

# Make the app available for Gunicorn
application = app

# Initialize bot only in the correct mode
bot = None

# When running on Koyeb with Gunicorn, start both web app and bot
if is_gunicorn and os.environ.get("KOYEB_APP_NAME"):
    if TELEGRAM_TOKEN:
        try:
            logger.info("Starting Video Merger Telegram Bot in production mode...")
            bot = VideoMergeBot()
            bot_thread = threading.Thread(target=bot.run)
            bot_thread.daemon = True
            bot_thread.start()
            logger.info("Bot initialized successfully in production mode")
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
    else:
        logger.warning("No TELEGRAM_TOKEN provided. Bot will not be started.")

def main():
    """Main entry point for bot-only mode."""
    # Only start the bot when running as a script and not under Gunicorn
    if is_script and not is_gunicorn:
        if not TELEGRAM_TOKEN:
            logger.error("No TELEGRAM_TOKEN provided. Bot cannot start.")
            sys.exit(1)
        
        # Only bot mode (for local testing)
        logger.info("Starting Video Merger Telegram Bot in standalone mode...")
        try:
            bot_instance = VideoMergeBot()
            bot_instance.run()
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            sys.exit(1)
    else:
        logger.info("Not running in bot-only mode. No action taken.")
        # Keep the script running
        while True:
            time.sleep(60)

if __name__ == "__main__":
    main()
