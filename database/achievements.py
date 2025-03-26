"""
Achievement system functionality for the database.
"""
import time
import logging
from typing import Dict, List, Tuple, Optional, Any

from .core import get_connection
from .cache import (
    ACHIEVEMENT_CACHE, USER_ACHIEVEMENT_CACHE, ACHIEVEMENT_BY_ID_CACHE,
    LEADERBOARD_CACHE, ACHIEVEMENT_STATS_CACHE, RELEVANT_ACHIEVEMENTS_CACHE,
    invalidate_achievement_caches
)
from .utils import safe_db_operation

async def _update_activity_counter_internal(guild_id: str, user_id: str, counter_type: str, increment: int = 1):
    """Internal function for updating activity counter with safe_db_operation"""
    try:
        async with get_connection() as conn:
            async with conn.transaction():
                # First, make sure the user exists in the levels table
                user_check_query = """
                SELECT 1 FROM levels 
                WHERE guild_id = $1 AND user_id = $2
                """
                user_exists = await conn.fetchval(user_check_query, guild_id, user_id)
                
                if not user_exists:
                    # Create user entry with default values
                    insert_query = """
                    INSERT INTO levels (guild_id, user_id, xp, level, last_xp_time, last_role, 
                                       total_messages, total_reactions, voice_time_seconds, commands_used)
                    VALUES ($1, $2, 0, 1, $3, NULL, 0, 0, 0, 0)
                    """
                    await conn.execute(insert_query, guild_id, user_id, time.time())
                
                # Update the counter
                query = f"""
                UPDATE levels 
                SET {counter_type} = COALESCE({counter_type}, 0) + $1
                WHERE guild_id = $2 AND user_id = $3
                RETURNING {counter_type}
                """
                
                new_value = await conn.fetchval(query, increment, guild_id, user_id)
                if new_value is None:
                    return -1, []
                
                # Check for and update achievements based on new value
                newly_completed = await _check_achievements_internal(
                    conn, guild_id, user_id, counter_type, new_value
                )
                
                return new_value, newly_completed
                
    except Exception as e:
        logging.error(f"Error in _update_activity_counter_internal: {e}")
        return -1, []

async def _get_relevant_achievements(conn, guild_id: str, counter_type: str, value: int) -> list:
    """
    Internal function to get relevant achievements for a counter type and value with caching
    
    Parameters:
    - conn: Database connection
    - guild_id: The guild ID
    - counter_type: Type of counter (total_messages, total_reactions, etc.)
    - value: Current counter value
    
    Returns:
    - List of achievement dictionaries that match the criteria
    """
    # Create cache key
    cache_key = f"{guild_id}:{counter_type}:{value}"
    
    # Check cache first
    cached_value = RELEVANT_ACHIEVEMENTS_CACHE.get(cache_key)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, query database
    try:
        query = """
        SELECT id, name, description, requirement_type, requirement_value, icon_path
        FROM achievements
        WHERE guild_id = $1
        AND requirement_type = $2 
        AND requirement_value <= $3
        ORDER BY requirement_value DESC
        """
        
        rows = await conn.fetch(query, guild_id, counter_type, value)
        achievements = [dict(row) for row in rows]
        
        # Cache the results
        RELEVANT_ACHIEVEMENTS_CACHE.set(cache_key, achievements)
        return achievements
    except Exception as e:
        logging.error(f"Error fetching relevant achievements: {e}")
        return []
    
async def _check_user_achievement_status(conn, guild_id: str, user_id: str, achievement_id: int) -> tuple:
    """
    Internal function to check if user already has an achievement
    
    Returns:
    - Tuple of (has_record, is_completed)
    """
    try:
        query = """
        SELECT completed
        FROM user_achievements
        WHERE guild_id = $1 AND user_id = $2 AND achievement_id = $3
        """
        
        row = await conn.fetchrow(query, guild_id, user_id, achievement_id)
        if row:
            return True, row['completed']
        return False, False
    except Exception as e:
        logging.error(f"Error checking achievement status: {e}")
        return False, False

