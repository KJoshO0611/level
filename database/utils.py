"""
Utility functions for database operations, error handling, and batch processing.
"""
import time
import asyncio
import logging
import random
from typing import Dict, List, Tuple, Optional, Any
import asyncpg

from .core import get_connection, db_lock, pending_operations

# Constants
MAX_RETRIES = 5
BATCH_SIZE = 100
MAX_BATCH_WAIT_TIME = 0.5  # seconds

# Batch update queue
xp_update_queue = []
xp_update_event = asyncio.Event()

async def batch_update_processor():
    """Background task to process batch updates"""
    while True:
        # Wait for updates or timeout
        try:
            await asyncio.wait_for(xp_update_event.wait(), timeout=MAX_BATCH_WAIT_TIME)
        except asyncio.TimeoutError:
            pass
        
        # Clear event
        xp_update_event.clear()
        
        # Process batch if there are updates
        if xp_update_queue:
            await process_xp_batch()
        
        # Small delay to prevent CPU thrashing
        await asyncio.sleep(0.1)

async def process_xp_batch():
    """Process a batch of XP updates"""
    global xp_update_queue
    
    async with db_lock:
        # Get current batch
        current_batch = xp_update_queue[:BATCH_SIZE]
        xp_update_queue = xp_update_queue[BATCH_SIZE:]
    
    if not current_batch:
        return
    
    # Create parameter batches
    try:
        async with get_connection() as conn:
            # Prepare the batch query
            query = """
            INSERT INTO levels (guild_id, user_id, xp, level, last_xp_time, last_role)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id, user_id) 
            DO UPDATE SET 
                xp = EXCLUDED.xp, 
                level = EXCLUDED.level, 
                last_xp_time = EXCLUDED.last_xp_time,
                last_role = EXCLUDED.last_role
            """
            
            # Execute batch upsert
            await conn.executemany(query, [
                (item['guild_id'], item['user_id'], item['xp'], item['level'], 
                 item['last_xp_time'], item['last_role']) 
                for item in current_batch
            ])
            
            logging.info(f"Processed batch of {len(current_batch)} XP updates")
            
            # Update cache for all affected users
            from .cache import level_cache, _set_in_cache
            for item in current_batch:
                cache_key = (item['guild_id'], item['user_id'])
                _set_in_cache(level_cache, cache_key, 
                            (item['xp'], item['level'], item['last_xp_time'], item['last_role']))
    
    except Exception as e:
        logging.error(f"Error processing XP batch: {e}")
        # Re-queue failed batch with exponential backoff
        await asyncio.sleep(1)
        async with db_lock:
            xp_update_queue.extend(current_batch)
            xp_update_event.set()

async def queue_xp_update(guild_id: str, user_id: str, xp: int, level: int, 
                        last_xp_time: Optional[float] = None, last_role: Optional[str] = None):
    """Queue an XP update for batch processing"""
    if last_xp_time is None:
        last_xp_time = time.time()
    
    # Add to queue
    async with db_lock:
        xp_update_queue.append({
            'guild_id': guild_id,
            'user_id': user_id,
            'xp': xp,
            'level': level,
            'last_xp_time': last_xp_time,
            'last_role': last_role
        })
        xp_update_event.set()
    
    # Immediately update cache
    from .cache import level_cache, _set_in_cache
    cache_key = (guild_id, user_id)
    _set_in_cache(level_cache, cache_key, (xp, level, last_xp_time, last_role))

