import os
import logging
import aiohttp
import aiofiles
from discord import Member, Attachment
from typing import Optional, List, Tuple, Union
import asyncio
from modules.databasev2 import (
    set_user_background, 
    get_user_background, 
    remove_user_background,
    get_all_user_backgrounds,
    get_guild_backgrounds
)
from config import load_config

# Load the external volume path from config
config = load_config()
EXTERNAL_VOLUME_PATH = config.get("EXTERNAL_VOLUME_PATH", "/external_volume")
BACKGROUNDS_DIR = os.path.join(EXTERNAL_VOLUME_PATH, "backgrounds")

# Ensure backgrounds directory exists at module import time
os.makedirs(BACKGROUNDS_DIR, exist_ok=True)

class BackgroundError(Exception):
    """Base class for background-related exceptions"""
    pass

class DownloadError(BackgroundError):
    """Exception raised when a background image cannot be downloaded"""
    pass

class StorageError(BackgroundError):
    """Exception raised when a background image cannot be stored"""
    pass

class BackgroundAPI:
    """API for managing user background images"""
    
    @staticmethod
    def get_guild_dir(guild_id: str) -> str:
        """Get the directory path for a guild's backgrounds"""
        guild_dir = os.path.join(BACKGROUNDS_DIR, guild_id)
        os.makedirs(guild_dir, exist_ok=True)
        return guild_dir
    
    @staticmethod
    def get_background_path(guild_id: str, user_id: str, file_ext: str) -> Tuple[str, str]:
        """
        Get the full and relative paths for a user's background
        
        Returns:
            Tuple[str, str]: (full_path, relative_path)
        """
        guild_dir = BackgroundAPI.get_guild_dir(guild_id)
        filename = f"{user_id}.{file_ext}"
        full_path = os.path.join(guild_dir, filename)
        relative_path = os.path.join("backgrounds", guild_id, filename)
        return full_path, relative_path
    
    @staticmethod
    async def download_from_url(url: str) -> bytes:
        """Download an image from a URL and return the bytes"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise DownloadError(f"Failed to download image, status code: {resp.status}")
                    return await resp.read()
        except Exception as e:
            raise DownloadError(f"Error downloading image: {str(e)}")
    
    @staticmethod
    async def save_background(image_data: bytes, full_path: str) -> None:
        """Save image data to a file"""
        try:
            async with aiofiles.open(full_path, 'wb') as f:
                await f.write(image_data)
        except Exception as e:
            raise StorageError(f"Error saving background: {str(e)}")
    
    @staticmethod
    async def set_from_url(guild_id: str, user_id: str, url: str) -> str:
        """
        Set a user's background from a URL
        
        Returns:
            str: The relative path to the background
        
        Raises:
            DownloadError: If the image cannot be downloaded
            StorageError: If the image cannot be saved
        """
        # Extract file extension from URL
        file_ext = url.split('.')[-1].lower()
        if file_ext not in ['png', 'jpg', 'jpeg', 'gif']:
            file_ext = 'png'  # Default to png if unrecognized
        
        # Get paths
        full_path, relative_path = BackgroundAPI.get_background_path(guild_id, user_id, file_ext)
        
        # Download and save the image
        image_data = await BackgroundAPI.download_from_url(url)
        await BackgroundAPI.save_background(image_data, full_path)
        
        # Save to database
        success = await set_user_background(guild_id, user_id, relative_path)
        if not success:
            raise StorageError("Failed to update database with background path")
        
        return relative_path
    
    @staticmethod
    async def set_from_attachment(guild_id: str, user_id: str, attachment: Attachment) -> str:
        """
        Set a user's background from a Discord attachment
        
        Returns:
            str: The relative path to the background
        
        Raises:
            DownloadError: If the image cannot be downloaded
            StorageError: If the image cannot be saved
        """
        return await BackgroundAPI.set_from_url(guild_id, user_id, attachment.url)
    
    @staticmethod
    async def remove_background(guild_id: str, user_id: str) -> bool:
        """
        Remove a user's background
        
        Returns:
            bool: True if successful, False otherwise
        """
        # Get current background path
        relative_path = await get_user_background(guild_id, user_id)
        
        if not relative_path:
            return False
        
        # Delete file if it exists
        try:
            full_path = os.path.join(EXTERNAL_VOLUME_PATH, relative_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                logging.info(f"Removed background file: {full_path}")
        except Exception as e:
            logging.error(f"Error removing background file: {e}")
            # Continue anyway to remove from database
        
        # Remove from database
        return await remove_user_background(guild_id, user_id)
    
    @staticmethod
    async def get_background_full_path(guild_id: str, user_id: str) -> Optional[str]:
        """
        Get the full path to a user's background
        
        Returns:
            Optional[str]: The full path to the background, or None if not set
        """
        relative_path = await get_user_background(guild_id, user_id)
        
        if not relative_path:
            return None
        
        full_path = os.path.join(EXTERNAL_VOLUME_PATH, relative_path)
        
        if os.path.exists(full_path):
            return full_path
        else:
            logging.warning(f"Background file not found: {full_path}")
            return None
    
    @staticmethod
    async def check_background_exists(guild_id: str, user_id: str) -> bool:
        """Check if a user has a valid background set"""
        full_path = await BackgroundAPI.get_background_full_path(guild_id, user_id)
        return full_path is not None
    
    @staticmethod
    async def cleanup_missing_backgrounds() -> List[Tuple[str, str]]:
        """
        Clean up database entries for backgrounds where the file is missing
        
        Returns:
            List[Tuple[str, str]]: List of (guild_id, user_id) tuples that were cleaned up
        """
        backgrounds = await get_all_user_backgrounds()
        removed = []
        
        for guild_id, user_id, relative_path in backgrounds:
            full_path = os.path.join(EXTERNAL_VOLUME_PATH, relative_path)
            if not os.path.exists(full_path):
                logging.info(f"Removing missing background entry for {guild_id}/{user_id}: {relative_path}")
                await remove_user_background(guild_id, user_id)
                removed.append((guild_id, user_id))
        
        return removed
    
    @staticmethod
    async def start_background_cleanup_task(bot, interval_hours: int = 24):
        """Start a background task to periodically clean up missing backgrounds"""
        async def cleanup_task():
            while True:
                try:
                    await asyncio.sleep(interval_hours * 3600)  # Convert hours to seconds
                    removed = await BackgroundAPI.cleanup_missing_backgrounds()
                    if removed:
                        logging.info(f"Background cleanup removed {len(removed)} entries")
                except Exception as e:
                    logging.error(f"Error in background cleanup task: {e}")
                
        bot.loop.create_task(cleanup_task())
        logging.info(f"Started background cleanup task (interval: {interval_hours} hours)")