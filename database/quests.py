"""
Quest system functionality for the database.
"""
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta

from .core import get_connection
from .utils import safe_db_operation
from .cache import _get_from_cache, _set_in_cache

# Quest-specific caches
QUEST_CACHE_TTL = 300  # 5 minutes
quest_cache = {}  # {quest_id: (quest_data, timestamp)}
active_quests_cache = {}  # {guild_id: (quests_list, timestamp)}
user_quest_cache = {}  # {(guild_id, user_id): (quests_list, timestamp)}
user_quest_stats_cache = {}  # {(guild_id, user_id): (stats_dict, timestamp)}

async def _create_quest_internal(guild_id: str, name: str, description: str, quest_type: str,
                                requirement_type: str, requirement_value: int, reward_xp: int,
                                reward_multiplier: float = 1.0, difficulty: str = "medium",
                                refresh_cycle: str = None) -> int:
    """Internal function to create a new quest"""
    try:
        async with get_connection() as conn:
            query = """
            INSERT INTO quests 
                (guild_id, name, description, quest_type, requirement_type, 
                 requirement_value, reward_xp, reward_multiplier, active, 
                 refresh_cycle, difficulty)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE, $9, $10)
            RETURNING id
            """
            
            quest_id = await conn.fetchval(
                query, guild_id, name, description, quest_type, requirement_type,
                requirement_value, reward_xp, reward_multiplier, refresh_cycle, difficulty
            )
            
            logging.info(f"Created new quest for guild {guild_id}: {name} (ID: {quest_id})")
            return quest_id
    except Exception as e:
        logging.error(f"Error creating quest: {e}")
        return -1

async def create_quest(guild_id: str, name: str, description: str, quest_type: str,
                       requirement_type: str, requirement_value: int, reward_xp: int,
                       reward_multiplier: float = 1.0, difficulty: str = "medium",
                       refresh_cycle: str = None) -> int:
    """
    Create a new quest for a guild
    
    Parameters:
    - guild_id: Guild ID
    - name: Quest name
    - description: Quest description
    - quest_type: Type of quest ('daily', 'weekly', 'special', etc.)
    - requirement_type: What needs to be done ('total_messages', 'voice_time_seconds', etc.)
    - requirement_value: Amount required
    - reward_xp: XP awarded for completion
    - reward_multiplier: XP multiplier for a period after completion
    - difficulty: Quest difficulty ('easy', 'medium', 'hard')
    - refresh_cycle: When quest resets ('daily', 'weekly', 'monthly', 'once')
    
    Returns:
    - int: ID of created quest or -1 on error
    """
    # Validate inputs
    if not name or not description:
        logging.error("Quest name and description are required")
        return -1
        
    valid_types = ['daily', 'weekly', 'special', 'event', 'challenge']
    if quest_type not in valid_types:
        logging.error(f"Invalid quest type: {quest_type}. Must be one of {valid_types}")
        return -1
        
    valid_req_types = ['total_messages', 'total_reactions', 'voice_time_seconds', 'commands_used']
    if requirement_type not in valid_req_types:
        logging.error(f"Invalid requirement type: {requirement_type}. Must be one of {valid_req_types}")
        return -1
    
    # Use safe_db_operation for retries and error handling    
    quest_id = await safe_db_operation(
        "create_quest_internal", guild_id, name, description, quest_type,
        requirement_type, requirement_value, reward_xp, reward_multiplier,
        difficulty, refresh_cycle
    )
    
    # Clear guild cache if successful
    if quest_id > 0:
        if guild_id in active_quests_cache:
            del active_quests_cache[guild_id]
    
    return quest_id

async def _get_quest_internal(quest_id: int) -> Optional[Dict]:
    """Internal function to get a quest by ID"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT id, guild_id, name, description, quest_type, requirement_type,
                   requirement_value, reward_xp, reward_multiplier, active,
                   refresh_cycle, difficulty, created_at
            FROM quests
            WHERE id = $1
            """
            row = await conn.fetchrow(query, quest_id)
            
            if row:
                return dict(row)
            return None
            
    except Exception as e:
        logging.error(f"Error getting quest: {e}")
        return None

