"""
Background management functionality for user profile cards.
"""
import logging
from typing import List, Tuple, Optional

from .core import get_connection
from .utils import safe_db_operation

async def _set_user_background(guild_id: str, user_id: str, relative_path: str) -> bool:
    """Internal function to set a custom background for a user"""
    try:
        async with get_connection() as conn:
            query = """
            INSERT INTO custom_backgrounds (guild_id, user_id, background_path)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) 
            DO UPDATE SET background_path = $3
            """
            await conn.execute(query, guild_id, user_id, relative_path)
            return True
    except Exception as e:
        logging.error(f"Error setting user background: {e}")
        return False

async def set_user_background(guild_id: str, user_id: str, relative_path: str) -> bool:
    """
    Set a custom background for a user
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    - relative_path: The path to the background image, relative to EXTERNAL_VOLUME_PATH
    
    Returns:
    - bool: True if successful, False otherwise
    """
    return await safe_db_operation("set_user_background", guild_id, user_id, relative_path)

async def _get_user_background(guild_id: str, user_id: str) -> str:
    """Internal function to get the custom background path for a user"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT background_path FROM custom_backgrounds
            WHERE guild_id = $1 AND user_id = $2
            """
            result = await conn.fetchval(query, guild_id, user_id)
            return result
    except Exception as e:
        logging.error(f"Error getting user background: {e}")
        return None

async def get_user_background(guild_id: str, user_id: str) -> str:
    """
    Get the custom background path for a user
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    
    Returns:
    - str: The relative path to the background image, or None if not set
    """
    try:
        return await _get_user_background(guild_id, user_id)
    except Exception as e:
        logging.error(f"Error in get_user_background: {e}")
        return None

async def _remove_user_background(guild_id: str, user_id: str) -> bool:
    """Internal function to remove a user's custom background"""
    try:
        async with get_connection() as conn:
            query = """
            DELETE FROM custom_backgrounds
            WHERE guild_id = $1 AND user_id = $2
            """
            await conn.execute(query, guild_id, user_id)
            return True
    except Exception as e:
        logging.error(f"Error removing user background: {e}")
        return False

async def remove_user_background(guild_id: str, user_id: str) -> bool:
    """
    Remove a user's custom background
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    
    Returns:
    - bool: True if successful, False otherwise
    """
    return await safe_db_operation("remove_user_background", guild_id, user_id)

async def get_all_user_backgrounds() -> list:
    """
    Get all custom backgrounds from the database
    
    Returns:
    - list: A list of tuples containing (guild_id, user_id, background_path)
    """
    try:
        async with get_connection() as conn:
            query = """
            SELECT guild_id, user_id, background_path 
            FROM custom_backgrounds
            """
            rows = await conn.fetch(query)
            return [(row['guild_id'], row['user_id'], row['background_path']) for row in rows]
    except Exception as e:
        logging.error(f"Error getting all backgrounds: {e}")
        return []

async def get_guild_backgrounds(guild_id: str) -> list:
    """
    Get all backgrounds for a specific guild
    
    Parameters:
    - guild_id: The guild ID
    
    Returns:
    - list: A list of tuples containing (user_id, background_path)
    """
    try:
        async with get_connection() as conn:
            query = """
            SELECT user_id, background_path 
            FROM custom_backgrounds
            WHERE guild_id = $1
            """
            rows = await conn.fetch(query, guild_id)
            return [(row['user_id'], row['background_path']) for row in rows]
    except Exception as e:
        logging.error(f"Error getting guild backgrounds: {e}")
        return []