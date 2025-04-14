import os
import tempfile
import logging
import time
from urllib.parse import urlparse
import yt_dlp
import requests
from config import TEMP_DOWNLOAD_DIR, SUPPORTED_SITES

logger = logging.getLogger(__name__)

class VideoDownloader:
    """Class to handle downloading videos from various sources."""
    
    def __init__(self):
        self.ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(TEMP_DOWNLOAD_DIR, '%(id)s.%(ext)s'),
            'noplaylist': True,
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': False,
        }
    
    def is_valid_url(self, url):
        """Check if the provided URL is valid."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception as e:
            logger.error(f"Invalid URL format: {e}")
            return False
    
    def is_supported_site(self, url):
        """Check if the URL is from a supported site."""
        domain = urlparse(url).netloc.lower()
        return any(site in domain for site in SUPPORTED_SITES)
    
    def download_video(self, url, progress_callback=None):
        """
        Download video from URL and return the local file path.
        
        Args:
            url: URL to download
            progress_callback: Optional callback function that accepts:
                - bytes_downloaded: int
                - total_bytes: int
                - percentage: int (0-100)
                - speed_kbps: float (download speed in KB/s)
                - eta_seconds: int (estimated time remaining in seconds)
                - status: str (description of current operation)
        
        Returns:
            str: Path to downloaded video file
        """
        if not self.is_valid_url(url):
            raise ValueError(f"Invalid URL format: {url}")
        
        # Create a temporary file for direct downloads
        temp_file = None
        
        try:
            if self.is_supported_site(url):
                logger.info(f"Downloading from supported site: {url}")
                return self._download_with_ytdlp(url, progress_callback)
            else:
                logger.info(f"Attempting direct download: {url}")
                return self._download_direct(url, progress_callback)
        except Exception as e:
            logger.error(f"Download failed: {e}")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            raise
    
    def _download_with_ytdlp(self, url, progress_callback=None):
        """
        Download video using yt-dlp with progress tracking.
        
        Args:
            url: URL to download
            progress_callback: Function to call with progress updates
        """
        # Create a progress hook if callback is provided
        progress_hooks = []
        
        if progress_callback:
            # Start time for calculating download speed
            start_time = time.time()
            downloaded_bytes = 0
            
            def progress_hook(d):
                nonlocal downloaded_bytes, start_time
                
                if d['status'] == 'downloading':
                    # Get download information
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    
                    # If this is a new amount of downloaded bytes, update our stats
                    if downloaded > downloaded_bytes:
                        downloaded_bytes = downloaded
                        
                        # Calculate percentage
                        if total > 0:
                            percentage = int(downloaded * 100 / total)
                        else:
                            percentage = 0
                        
                        # Calculate speed
                        elapsed = time.time() - start_time
                        if elapsed > 0:
                            speed_kbps = downloaded / elapsed / 1024  # KB/s
                            
                            # Calculate ETA
                            if speed_kbps > 0 and total > 0:
                                remaining_bytes = total - downloaded
                                eta_seconds = int(remaining_bytes / (speed_kbps * 1024))
                            else:
                                eta_seconds = 0
                            
                            # Call progress callback with stats
                            progress_callback(
                                downloaded, 
                                total, 
                                percentage, 
                                speed_kbps, 
                                eta_seconds,
                                f"Downloading from {d.get('info_dict', {}).get('extractor', 'YouTube')}"
                            )
                
                elif d['status'] == 'finished':
                    # Download finished
                    if progress_callback:
                        progress_callback(
                            downloaded_bytes, 
                            downloaded_bytes, 
                            100, 
                            0, 
                            0,
                            "Download complete, processing video..."
                        )
            
            progress_hooks.append(progress_hook)
        
        # Update options with progress hook
        ydl_opts = self.ydl_opts.copy()
        ydl_opts['progress_hooks'] = progress_hooks
        
        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'entries' in info:
                # Playlist, take the first video
                info = info['entries'][0]
            
            # Get downloaded file path
            video_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{info['id']}.{info['ext']}")
            logger.info(f"Downloaded video to {video_path}")
            
            return video_path
    
    def _download_direct(self, url, progress_callback=None):
        """
        Attempt to download video directly using requests with progress tracking.
        
        Args:
            url: URL to download
            progress_callback: Function to call with progress updates
        """
        # Create a temporary file with a random name
        fd, temp_path = tempfile.mkstemp(dir=TEMP_DOWNLOAD_DIR, suffix='.mp4')
        os.close(fd)
        
        try:
            with requests.get(url, stream=True) as response:
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                
                # Setup for progress tracking
                downloaded = 0
                start_time = time.time()
                last_update_time = start_time
                chunk_size = 1024 * 1024  # 1MB chunks for better progress reporting
                
                with open(temp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            current_time = time.time()
                            
                            # Update progress at most once every 0.5 seconds or every 1MB
                            if current_time - last_update_time >= 0.5 or downloaded % chunk_size == 0:
                                last_update_time = current_time
                                
                                # Log progress
                                logger.info(f"Downloaded {downloaded/(1024*1024):.1f}MB of {total_size/(1024*1024):.1f}MB")
                                
                                # Calculate statistics
                                elapsed = current_time - start_time
                                if elapsed > 0 and progress_callback:
                                    speed_kbps = downloaded / elapsed / 1024  # KB/s
                                    
                                    # Calculate percentage
                                    if total_size > 0:
                                        percentage = int(downloaded * 100 / total_size)
                                    else:
                                        percentage = 0
                                    
                                    # Calculate ETA
                                    if speed_kbps > 0 and total_size > 0:
                                        remaining_bytes = total_size - downloaded
                                        eta_seconds = int(remaining_bytes / (speed_kbps * 1024))
                                    else:
                                        eta_seconds = 0
                                    
                                    # Call progress callback
                                    progress_callback(
                                        downloaded, 
                                        total_size, 
                                        percentage, 
                                        speed_kbps, 
                                        eta_seconds,
                                        "Downloading video..."
                                    )
                
                # Final progress update
                if progress_callback and total_size > 0:
                    progress_callback(
                        total_size,  # Assuming we got it all
                        total_size,
                        100,  # 100%
                        0,    # Speed not relevant at end
                        0,    # ETA not relevant at end
                        "Download complete"
                    )
            
            logger.info(f"Direct download completed: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"Direct download failed: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