async def get_quest(quest_id: int) -> Optional[Dict]:
    """
    Get a quest by ID with caching
    
    Parameters:
    - quest_id: Quest ID
    
    Returns:
    - Dict or None: Quest data or None if not found
    """
    # Check cache first
    cached_quest = _get_from_cache(quest_cache, quest_id)
    if cached_quest is not None:
        return cached_quest
    
    # Get from database and cache the result
    quest = await safe_db_operation("get_quest_internal", quest_id)
    
    if quest:
        _set_in_cache(quest_cache, quest_id, quest)
    
    return quest

async def _update_quest_internal(quest_id: int, guild_id: str, field: str, value: Any) -> bool:
    """Internal function to update a quest field"""
    try:
        async with get_connection() as conn:
            # Verify the quest exists and belongs to this guild
            check_query = """
            SELECT 1 FROM quests
            WHERE id = $1 AND guild_id = $2
            """
            exists = await conn.fetchval(check_query, quest_id, guild_id)
            
            if not exists:
                return False
            
            # Map field name to database column
            field_map = {
                "name": "name",
                "description": "description",
                "active": "active",
                "quest_type": "quest_type",
                "requirement_type": "requirement_type",
                "requirement_value": "requirement_value",
                "reward_xp": "reward_xp",
                "reward_multiplier": "reward_multiplier",
                "refresh_cycle": "refresh_cycle",
                "difficulty": "difficulty"
            }
            
            if field.lower() not in field_map:
                logging.error(f"Invalid field for update_quest: {field}")
                return False
                
            db_field = field_map[field.lower()]
            
            # Update the field
            update_query = f"""
            UPDATE quests
            SET {db_field} = $1
            WHERE id = $2 AND guild_id = $3
            RETURNING id
            """
            
            result = await conn.fetchval(update_query, value, quest_id, guild_id)
            return result is not None
            
    except Exception as e:
        logging.error(f"Error updating quest: {e}")
        return False

async def update_quest(quest_id: int, guild_id: str, field: str, value: Any) -> bool:
    """
    Update a field in a quest
    
    Parameters:
    - quest_id: Quest ID
    - guild_id: Guild ID (for verification)
    - field: Field to update
    - value: New value
    
    Returns:
    - bool: True if successful
    """
    result = await safe_db_operation("update_quest_internal", quest_id, guild_id, field, value)
    
    # Invalidate caches if successful
    if result:
        if quest_id in quest_cache:
            del quest_cache[quest_id]
        if guild_id in active_quests_cache:
            del active_quests_cache[guild_id]
    
    return result

async def _delete_quest_internal(quest_id: int, guild_id: str) -> bool:
    """Internal function to delete a quest"""
    try:
        async with get_connection() as conn:
            async with conn.transaction():
                # First delete related user_quests records
                delete_user_quest_query = """
                DELETE FROM user_quests
                WHERE quest_id = $1 AND guild_id = $2
                """
                await conn.execute(delete_user_quest_query, quest_id, guild_id)
                
                # Then delete the quest itself
                delete_quest_query = """
                DELETE FROM quests
                WHERE id = $1 AND guild_id = $2
                RETURNING id
                """
                result = await conn.fetchval(delete_quest_query, quest_id, guild_id)
                return result is not None
                
    except Exception as e:
        logging.error(f"Error deleting quest: {e}")
        return False

async def delete_quest(quest_id: int, guild_id: str) -> bool:
    """
    Delete a quest and all related user progress
    
    Parameters:
    - quest_id: Quest ID
    - guild_id: Guild ID (for verification)
    
    Returns:
    - bool: True if successful
    """
    result = await safe_db_operation("delete_quest_internal", quest_id, guild_id)
    
    # Invalidate caches if successful
    if result:
        if quest_id in quest_cache:
            del quest_cache[quest_id]
        if guild_id in active_quests_cache:
            del active_quests_cache[guild_id]
            
        # Clear all user quest caches for this guild (since we don't know which users had this quest)
        for key in list(user_quest_cache.keys()):
            if key[0] == guild_id:
                del user_quest_cache[key]
        for key in list(user_quest_stats_cache.keys()):
            if key[0] == guild_id:
                del user_quest_stats_cache[key]
    
    return result