async def _update_user_achievement(conn, guild_id: str, user_id: str, achievement_id: int, 
                                 progress: int, completed: bool) -> bool:
    """
    Internal function to insert or update a user achievement
    
    Returns:
    - bool: True if successful, False otherwise
    """
    # If completed, set completed_at timestamp, otherwise set to NULL
    completed_at = 'CURRENT_TIMESTAMP' if completed else 'NULL'
    
    try:
        query = f"""
        INSERT INTO user_achievements 
            (guild_id, user_id, achievement_id, progress, completed, completed_at)
        VALUES 
            ($1, $2, $3, $4, $5, {completed_at})
        ON CONFLICT (guild_id, user_id, achievement_id) 
        DO UPDATE SET 
            progress = $4,
            completed = $5,
            completed_at = CASE WHEN 
                user_achievements.completed = false AND $5 = true 
                THEN CURRENT_TIMESTAMP 
                ELSE user_achievements.completed_at 
            END
        RETURNING id
        """
        
        result = await conn.fetchval(query, guild_id, user_id, achievement_id, progress, completed)
        return result is not None
    except Exception as e:
        logging.error(f"Error updating user achievement: {e}")
        return False

async def _get_newly_completed_achievements(conn, guild_id: str, user_id: str, 
                                         time_window: int = 10) -> list:
    """
    Internal function to get achievements that were just completed
    
    Parameters:
    - conn: Database connection
    - guild_id: The guild ID
    - user_id: The user ID
    - time_window: Number of seconds to look back for "newly" completed
    
    Returns:
    - List of newly completed achievements
    """
    try:
        query = """
        SELECT a.id, a.name, a.description, a.requirement_type, a.requirement_value, a.icon_path, 
               ua.completed_at, ua.progress
        FROM user_achievements ua
        JOIN achievements a ON ua.achievement_id = a.id
        WHERE ua.guild_id = $1 
        AND ua.user_id = $2 
        AND a.guild_id = $1
        AND ua.completed = true
        AND ua.completed_at > CURRENT_TIMESTAMP - ($3 * INTERVAL '1 second')
        """
        
        rows = await conn.fetch(query, guild_id, user_id, time_window)
        return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Error fetching newly completed achievements: {e}")
        return []

async def _check_achievements_internal(conn, guild_id: str, user_id: str, 
                                    counter_type: str, value: int) -> list:
    """
    Internal function to check and update achievements for a user
    
    Parameters:
    - conn: Database connection 
    - guild_id: The guild ID
    - user_id: The user ID
    - counter_type: Type of counter being updated
    - value: New counter value
    
    Returns:
    - List of newly completed achievements
    """
    # Get all relevant achievements for this counter type and value for this guild
    achievements = await _get_relevant_achievements(conn, guild_id, counter_type, value)
    
    # Track if any achievements were completed
    newly_completed = False
    
    # Process each achievement
    for achievement in achievements:
        # Check if user already has this achievement
        has_record, already_completed = await _check_user_achievement_status(
            conn, guild_id, user_id, achievement['id']
        )
        
        # If already completed, skip
        if already_completed:
            continue
        
        # Check if the achievement is completed now
        is_completed = value >= achievement['requirement_value']
        
        # Update or insert progress
        success = await _update_user_achievement(
            conn, guild_id, user_id, achievement['id'], value, is_completed
        )
        
        if success and is_completed:
            newly_completed = True
    
    # Return newly completed achievements
    if newly_completed:
        return await _get_newly_completed_achievements(conn, guild_id, user_id)
    return []

async def update_activity_counter_db(guild_id: str, user_id: str, counter_type: str, increment: int = 1) -> tuple:
    """
    Update an activity counter and check for completed achievements
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    - counter_type: Type of counter (total_messages, total_reactions, voice_time_seconds, etc.)
    - increment: Amount to increment by
    
    Returns:
    - Tuple of (new counter value, list of newly completed achievements)
    """
    result = await safe_db_operation("update_activity_counter_internal", guild_id, user_id, counter_type, increment)
    
    # If we completed achievements, invalidate user's achievement cache
    if result and result[1]:  # Check if list of completed achievements is non-empty
        invalidate_achievement_caches(guild_id, user_id)
    
    return result

