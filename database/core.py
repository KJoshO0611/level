"""
Core database functionality for connection handling and health monitoring.
"""
import time
import asyncio
import logging
import random
from typing import Dict, List, Tuple, Optional, Any
import asyncpg
from contextlib import asynccontextmanager

from config import load_config

# Load configuration
config = load_config()
DATABASE = config["DATABASE"]

# Global variables
pool = None
db_lock = asyncio.Lock()
pending_operations = []

# Health monitoring constants
HEALTH_CHECK_INTERVAL = 60  # seconds
CONNECTION_TIMEOUT = 5  # seconds
MAX_CONSECUTIVE_FAILURES = 3

# Health status tracking
health_status = {
    "last_check_time": None,
    "consecutive_failures": 0,
    "is_healthy": True,
    "last_failure_reason": None,
    "last_recovery_time": None
}

async def init_db(bot):
    """Initialize the database connection pool and create tables"""
    global pool
    
    try:
        # Create connection pool with optimal settings
        pool = await asyncpg.create_pool(
            host=DATABASE["HOST"],
            database=DATABASE["NAME"],
            user=DATABASE["USER"],
            password=DATABASE["PASSWORD"],
            port=DATABASE["PORT"],
            min_size=5,        # Minimum connections in pool
            max_size=20,       # Maximum connections in pool
            max_inactive_connection_lifetime=300.0,  # Close inactive connections after 5 minutes
            command_timeout=60.0,  # Commands timeout after 60 seconds
            statement_cache_size=1000  # Cache size for prepared statements
        )
        
        bot.db = pool
        
        # Create tables
        await _create_tables(bot)

        # Run migrations
        from utils.database_migration import run_all_migrations
        await run_all_migrations(bot)

        # Load channel boosts
        from .config import load_channel_boosts
        await load_channel_boosts(bot)
        
        # Start the batch update processor
        from .utils import batch_update_processor
        asyncio.create_task(batch_update_processor())
        
        # Start health monitoring
        asyncio.create_task(health_check_loop(bot))
        
        logging.info("Database connection pool initialized successfully")
        return True
        
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        return False

@asynccontextmanager
async def get_connection():
    """Context manager for acquiring a connection from the pool"""
    global pool
    conn = None
    try:
        conn = await pool.acquire()
        yield conn
    finally:
        if conn:
            await pool.release(conn)

async def close_db():
    """Close the database connection pool gracefully"""
    global pool
    if pool:
        await pool.close()
        logging.info("Database connection pool closed")