async def _get_guild_active_quests_internal(guild_id: str, quest_type: str = None) -> List[Dict]:
    """Internal function to get active quests for a guild"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT id, name, description, quest_type, requirement_type,
                   requirement_value, reward_xp, reward_multiplier, active,
                   refresh_cycle, difficulty, created_at
            FROM quests
            WHERE guild_id = $1 AND active = TRUE
            """
            
            # Add quest_type filter if provided
            if quest_type:
                query += " AND quest_type = $2"
                params = [guild_id, quest_type]
            else:
                params = [guild_id]
                
            query += " ORDER BY quest_type, difficulty"
            
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
            
    except Exception as e:
        logging.error(f"Error getting guild active quests: {e}")
        return []

async def get_guild_active_quests(guild_id: str, quest_type: str = None) -> List[Dict]:
    """
    Get all active quests for a guild
    
    Parameters:
    - guild_id: Guild ID
    - quest_type: Optional filter for specific quest types
    
    Returns:
    - List of quest dictionaries
    """
    # Use different cache keys based on whether we're filtering by quest_type
    cache_key = f"{guild_id}_{quest_type}" if quest_type else guild_id
    
    # Check cache first
    cached_quests = _get_from_cache(active_quests_cache, cache_key)
    if cached_quests is not None:
        return cached_quests
    
    # Get from database and cache the result
    quests = await safe_db_operation("get_guild_active_quests_internal", guild_id, quest_type)
    
    if quests is not None:
        _set_in_cache(active_quests_cache, cache_key, quests)
    
    return quests if quests is not None else []

async def _mark_quests_inactive_internal(guild_id: str, quest_type: str = None) -> bool:
    """Internal function to mark quests as inactive"""
    try:
        async with get_connection() as conn:
            # Base query
            query = """
            UPDATE quests
            SET active = FALSE
            WHERE guild_id = $1 AND active = TRUE
            """
            
            params = [guild_id]
            
            # Add quest_type filter if provided
            if quest_type:
                query += " AND quest_type = $2"
                params.append(quest_type)
                
            await conn.execute(query, *params)
            return True
            
    except Exception as e:
        logging.error(f"Error marking quests inactive: {e}")
        return False

async def mark_quests_inactive(guild_id: str, quest_type: str = None) -> bool:
    """
    Mark quests as inactive
    
    Parameters:
    - guild_id: Guild ID
    - quest_type: Optional type to filter ('daily', 'weekly', etc.)
    
    Returns:
    - bool: True if successful
    """
    result = await safe_db_operation("mark_quests_inactive_internal", guild_id, quest_type)
    
    # Invalidate caches if successful
    if result:
        # Clear all related cache keys
        if guild_id in active_quests_cache:
            del active_quests_cache[guild_id]
            
        # Also clear any type-specific keys
        if quest_type:
            type_key = f"{guild_id}_{quest_type}"
            if type_key in active_quests_cache:
                del active_quests_cache[type_key]
    
    return result

async def _get_user_quest_progress_internal(guild_id: str, user_id: str, quest_id: int) -> Tuple[int, bool, Optional[datetime]]:
    """Internal function to get user quest progress"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT progress, completed, completed_at, expires_at
            FROM user_quests
            WHERE guild_id = $1 AND user_id = $2 AND quest_id = $3
            """
            row = await conn.fetchrow(query, guild_id, user_id, quest_id)
            
            if row:
                # Check if quest has expired
                if row['expires_at'] and row['expires_at'] < datetime.now() and not row['completed']:
                    return row['progress'], False, None
                return row['progress'], row['completed'], row['completed_at']
            
            # No progress record yet
            return 0, False, None
            
    except Exception as e:
        logging.error(f"Error getting quest progress: {e}")
        return 0, False, None

