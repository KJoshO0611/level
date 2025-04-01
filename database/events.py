"""
XP boost events functionality for the database.
"""
import time
import logging
from typing import Dict, List, Optional

from .core import get_connection
from .cache import (
    _get_from_cache, _set_in_cache,
    active_events_cache, upcoming_events_cache, event_details_cache
)
from .utils import safe_db_operation

async def _create_xp_boost_event(guild_id: str, name: str, multiplier: float, 
                               start_time: float, end_time: float, created_by: str) -> int:
    """Internal function to create a new XP boost event"""
    try:
        async with get_connection() as conn:
            query = """
            INSERT INTO xp_boost_events 
            (guild_id, name, multiplier, start_time, end_time, created_by, active)
            VALUES ($1, $2, $3, $4, $5, $6, TRUE)
            RETURNING id
            """
            event_id = await conn.fetchval(query, guild_id, name, multiplier, 
                                         start_time, end_time, created_by)
            return event_id
    except Exception as e:
        logging.error(f"Error creating XP boost event: {e}")
        return None

async def create_xp_boost_event(guild_id: str, name: str, multiplier: float, 
                               start_time: float, end_time: float, created_by: str) -> int:
    """Create a new XP boost event and return its ID"""
    # Use safe_db_operation for error handling
    event_id = await safe_db_operation("create_xp_boost_event", guild_id, name, multiplier, 
                                     start_time, end_time, created_by)
    
    if event_id:
        # Invalidate caches for this guild to force a refresh
        if guild_id in active_events_cache:
            del active_events_cache[guild_id]
        if guild_id in upcoming_events_cache:
            del upcoming_events_cache[guild_id]
    
    return event_id

async def _get_active_xp_boost_events(guild_id: str) -> list:
    """Internal function to get active XP boost events for a guild"""
    current_time = time.time()
    
    try:
        async with get_connection() as conn:
            query = """
            SELECT id, name, multiplier, start_time, end_time, created_by
            FROM xp_boost_events
            WHERE guild_id = $1 
              AND start_time <= $2 
              AND end_time >= $2
              AND active = TRUE
            ORDER BY start_time ASC
            """
            rows = await conn.fetch(query, guild_id, current_time)
            
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "multiplier": row["multiplier"],
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "created_by": row["created_by"]
                }
                for row in rows
            ]
    except Exception as e:
        logging.error(f"Error getting active XP boost events: {e}")
        return []

async def get_active_xp_boost_events(guild_id: str) -> list:
    """Get all active XP boost events for a guild with caching"""
    # Try cache first
    cached_value = _get_from_cache(active_events_cache, guild_id)
    if cached_value is not None:
        # Filter out any events that have ended since caching
        current_time = time.time()
        valid_events = [event for event in cached_value 
                      if event["end_time"] >= current_time]
        
        # If the list changed (events ended), update the cache
        if len(valid_events) != len(cached_value):
            _set_in_cache(active_events_cache, guild_id, valid_events)
            
        return valid_events
    
    # If not in cache or cache expired, get from database
    events = await _get_active_xp_boost_events(guild_id)
    
    # Cache the results
    if events is not None:
        _set_in_cache(active_events_cache, guild_id, events)
    
    return events

async def _get_upcoming_xp_boost_events(guild_id: str) -> list:
    """Internal function to get upcoming XP boost events for a guild"""
    current_time = time.time()
    
    try:
        async with get_connection() as conn:
            query = """
            SELECT id, name, multiplier, start_time, end_time, created_by
            FROM xp_boost_events
            WHERE guild_id = $1 
              AND start_time > $2
              AND active = TRUE
            ORDER BY start_time ASC
            """
            rows = await conn.fetch(query, guild_id, current_time)
            
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "multiplier": row["multiplier"],
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "created_by": row["created_by"]
                }
                for row in rows
            ]
    except Exception as e:
        logging.error(f"Error getting upcoming XP boost events: {e}")
        return []

