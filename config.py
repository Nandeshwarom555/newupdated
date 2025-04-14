import os
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Bot configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("No TELEGRAM_TOKEN found in environment variables")
    raise ValueError("TELEGRAM_TOKEN environment variable is required")

# Video processing configuration
MAX_VIDEO_SIZE_MB = 10000  # Effectively no limit (10 GB should be enough for most use cases)
MAX_MERGE_VIDEOS = 50    # Allow more videos to be merged in a single request
SUPPORTED_SITES = ["youtube", "vimeo", "dailymotion", "twitter", "instagram", "facebook"]

# Temporary file paths - always use absolute paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DOWNLOAD_DIR = os.path.join(BASE_DIR, "temp_downloads")
TEMP_OUTPUT_DIR = os.path.join(BASE_DIR, "temp_output")

# Create necessary directories if they don't exist
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_OUTPUT_DIR, exist_ok=True)

logger.info(f"Temporary download directory: {TEMP_DOWNLOAD_DIR}")
logger.info(f"Temporary output directory: {TEMP_OUTPUT_DIR}")

# FFmpeg configuration
FFMPEG_PRESET = "medium"  # Options: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
OUTPUT_FORMAT = "mp4"     # Default output format
OUTPUT_CODEC = "libx264"  # Default video codec
AUDIO_CODEC = "aac"       # Default audio codec