async def get_user_quest_progress(guild_id: str, user_id: str, quest_id: int) -> Tuple[int, int, bool, Optional[datetime]]:
    """
    Get a user's progress for a specific quest
    
    Returns:
    - Tuple of (achievement_progress, quest_specific_progress, completed, completed_at)
    """
    # Implement your function to return both progress types
    try:
        async with get_connection() as conn:
            query = """
            SELECT progress, quest_specific_progress, completed, completed_at, expires_at
            FROM user_quests
            WHERE guild_id = $1 AND user_id = $2 AND quest_id = $3
            """
            row = await conn.fetchrow(query, guild_id, user_id, quest_id)
            
            if row:
                # Check if quest has expired
                if row['expires_at'] and row['expires_at'] < datetime.now() and not row['completed']:
                    return row['progress'], row['quest_specific_progress'], False, None
                return row['progress'], row['quest_specific_progress'], row['completed'], row['completed_at']
            
            # No progress record yet
            return 0, 0, False, None
            
    except Exception as e:
        logging.error(f"Error getting quest progress: {e}")
        return 0, 0, False, None

async def check_quest_progress(guild_id: str, user_id: str, counter_type: str, counter_value: int, session_value: int = None) -> List[Dict]:
    """
    Check and update progress on all active quests for a user based on a counter
    
    Parameters:
    - guild_id: Guild ID
    - user_id: User ID
    - counter_type: Type of counter being updated
    - counter_value: New counter value
    - session_value: For voice quests, the value from just this session (optional)
    
    Returns:
    - List of newly completed quests
    """
    try:
        # Validate counter_value
        if counter_value is None:
            logging.error(f"Invalid counter_value (None) for {counter_type}")
            return []
            
        logging.debug(f"Checking quest progress for {counter_type}, counter_value={counter_value}, session_value={session_value}")
        
        # Get all active quests for this guild that match the counter type
        async with get_connection() as conn:
            quest_query = """
            SELECT id, name, description, requirement_type, requirement_value, reward_xp, reward_multiplier, quest_type
            FROM quests
            WHERE guild_id = $1 AND active = TRUE AND requirement_type = $2
            """
            quests = await conn.fetch(quest_query, guild_id, counter_type)
            
            if not quests:
                logging.debug(f"No active quests found for {counter_type} in guild {guild_id}")
                return []
                
            logging.debug(f"Found {len(quests)} active quests for {counter_type}")
                
            # Check each quest for progress/completion
            newly_completed = []
            
            for quest in quests:
                quest_id = quest['id']
                quest_name = quest['name']
                quest_type = quest['quest_type']
                
                logging.debug(f"Processing quest {quest_name} (ID: {quest_id}, type: {quest_type})")
                
                # Get current progress
                progress_query = """
                SELECT progress, quest_specific_progress, completed
                FROM user_quests
                WHERE guild_id = $1 AND user_id = $2 AND quest_id = $3
                """
                progress_row = await conn.fetchrow(progress_query, guild_id, user_id, quest_id)
                
                if progress_row:
                    progress = progress_row['progress']
                    quest_specific_progress = progress_row['quest_specific_progress']
                    completed = progress_row['completed']
                    logging.debug(f"Existing progress for quest {quest_name}: {quest_specific_progress}/{quest['requirement_value']}")
                else:
                    progress = 0
                    quest_specific_progress = 0
                    completed = False
                    logging.debug(f"No existing progress for quest {quest_name}, starting at 0")
                
                # Skip if already completed
                if completed:
                    logging.debug(f"Quest {quest_name} already completed, skipping")
                    continue
                    
                # Ensure requirement_value is valid
                if quest['requirement_value'] is None:
                    logging.error(f"Invalid requirement_value (None) for quest {quest_id}")
                    continue
                
                # Calculate the progress increment based on the counter type
                quest_progress_increment = 1  # Default increment for most actions
                
                # Special handling for voice quests
                if counter_type == "voice_time_seconds":
                    # Determine if we're using the session value or calculating from total
                    if session_value is not None:
                        # Use the session value directly (seconds from this session only)
                        quest_progress_increment = session_value
                        logging.debug(f"Using session_value directly: {quest_progress_increment} seconds")
                    else:
                        # Use the difference between the new counter value and the previous progress
                        if progress > 0:
                            latest_contribution = counter_value - progress
                            if latest_contribution > 0:
                                quest_progress_increment = latest_contribution
                                logging.debug(f"Calculated increment from counter difference: {quest_progress_increment} seconds")
                            else:
                                logging.warning(f"Negative or zero contribution calculated: {latest_contribution}")
                                quest_progress_increment = 0
                        else:
                            # First time tracking this quest, use the full counter value
                            quest_progress_increment = counter_value
                            logging.debug(f"First tracking for quest, using full counter: {quest_progress_increment} seconds")
                
                # Update the quest-specific progress based on the calculated increment
                new_progress = quest_specific_progress + quest_progress_increment
                logging.debug(f"Updating quest progress from {quest_specific_progress} to {new_progress} (requirement: {quest['requirement_value']})")
                
                # Check if this update will complete the quest
                will_complete = new_progress >= quest['requirement_value']
                if will_complete:
                    logging.info(f"Quest '{quest_name}' will be completed with this update!")
                
                # Update the progress
                success = await _update_user_quest_progress_internal(
                    guild_id, user_id, quest_id, counter_value, quest_progress_increment, will_complete
                )
                
                # Log the result of the update
                if not success:
                    logging.error(f"Failed to update progress for quest {quest_id}")
                
                # If newly completed, add to list
                if will_complete and success:
                    newly_completed.append({
                        "id": quest_id,
                        "name": quest_name,
                        "description": quest['description'],
                        "reward_xp": quest['reward_xp'],
                        "reward_multiplier": quest['reward_multiplier']
                    })
            
            # Invalidate caches
            cache_key = (guild_id, user_id)
            if cache_key in user_quest_cache:
                del user_quest_cache[cache_key]
                logging.debug(f"Invalidated user_quest_cache for {user_id}")
            if cache_key in user_quest_stats_cache:
                del user_quest_stats_cache[cache_key]
                logging.debug(f"Invalidated user_quest_stats_cache for {user_id}")
            
            if newly_completed:
                logging.info(f"User {user_id} completed {len(newly_completed)} quests for {counter_type}")
            return newly_completed
                
    except Exception as e:
        logging.error(f"Error checking quest progress: {e}", exc_info=True)
        return []

