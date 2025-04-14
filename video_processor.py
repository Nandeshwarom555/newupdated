import os
import subprocess
import tempfile
import logging
import json
import time
import re
import threading
import shlex
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from config import (
    TEMP_DOWNLOAD_DIR, TEMP_OUTPUT_DIR, 
    FFMPEG_PRESET, OUTPUT_FORMAT, OUTPUT_CODEC, AUDIO_CODEC
)

logger = logging.getLogger(__name__)

class VideoProcessor:
    """Class to handle video processing and merging using FFmpeg."""
    
    def __init__(self):
        # Verify FFmpeg is installed
        try:
            version = subprocess.check_output(['ffmpeg', '-version'], stderr=subprocess.STDOUT)
            logger.info(f"FFmpeg detected: {version.decode().splitlines()[0]}")
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"FFmpeg not found: {e}")
            raise RuntimeError("FFmpeg is required but not found on the system.")
        
        # For tracking progress and cancellation
        self.current_process = None
        self.is_cancelled = False
        self.progress_callback = None
        
    def cancel_current_operation(self):
        """Cancel any ongoing operation."""
        logger.info("Cancelling current video processing operation")
        self.is_cancelled = True
        if self.current_process:
            try:
                self.current_process.terminate()
                logger.info("Process terminated")
            except Exception as e:
                logger.error(f"Error terminating process: {e}")
                
    def _get_progress_from_ffmpeg_output(self, line, duration):
        """Extract progress information from ffmpeg output line."""
        try:
            # Extract time position
            time_match = re.search(r'time=(\d+):(\d+):(\d+.\d+)', line)
            if time_match:
                h, m, s = map(float, time_match.groups())
                current_seconds = h * 3600 + m * 60 + s
                
                # Calculate percentage
                if duration > 0:
                    percentage = min(int(current_seconds * 100 / duration), 100)
                    return percentage
        except Exception as e:
            logger.debug(f"Error parsing ffmpeg progress: {e}")
        return None
    
    def _run_ffmpeg_with_progress(self, cmd, total_duration, operation_type="Processing", 
                                 progress_callback=None, additional_info=None):
        """
        Run ffmpeg command with progress tracking.
        
        Args:
            cmd: FFmpeg command list
            total_duration: Expected duration in seconds
            operation_type: String describing the operation (e.g., "Transcoding", "Merging")
            progress_callback: Function to call with progress updates
            additional_info: Additional info to include in progress updates
            
        Returns:
            CompletedProcess instance
        """
        if self.is_cancelled:
            raise Exception("Operation cancelled")
        
        # Save callback for potential cancellation
        self.progress_callback = progress_callback
        
        # Initialize progress
        start_time = time.time()
        if progress_callback:
            progress_callback(0, operation_type, 
                             f"Starting {operation_type.lower()}...", 
                             additional_info)
        
        # Format command for logging
        cmd_str = ' '.join(cmd)
        logger.info(f"{operation_type} command: {cmd_str}")
        
        # Create process with pipe for stderr to capture progress
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            universal_newlines=True,
            bufsize=1
        )
        
        # Save reference for potential cancellation
        self.current_process = process
        
        stdout_data = []
        stderr_data = []
        last_progress = 0
        last_update_time = time.time()
        
        # Read output line by line to track progress
        while True:
            if self.is_cancelled:
                process.terminate()
                raise Exception("Operation cancelled by user")
                
            # Check stdout
            stdout_line = process.stdout.readline()
            if stdout_line:
                stdout_data.append(stdout_line)
                
            # Check stderr (where ffmpeg writes progress)
            stderr_line = process.stderr.readline()
            if stderr_line:
                stderr_data.append(stderr_line)
                
                # Check for progress updates (not too frequently)
                current_time = time.time()
                if progress_callback and current_time - last_update_time >= 0.5:
                    progress = self._get_progress_from_ffmpeg_output(stderr_line, total_duration)
                    if progress is not None and progress > last_progress:
                        last_progress = progress
                        
                        # Calculate ETA
                        elapsed = current_time - start_time
                        if progress > 0:
                            total_estimated = elapsed * 100 / progress
                            eta_seconds = int(total_estimated - elapsed)
                            eta_text = str(timedelta(seconds=eta_seconds))
                        else:
                            eta_text = "calculating..."
                        
                        # Calculate processing speed
                        speed_factor = 1.0  # Default
                        speed_match = re.search(r'speed=(\d+\.?\d*)x', stderr_line)
                        if speed_match:
                            try:
                                speed_factor = float(speed_match.group(1))
                            except ValueError:
                                pass
                        
                        # Send progress update
                        progress_callback(
                            progress, 
                            operation_type,
                            f"{operation_type} {progress}% complete (ETA: {eta_text}, Speed: {speed_factor:.1f}x)",
                            additional_info
                        )
                        last_update_time = current_time
            
            # Check if process is still running
            if process.poll() is not None:
                break
        
        # Get remaining output
        stdout_rest = process.stdout.read()
        if stdout_rest:
            stdout_data.append(stdout_rest)
        stderr_rest = process.stderr.read()
        if stderr_rest:
            stderr_data.append(stderr_rest)
        
        # Final progress update
        if progress_callback:
            progress_callback(100, operation_type, 
                            f"{operation_type} completed", 
                            additional_info)
        
        # Check return code
        return_code = process.wait()
        if return_code != 0:
            stderr_text = ''.join(stderr_data)
            raise subprocess.CalledProcessError(
                returncode=return_code,
                cmd=cmd,
                output=''.join(stdout_data),
                stderr=stderr_text
            )
        
        # Reset current process reference
        self.current_process = None
        
        # Return result as if subprocess.run() was used
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=return_code,
            stdout=''.join(stdout_data),
            stderr=''.join(stderr_data)
        )
    
    def ensure_even_dimensions(self, width, height):
        """Ensure width and height are even numbers required by x264 codec."""
        width = int(width)
        height = int(height)
        # Make sure dimensions are even (required by x264)
        if width % 2 != 0:
            width -= 1
        if height % 2 != 0:
            height -= 1
        # Ensure dimensions are at least 2x2
        width = max(2, width)
        height = max(2, height)
        return width, height
    
    def get_video_info(self, video_path):
        """Get video information using FFprobe."""
        try:
            cmd = [
                'ffprobe', 
                '-v', 'quiet', 
                '-print_format', 'json', 
                '-show_format', 
                '-show_streams', 
                video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            
            # Extract relevant information
            video_info = {
                'filename': os.path.basename(video_path),
                'format': info.get('format', {}).get('format_name'),
                'duration': float(info.get('format', {}).get('duration', 0)),
                'size': int(info.get('format', {}).get('size', 0)),
                'streams': []
            }
            
            # Extract stream information
            for stream in info.get('streams', []):
                stream_info = {
                    'index': stream.get('index'),
                    'codec_type': stream.get('codec_type'),
                    'codec_name': stream.get('codec_name')
                }
                
                if stream.get('codec_type') == 'video':
                    stream_info.update({
                        'width': stream.get('width'),
                        'height': stream.get('height'),
                        'fps': eval(stream.get('r_frame_rate', '0/1')),
                        'bit_rate': stream.get('bit_rate')
                    })
                elif stream.get('codec_type') == 'audio':
                    stream_info.update({
                        'sample_rate': stream.get('sample_rate'),
                        'channels': stream.get('channels'),
                        'bit_rate': stream.get('bit_rate')
                    })
                
                video_info['streams'].append(stream_info)
            
            return video_info
        except subprocess.SubprocessError as e:
            logger.error(f"Error getting video info: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing FFprobe output: {e}")
            raise
    
    def transcode_video(self, video_path, target_resolution=None, progress_callback=None):
        """
        Transcode video to a standard format/codec for easier merging.
        
        Args:
            video_path: Path to the video file
            target_resolution: Optional resolution to transcode to (e.g., "1280x720")
            progress_callback: Optional function to call with progress updates
            
        Returns:
            str: Path to the transcoded video
        """
        # Reset cancellation flag
        self.is_cancelled = False
        
        try:
            # Get original video info
            video_info = self.get_video_info(video_path)
            logger.info(f"Video info: {video_info}")
            
            # Extract video details for progress reporting
            duration = float(video_info.get('duration', 0))
            format_name = video_info.get('format', 'unknown')
            size_mb = video_info.get('size', 0) / (1024 * 1024)
            
            # Get codec information
            video_codec = "unknown"
            audio_codec = "unknown"
            resolution = "unknown"
            
            for stream in video_info.get('streams', []):
                if stream.get('codec_type') == 'video':
                    video_codec = stream.get('codec_name', 'unknown')
                    if stream.get('width') and stream.get('height'):
                        resolution = f"{stream.get('width')}x{stream.get('height')}"
                elif stream.get('codec_type') == 'audio':
                    audio_codec = stream.get('codec_name', 'unknown')
            
            # Prepare additional info for progress reporting
            file_info = {
                'filename': os.path.basename(video_path),
                'duration': duration,
                'size_mb': size_mb,
                'format': format_name,
                'video_codec': video_codec,
                'audio_codec': audio_codec,
                'resolution': resolution,
                'target_format': OUTPUT_FORMAT,
                'target_codec': OUTPUT_CODEC
            }
            
            # Create output filename in temp directory
            output_filename = f"transcoded_{os.path.splitext(os.path.basename(video_path))[0]}.{OUTPUT_FORMAT}"
            output_path = os.path.join(TEMP_OUTPUT_DIR, output_filename)
            
            # Create base ffmpeg command
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-c:v', OUTPUT_CODEC,
                '-preset', FFMPEG_PRESET,
                # Add progress flag for better parsing
                '-progress', 'pipe:1',
            ]
            
            # Handle video dimensions
            video_stream = next((s for s in video_info['streams'] if s.get('codec_type') == 'video'), None)
            if video_stream and video_stream.get('width') and video_stream.get('height'):
                width = video_stream.get('width')
                height = video_stream.get('height')
                
                # Cap height at 720p but maintain aspect ratio
                if height > 720:
                    # Calculate new width maintaining aspect ratio
                    scale_factor = 720 / height
                    width = int(width * scale_factor)
                    height = 720
                
                # Ensure dimensions are even (x264 requirement)
                width, height = self.ensure_even_dimensions(width, height)
                file_info['target_resolution'] = f"{width}x{height}"
                
                # If target_resolution is provided, use it instead
                if target_resolution:
                    # Use provided resolution
                    cmd.extend(['-s', target_resolution])
                    file_info['target_resolution'] = target_resolution
                else:
                    # Use scale filter with padding for better quality and aspect ratio preservation
                    cmd.extend([
                        '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p'
                    ])
                    
                    # Set pixel format explicitly for compatibility
                    cmd.extend([
                        '-pix_fmt', 'yuv420p'
                    ])
            elif target_resolution:
                # Use provided resolution if video stream info is not available
                cmd.extend(['-s', target_resolution])
                file_info['target_resolution'] = target_resolution
            
            # Add audio and other parameters
            cmd.extend([
                '-c:a', AUDIO_CODEC,
                '-ar', '44100',  # Standard audio sample rate
                # Make sure we preserve all audio and subtitle streams
                '-map', '0',
                # Use higher bitrate for better quality
                '-b:v', '2M',
                '-y',  # Overwrite output file
                output_path
            ])
            
            # Run FFmpeg with progress tracking
            self._run_ffmpeg_with_progress(
                cmd, 
                duration, 
                "Transcoding", 
                progress_callback,
                file_info
            )
            
            logger.info(f"Transcoded video to: {output_path}")
            return output_path
        except subprocess.SubprocessError as e:
            logger.error(f"Transcoding error: {e}")
            # CompletedProcess has stderr and stdout, other subprocess errors don't
            if isinstance(e, subprocess.CalledProcessError) and e.stderr:
                logger.error(f"FFmpeg error: {e.stderr.decode()}")
            raise
    
    def merge_videos(self, video_paths, output_filename=None, progress_callback=None):
        """
        Merge multiple videos into a single file.
        
        Args:
            video_paths: List of paths to video files to merge
            output_filename: Optional custom output filename
            progress_callback: Function to report progress updates
            
        Returns:
            str: Path to the merged output video
        """
        # Reset cancellation flag
        self.is_cancelled = False
        
        if not video_paths:
            raise ValueError("No videos provided for merging")
        
        if len(video_paths) == 1:
            logger.info("Only one video provided, returning without merging")
            # Call progress callback with 100% if provided
            if progress_callback:
                progress_callback(100, "Merging", "Only one video provided, no merging needed", None)
            return video_paths[0]
        
        # For merging videos with different codecs, we should always transcode
        # rather than trying the simple concatenation first
        if not output_filename:
            output_filename = f"merged_video_{int(time.time())}.{OUTPUT_FORMAT}"
        
        return self._merge_with_transcoding(video_paths, output_filename, progress_callback)
    
    def _merge_with_transcoding(self, video_paths, output_filename=None, progress_callback=None):
        """
        Merge videos by transcoding them to a consistent format first.
        
        Args:
            video_paths: List of paths to video files to merge
            output_filename: Optional custom output filename
            progress_callback: Function to report progress updates
            
        Returns:
            str: Path to the merged output video
        """
        logger.info("Merging videos with transcoding to ensure compatibility")
        
        # Reset cancellation flag
        self.is_cancelled = False
        
        if not output_filename:
            output_filename = f"merged_video_{int(time.time())}.{OUTPUT_FORMAT}"
        
        output_path = os.path.join(TEMP_OUTPUT_DIR, output_filename)
        
        try:
            # For maximum compatibility, we'll transcode each video individually 
            # preserving its original aspect ratio but using consistent codec/format
            transcoded_paths = []
            
            # Calculate total work to do for progress tracking
            total_videos = len(video_paths)
            total_duration = 0  # Total duration in seconds for all videos
            video_details = []
            
            # First pass: gather all video information
            if progress_callback:
                progress_callback(0, "Analyzing", f"Analyzing {total_videos} videos...", None)
                
            for i, video_path in enumerate(video_paths):
                try:
                    # Get video info
                    video_info = self.get_video_info(video_path)
                    duration = float(video_info.get('duration', 0))
                    total_duration += duration
                    
                    # Store details for later
                    video_details.append({
                        'path': video_path,
                        'info': video_info,
                        'duration': duration,
                        'index': i
                    })
                    
                    # Report analysis progress
                    if progress_callback:
                        progress_callback(
                            int((i+1) * 100 / total_videos), 
                            "Analyzing", 
                            f"Analyzed video {i+1}/{total_videos}: {os.path.basename(video_path)}", 
                            {'filename': os.path.basename(video_path)}
                        )
                except Exception as e:
                    logger.error(f"Error analyzing video {i+1}: {e}")
                    if progress_callback:
                        progress_callback(0, "Error", f"Failed to analyze video {i+1}: {str(e)}", None)
                    raise
            
            # Second pass: transcode each video
            for i, video_detail in enumerate(video_details):
                if self.is_cancelled:
                    raise Exception("Operation cancelled by user")
                    
                video_path = video_detail['path']
                video_info = video_detail['info']
                
                try:
                    # Create output filename in temp directory
                    temp_output = f"transcoded_{os.path.splitext(os.path.basename(video_path))[0]}.{OUTPUT_FORMAT}"
                    temp_output_path = os.path.join(TEMP_OUTPUT_DIR, temp_output)
                    
                    # Report progress
                    if progress_callback:
                        progress_percent = int(i * 100 / total_videos)
                        progress_callback(
                            progress_percent,
                            "Transcoding",
                            f"Transcoding video {i+1}/{total_videos}: {os.path.basename(video_path)}",
                            {
                                'current_video': i+1,
                                'total_videos': total_videos,
                                'filename': os.path.basename(video_path),
                                'duration': video_detail['duration'],
                                'progress_percent': progress_percent
                            }
                        )
                    
                    # Find video stream info
                    video_stream = next((s for s in video_info['streams'] if s.get('codec_type') == 'video'), None)
                    
                    # Create base ffmpeg command
                    cmd = [
                        'ffmpeg',
                        '-i', video_path,
                        '-c:v', OUTPUT_CODEC,
                        '-preset', FFMPEG_PRESET,
                        # Add progress flag for better parsing
                        '-progress', 'pipe:1',
                    ]
                    
                    # If we have valid video stream info, handle resolution appropriately
                    if video_stream and video_stream.get('width') and video_stream.get('height'):
                        width = video_stream.get('width')
                        height = video_stream.get('height')
                        
                        # Cap height at 720p but maintain aspect ratio
                        if height > 720:
                            # Calculate new width maintaining aspect ratio
                            scale_factor = 720 / height
                            width = int(width * scale_factor)
                            height = 720
                        
                        # Ensure dimensions are even (x264 requirement)
                        width, height = self.ensure_even_dimensions(width, height)
                        
                        # Use scale filter instead of -s for better quality and standardize pixel format
                        cmd.extend([
                            '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p'
                        ])
                        
                        # Set pixel format explicitly for compatibility
                        cmd.extend([
                            '-pix_fmt', 'yuv420p'
                        ])
                    
                    # Add audio transcoding parameters
                    cmd.extend([
                        '-c:a', AUDIO_CODEC,
                        '-ar', '44100',  # Standard audio sample rate
                        # Make sure we preserve all audio and subtitle streams
                        '-map', '0',
                        # Use higher bitrate for better quality
                        '-b:v', '2M',
                        '-y',  # Overwrite output file
                        temp_output_path
                    ])
                    
                    # Define a transcoding progress wrapper
                    def transcoding_progress_wrapper(progress, operation_type, message, details):
                        if progress_callback:
                            # Adjust progress to fit within the current phase
                            adjusted_progress = int(((i + progress/100) / total_videos) * 50)  # Transcoding is 50% of total
                            progress_callback(
                                adjusted_progress, 
                                "Transcoding", 
                                f"Video {i+1}/{total_videos}: {message}", 
                                {
                                    'current_video': i+1,
                                    'total_videos': total_videos,
                                    'filename': os.path.basename(video_path),
                                    'sub_progress': progress,
                                    'details': details
                                }
                            )
                    
                    # Run FFmpeg with progress tracking for this transcode
                    self._run_ffmpeg_with_progress(
                        cmd, 
                        video_detail['duration'], 
                        f"Transcoding {i+1}/{total_videos}", 
                        transcoding_progress_wrapper,
                        {'filename': os.path.basename(video_path)}
                    )
                    
                    transcoded_paths.append(temp_output_path)
                    logger.info(f"Transcoded video {i+1} to: {temp_output_path}")
                except Exception as e:
                    if not self.is_cancelled:  # Don't log errors if we cancelled intentionally
                        logger.error(f"Error transcoding video {i+1}: {e}")
                        if progress_callback:
                            progress_callback(0, "Error", f"Failed to transcode video {i+1}: {str(e)}", None)
                    raise
            
            # All videos transcoded, now prepare for final merge
            if progress_callback:
                progress_callback(50, "Preparing", "Preparing to merge videos...", 
                                 {'transcoded_videos': len(transcoded_paths)})
            
            logger.info(f"Transcoded all videos: {transcoded_paths}")
            
            # Now merge the transcoded videos
            fd, concat_list_path = tempfile.mkstemp(suffix='.txt')
            os.close(fd)
            
            with open(concat_list_path, 'w') as f:
                for video_path in transcoded_paths:
                    # Always use absolute paths to avoid issues
                    abs_path = os.path.abspath(video_path)
                    escaped_path = abs_path.replace('\\', '/').replace("'", "\\'")
                    f.write(f"file '{escaped_path}'\n")
                
                # Log the content of the concat file for debugging
                with open(concat_list_path, 'r') as debug_f:
                    logger.info(f"Concat file content: {debug_f.read()}")
            
            # Calculate total duration for progress estimation
            if progress_callback:
                progress_callback(55, "Merging", "Merging videos...", 
                                 {'total_videos': len(transcoded_paths), 'output_file': output_filename})
            
            # Use concat demuxer first - it's faster and usually works with properly transcoded files
            try:
                # Try concat demuxer first with stream copy (much faster)
                concat_cmd = [
                    'ffmpeg',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_list_path,
                    '-c', 'copy',  # Use stream copy for speed
                    '-progress', 'pipe:1',  # Add progress flag
                    '-y',
                    output_path
                ]
                
                logger.info(f"Fast merge command (attempt 1): {' '.join(concat_cmd)}")
                
                # Define a merging progress wrapper
                def merge_progress_wrapper(progress, operation_type, message, details):
                    if progress_callback:
                        # Adjust progress to fit within the final phase (50-100%)
                        adjusted_progress = 55 + int(progress * 0.45)  # Merging is 45% of total
                        progress_callback(
                            adjusted_progress, 
                            "Merging", 
                            message, 
                            details
                        )
                
                # First try fast merge with progress tracking
                self._run_ffmpeg_with_progress(
                    concat_cmd, 
                    total_duration, 
                    "Merging", 
                    merge_progress_wrapper,
                    {'method': 'fast', 'output_file': output_filename}
                )
                
                logger.info("Fast merge successful!")
            except subprocess.SubprocessError as e:
                logger.warning(f"Fast merge failed, using more robust method: {e}")
                
                if progress_callback:
                    progress_callback(60, "Merging", "Fast merge failed, trying alternative method...", None)
                
                # Try with re-encoding which is more compatible but slower
                robust_cmd = [
                    'ffmpeg',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_list_path,
                    '-c:v', OUTPUT_CODEC,  # Re-encode for compatibility
                    '-c:a', AUDIO_CODEC,
                    '-b:v', '2M',  # Maintain good quality
                    '-pix_fmt', 'yuv420p',  # Standard pixel format for maximum compatibility
                    '-progress', 'pipe:1',  # Add progress flag
                    '-y',
                    output_path
                ]
                
                logger.info(f"Robust merge command (attempt 2): {' '.join(robust_cmd)}")
                
                # Second try with robust merge
                self._run_ffmpeg_with_progress(
                    robust_cmd, 
                    total_duration, 
                    "Merging", 
                    merge_progress_wrapper,
                    {'method': 'robust', 'output_file': output_filename}
                )
                
                logger.info("Robust merge successful!")
            
            # Clean up
            os.unlink(concat_list_path)
            
            # Final progress update
            if progress_callback:
                progress_callback(100, "Completed", "Merge completed successfully", 
                                 {'output_file': output_path, 'total_videos': len(video_paths)})
            
            logger.info(f"Successfully merged videos to: {output_path}")
            return output_path
            
        except subprocess.SubprocessError as e:
            logger.error(f"Transcoded merging error: {e}")
            # CompletedProcess has stderr and stdout, other subprocess errors don't
            if isinstance(e, subprocess.CalledProcessError) and e.stderr:
                logger.error(f"FFmpeg error: {e.stderr.decode()}")
            raise
    
    def cleanup_temp_files(self, file_paths):
        """Remove temporary files after processing."""
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.info(f"Removed temporary file: {file_path}")
            except OSError as e:
                logger.warning(f"Could not remove file {file_path}: {e}")