async def _get_user_achievements_internal(guild_id: str, user_id: str) -> dict:
    """Internal function for getting user achievements with error handling via safe_db_operation"""
    try:
        async with get_connection() as conn:
            # Get all achievements for this guild
            query = """
            SELECT a.id, a.name, a.description, a.requirement_type, a.requirement_value, 
                   a.icon_path, ua.progress, ua.completed, ua.completed_at
            FROM achievements a
            LEFT JOIN user_achievements ua ON 
                a.id = ua.achievement_id AND 
                ua.guild_id = $1 AND 
                ua.user_id = $2
            WHERE a.guild_id = $1
            ORDER BY a.requirement_type, a.requirement_value
            """
            rows = await conn.fetch(query, guild_id, user_id)
            
            # Organize into categories
            completed = []
            in_progress = []
            locked = []
            
            for row in rows:
                achievement = dict(row)
                
                # Calculate progress percentage
                if achievement['progress'] is not None and achievement['requirement_value'] > 0:
                    achievement['percent'] = min(100, int((achievement['progress'] / achievement['requirement_value']) * 100))
                else:
                    achievement['percent'] = 0
                
                if achievement['completed']:
                    completed.append(achievement)
                elif achievement['progress'] is not None and achievement['progress'] > 0:
                    in_progress.append(achievement)
                else:
                    locked.append(achievement)
            
            return {
                "completed": completed,
                "in_progress": in_progress,
                "locked": locked,
                "total_count": len(rows),
                "completed_count": len(completed)
            }
    except Exception as e:
        logging.error(f"Error fetching user achievements: {e}")
        return {"completed": [], "in_progress": [], "locked": [], "total_count": 0, "completed_count": 0}

async def get_user_achievements_db(guild_id: str, user_id: str) -> dict:
    """
    Get all achievements for a user with progress and caching
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    
    Returns:
    - Dictionary containing completed and in-progress achievements
    """
    # Create cache key
    cache_key = f"{guild_id}:{user_id}"
    
    # Check cache first
    cached_value = USER_ACHIEVEMENT_CACHE.get(cache_key)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    result = await safe_db_operation("get_user_achievements_internal", guild_id, user_id)
    
    # Cache the result if valid
    if result is not None:
        USER_ACHIEVEMENT_CACHE.set(cache_key, result)
    
    return result

async def _create_achievement_internal(guild_id: str, name: str, description: str, requirement_type: str, 
                                     requirement_value: int, icon_path: str = None) -> int:
    """Internal function for creating achievement with error handling via safe_db_operation"""
    try:
        async with get_connection() as conn:
            query = """
            INSERT INTO achievements (guild_id, name, description, requirement_type, requirement_value, icon_path)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """
            
            achievement_id = await conn.fetchval(
                query, guild_id, name, description, requirement_type, requirement_value, icon_path
            )
            
            logging.info(f"Created new achievement for guild {guild_id}: {name} (ID: {achievement_id})")
            return achievement_id
    except Exception as e:
        logging.error(f"Error creating achievement: {e}")
        return -1

async def create_achievement_db(guild_id: str, name: str, description: str, requirement_type: str, 
                              requirement_value: int, icon_path: str = None) -> int:
    """
    Create a new achievement for a specific guild
    
    Parameters:
    - guild_id: The guild ID this achievement belongs to
    - name: Achievement name
    - description: Description text
    - requirement_type: Type of requirement (total_messages, voice_time_seconds, etc.)
    - requirement_value: Value required to earn the achievement
    - icon_path: Optional path to icon image
    
    Returns:
    - int: ID of the created achievement, or -1 on error
    """
    result = await safe_db_operation("create_achievement_internal", guild_id, name, description, 
                                    requirement_type, requirement_value, icon_path)
    
    # Invalidate guild's achievement cache if successful
    if result > 0:
        invalidate_achievement_caches(guild_id)
        
    return result

async def _get_achievement_leaderboard_internal(guild_id: str, limit: int = 10) -> list:
    """Internal function for getting achievement leaderboard with error handling via safe_db_operation"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT 
                user_id, 
                COUNT(CASE WHEN completed = true THEN 1 END) as completed_count,
                (SELECT COUNT(*) FROM achievements WHERE guild_id = $1) as total_achievements,
                MAX(completed_at) as last_completed
            FROM user_achievements
            WHERE guild_id = $1 AND completed = true
            GROUP BY user_id
            ORDER BY completed_count DESC, last_completed DESC
            LIMIT $2
            """
            
            rows = await conn.fetch(query, guild_id, limit)
            return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Error getting achievement leaderboard: {e}")
        return []

