"""
Cache management for database operations.
"""
import time
import logging
from typing import Dict, Tuple, Any, Optional

from utils.memory_cache import MemoryAwareCache

# Cache constants
CACHE_TTL = 300  # 5 minutes
MAX_CACHE_SIZE = 1000

# Simple cache dictionaries
level_cache = {}  # {(guild_id, user_id): (xp, level, last_xp_time, last_role, timestamp)}
config_cache = {}  # {guild_id: (level_up_channel, timestamp)}
role_cache = {}    # {guild_id: ({level: role_id}, timestamp)}
server_xp_settings_cache = {}  # {guild_id: (settings_dict, timestamp)}
active_events_cache = {}   # {guild_id: (events_list, timestamp)}
upcoming_events_cache = {} # {guild_id: (events_list, timestamp)}
event_details_cache = {}   # {event_id: (event_dict, timestamp)}

# Memory-aware caches for achievements
ACHIEVEMENT_CACHE = MemoryAwareCache(
    name="achievement_cache", 
    maxsize=100,  # 100 guild achievement sets
    max_memory_mb=20,
    ttl=600  # 10 minutes
)

USER_ACHIEVEMENT_CACHE = MemoryAwareCache(
    name="user_achievement_cache", 
    maxsize=1000,
    max_memory_mb=50,
    ttl=120  # 2 minutes
)

ACHIEVEMENT_BY_ID_CACHE = MemoryAwareCache(
    name="achievement_by_id_cache", 
    maxsize=500,
    max_memory_mb=10,
    ttl=300  # 5 minutes
)

LEADERBOARD_CACHE = MemoryAwareCache(
    name="achievement_leaderboard", 
    maxsize=50,
    max_memory_mb=10,
    ttl=60  # 1 minute
)

ACHIEVEMENT_STATS_CACHE = MemoryAwareCache(
    name="achievement_stats", 
    maxsize=100,
    max_memory_mb=10,
    ttl=300  # 5 minutes
)

RELEVANT_ACHIEVEMENTS_CACHE = MemoryAwareCache(
    name="relevant_achievements", 
    maxsize=200,
    max_memory_mb=15,
    ttl=120  # 2 minutes
)

def _get_from_cache(cache: Dict[Any, Tuple], key: Any) -> Optional[Any]:
    """Get an item from cache if it exists and is not expired"""
    if key in cache:
        value, timestamp = cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return value
        # If expired, remove from cache
        del cache[key]
    return None

def _set_in_cache(cache: Dict[Any, Tuple], key: Any, value: Any):
    """Set an item in cache with current timestamp"""
    # If cache is full, remove oldest items
    if len(cache) >= MAX_CACHE_SIZE:
        # Sort by timestamp and remove oldest 10%
        items_to_remove = sorted(
            cache.items(), 
            key=lambda x: x[1][1]
        )[:MAX_CACHE_SIZE // 10]
        
        for key_to_remove, _ in items_to_remove:
            del cache[key_to_remove]
    
    cache[key] = (value, time.time())

def invalidate_user_cache(guild_id: str, user_id: str):
    """Invalidate cache for a specific user"""
    cache_key = (guild_id, user_id)
    if cache_key in level_cache:
        del level_cache[cache_key]
        logging.debug(f"Cache invalidated for user {user_id} in guild {guild_id}")

def invalidate_guild_cache(guild_id: str):
    """Invalidate all cache for a specific guild"""
    # Remove from config cache
    if guild_id in config_cache:
        del config_cache[guild_id]
    
    # Remove from role cache
    if guild_id in role_cache:
        del role_cache[guild_id]
    
    # Remove matching users from level cache
    keys_to_remove = [key for key in level_cache.keys() if key[0] == guild_id]
    for key in keys_to_remove:
        del level_cache[key]
    
    # Remove from server XP settings cache
    if guild_id in server_xp_settings_cache:
        del server_xp_settings_cache[guild_id]
        
    # Remove from XP boost event caches
    if guild_id in active_events_cache:
        del active_events_cache[guild_id]
    if guild_id in upcoming_events_cache:
        del upcoming_events_cache[guild_id]
    
    logging.debug(f"Cache invalidated for guild {guild_id}")

def invalidate_achievement_caches(guild_id: str, user_id: str = None, achievement_id: int = None):
    """
    Invalidate achievement caches when data changes
    
    Parameters:
    - guild_id: The guild ID to invalidate
    - user_id: Optional user ID to invalidate
    - achievement_id: Optional specific achievement ID to invalidate
    """
    # Always invalidate guild achievements and stats
    ACHIEVEMENT_CACHE.invalidate(guild_id)
    ACHIEVEMENT_STATS_CACHE.invalidate(guild_id)
    
    # Invalidate specific achievement if provided
    if achievement_id:
        ACHIEVEMENT_BY_ID_CACHE.invalidate(f"{guild_id}:{achievement_id}")
        
        # Also invalidate any relevant achievements caches that might contain this achievement
        for key in list(RELEVANT_ACHIEVEMENTS_CACHE.cache.keys()):
            if key.startswith(f"{guild_id}:"):
                RELEVANT_ACHIEVEMENTS_CACHE.invalidate(key)
    
    # Invalidate all leaderboard cache entries for this guild
    for key in list(LEADERBOARD_CACHE.cache.keys()):
        if key.startswith(f"{guild_id}:"):
            LEADERBOARD_CACHE.invalidate(key)
    
    # If user is specified, invalidate their cache
    if user_id:
        USER_ACHIEVEMENT_CACHE.invalidate(f"{guild_id}:{user_id}")

def log_achievement_cache_stats():
    """Log cache hit rates and memory usage for achievement caches"""
    caches = [
        ACHIEVEMENT_CACHE,
        USER_ACHIEVEMENT_CACHE,
        ACHIEVEMENT_BY_ID_CACHE,
        LEADERBOARD_CACHE,
        ACHIEVEMENT_STATS_CACHE,
        RELEVANT_ACHIEVEMENTS_CACHE
    ]
    
    for cache in caches:
        stats = cache.stats()
        hit_ratio = stats['hit_ratio'] * 100
        logging.info(f"{stats['name']}: {hit_ratio:.1f}% hit rate, {stats['memory_mb']:.2f}MB used, {stats['items']}/{stats['max_items']} items")

def init_achievement_caches():
    """Initialize achievement caches"""
    logging.info("Initializing achievement caches")
    ACHIEVEMENT_CACHE
    USER_ACHIEVEMENT_CACHE
    ACHIEVEMENT_BY_ID_CACHE
    LEADERBOARD_CACHE
    ACHIEVEMENT_STATS_CACHE
    RELEVANT_ACHIEVEMENTS_CACHE