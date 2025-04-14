"""
File uploader module for the Video Merger Bot.
Handles uploading files to various free file hosting platforms.
"""

import os
import time
import logging
import random
import string
import requests
import json
from typing import Dict, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

class FileHostingService(ABC):
    """Base class for file hosting services."""
    
    name = "Base Service"
    max_file_size = 100 * 1024 * 1024  # Default 100MB
    
    @abstractmethod
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """
        Upload a file to the hosting service.
        
        Args:
            file_path: Path to the file to upload
            progress_callback: Function to call with progress updates
            
        Returns:
            Dict containing upload result with at least:
                - success: bool
                - url: str (if success is True)
                - error: str (if success is False)
        """
        pass
    
    def get_file_size(self, file_path: str) -> int:
        """Get file size in bytes."""
        return os.path.getsize(file_path)
    
    def check_file_size(self, file_path: str) -> bool:
        """Check if file size is within service limits."""
        return self.get_file_size(file_path) <= self.max_file_size


class GofileService(FileHostingService):
    """Gofile.io file hosting service."""
    
    name = "Gofile.io"
    max_file_size = 1024 * 1024 * 1024 * 2  # 2GB
    
    def __init__(self):
        self.api_url = "https://api.gofile.io"
    
    def get_server(self) -> str:
        """Get best server for uploading."""
        try:
            response = requests.get(f"{self.api_url}/getServer")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ok":
                    return data.get("data", {}).get("server", "store")
            logger.warning(f"Error getting Gofile server: {response.text}")
            return "store"  # Default server
        except Exception as e:
            logger.error(f"Error getting Gofile server: {e}")
            return "store"  # Default server
        
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to Gofile."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            server = self.get_server()
            upload_url = f"https://{server}.gofile.io/uploadFile"
            
            # For simpler progress tracking, we'll use a session with a custom adapter
            file_size = self.get_file_size(file_path)
            
            class ProgressCallback:
                def __init__(self, callback=None):
                    self.callback = callback
                    self.last_update = 0
                    
                def __call__(self, bytes_sent):
                    if self.callback and time.time() - self.last_update > 0.5:  # Update every 0.5 seconds
                        percent = int(bytes_sent * 100 / file_size)
                        self.callback(percent)
                        self.last_update = time.time()
            
            progress = ProgressCallback(progress_callback)
            file_name = os.path.basename(file_path)
            
            with open(file_path, 'rb') as f:
                # Prepare callback for monitoring upload progress
                def read_callback(size):
                    data = f.read(size)
                    progress(f.tell())
                    return data
                
                # Submit the file
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                files = {'file': (file_name, read_callback)}
                response = requests.post(upload_url, files=files)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "ok":
                        download_url = data.get("data", {}).get("downloadPage", "")
                        return {
                            "success": True,
                            "url": download_url,
                            "direct_url": data.get("data", {}).get("directLink", ""),
                            "service": self.name
                        }
            
            return {"success": False, "error": f"Upload to {self.name} failed"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class Catbox(FileHostingService):
    """Catbox.moe file hosting service."""
    
    name = "Catbox.moe"
    max_file_size = 200 * 1024 * 1024  # 200MB
    
    def __init__(self):
        self.upload_url = "https://catbox.moe/user/api.php"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to Catbox."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                files = {'fileToUpload': (file_name, f)}
                data = {'reqtype': 'fileupload', 'userhash': ''}
                
                # Make the request
                response = requests.post(self.upload_url, files=files, data=data)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200 and response.text.startswith('https://'):
                    return {
                        "success": True,
                        "url": response.text,
                        "direct_url": response.text,
                        "service": self.name
                    }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class TempFileSh(FileHostingService):
    """Tempfile.sh file hosting service."""
    
    name = "TempFile.sh"
    max_file_size = 10 * 1024 * 1024 * 1024  # 10GB
    
    def __init__(self):
        self.upload_url = "https://tempfile.sh/api/upload"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to TempFile.sh."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                files = {'file': (file_name, f)}
                
                # Make the request
                response = requests.post(self.upload_url, files=files)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return {
                            "success": True,
                            "url": data.get("data", {}).get("url", ""),
                            "direct_url": data.get("data", {}).get("url", ""),
                            "service": self.name
                        }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class FileIo(FileHostingService):
    """File.io file hosting service."""
    
    name = "File.io"
    max_file_size = 2 * 1024 * 1024 * 1024  # 2GB
    
    def __init__(self):
        self.upload_url = "https://file.io"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to File.io."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                files = {'file': (file_name, f)}
                
                # Make the request
                response = requests.post(self.upload_url, files=files)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        return {
                            "success": True,
                            "url": data.get("link", ""),
                            "direct_url": data.get("link", ""),
                            "service": self.name
                        }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class AnonFiles(FileHostingService):
    """AnonFiles.com file hosting service."""
    
    name = "AnonFiles.com"
    max_file_size = 5 * 1024 * 1024 * 1024  # 5GB
    
    def __init__(self):
        self.upload_url = "https://api.anonfiles.com/upload"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to AnonFiles."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                files = {'file': (file_name, f)}
                
                # Make the request
                response = requests.post(self.upload_url, files=files)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status"):
                        file_data = data.get("data", {}).get("file", {})
                        return {
                            "success": True,
                            "url": file_data.get("url", {}).get("full", ""),
                            "direct_url": file_data.get("url", {}).get("short", ""),
                            "service": self.name
                        }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class BayFiles(FileHostingService):
    """BayFiles.com file hosting service."""
    
    name = "BayFiles.com"
    max_file_size = 5 * 1024 * 1024 * 1024  # 5GB
    
    def __init__(self):
        self.upload_url = "https://api.bayfiles.com/upload"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to BayFiles."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                files = {'file': (file_name, f)}
                
                # Make the request
                response = requests.post(self.upload_url, files=files)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status"):
                        file_data = data.get("data", {}).get("file", {})
                        return {
                            "success": True,
                            "url": file_data.get("url", {}).get("full", ""),
                            "direct_url": file_data.get("url", {}).get("short", ""),
                            "service": self.name
                        }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class PixelDrain(FileHostingService):
    """PixelDrain.com file hosting service."""
    
    name = "PixelDrain.com"
    max_file_size = 10 * 1024 * 1024 * 1024  # 10GB
    
    def __init__(self):
        self.upload_url = "https://pixeldrain.com/api/file"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to PixelDrain."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                headers = {"accept": "application/json"}
                
                # Make the request
                response = requests.post(f"{self.upload_url}/{file_name}", data=f, headers=headers)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        file_id = data.get("id", "")
                        return {
                            "success": True,
                            "url": f"https://pixeldrain.com/u/{file_id}",
                            "direct_url": f"https://pixeldrain.com/api/file/{file_id}",
                            "service": self.name
                        }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class FileBin(FileHostingService):
    """FileBin.net file hosting service."""
    
    name = "FileBin.net"
    max_file_size = 50 * 1024 * 1024  # 50MB
    
    def __init__(self):
        self.upload_url = "https://filebin.net"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to FileBin."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            # Generate a random bin ID
            bin_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                headers = {'Content-Type': 'application/octet-stream'}
                
                # Make the request
                response = requests.post(f"{self.upload_url}/{bin_id}/{file_name}", data=f, headers=headers)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code in [200, 201]:
                    return {
                        "success": True,
                        "url": f"{self.upload_url}/{bin_id}/{file_name}",
                        "direct_url": f"{self.upload_url}/{bin_id}/{file_name}",
                        "service": self.name
                    }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class TransferSh(FileHostingService):
    """Transfer.sh file hosting service."""
    
    name = "Transfer.sh"
    max_file_size = 10 * 1024 * 1024 * 1024  # 10GB
    
    def __init__(self):
        self.upload_url = "https://transfer.sh"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to Transfer.sh."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Make the request
                response = requests.put(f"{self.upload_url}/{file_name}", data=f)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    direct_url = response.text.strip()
                    return {
                        "success": True,
                        "url": direct_url,
                        "direct_url": direct_url,
                        "service": self.name
                    }
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class UguuSe(FileHostingService):
    """Uguu.se file hosting service."""
    
    name = "Uguu.se"
    max_file_size = 100 * 1024 * 1024  # 100MB
    
    def __init__(self):
        self.upload_url = "https://uguu.se/upload.php"
    
    def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to Uguu.se."""
        try:
            if not self.check_file_size(file_path):
                return {"success": False, "error": f"File too large for {self.name}"}
            
            file_name = os.path.basename(file_path)
            file_size = self.get_file_size(file_path)
            
            with open(file_path, 'rb') as f:
                if progress_callback:
                    progress_callback(0)  # Start at 0%
                
                # Create the form data
                files = {'files[]': (file_name, f)}
                
                # Make the request
                response = requests.post(self.upload_url, files=files)
                
                if progress_callback:
                    progress_callback(100)  # End at 100%
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if isinstance(data, list) and len(data) > 0:
                            file_data = data[0]
                            return {
                                "success": True,
                                "url": file_data.get("url", ""),
                                "direct_url": file_data.get("url", ""),
                                "service": self.name
                            }
                    except:
                        pass
            
            return {"success": False, "error": f"Upload to {self.name} failed: {response.text}"}
        except Exception as e:
            logger.error(f"Error uploading to {self.name}: {e}")
            return {"success": False, "error": f"Error uploading to {self.name}: {str(e)}"}


class FileUploader:
    """File uploader manager that tries multiple services."""
    
    def __init__(self):
        """Initialize with a list of available file hosting services."""
        self.services = [
            GofileService(),
            Catbox(),
            TempFileSh(),
            FileIo(),
            AnonFiles(),
            BayFiles(),
            PixelDrain(),
            FileBin(),
            TransferSh(),
            UguuSe()
        ]
    
    def get_service_names(self) -> List[str]:
        """Get a list of all service names."""
        return [service.name for service in self.services]
    
    def upload_file(self, file_path: str, max_attempts: int = 3, progress_callback=None) -> Dict:
        """
        Upload a file to a hosting service, trying multiple services if needed.
        
        Args:
            file_path: Path to the file to upload
            max_attempts: Maximum number of services to try
            progress_callback: Function to call with progress updates:
                - service_index: int (which service is being tried, 0-based)
                - service_name: str
                - service_progress: int (0-100 for the current service)
                - overall_progress: int (0-100 for the overall process)
                
        Returns:
            Dict containing upload result.
        """
        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}
        
        file_size = os.path.getsize(file_path)
        logger.info(f"Uploading file: {file_path} ({file_size / 1024 / 1024:.2f} MB)")
        
        # Filter services that can handle this file size
        eligible_services = [s for s in self.services if s.check_file_size(file_path)]
        if not eligible_services:
            return {"success": False, "error": f"File too large for all services ({file_size / 1024 / 1024:.2f} MB)"}
        
        # Try each service in order until one succeeds or max_attempts is reached
        attempts = 0
        results = []
        overall_max_progress = min(len(eligible_services), max_attempts) * 100
        overall_progress = 0
        
        for i, service in enumerate(eligible_services[:max_attempts]):
            attempts += 1
            logger.info(f"Trying service {attempts}/{max_attempts}: {service.name}")
            
            try:
                # Create a progress callback for this service
                def service_progress_callback(progress_percent):
                    if progress_callback:
                        current_overall = overall_progress + progress_percent
                        overall_percent = int(min(100, current_overall * 100 / overall_max_progress))
                        progress_callback(i, service.name, progress_percent, overall_percent)
                
                # Upload the file
                result = service.upload_file(file_path, service_progress_callback)
                results.append(result)
                
                # Update overall progress
                overall_progress += 100
                
                if result["success"]:
                    logger.info(f"Successfully uploaded file to {service.name}: {result.get('url')}")
                    return result
                else:
                    logger.warning(f"Failed to upload to {service.name}: {result.get('error')}")
            except Exception as e:
                logger.error(f"Error uploading to {service.name}: {e}")
                results.append({"success": False, "error": str(e), "service": service.name})
                overall_progress += 100
        
        # If we get here, all attempts failed
        return {
            "success": False, 
            "error": "All upload attempts failed", 
            "attempts": attempts,
            "results": results
        }


# For testing
if __name__ == "__main__":
    # Test uploading a file
    def print_progress(service_index, service_name, service_progress, overall_progress):
        print(f"Service {service_index+1} ({service_name}): {service_progress}%, Overall: {overall_progress}%")
    
    uploader = FileUploader()
    print(f"Available services: {uploader.get_service_names()}")
    
    test_file = "test_file.txt"
    with open(test_file, "w") as f:
        f.write("This is a test file for uploading.")
    
    result = uploader.upload_file(test_file, progress_callback=print_progress)
    print(f"Upload result: {result}")