"""
Server configuration functions for the database.
"""
import logging
from typing import Dict, Optional
from config import load_config, XP_SETTINGS

from .core import get_connection
from .cache import (
    _get_from_cache, _set_in_cache, 
    config_cache, role_cache, server_xp_settings_cache
)
from .utils import safe_db_operation

# Global state
CHANNEL_XP_BOOSTS = {}  # {channel_id: multiplier}

async def _set_level_up_channel(guild_id: str, channel_id: str):
    """Set level up channel with transaction protection"""
    async with get_connection() as conn:
        query = """
        INSERT INTO server_config (guild_id, level_up_channel) 
        VALUES ($1, $2)
        ON CONFLICT (guild_id) 
        DO UPDATE SET level_up_channel = $2
        """
        await conn.execute(query, guild_id, channel_id)
        
        # Update cache
        _set_in_cache(config_cache, guild_id, channel_id)

async def set_level_up_channel(guild_id: str, channel_id: str):
    """Set the level-up notification channel with safety wrapper"""
    result = await safe_db_operation("set_level_up_channel", guild_id, channel_id)
    
    # Update cache
    if result is not None:
        _set_in_cache(config_cache, guild_id, channel_id)
    
    return result

async def get_level_up_channel(guild_id: str):
    """Get level up channel with caching"""
    # Try cache first
    cached_value = _get_from_cache(config_cache, guild_id)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    async with get_connection() as conn:
        query = "SELECT level_up_channel FROM server_config WHERE guild_id = $1"
        row = await conn.fetchrow(query, guild_id)
        
        channel_id = row['level_up_channel'] if row else None
        
        # Store in cache if found
        if channel_id is not None:
            _set_in_cache(config_cache, guild_id, channel_id)
        
        return channel_id

async def _set_channel_boost_db(guild_id: str, channel_id: str, multiplier: float):
    """Set channel XP boost with transaction protection"""
    # Update in-memory storage
    CHANNEL_XP_BOOSTS[channel_id] = multiplier
    
    async with get_connection() as conn:
        query = """
        INSERT INTO channel_boosts (guild_id, channel_id, multiplier) 
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, channel_id) 
        DO UPDATE SET multiplier = $3
        """
        await conn.execute(query, guild_id, channel_id, multiplier)

async def set_channel_boost_db(guild_id: str, channel_id: str, multiplier: float):
    """Set channel XP boost with safety wrapper"""
    return await safe_db_operation("set_channel_boost_db", guild_id, channel_id, multiplier)

async def _remove_channel_boost_db(guild_id: str, channel_id: str):
    """Remove channel XP boost with transaction protection"""
    # Remove from in-memory storage
    if channel_id in CHANNEL_XP_BOOSTS:
        del CHANNEL_XP_BOOSTS[channel_id]
    
    async with get_connection() as conn:
        query = "DELETE FROM channel_boosts WHERE guild_id = $1 AND channel_id = $2"
        await conn.execute(query, guild_id, channel_id)

async def remove_channel_boost_db(guild_id: str, channel_id: str):
    """Remove channel XP boost with safety wrapper"""
    return await safe_db_operation("remove_channel_boost_db", guild_id, channel_id)

async def load_channel_boosts(bot):
    """Load channel boosts from database"""
    global CHANNEL_XP_BOOSTS
    
    try:
        # Get a direct connection from the bot's pool
        async with bot.db.acquire() as conn:
            query = "SELECT channel_id, multiplier FROM channel_boosts"
            rows = await conn.fetch(query)
            
            # Create a new dictionary with the results
            new_boosts = {row['channel_id']: row['multiplier'] for row in rows}
            
            # Log details for debugging
            logging.info(f"Channel boosts loaded from database: {len(new_boosts)} boosts")
            
            # Log a sample of the loaded boosts for debugging
            if len(new_boosts) > 0:
                sample = list(new_boosts.items())[:3]  # Show up to 3 boosts
                logging.info(f"Sample of loaded boosts: {sample}")
            
            # Update the global dictionary
            CHANNEL_XP_BOOSTS.clear()  # Clear existing
            CHANNEL_XP_BOOSTS.update(new_boosts)  # Add new values
            
            logging.info(f"Global CHANNEL_XP_BOOSTS now contains {len(CHANNEL_XP_BOOSTS)} boosts")
            
            return len(CHANNEL_XP_BOOSTS)
            
    except Exception as e:
        logging.error(f"Error loading channel boosts: {e}")
        # Don't clear existing boosts if there was an error
        return -1

