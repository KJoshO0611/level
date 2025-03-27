import logging
from typing import Dict, Any, Optional, List

from .core import get_connection
from .utils import safe_db_operation

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
                from config import QUEST_SETTINGS
                return QUEST_SETTINGS["COOLDOWNS"]
                
    except Exception as e:
        logging.error(f"Error getting quest cooldowns: {e}")
        from config import QUEST_SETTINGS
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