async def _update_user_quest_progress_internal(guild_id, user_id, quest_id, 
                                            achievement_progress, quest_progress_increment=1,
                                            completed=False):
    """Internal function to update user quest progress"""
    try:
        logging.debug(f"Updating quest progress for user {user_id}, quest {quest_id}")
        logging.debug(f"Parameters: achievement_progress={achievement_progress}, increment={quest_progress_increment}, completed={completed}")
        
        async with get_connection() as conn:
            # Get the quest to determine expiration and type
            quest_query = """
            SELECT refresh_cycle, quest_type, requirement_type, requirement_value
            FROM quests
            WHERE id = $1 AND guild_id = $2
            """
            quest = await conn.fetchrow(quest_query, quest_id, guild_id)
            
            if not quest:
                logging.error(f"Quest {quest_id} not found for guild {guild_id}")
                return False
            
            logging.debug(f"Quest details - type={quest['quest_type']}, requirement={quest['requirement_type']}:{quest['requirement_value']}")
            
            # First check if user already has progress on this quest
            check_query = """
            SELECT quest_specific_progress, completed
            FROM user_quests
            WHERE guild_id = $1 AND user_id = $2 AND quest_id = $3
            """
            existing = await conn.fetchrow(check_query, guild_id, user_id, quest_id)
            
            # Calculate expiration time based on refresh cycle
            expires_at = None
            if quest['refresh_cycle'] == 'daily':
                expires_at = datetime.now() + timedelta(days=1)
            elif quest['refresh_cycle'] == 'weekly':
                expires_at = datetime.now() + timedelta(weeks=1)
            elif quest['refresh_cycle'] == 'monthly':
                expires_at = datetime.now() + timedelta(days=30)
            
            # Calculate quest-specific progress
            if existing:
                logging.debug(f"Existing record found - progress={existing['quest_specific_progress']}, completed={existing['completed']}")
                
                # Only increment if not already completed
                if not existing['completed']:
                    new_progress = existing['quest_specific_progress'] + quest_progress_increment
                    logging.debug(f"Updating progress from {existing['quest_specific_progress']} to {new_progress}")
                    
                    # Check if the quest should be completed
                    if new_progress >= quest['requirement_value']:
                        completed = True
                        logging.info(f"Quest will be marked as completed (progress={new_progress}/{quest['requirement_value']})")
                else:
                    # Already completed, don't change progress
                    new_progress = existing['quest_specific_progress']
                    logging.debug(f"Quest already completed, keeping progress at {new_progress}")
            else:
                # New record, start with increment
                new_progress = quest_progress_increment
                logging.debug(f"New record, starting with progress={new_progress}")
                
                if new_progress >= quest['requirement_value']:
                    completed = True
                    logging.info(f"Quest will be marked as completed immediately (progress={new_progress}/{quest['requirement_value']})")
            
            # Set completed_at if completing the quest
            completed_at = 'CURRENT_TIMESTAMP' if completed and not (existing and existing['completed']) else 'NULL'
            
            # Insert or update progress
            query = f"""
            INSERT INTO user_quests 
                (guild_id, user_id, quest_id, progress, quest_specific_progress, completed, completed_at, expires_at)
            VALUES 
                ($1, $2, $3, $4, $5, $6, {completed_at}, $7)
            ON CONFLICT (guild_id, user_id, quest_id) 
            DO UPDATE SET 
                progress = $4,
                quest_specific_progress = $5,
                completed = $6,
                completed_at = CASE WHEN 
                    user_quests.completed = false AND $6 = true 
                    THEN CURRENT_TIMESTAMP 
                    ELSE user_quests.completed_at 
                END,
                expires_at = $7
            RETURNING id
            """
            
            result = await conn.fetchval(query, guild_id, user_id, quest_id, 
                                      achievement_progress, new_progress, completed, expires_at)
            
            success = result is not None
            logging.debug(f"Database update {'successful' if success else 'failed'}")
            return success
                
    except Exception as e:
        logging.error(f"Error updating quest progress: {e}", exc_info=True)
        return False

