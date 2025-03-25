"""
User data and leveling functions for the database.
"""
import time
import logging
from typing import Dict, List, Tuple, Optional, Any

from .core import get_connection
from .cache import _get_from_cache, _set_in_cache, level_cache
from .utils import safe_db_operation, queue_xp_update

async def _get_or_create_user_level(guild_id: str, user_id: str) -> Tuple[int, int, float, Optional[str]]:
    """Get or create user level data using a transaction for consistency"""
    async with get_connection() as conn:
        async with conn.transaction():
            # Try to get existing record with FOR UPDATE to lock the row
            query = """
            SELECT xp, level, last_xp_time, last_role 
            FROM levels 
            WHERE guild_id = $1 AND user_id = $2
            FOR UPDATE
            """
            row = await conn.fetchrow(query, guild_id, user_id)
            
            if row is None:
                # Create new user record
                xp = 0
                level = 1
                last_xp_time = time.time()
                
                # Get level 1 role if available
                level_roles_query = """
                SELECT role_id FROM level_roles
                WHERE guild_id = $1 AND level = 1
                """
                role_row = await conn.fetchrow(level_roles_query, guild_id)
                last_role = role_row['role_id'] if role_row else None
                
                # Insert new record
                insert_query = """
                INSERT INTO levels (guild_id, user_id, xp, level, last_xp_time, last_role)
                VALUES ($1, $2, $3, $4, $5, $6)
                """
                await conn.execute(insert_query, guild_id, user_id, xp, level, last_xp_time, last_role)
                
                return (xp, level, last_xp_time, last_role)
            else:
                return (row['xp'], row['level'], row['last_xp_time'], row['last_role'])

async def _update_user_xp(guild_id: str, user_id: str, xp: int, level: int, 
                         last_xp_time: Optional[float] = None, last_role: Optional[str] = None):
    """Update user XP with transaction protection"""
    if last_xp_time is None:
        last_xp_time = time.time()
    
    async with get_connection() as conn:
        query = """
        UPDATE levels 
        SET xp = $1, level = $2, last_xp_time = $3, last_role = $4 
        WHERE guild_id = $5 AND user_id = $6
        """
        await conn.execute(query, xp, level, last_xp_time, last_role, guild_id, user_id)

async def get_or_create_user_level(guild_id: str, user_id: str):
    """Get or create user level with safety wrapper"""
    # Try cache first
    cache_key = (guild_id, user_id)
    cached_value = _get_from_cache(level_cache, cache_key)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    result = await safe_db_operation("get_or_create_user_level", guild_id, user_id)
    
    # Store in cache if successful
    if result is not None:
        _set_in_cache(level_cache, cache_key, result)
    
    return result

async def update_user_xp(guild_id: str, user_id: str, xp: int, level: int, 
                         last_xp_time: Optional[float] = None, last_role: Optional[str] = None):
    """Update user XP with safety wrapper"""
    # For high-concurrency scenarios, queue the update
    await queue_xp_update(guild_id, user_id, xp, level, last_xp_time, last_role)
    
    # Return immediately since update will happen asynchronously
    return True

async def get_user_levels(guild_id: str, user_id: str):
    """Get user levels with caching"""
    # Try cache first
    cache_key = (guild_id, user_id)
    cached_value = _get_from_cache(level_cache, cache_key)
    if cached_value is not None:
        xp, level, _, _ = cached_value
        return (xp, level)
    
    # If not in cache, get from database
    async with get_connection() as conn:
        query = "SELECT xp, level FROM levels WHERE guild_id = $1 AND user_id = $2"
        row = await conn.fetchrow(query, guild_id, user_id)
        
        if row:
            return (row['xp'], row['level'])
        else:
            # Default values if user not found
            return (0, 1)

async def get_user_rank(guild_id: str, user_id: str):
    """Get a user's rank in the guild leaderboard"""
    async with get_connection() as conn:
        # Use a window function to calculate rank efficiently
        query = """
        SELECT user_rank FROM (
            SELECT user_id, 
                   RANK() OVER (ORDER BY level DESC, xp DESC) as user_rank
            FROM levels
            WHERE guild_id = $1
        ) ranks
        WHERE user_id = $2
        """
        row = await conn.fetchrow(query, guild_id, user_id)
        return row['user_rank'] if row else None

async def get_leaderboard(guild_id: str, limit: int = 10, offset: int = 0):
    """Get top users by level and XP with pagination"""
    async with get_connection() as conn:
        query = """
        SELECT user_id, xp, level 
        FROM levels 
        WHERE guild_id = $1 
        ORDER BY level DESC, xp DESC 
        LIMIT $2 OFFSET $3
        """
        rows = await conn.fetch(query, guild_id, limit, offset)
        return [(row['user_id'], row['xp'], row['level']) for row in rows]

async def get_bulk_user_levels(guild_id: str, user_ids: List[str]):
    """Efficiently get level data for multiple users in one query"""
    if not user_ids:
        return {}
    
    result = {}
    
    # First check cache for all users
    missing_users = []
    for user_id in user_ids:
        cache_key = (guild_id, user_id)
        cached_value = _get_from_cache(level_cache, cache_key)
        if cached_value is not None:
            result[user_id] = cached_value
        else:
            missing_users.append(user_id)
    
    # If all users were in cache, return early
    if not missing_users:
        return result
    
    # Get missing users from database
    async with get_connection() as conn:
        query = """
        SELECT user_id, xp, level, last_xp_time, last_role
        FROM levels
        WHERE guild_id = $1 AND user_id = ANY($2::text[])
        """
        rows = await conn.fetch(query, guild_id, missing_users)
        
        # Add to result and cache
        for row in rows:
            user_id = row['user_id']
            data = (row['xp'], row['level'], row['last_xp_time'], row['last_role'])
            result[user_id] = data
            
            # Update cache
            cache_key = (guild_id, user_id)
            _set_in_cache(level_cache, cache_key, data)
    
    return result