async def _create_tables(bot):
    """Create necessary database tables if they don't exist"""
    # Transaction to ensure all tables are created or none are
    async with bot.db.acquire() as conn:
        async with conn.transaction():
            # Table for user leveling data
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS levels (
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    xp INTEGER NOT NULL,
                    level INTEGER NOT NULL,
                    last_xp_time DOUBLE PRECISION NOT NULL,
                    last_role TEXT,
                    total_messages INTEGER DEFAULT 0,
                    total_reactions INTEGER DEFAULT 0,
                    voice_time_seconds INTEGER DEFAULT 0,
                    commands_used INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            
            # Table for per-guild configuration
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS server_config (
                    guild_id TEXT PRIMARY KEY,
                    level_up_channel TEXT NOT NULL,
                    event_channel TEXT
                )
            ''')

            # Table for channel XP boosts
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS channel_boosts (
                    guild_id TEXT,
                    channel_id TEXT,
                    multiplier REAL,
                    PRIMARY KEY (guild_id, channel_id))
            ''')
            
            # Table for storing user roles
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS level_roles (
                    id SERIAL NOT NULL,
                    guild_id TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    role_id TEXT NOT NULL,
                    PRIMARY KEY (id),          
                    UNIQUE(guild_id, level))
            ''')

            # Table for server XP settings
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS server_xp_settings (
                    guild_id TEXT PRIMARY KEY,
                    min_xp INTEGER DEFAULT 10,
                    max_xp INTEGER DEFAULT 20,
                    cooldown INTEGER DEFAULT 60
                )
            ''')

            # Table for custom backgrounds
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS custom_backgrounds (
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    background_path TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            
            # Table for XP boost events
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS xp_boost_events (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    multiplier REAL NOT NULL,
                    start_time DOUBLE PRECISION NOT NULL,
                    end_time DOUBLE PRECISION NOT NULL,
                    created_by TEXT NOT NULL,
                    active BOOLEAN DEFAULT TRUE
                )
            ''')
            
            # Tables for achievements
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS achievements (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    requirement_type TEXT NOT NULL,
                    requirement_value INTEGER NOT NULL,
                    icon_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_achievements (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    achievement_id INTEGER REFERENCES achievements(id),
                    progress INTEGER NOT NULL DEFAULT 0,
                    completed BOOLEAN DEFAULT FALSE,
                    completed_at TIMESTAMP,
                    UNIQUE(guild_id, user_id, achievement_id)
                )
            ''')

            # Table for Quests
            await conn.execute('''CREATE TABLE IF NOT EXISTS quests (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    quest_type TEXT NOT NULL, -- 'daily', 'weekly', 'special'
                    requirement_type TEXT NOT NULL, -- 'messages', 'voice_time', 'reactions', etc.
                    requirement_value INTEGER NOT NULL,
                    reward_xp INTEGER NOT NULL,
                    reward_multiplier FLOAT DEFAULT 1.0,
                    icon_path TEXT,
                    active BOOLEAN DEFAULT TRUE,
                    refresh_cycle TEXT DEFAULT 'daily', -- 'daily', 'weekly', 'monthly', 'once'
                    difficulty TEXT DEFAULT 'normal', -- 'easy', 'normal', 'hard', 'expert'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Table for user quests
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_quests (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    quest_id INTEGER REFERENCES quests(id),
                    progress INTEGER DEFAULT 0,
                    completed BOOLEAN DEFAULT FALSE,
                    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    UNIQUE(guild_id, user_id, quest_id)
                )
            ''')

            # Create indexes for frequently queried columns
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_levels_guild_user ON levels(guild_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_levels_guild_level ON levels(guild_id, level);
                CREATE INDEX IF NOT EXISTS idx_xp_events_guild_time ON xp_boost_events(guild_id, start_time, end_time);
                CREATE INDEX IF NOT EXISTS idx_custom_backgrounds ON custom_backgrounds(guild_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_achievements_type ON achievements(requirement_type);
                CREATE INDEX IF NOT EXISTS idx_user_achievements_guild_user ON user_achievements(guild_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_user_achievements_completed ON user_achievements(completed);
                CREATE INDEX IF NOT EXISTS idx_user_quests_user ON user_quests(guild_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_user_quests_completed ON user_quests(completed);
                CREATE INDEX IF NOT EXISTS idx_quests_active ON quests(guild_id, active);
            ''')

async def health_check_loop(bot):
    """Periodically check database health"""
    global health_status
    
    while True:
        try:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            await check_database_health(bot)
        except Exception as e:
            logging.error(f"Error in health check loop: {e}")

async def check_database_health(bot):
    """Check if the database is responsive and healthy"""
    global health_status
    health_status["last_check_time"] = time.time()
    
    try:
        # Try a simple query with timeout
        async with asyncio.timeout(CONNECTION_TIMEOUT):
            async with get_connection() as conn:
                await conn.fetchval("SELECT 1")
        
        # If we got here, the database is healthy
        if health_status["consecutive_failures"] > 0:
            health_status["consecutive_failures"] = 0
            health_status["is_healthy"] = True
            health_status["last_recovery_time"] = time.time()
            health_status["last_failure_reason"] = None
            logging.info("Database connection recovered")
            
            # Process any pending operations
            from .utils import retry_pending_operations
            await retry_pending_operations()
        
    except Exception as e:
        # Database is not healthy
        health_status["consecutive_failures"] += 1
        health_status["is_healthy"] = False
        health_status["last_failure_reason"] = str(e)
        
        logging.warning(f"Database health check failed: {e}")
        
        # If we've failed too many times, try to repair
        if health_status["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
            logging.error("Multiple consecutive database failures. Attempting to repair connection...")
            await repair_database_connection(bot)

async def repair_database_connection(bot):
    """Attempt to repair the database connection"""
    global pool
    
    try:
        # Close the existing pool if it exists
        if pool:
            await pool.close()
            logging.info("Closed existing connection pool")
        
        # Recreate the connection pool
        success = await init_db(bot)
        
        if success:
            logging.info("Successfully repaired database connection")
            health_status["consecutive_failures"] = 0
            health_status["is_healthy"] = True
            health_status["last_recovery_time"] = time.time()
            
            # Process any pending operations
            from .utils import retry_pending_operations
            await retry_pending_operations()
        else:
            logging.error("Failed to repair database connection")
    
    except Exception as e:
        logging.error(f"Error repairing database connection: {e}")

async def get_health_stats():
    """Get database health statistics"""
    global health_status, pending_operations
    
    # Import here to avoid circular imports
    from .cache import (
        level_cache, config_cache, role_cache,
        ACHIEVEMENT_CACHE, USER_ACHIEVEMENT_CACHE
    )
    
    stats = {
        "is_healthy": health_status["is_healthy"],
        "consecutive_failures": health_status["consecutive_failures"],
        "last_check_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(health_status["last_check_time"])) if health_status["last_check_time"] else None,
        "last_failure_reason": health_status["last_failure_reason"],
        "last_recovery_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(health_status["last_recovery_time"])) if health_status["last_recovery_time"] else None,
        "pending_operations": len(pending_operations),
        "cache_stats": {
            "level_cache_size": len(level_cache),
            "config_cache_size": len(config_cache),
            "role_cache_size": len(role_cache),
            "achievement_cache_size": len(ACHIEVEMENT_CACHE.cache) if hasattr(ACHIEVEMENT_CACHE, 'cache') else 0,
            "user_achievement_cache_size": len(USER_ACHIEVEMENT_CACHE.cache) if hasattr(USER_ACHIEVEMENT_CACHE, 'cache') else 0
        }
    }
    
    return stats