async def get_upcoming_xp_boost_events(guild_id: str) -> list:
    """Get upcoming XP boost events for a guild with caching"""
    # Try cache first
    cached_value = _get_from_cache(upcoming_events_cache, guild_id)
    if cached_value is not None:
        # Filter out any events that have started since caching
        current_time = time.time()
        valid_events = [event for event in cached_value 
                      if event["start_time"] > current_time]
        
        # If the list changed (events started), update the cache
        if len(valid_events) != len(cached_value):
            _set_in_cache(upcoming_events_cache, guild_id, valid_events)
            
        return valid_events
    
    # If not in cache or cache expired, get from database
    events = await _get_upcoming_xp_boost_events(guild_id)
    
    # Cache the results
    if events is not None:
        _set_in_cache(upcoming_events_cache, guild_id, events)
    
    return events

async def _delete_xp_boost_event(event_id: int) -> bool:
    """Internal function to delete/deactivate an XP boost event"""
    try:
        async with get_connection() as conn:
            query = """
            UPDATE xp_boost_events
            SET active = FALSE
            WHERE id = $1
            RETURNING id
            """
            result = await conn.fetchval(query, event_id)
            return result is not None
    except Exception as e:
        logging.error(f"Error deleting XP boost event: {e}")
        return False

async def delete_xp_boost_event(event_id: int) -> bool:
    """Delete (deactivate) an XP boost event with error handling"""
    # Get the event first to find its guild_id for cache invalidation
    event = await get_xp_boost_event(event_id)
    guild_id = event["guild_id"] if event else None
    
    # Use safe_db_operation for error handling
    result = await safe_db_operation("delete_xp_boost_event", event_id)
    
    if result and guild_id:
        # Invalidate caches
        if guild_id in active_events_cache:
            del active_events_cache[guild_id]
        if guild_id in upcoming_events_cache:
            del upcoming_events_cache[guild_id]
        if event_id in event_details_cache:
            del event_details_cache[event_id]
    
    return result is not False

async def _get_xp_boost_event(event_id: int) -> dict:
    """Internal function to get details of a specific XP boost event"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT id, guild_id, name, multiplier, start_time, end_time, created_by, active
            FROM xp_boost_events
            WHERE id = $1
            """
            row = await conn.fetchrow(query, event_id)
            
            if not row:
                return None
                
            return {
                "id": row["id"],
                "guild_id": row["guild_id"],
                "name": row["name"],
                "multiplier": row["multiplier"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "created_by": row["created_by"],
                "active": row["active"]
            }
    except Exception as e:
        logging.error(f"Error getting XP boost event: {e}")
        return None

async def get_xp_boost_event(event_id: int) -> dict:
    """Get details of a specific XP boost event with caching"""
    # Try cache first
    cached_value = _get_from_cache(event_details_cache, event_id)
    if cached_value is not None:
        return cached_value
    
    # If not in cache or cache expired, get from database
    event = await _get_xp_boost_event(event_id)
    
    # Cache the results if found
    if event:
        _set_in_cache(event_details_cache, event_id, event)
    
    return event

async def get_event_xp_multiplier(guild_id: str) -> float:
    """
    Get the XP multiplier from all active events for a guild.
    If multiple events are active, we take the highest multiplier.
    """
    active_events = await get_active_xp_boost_events(guild_id)
    
    # Default multiplier is 1.0 (no change)
    if not active_events:
        return 1.0
    
    # Get the highest multiplier from active events
    max_multiplier = max(event["multiplier"] for event in active_events)
    return max_multiplier

async def invalidate_boost_caches(event_id: int):
    """Invalidate all caches related to a boost event"""
    event = await get_xp_boost_event(event_id)
    if event:
        guild_id = event["guild_id"]
        if guild_id in active_events_cache:
            del active_events_cache[guild_id]
        if guild_id in upcoming_events_cache:
            del upcoming_events_cache[guild_id]
        if event_id in event_details_cache:
            del event_details_cache[event_id]

async def update_xp_boost_start_time(event_id: int, new_start_time: float) -> bool:
    """Update the start time of an XP boost event.
    
    Args:
        event_id: The ID of the XP boost event
        new_start_time: The new start time as a Unix timestamp
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        async with get_connection() as conn:
            query = """
            UPDATE xp_boost_events 
            SET start_time = $1
            WHERE id = $2
            RETURNING id
            """
            result = await conn.fetchval(query, new_start_time, event_id)
            
            if result:
                # Invalidate relevant caches
                await invalidate_boost_caches(event_id)
                return True
            return False
    except Exception as e:
        logging.error(f"Error updating XP boost start time: {e}")
        return False