async def update_user_quest_progress(guild_id: str, user_id: str, quest_id: int, 
                                    progress: int, completed: bool = False) -> bool:
    """
    Update a user's progress on a quest
    
    Parameters:
    - guild_id: Guild ID
    - user_id: User ID
    - quest_id: Quest ID
    - progress: Current progress value
    - completed: Whether the quest is completed
    
    Returns:
    - bool: True if successful
    """
    result = await safe_db_operation(
        "_update_user_quest_progress_internal", 
        guild_id, user_id, quest_id, progress, completed
    )
    
    # Invalidate user quest caches if successful
    if result:
        cache_key = (guild_id, user_id)
        if cache_key in user_quest_cache:
            del user_quest_cache[cache_key]
        if cache_key in user_quest_stats_cache:
            del user_quest_stats_cache[cache_key]
    
    return result

async def _get_user_active_quests_internal(guild_id: str, user_id: str) -> List[Dict]:
    """Internal function to get active quests for a user"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT q.id, q.name, q.description, q.quest_type, q.requirement_type,
                   q.requirement_value, q.reward_xp, q.reward_multiplier, 
                   q.difficulty, q.refresh_cycle,
                   COALESCE(uq.progress, 0) as progress,
                   COALESCE(uq.quest_specific_progress, 0) as quest_specific_progress,  
                   COALESCE(uq.completed, false) as completed,
                   uq.completed_at, uq.expires_at
            FROM quests q
            LEFT JOIN user_quests uq ON 
                q.id = uq.quest_id AND 
                uq.guild_id = $1 AND 
                uq.user_id = $2
            WHERE q.guild_id = $1 AND q.active = TRUE
                AND (uq.expires_at IS NULL OR uq.expires_at > CURRENT_TIMESTAMP OR uq.completed = TRUE)
            ORDER BY q.quest_type, q.difficulty
            """
            
            rows = await conn.fetch(query, guild_id, user_id)
            return [dict(row) for row in rows]
            
    except Exception as e:
        logging.error(f"Error getting user active quests: {e}")
        return []