async def get_achievement_leaderboard_db(guild_id: str, limit: int = 10) -> list:
    """
    Get a leaderboard of users ranked by achievement count with caching
    
    Parameters:
    - guild_id: The guild ID
    - limit: Maximum number of users to return
    
    Returns:
    - List of user dictionaries with achievement counts
    """
    # Create cache key
    cache_key = f"{guild_id}:{limit}"
    
    # Check cache first
    cached_value = LEADERBOARD_CACHE.get(cache_key)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    result = await safe_db_operation("get_achievement_leaderboard_internal", guild_id, limit)
    
    # Cache the result if valid
    if result is not None:
        LEADERBOARD_CACHE.set(cache_key, result)
    
    return result

async def _get_achievement_stats_internal(guild_id: str) -> dict:
    """Internal function for getting achievement stats with error handling via safe_db_operation"""
    try:
        async with get_connection() as conn:
            # Get total achievements for this guild
            total_query = "SELECT COUNT(*) FROM achievements WHERE guild_id = $1"
            total_achievements = await conn.fetchval(total_query, guild_id)
            
            # Get counts by category for this guild
            category_query = """
            SELECT requirement_type, COUNT(*) 
            FROM achievements 
            WHERE guild_id = $1
            GROUP BY requirement_type
            """
            categories = await conn.fetch(category_query, guild_id)
            
            # Get most common achievements
            common_query = """
            SELECT a.name, a.requirement_type, COUNT(ua.user_id) as earner_count
            FROM achievements a
            JOIN user_achievements ua ON a.id = ua.achievement_id
            WHERE a.guild_id = $1 AND ua.guild_id = $1 AND ua.completed = true
            GROUP BY a.id, a.name, a.requirement_type
            ORDER BY earner_count DESC
            LIMIT 5
            """
            most_common = await conn.fetch(common_query, guild_id)
            
            # Get rarest achievements
            rare_query = """
            SELECT a.name, a.requirement_type, COUNT(ua.user_id) as earner_count
            FROM achievements a
            JOIN user_achievements ua ON a.id = ua.achievement_id
            WHERE a.guild_id = $1 AND ua.guild_id = $1 AND ua.completed = true
            GROUP BY a.id, a.name, a.requirement_type
            ORDER BY earner_count ASC
            LIMIT 5
            """
            rarest = await conn.fetch(rare_query, guild_id)
            
            return {
                "total_achievements": total_achievements,
                "categories": {row["requirement_type"]: row["count"] for row in categories},
                "most_common": [dict(row) for row in most_common],
                "rarest": [dict(row) for row in rarest]
            }
    except Exception as e:
        logging.error(f"Error getting achievement stats: {e}")
        return {
            "total_achievements": 0,
            "categories": {},
            "most_common": [],
            "rarest": []
        }

async def get_achievement_stats_db(guild_id: str) -> dict:
    """
    Get overall achievement statistics for a guild with caching
    
    Parameters:
    - guild_id: The guild ID
    
    Returns:
    - Dictionary with achievement statistics
    """
    # Check cache first
    cached_value = ACHIEVEMENT_STATS_CACHE.get(guild_id)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
    result = await safe_db_operation("get_achievement_stats_internal", guild_id)
    
    # Cache the result if valid
    if result is not None:
        ACHIEVEMENT_STATS_CACHE.set(guild_id, result)
    
    return result

async def get_guild_achievements(guild_id: str) -> list:
    """
    Get all achievements for a guild with caching
    
    Parameters:
    - guild_id: The guild ID
    
    Returns:
    - List of achievement dictionaries
    """
    # Check cache first
    cached_value = ACHIEVEMENT_CACHE.get(guild_id)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, query database
    try:
        async with get_connection() as conn:
            query = """
            SELECT id, name, description, requirement_type, requirement_value, icon_path
            FROM achievements
            WHERE guild_id = $1
            ORDER BY requirement_type, requirement_value
            """
            rows = await conn.fetch(query, guild_id)
            achievements = [dict(row) for row in rows]
            
            # Cache the results
            ACHIEVEMENT_CACHE.set(guild_id, achievements)
            return achievements
    except Exception as e:
        logging.error(f"Error getting guild achievements: {e}")
        return []

