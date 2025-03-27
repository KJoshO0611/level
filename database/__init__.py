"""
Database package for the Discord Bot Leveling System.
This package provides database operations and caching for all bot features.
"""
import logging
from typing import Dict, List, Tuple, Optional, Any

# Import from submodules
from .core import (
    init_db,
    close_db,
    get_health_stats,
    pool
)

from .cache import (
    CACHE_TTL,
    MAX_CACHE_SIZE,
    invalidate_user_cache,
    invalidate_guild_cache,
    invalidate_achievement_caches,
    log_achievement_cache_stats,
    init_achievement_caches
)

from .users import (
    get_or_create_user_level,
    update_user_xp,
    get_user_levels,
    get_user_rank,
    get_leaderboard,
    get_bulk_user_levels,
)

from .config import (
    set_level_up_channel,
    get_level_up_channel,
    create_level_role,
    get_level_roles,
    delete_level_role,
    set_channel_boost_db,
    remove_channel_boost_db,
    load_channel_boosts,
    apply_channel_boost,
    CHANNEL_XP_BOOSTS,
    get_server_xp_settings,
    update_server_xp_settings,
    reset_server_xp_settings,
    set_achievement_channel,
    get_achievement_channel,
    set_quest_channel,
    get_quest_channel
)

from .events import (
    create_xp_boost_event,
    get_active_xp_boost_events,
    get_upcoming_xp_boost_events,
    delete_xp_boost_event,
    get_xp_boost_event,
    get_event_xp_multiplier
)

from .achievements import (
    update_activity_counter_db,
    get_user_achievements_db, 
    create_achievement_db,
    get_achievement_leaderboard_db,
    get_achievement_stats_db,
    get_guild_achievements, 
    get_achievement_by_id,
    update_achievement,
    delete_achievement,
    get_user_selected_title_db,
    set_user_selected_title_db
)

from .backgrounds import (
    set_user_background,
    get_user_background,
    remove_user_background,
    get_all_user_backgrounds,
    get_guild_backgrounds
)

from .utils import (
    safe_db_operation,
    retry_pending_operations
)

from .quests import (
    create_quest,
    get_quest,
    update_quest,
    delete_quest,
    get_guild_active_quests,
    mark_quests_inactive,
    get_user_quest_progress,
    update_user_quest_progress,
    get_user_active_quests,
    get_user_quest_stats,
    check_quest_progress,
    award_quest_rewards,
)

# Export all public functions
__all__ = [
    # Core
    'init_db', 'close_db', 'get_health_stats', 'pool',
    
    # Cache
    'invalidate_user_cache', 'invalidate_guild_cache', 'invalidate_achievement_caches',
    'log_achievement_cache_stats', 'init_achievement_caches',
    
    # Users and Leveling
    'get_or_create_user_level', 'update_user_xp', 'get_user_levels', 'get_user_rank',
    'get_leaderboard', 'get_bulk_user_levels',
    
    # Config
    'set_level_up_channel', 'get_level_up_channel', 'create_level_role', 'get_level_roles',
    'delete_level_role', 'set_channel_boost_db', 'remove_channel_boost_db', 'load_channel_boosts',
    'apply_channel_boost', 'CHANNEL_XP_BOOSTS', 'get_server_xp_settings', 'update_server_xp_settings',
    'reset_server_xp_settings', 'set_achievement_channel', 'get_achievement_channel',
    'set_quest_channel', 'get_quest_channel',
    
    # Events
    'create_xp_boost_event', 'get_active_xp_boost_events', 'get_upcoming_xp_boost_events',
    'delete_xp_boost_event', 'get_xp_boost_event', 'get_event_xp_multiplier',
    
    # Achievements
    'update_activity_counter_db', 'get_user_achievements_db', 'create_achievement_db',
    'get_achievement_leaderboard_db', 'get_achievement_stats_db', 'get_guild_achievements',
    'get_achievement_by_id', 'update_achievement', 'delete_achievement',
    'get_user_selected_title_db', 'set_user_selected_title_db',
    
    # Backgrounds
    'set_user_background', 'get_user_background', 'remove_user_background',
    'get_all_user_backgrounds', 'get_guild_backgrounds',
    
    # Utils
    'safe_db_operation', 'retry_pending_operations'
]

# Add these to __all__ list:
__all__.extend([
    # Quests
    'create_quest', 'get_quest', 'update_quest', 'delete_quest',
    'get_guild_active_quests', 'mark_quests_inactive',
    'get_user_quest_progress', 'update_user_quest_progress',
    'get_user_active_quests', 'get_user_quest_stats',
    'check_quest_progress', 'award_quest_rewards'
])