def apply_channel_boost(base_xp: int, channel_id: str) -> int:
    """Apply channel-specific XP boost if applicable"""
    if channel_id and channel_id in CHANNEL_XP_BOOSTS:
        return int(base_xp * CHANNEL_XP_BOOSTS[channel_id])
    return base_xp

async def create_level_role(guild_id: str, level: int, role_id: str):
    """Creates or updates a level-role mapping with transaction safety"""
    try:
        async with get_connection() as conn:
            async with conn.transaction():
                # Check if mapping already exists
                check_query = """
                SELECT * FROM level_roles 
                WHERE guild_id = $1 AND level = $2
                FOR UPDATE
                """
                existing = await conn.fetchrow(check_query, guild_id, level)
                
                if existing:
                    # Update existing mapping
                    update_query = """
                    UPDATE level_roles 
                    SET role_id = $3 
                    WHERE guild_id = $1 AND level = $2
                    """
                    await conn.execute(update_query, guild_id, level, role_id)
                else:
                    # Create new mapping
                    insert_query = """
                    INSERT INTO level_roles (guild_id, level, role_id) 
                    VALUES ($1, $2, $3)
                    """
                    await conn.execute(insert_query, guild_id, level, role_id)
                
                # Invalidate cache
                if guild_id in role_cache:
                    del role_cache[guild_id]
                
                return True
    except Exception as e:
        logging.error(f"Database error in create_level_role: {e}")
        return False

async def get_level_roles(guild_id: str):
    """Gets all level-role mappings for a guild with caching"""
    # Try cache first
    cached_value = _get_from_cache(role_cache, guild_id)
    if cached_value is not None:
        return cached_value
    
    try:
        async with get_connection() as conn:
            query = """
            SELECT level, role_id FROM level_roles 
            WHERE guild_id = $1
            ORDER BY level
            """
            rows = await conn.fetch(query, guild_id)
            
            # Convert to dictionary
            level_roles = {row['level']: row['role_id'] for row in rows}
            
            # Store in cache
            _set_in_cache(role_cache, guild_id, level_roles)
            
            return level_roles
    except Exception as e:
        logging.error(f"Database error in get_level_roles: {e}")
        return {}

async def delete_level_role(guild_id: str, level: int):
    """Deletes a level-role mapping with transaction safety"""
    try:
        async with get_connection() as conn:
            query = """
            DELETE FROM level_roles 
            WHERE guild_id = $1 AND level = $2
            RETURNING *
            """
            result = await conn.fetchrow(query, guild_id, level)
            
            # Invalidate cache
            if guild_id in role_cache:
                del role_cache[guild_id]
            
            return result is not None  # True if something was deleted
    except Exception as e:
        logging.error(f"Database error in delete_level_role: {e}")
        return False

async def _get_server_xp_settings(guild_id: str) -> dict:
    """Internal function to get XP settings for a server"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT min_xp, max_xp, cooldown 
            FROM server_xp_settings
            WHERE guild_id = $1
            """
            row = await conn.fetchrow(query, guild_id)
            
            # Return defaults from config if not found
            if not row:
                return {
                    "min_xp": XP_SETTINGS["MIN"], 
                    "max_xp": XP_SETTINGS["MAX"],
                    "cooldown": XP_SETTINGS["COOLDOWN"]
                }
            
            return {
                "min_xp": row["min_xp"],
                "max_xp": row["max_xp"],
                "cooldown": row["cooldown"]
            }
    except Exception as e:
        logging.error(f"Error getting server XP settings: {e}")
        # Return defaults on error
        return {
            "min_xp": XP_SETTINGS["MIN"], 
            "max_xp": XP_SETTINGS["MAX"],
            "cooldown": XP_SETTINGS["COOLDOWN"]
        }