async def get_achievement_by_id(guild_id: str, achievement_id: int) -> Optional[Dict]:
    """
    Get a specific achievement by ID with caching
    
    Parameters:
    - guild_id: The guild ID
    - achievement_id: The achievement ID
    
    Returns:
    - Achievement dictionary or None if not found
    """
    # Create cache key
    cache_key = f"{guild_id}:{achievement_id}"
    
    # Check cache first
    cached_value = ACHIEVEMENT_BY_ID_CACHE.get(cache_key)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, query database
    try:
        async with get_connection() as conn:
            query = """
            SELECT id, guild_id, name, description, requirement_type, requirement_value, icon_path
            FROM achievements
            WHERE id = $1 AND guild_id = $2
            """
            row = await conn.fetchrow(query, achievement_id, guild_id)
            
            if not row:
                return None
                
            achievement = dict(row)
            
            # Cache the result
            ACHIEVEMENT_BY_ID_CACHE.set(cache_key, achievement)
            return achievement
    except Exception as e:
        logging.error(f"Error getting achievement by ID: {e}")
        return None

async def _update_achievement_internal(guild_id: str, achievement_id: int, field: str, value: Any) -> bool:
    """Internal function for updating achievement with safe_db_operation wrapper"""
    try:
        async with get_connection() as conn:
            # Verify the achievement exists and belongs to this guild
            check_query = """
            SELECT 1 FROM achievements
            WHERE id = $1 AND guild_id = $2
            """
            exists = await conn.fetchval(check_query, achievement_id, guild_id)
            
            if not exists:
                return False
            
            # Map field name to database column
            field_map = {
                "name": "name",
                "description": "description",
                "type": "requirement_type",
                "value": "requirement_value",
                "badge": "icon_path",
                "icon_path": "icon_path"
            }
            
            if field.lower() not in field_map:
                logging.error(f"Invalid field for update_achievement: {field}")
                return False
                
            db_field = field_map[field.lower()]
            
            # Update the field
            update_query = f"""
            UPDATE achievements
            SET {db_field} = $1
            WHERE id = $2 AND guild_id = $3
            RETURNING id
            """
            
            result = await conn.fetchval(update_query, value, achievement_id, guild_id)
            return result is not None
            
    except Exception as e:
        logging.error(f"Error updating achievement: {e}")
        return False

async def update_achievement(guild_id: str, achievement_id: int, field: str, value: Any) -> bool:
    """
    Update a field in an achievement
    
    Parameters:
    - guild_id: The guild ID
    - achievement_id: The achievement ID
    - field: Field to update (name, description, requirement_type, requirement_value, icon_path)
    - value: New value for the field
    
    Returns:
    - bool: True if successful, False otherwise
    """
    result = await safe_db_operation("update_achievement_internal", guild_id, achievement_id, field, value)
    
    # If successful, invalidate cache
    if result:
        invalidate_achievement_caches(guild_id, achievement_id=achievement_id)
        
    return result

async def _delete_achievement_internal(guild_id: str, achievement_id: int) -> bool:
    """Internal function for deleting achievement with safe_db_operation wrapper"""
    try:
        async with get_connection() as conn:
            async with conn.transaction():
                # First delete related user_achievements records
                delete_user_ach_query = """
                DELETE FROM user_achievements
                WHERE achievement_id = $1 AND guild_id = $2
                """
                await conn.execute(delete_user_ach_query, achievement_id, guild_id)
                
                # Then delete the achievement itself
                delete_ach_query = """
                DELETE FROM achievements
                WHERE id = $1 AND guild_id = $2
                RETURNING id
                """
                result = await conn.fetchval(delete_ach_query, achievement_id, guild_id)
                return result is not None
                
    except Exception as e:
        logging.error(f"Error deleting achievement: {e}")
        return False

async def delete_achievement(guild_id: str, achievement_id: int) -> bool:
    """
    Delete an achievement
    
    Parameters:
    - guild_id: The guild ID
    - achievement_id: The achievement ID
    
    Returns:
    - bool: True if successful, False otherwise
    """
    result = await safe_db_operation("delete_achievement_internal", guild_id, achievement_id)
    
    # If successful, invalidate cache
    if result:
        invalidate_achievement_caches(guild_id, achievement_id=achievement_id)
        
    return result