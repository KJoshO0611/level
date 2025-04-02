import logging
from typing import Dict, Any, Optional, List, Tuple

from .core import get_connection
from .utils import safe_db_operation
from config import load_config, QUEST_SETTINGS

from .cache import (
    _get_from_cache, _set_in_cache, 
    config_cache
)

# Add these new functions for quest cooldown configuration

async def _get_quest_cooldowns(guild_id: str) -> dict:
    """Internal function to get quest cooldown settings for a guild"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT quest_cooldowns FROM server_config 
            WHERE guild_id = $1
            """
            
            result = await conn.fetchval(query, guild_id)
            
            if result:
                # Return the JSONB data as a Python dict
                return result
            else:
                # Return default settings from config
                return QUEST_SETTINGS["COOLDOWNS"]
                
    except Exception as e:
        logging.error(f"Error getting quest cooldowns: {e}")
        return QUEST_SETTINGS["COOLDOWNS"]

async def get_quest_cooldowns(guild_id: str) -> dict:
    """
    Get quest cooldown settings for a guild
    
    Parameters:
    - guild_id: The guild ID
    
    Returns:
    - dict: Quest cooldown settings
    """
    return await _get_quest_cooldowns(guild_id)

async def _update_quest_cooldowns(guild_id: str, cooldowns: dict) -> bool:
    """Internal function to update quest cooldown settings"""
    try:
        async with get_connection() as conn:
            # First check if guild exists in server_config
            check_query = """
            SELECT 1 FROM server_config 
            WHERE guild_id = $1
            """
            exists = await conn.fetchval(check_query, guild_id)
            
            if exists:
                # Update existing record
                query = """
                UPDATE server_config 
                SET quest_cooldowns = $1
                WHERE guild_id = $2
                """
                await conn.execute(query, cooldowns, guild_id)
            else:
                # Insert new record with defaults
                query = """
                INSERT INTO server_config (guild_id, level_up_channel, quest_cooldowns) 
                VALUES ($1, 'general', $2)
                """
                await conn.execute(query, guild_id, cooldowns)
            
            return True
                
    except Exception as e:
        logging.error(f"Error updating quest cooldowns: {e}")
        return False

async def update_quest_cooldowns(guild_id: str, cooldowns: dict) -> bool:
    """
    Update quest cooldown settings for a guild
    
    Parameters:
    - guild_id: The guild ID
    - cooldowns: Dictionary of cooldown settings
    
    Returns:
    - bool: True if successful
    """
    return await safe_db_operation("update_quest_cooldowns", guild_id, cooldowns)

async def update_quest_cooldown(guild_id: str, quest_type: str, cooldown: int) -> bool:
    """
    Update a specific quest cooldown setting
    
    Parameters:
    - guild_id: The guild ID
    - quest_type: The type of quest (total_messages, total_reactions, etc.)
    - cooldown: Cooldown in seconds
    
    Returns:
    - bool: True if successful
    """
    # Get current cooldowns
    current_cooldowns = await get_quest_cooldowns(guild_id)
    
    # Update the specific cooldown
    current_cooldowns[quest_type] = cooldown
    
    # Save the updated cooldowns
    return await update_quest_cooldowns(guild_id, current_cooldowns)

# Functions for quest reset settings