async def _update_server_xp_settings(guild_id: str, settings: dict) -> bool:
    """Internal function to update server XP settings"""
    try:
        async with get_connection() as conn:
            # Check if settings exist
            query = """
            SELECT 1 FROM server_xp_settings
            WHERE guild_id = $1
            """
            exists = await conn.fetchval(query, guild_id)
            
            if exists:
                # Build update query based on provided settings
                update_parts = []
                params = [guild_id]
                param_index = 2
                
                for key in ["min_xp", "max_xp", "cooldown"]:
                    if key in settings:
                        update_parts.append(f"{key} = ${param_index}")
                        params.append(settings[key])
                        param_index += 1
                
                if update_parts:
                    query = f"""
                    UPDATE server_xp_settings
                    SET {', '.join(update_parts)}
                    WHERE guild_id = $1
                    """
                    await conn.execute(query, *params)
            else:
                # Get current defaults to fill in any missing values
                defaults = {
                    "min_xp": XP_SETTINGS["MIN"], 
                    "max_xp": XP_SETTINGS["MAX"],
                    "cooldown": XP_SETTINGS["COOLDOWN"]
                }
                
                # Override with provided settings
                for key in settings:
                    if key in defaults:
                        defaults[key] = settings[key]
                
                query = """
                INSERT INTO server_xp_settings (guild_id, min_xp, max_xp, cooldown)
                VALUES ($1, $2, $3, $4)
                """
                await conn.execute(
                    query,
                    guild_id,
                    defaults["min_xp"],
                    defaults["max_xp"],
                    defaults["cooldown"]
                )
            
            return True
    except Exception as e:
        logging.error(f"Error updating server XP settings: {e}")
        return False

async def _reset_server_xp_settings(guild_id: str) -> bool:
    """Internal function to reset server XP settings to defaults"""
    try:
        async with get_connection() as conn:
            query = """
            DELETE FROM server_xp_settings
            WHERE guild_id = $1
            """
            await conn.execute(query, guild_id)
            return True
    except Exception as e:
        logging.error(f"Error resetting server XP settings: {e}")
        return False

async def get_server_xp_settings(guild_id: str) -> dict:
    """Get XP settings for a server with caching"""
    # Try cache first
    cached_value = _get_from_cache(server_xp_settings_cache, guild_id)
    if cached_value is not None:
        return cached_value
    
    # If not in cache or cache expired, get from database
    settings = await _get_server_xp_settings(guild_id)
    
    # Cache the settings if valid
    if settings:
        _set_in_cache(server_xp_settings_cache, guild_id, settings)
    
    return settings

async def update_server_xp_settings(guild_id: str, settings: dict) -> bool:
    """Update server XP settings with error handling and cache management"""
    # Validate settings
    for key in settings:
        if key not in ["min_xp", "max_xp", "cooldown"]:
            logging.warning(f"Invalid setting key: {key}")
            return False
            
    # Use safe_db_operation for error handling and retries
    result = await safe_db_operation("update_server_xp_settings", guild_id, settings)
    
    if result:
        # Update cache if operation was successful
        # First get current cached settings or fetch from db if not cached
        cached_settings = _get_from_cache(server_xp_settings_cache, guild_id)
        if cached_settings:
            # Update only the changed settings
            for key, value in settings.items():
                cached_settings[key] = value
            _set_in_cache(server_xp_settings_cache, guild_id, cached_settings)
        else:
            # Invalidate cache to force a fresh fetch next time
            if guild_id in server_xp_settings_cache:
                del server_xp_settings_cache[guild_id]
    
    return result is not False