async def get_user_active_quests(guild_id: str, user_id: str) -> List[Dict]:
    """
    Get all active quests for a user with progress
    
    Parameters:
    - guild_id: Guild ID
    - user_id: User ID
    
    Returns:
    - List of quest dictionaries with progress
    """
    cache_key = (guild_id, user_id)
    
    # Check cache first
    cached_quests = _get_from_cache(user_quest_cache, cache_key)
    if cached_quests is not None:
        return cached_quests
    
    # Get from database and cache the result
    quests = await safe_db_operation("get_user_active_quests_internal", guild_id, user_id)
    
    if quests is not None:
        _set_in_cache(user_quest_cache, cache_key, quests)
    
    return quests if quests is not None else []

async def _get_user_quest_stats_internal(guild_id: str, user_id: str) -> Dict:
    """Internal function to get user quest statistics"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT 
                COUNT(CASE WHEN uq.completed = TRUE THEN 1 END) as completed_count,
                COUNT(CASE WHEN uq.completed = FALSE AND 
                          (uq.expires_at IS NULL OR uq.expires_at > CURRENT_TIMESTAMP) 
                          THEN 1 END) as active_count,
                COUNT(CASE WHEN q.quest_type = 'daily' AND uq.completed = TRUE THEN 1 END) as daily_completed,
                COUNT(CASE WHEN q.quest_type = 'weekly' AND uq.completed = TRUE THEN 1 END) as weekly_completed,
                COUNT(CASE WHEN q.quest_type = 'special' AND uq.completed = TRUE THEN 1 END) as special_completed,
                SUM(CASE WHEN uq.completed = TRUE THEN q.reward_xp ELSE 0 END) as total_xp_earned,
                MAX(uq.completed_at) as last_completed
            FROM user_quests uq
            JOIN quests q ON uq.quest_id = q.id
            WHERE uq.guild_id = $1 AND uq.user_id = $2
            """
            row = await conn.fetchrow(query, guild_id, user_id)
            
            if row:
                return dict(row)
            
            # Return default values if no quests found
            return {
                'completed_count': 0,
                'active_count': 0,
                'daily_completed': 0,
                'weekly_completed': 0,
                'special_completed': 0,
                'total_xp_earned': 0,
                'last_completed': None
            }
            
    except Exception as e:
        logging.error(f"Error getting user quest stats: {e}")
        return {
            'completed_count': 0,
            'active_count': 0,
            'daily_completed': 0,
            'weekly_completed': 0,
            'special_completed': 0,
            'total_xp_earned': 0,
            'last_completed': None
        }

async def get_user_quest_stats(guild_id: str, user_id: str) -> Dict:
    """
    Get quest completion statistics for a user
    
    Parameters:
    - guild_id: Guild ID
    - user_id: User ID
    
    Returns:
    - Dictionary with quest statistics
    """
    cache_key = (guild_id, user_id)
    
    # Check cache first
    cached_stats = _get_from_cache(user_quest_stats_cache, cache_key)
    if cached_stats is not None:
        return cached_stats
    
    # Get from database and cache the result
    stats = await safe_db_operation("get_user_quest_stats_internal", guild_id, user_id)
    
    if stats is not None:
        _set_in_cache(user_quest_stats_cache, cache_key, stats)
    
    return stats

async def award_quest_rewards(guild_id: str, user_id: str, quest_id: int, member) -> bool:
    """
    Award rewards for completing a quest
    
    Parameters:
    - guild_id: Guild ID
    - user_id: User ID
    - quest_id: Quest ID
    - member: Discord member object for XP awarding
    
    Returns:
    - bool: True if rewards were awarded
    """
    try:
        # Get quest details
        quest = await get_quest(quest_id)
        if not quest:
            return False
            
        # Get progress to verify completion
        # Updated to handle the new return value format
        achievement_progress, quest_specific_progress, completed, completed_at = await get_user_quest_progress(guild_id, user_id, quest_id)
        if not completed:
            return False
            
        # Award XP (use the existing award_xp_without_event_multiplier function)
        from modules.levels import award_xp_without_event_multiplier
        await award_xp_without_event_multiplier(guild_id, user_id, quest['reward_xp'], member)
        
        logging.info(f"Awarded {quest['reward_xp']} XP to {member.name} for completing quest: {quest['name']}")
        return True
            
    except Exception as e:
        logging.error(f"Error awarding quest rewards: {e}")
        return False