async def get_quest_reset_settings(guild_id: str) -> Tuple[int, int]:
    """
    Get the quest reset settings for a guild.
    
    Returns:
        Tuple containing (reset_hour, reset_day)
        reset_hour: Hour of day (UTC) when daily quests reset (0-23)
        reset_day: Day of week when weekly quests reset (0=Monday, 6=Sunday)
    """
    # Try cache first
    cache_key = f"{guild_id}_quest_reset"
    cached_value = _get_from_cache(config_cache, cache_key)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    async with get_connection() as conn:
        query = """
        SELECT quest_reset_hour, quest_reset_day 
        FROM server_config 
        WHERE guild_id = $1
        """
        row = await conn.fetchrow(query, guild_id)
        
        if row:
            reset_hour = row['quest_reset_hour']
            reset_day = row['quest_reset_day']
        else:
            # Default values if not set
            reset_hour = 0  # Midnight UTC
            reset_day = 0   # Monday
            
            # Insert default values
            await conn.execute("""
            INSERT INTO server_config 
                (guild_id, level_up_channel, quest_reset_hour, quest_reset_day)
            VALUES 
                ($1, 'general', $2, $3)
            ON CONFLICT (guild_id) DO NOTHING
            """, guild_id, reset_hour, reset_day)
        
        # Store in cache
        result = (reset_hour, reset_day)
        _set_in_cache(config_cache, cache_key, result)
        
        return result

async def set_quest_reset_time(guild_id: str, reset_hour: int) -> bool:
    """
    Set the hour of day (UTC) when daily quests reset for a guild.
    
    Args:
        guild_id: The ID of the guild
        reset_hour: Hour of day (0-23) when daily quests should reset
        
    Returns:
        True if successful, False otherwise
    """
    # Validate input
    if not 0 <= reset_hour <= 23:
        logging.error(f"Invalid reset hour: {reset_hour}. Must be 0-23.")
        return False
    
    try:
        async with get_connection() as conn:
            # Check if guild exists in server_config
            check_query = "SELECT 1 FROM server_config WHERE guild_id = $1"
            exists = await conn.fetchval(check_query, guild_id)
            
            if exists:
                # Update existing record
                query = """
                UPDATE server_config 
                SET quest_reset_hour = $1
                WHERE guild_id = $2
                """
                await conn.execute(query, reset_hour, guild_id)
            else:
                # Insert new record with defaults
                query = """
                INSERT INTO server_config 
                    (guild_id, level_up_channel, quest_reset_hour) 
                VALUES 
                    ($1, 'general', $2)
                """
                await conn.execute(query, guild_id, reset_hour)
            
            # Update cache
            cache_key = f"{guild_id}_quest_reset"
            cached_value = _get_from_cache(config_cache, cache_key)
            if cached_value is not None:
                reset_day = cached_value[1]
                _set_in_cache(config_cache, cache_key, (reset_hour, reset_day))
            
            return True
                
    except Exception as e:
        logging.error(f"Error setting quest reset hour: {e}")
        return False

async def set_quest_reset_day(guild_id: str, reset_day: int) -> bool:
    """
    Set the day of week when weekly quests reset for a guild.
    
    Args:
        guild_id: The ID of the guild
        reset_day: Day of week (0=Monday, 6=Sunday) when weekly quests should reset
        
    Returns:
        True if successful, False otherwise
    """
    # Validate input
    if not 0 <= reset_day <= 6:
        logging.error(f"Invalid reset day: {reset_day}. Must be 0-6 (0=Monday, 6=Sunday).")
        return False
    
    try:
        async with get_connection() as conn:
            # Check if guild exists in server_config
            check_query = "SELECT 1 FROM server_config WHERE guild_id = $1"
            exists = await conn.fetchval(check_query, guild_id)
            
            if exists:
                # Update existing record
                query = """
                UPDATE server_config 
                SET quest_reset_day = $1
                WHERE guild_id = $2
                """
                await conn.execute(query, reset_day, guild_id)
            else:
                # Insert new record with defaults
                query = """
                INSERT INTO server_config 
                    (guild_id, level_up_channel, quest_reset_day) 
                VALUES 
                    ($1, 'general', $2)
                """
                await conn.execute(query, guild_id, reset_day)
            
            # Update cache
            cache_key = f"{guild_id}_quest_reset"
            cached_value = _get_from_cache(config_cache, cache_key)
            if cached_value is not None:
                reset_hour = cached_value[0]
                _set_in_cache(config_cache, cache_key, (reset_hour, reset_day))
            
            return True
                
    except Exception as e:
        logging.error(f"Error setting quest reset day: {e}")
        return False 