async def reset_server_xp_settings(guild_id: str) -> bool:
    """Reset server XP settings to defaults with error handling"""
    # Use safe_db_operation for error handling and retries
    result = await safe_db_operation("reset_server_xp_settings", guild_id)
    
    if result:
        # Remove from cache if operation was successful
        if guild_id in server_xp_settings_cache:
            del server_xp_settings_cache[guild_id]
    
    return result is not False

async def get_event_channel(guild_id: str):
    """Get event channel with caching"""
    # Try cache first
    cached_value = _get_from_cache(config_cache, f"{guild_id}_event")
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    async with get_connection() as conn:
        query = "SELECT event_channel FROM server_config WHERE guild_id = $1"
        row = await conn.fetchrow(query, guild_id)
        
        channel_id = row['event_channel'] if row else None
        
        # Store in cache if found
        if channel_id is not None:
            _set_in_cache(config_cache, f"{guild_id}_event", channel_id)
        
        return channel_id

async def _set_achievement_channel(guild_id: str, channel_id: str):
    """Set achievement channel with transaction protection"""
    async with get_connection() as conn:
        query = """
        INSERT INTO server_config (guild_id, achievement_channel) 
        VALUES ($1, $2)
        ON CONFLICT (guild_id) 
        DO UPDATE SET achievement_channel = $2
        """
        await conn.execute(query, guild_id, channel_id)
        
        # Update cache
        _set_in_cache(config_cache, f"{guild_id}_achievement", channel_id)

async def set_achievement_channel(guild_id: str, channel_id: str):
    """Set the achievement notification channel with safety wrapper"""
    result = await safe_db_operation("set_achievement_channel", guild_id, channel_id)
    
    # Update cache
    if result is not None:
        _set_in_cache(config_cache, f"{guild_id}_achievement", channel_id)
    
    return result

async def get_achievement_channel(guild_id: str):
    """Get achievement channel with caching"""
    # Try cache first
    cached_value = _get_from_cache(config_cache, f"{guild_id}_achievement")
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    async with get_connection() as conn:
        query = "SELECT achievement_channel FROM server_config WHERE guild_id = $1"
        row = await conn.fetchrow(query, guild_id)
        
        channel_id = row['achievement_channel'] if row else None
        
        # Store in cache if found
        if channel_id is not None:
            _set_in_cache(config_cache, f"{guild_id}_achievement", channel_id)
        
        return channel_id

async def _set_quest_channel(guild_id: str, channel_id: str):
    """Set quest channel with transaction protection"""
    async with get_connection() as conn:
        query = """
        INSERT INTO server_config (guild_id, quest_channel) 
        VALUES ($1, $2)
        ON CONFLICT (guild_id) 
        DO UPDATE SET quest_channel = $2
        """
        await conn.execute(query, guild_id, channel_id)
        
        # Update cache
        _set_in_cache(config_cache, f"{guild_id}_quest", channel_id)

async def set_quest_channel(guild_id: str, channel_id: str):
    """Set the quest notification channel with safety wrapper"""
    result = await safe_db_operation("set_quest_channel", guild_id, channel_id)
    
    # Update cache
    if result is not None:
        _set_in_cache(config_cache, f"{guild_id}_quest", channel_id)
    
    return result

async def get_quest_channel(guild_id: str):
    """Get quest channel with caching"""
    # Try cache first
    cached_value = _get_from_cache(config_cache, f"{guild_id}_quest")
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    async with get_connection() as conn:
        query = "SELECT quest_channel FROM server_config WHERE guild_id = $1"
        row = await conn.fetchrow(query, guild_id)
        
        channel_id = row['quest_channel'] if row else None
        
        # Store in cache if found
        if channel_id is not None:
            _set_in_cache(config_cache, f"{guild_id}_quest", channel_id)
        
        return channel_id