async def safe_db_operation(func_name: str, *args, **kwargs):
    """
    Execute a database operation with retry logic.
    If it fails, store it for later retry.
    """
    global pending_operations, MAX_RETRIES
    retries = 0
    
    while retries < MAX_RETRIES:
        try:
            # Import all the internal functions we might need to call
            # This is to prevent circular imports
            from .users import _get_or_create_user_level, _update_user_xp
            from .config import (_set_level_up_channel, _set_channel_boost_db, 
                                _remove_channel_boost_db, _update_server_xp_settings, 
                                _reset_server_xp_settings)
            from .events import _create_xp_boost_event, _delete_xp_boost_event
            from .backgrounds import _set_user_background, _remove_user_background
            from .achievements import (_update_activity_counter_internal, _get_user_achievements_internal, 
                                     _create_achievement_internal, _get_achievement_leaderboard_internal,
                                     _get_achievement_stats_internal, _update_achievement_internal,
                                     _delete_achievement_internal)
            from .quests import (_create_quest_internal, _get_quest_internal, _update_quest_internal,
                    _delete_quest_internal, _get_guild_active_quests_internal,
                    _mark_quests_inactive_internal, _get_user_quest_progress_internal,
                    _update_user_quest_progress_internal, _get_user_active_quests_internal,
                    _get_user_quest_stats_internal)


            # Map function name to actual function
            function_map = {
                "get_or_create_user_level": _get_or_create_user_level,
                "update_user_xp": _update_user_xp,
                "set_level_up_channel": _set_level_up_channel,
                "set_channel_boost_db": _set_channel_boost_db,
                "remove_channel_boost_db": _remove_channel_boost_db,
                "update_server_xp_settings": _update_server_xp_settings,
                "reset_server_xp_settings": _reset_server_xp_settings,
                "create_xp_boost_event": _create_xp_boost_event,
                "delete_xp_boost_event": _delete_xp_boost_event,
                "set_user_background": _set_user_background,
                "remove_user_background": _remove_user_background,
                "update_activity_counter_internal": _update_activity_counter_internal,
                "get_user_achievements_internal": _get_user_achievements_internal,
                "create_achievement_internal": _create_achievement_internal,
                "get_achievement_leaderboard_internal": _get_achievement_leaderboard_internal,
                "get_achievement_stats_internal": _get_achievement_stats_internal,
                "update_achievement_internal": _update_achievement_internal,
                "delete_achievement_internal": _delete_achievement_internal,
                "create_quest_internal": _create_quest_internal,
                "get_quest_internal": _get_quest_internal,
                "update_quest_internal": _update_quest_internal,
                "delete_quest_internal": _delete_quest_internal,
                "get_guild_active_quests_internal": _get_guild_active_quests_internal,
                "mark_quests_inactive_internal": _mark_quests_inactive_internal,
                "get_user_quest_progress_internal": _get_user_quest_progress_internal,
                "update_user_quest_progress_internal": _update_user_quest_progress_internal,
                "get_user_active_quests_internal": _get_user_active_quests_internal,
                "get_user_quest_stats_internal": _get_user_quest_stats_internal
            }
            
            if func_name not in function_map:
                logging.error(f"Unknown function name: {func_name}")
                return None
                
            # Call the function with arguments
            return await function_map[func_name](*args, **kwargs)

        except asyncpg.exceptions.PostgresError as e:
            logging.error(f"Database error in {func_name}: {e}")
            
            # Handle specific database errors
            if isinstance(e, asyncpg.exceptions.DeadlockDetectedError):
                logging.warning(f"Deadlock detected, retrying {func_name} (attempt {retries+1}/{MAX_RETRIES})")
            elif isinstance(e, (asyncpg.exceptions.ConnectionDoesNotExistError, asyncpg.exceptions.InterfaceError)):
                logging.error(f"Lost database connection during {func_name}")
                # Don't try to immediately reconnect - add to pending ops
            else:
                # Queue the operation for later retry
                pending_operations.append({
                    "function": func_name,
                    "args": args,
                    "kwargs": kwargs,
                    "retries": retries
                })
                logging.warning(f"Operation {func_name} queued for later retry")
                return None

            # Exponential backoff with jitter to prevent thundering herd
            retries += 1
            backoff_time = 0.5 * (2 ** retries) * (0.8 + 0.4 * random.random())
            await asyncio.sleep(backoff_time)

        except Exception as e:
            # Unexpected error, queue for later
            logging.error(f"Unexpected error in {func_name}: {str(e)}")
            pending_operations.append({
                "function": func_name,
                "args": args,
                "kwargs": kwargs,
                "retries": retries
            })
            return None

    # If we exhausted retries, queue the operation
    logging.warning(f"Max retries reached for {func_name}, queueing for later")
    pending_operations.append({
        "function": func_name,
        "args": args,
        "kwargs": kwargs,
        "retries": retries
    })
    return None

async def retry_pending_operations():
    """Process any pending database operations with better handling"""
    global pending_operations
    
    if not pending_operations:
        return
        
    async with db_lock:
        operations_to_retry = pending_operations.copy()
        successful_ops = []
        
        for operation in operations_to_retry:
            try:
                func_name = operation["function"]
                args = operation["args"]
                kwargs = operation["kwargs"]
                
                # Try again with the safe_db_operation function
                result = await safe_db_operation(func_name, *args, **kwargs)
                
                if result is not None:
                    successful_ops.append(operation)
                    logging.info(f"Successfully processed pending {func_name} operation")
                
            except Exception as e:
                logging.error(f"Failed to process pending operation: {e}")
                # Increment retry count
                operation["retries"] = operation.get("retries", 0) + 1
                
                # If max retries reached, log and remove
                if operation.get("retries", 0) >= MAX_RETRIES:
                    logging.error(f"Operation {operation['function']} failed after maximum retries. Dropping.")
                    successful_ops.append(operation)
        
        # Remove successful operations
        for op in successful_ops:
            if op in pending_operations:
                pending_operations.remove(op)