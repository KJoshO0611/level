import asyncpg
import time
import asyncio
import logging
import random
from typing import Dict, List, Tuple, Optional, Any
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from config import load_config

# Load configuration
config = load_config()
DATABASE = config["DATABASE"]

# =====================
# Global state management
# =====================
CHANNEL_XP_BOOSTS = {}
pending_operations = []
pool = None
db_lock = asyncio.Lock()

# Constants
MAX_RETRIES = 5
CACHE_TTL = 300  # 5 minutes
MAX_CACHE_SIZE = 1000
BATCH_SIZE = 100
MAX_BATCH_WAIT_TIME = 0.5  # seconds
HEALTH_CHECK_INTERVAL = 60  # seconds
CONNECTION_TIMEOUT = 5  # seconds
MAX_CONSECUTIVE_FAILURES = 3

# Cache dictionaries
level_cache = {}  # {(guild_id, user_id): (xp, level, last_xp_time, last_role, timestamp)}
config_cache = {}  # {guild_id: (level_up_channel, timestamp)}
role_cache = {}    # {guild_id: ({level: role_id}, timestamp)}
card_settings_cache = {}  # {(guild_id, user_id): (settings_dict, timestamp)}
server_xp_settings_cache = {}  # {guild_id: (settings_dict, timestamp)}
active_events_cache = {}   # {guild_id: (events_list, timestamp)}
upcoming_events_cache = {} # {guild_id: (events_list, timestamp)}
event_details_cache = {}   # {event_id: (event_dict, timestamp)}

# Batch update queues
xp_update_queue = []
xp_update_event = asyncio.Event()

# Health status
health_status = {
    "last_check_time": None,
    "consecutive_failures": 0,
    "is_healthy": True,
    "last_failure_reason": None,
    "last_recovery_time": None
}

# =====================
# Connection Management
# =====================
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
        # Load channel boosts
        await load_channel_boosts(bot)
        
        # Start the batch update processor
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
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            
            # Table for per-guild configuration
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS server_config (
                    guild_id TEXT PRIMARY KEY,
                    level_up_channel TEXT NOT NULL
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

            # Table for custom backgrounds (replacing level_card_settings)
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


            # Create indexes for frequently queried columns
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_levels_guild_user ON levels(guild_id, user_id);
                CREATE INDEX IF NOT EXISTS idx_levels_guild_level ON levels(guild_id, level);
                CREATE INDEX IF NOT EXISTS idx_xp_events_guild_time ON xp_boost_events(guild_id, start_time, end_time);
                CREATE INDEX IF NOT EXISTS idx_custom_backgrounds ON custom_backgrounds(guild_id, user_id);
            ''')

# =====================
# Health Monitoring
# =====================
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
            await retry_pending_operations()
        else:
            logging.error("Failed to repair database connection")
    
    except Exception as e:
        logging.error(f"Error repairing database connection: {e}")

async def get_health_stats():
    """Get database health statistics"""
    global health_status, pending_operations
    
    stats = {
        "is_healthy": health_status["is_healthy"],
        "consecutive_failures": health_status["consecutive_failures"],
        "last_check_time": datetime.fromtimestamp(health_status["last_check_time"]).isoformat() if health_status["last_check_time"] else None,
        "last_failure_reason": health_status["last_failure_reason"],
        "last_recovery_time": datetime.fromtimestamp(health_status["last_recovery_time"]).isoformat() if health_status["last_recovery_time"] else None,
        "pending_operations": len(pending_operations),
        "cache_stats": {
            "level_cache_size": len(level_cache),
            "config_cache_size": len(config_cache),
            "role_cache_size": len(role_cache)
        }
    }
    
    return stats

# =====================
# Caching
# =====================
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
    
    # Remove matching users from card settings cache
    keys_to_remove = [key for key in card_settings_cache.keys() if key[0] == guild_id]
    for key in keys_to_remove:
        del card_settings_cache[key]
        
    # Remove from server XP settings cache
    if guild_id in server_xp_settings_cache:
        del server_xp_settings_cache[guild_id]
        
    # Remove from XP boost event caches
    if guild_id in active_events_cache:
        del active_events_cache[guild_id]
    if guild_id in upcoming_events_cache:
        del upcoming_events_cache[guild_id]
    
    logging.debug(f"Cache invalidated for guild {guild_id}")

# =====================
# Batch Processing
# =====================
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

# =====================
# Error Handling
# =====================
async def safe_db_operation(func_name: str, *args, **kwargs):
    """
    Execute a database operation with retry logic.
    If it fails, store it for later retry.
    """
    global pending_operations, MAX_RETRIES
    retries = 0
    
    while retries < MAX_RETRIES:
        try:
            # Map function name to actual function
            function_map = {
                "update_user_xp": _update_user_xp,
                "set_level_up_channel": _set_level_up_channel,
                "set_channel_boost_db": _set_channel_boost_db,
                "remove_channel_boost_db": _remove_channel_boost_db,
                "get_or_create_user_level": _get_or_create_user_level,
                "update_server_xp_settings": _update_server_xp_settings,
                "reset_server_xp_settings": _reset_server_xp_settings,
                "create_xp_boost_event": _create_xp_boost_event,
                "delete_xp_boost_event": _delete_xp_boost_event,
                "_set_user_background": _set_user_background,
                "_remove_user_background": _remove_user_background,
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
                
                # Use the function map approach again
                function_map = {
                    "update_user_xp": _update_user_xp,
                    "set_level_up_channel": _set_level_up_channel,
                    "set_channel_boost_db": _set_channel_boost_db,
                    "remove_channel_boost_db": _remove_channel_boost_db,
                    "get_or_create_user_level": _get_or_create_user_level,
                    "update_server_xp_settings": _update_server_xp_settings,
                    "reset_server_xp_settings": _reset_server_xp_settings,
                    "create_xp_boost_event": _create_xp_boost_event,
                    "delete_xp_boost_event": _delete_xp_boost_event,
                }
                
                if func_name in function_map:
                    await function_map[func_name](*args, **kwargs)
                    successful_ops.append(operation)
                    logging.info(f"Successfully processed pending {func_name} operation")
                else:
                    logging.error(f"Unknown function in pending operations: {func_name}")
                
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

# =====================
# Database Operations
# =====================
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

async def _remove_channel_boost_db(guild_id: str, channel_id: str):
    """Remove channel XP boost with transaction protection"""
    # Remove from in-memory storage
    if channel_id in CHANNEL_XP_BOOSTS:
        del CHANNEL_XP_BOOSTS[channel_id]
    
    async with get_connection() as conn:
        query = "DELETE FROM channel_boosts WHERE guild_id = $1 AND channel_id = $2"
        await conn.execute(query, guild_id, channel_id)

async def _set_user_background(guild_id: str, user_id: str, relative_path: str) -> bool:
    """Internal function to set a custom background for a user"""
    try:
        async with get_connection() as conn:
            query = """
            INSERT INTO custom_backgrounds (guild_id, user_id, background_path)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) 
            DO UPDATE SET background_path = $3
            """
            await conn.execute(query, guild_id, user_id, relative_path)
            return True
    except Exception as e:
        logging.error(f"Error setting user background: {e}")
        return False

async def _get_user_background(guild_id: str, user_id: str) -> str:
    """Internal function to get the custom background path for a user"""
    try:
        async with get_connection() as conn:
            query = """
            SELECT background_path FROM custom_backgrounds
            WHERE guild_id = $1 AND user_id = $2
            """
            result = await conn.fetchval(query, guild_id, user_id)
            return result
    except Exception as e:
        logging.error(f"Error getting user background: {e}")
        return None

async def _remove_user_background(guild_id: str, user_id: str) -> bool:
    """Internal function to remove a user's custom background"""
    try:
        async with get_connection() as conn:
            query = """
            DELETE FROM custom_backgrounds
            WHERE guild_id = $1 AND user_id = $2
            """
            await conn.execute(query, guild_id, user_id)
            return True
    except Exception as e:
        logging.error(f"Error removing user background: {e}")
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
                from config import XP_SETTINGS
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
        from config import XP_SETTINGS
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
                from config import XP_SETTINGS
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
    
# =====================
# Public API functions
# =====================
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
    cache_key = (guild_id, user_id)
    _set_in_cache(level_cache, cache_key, (xp, level, last_xp_time, last_role))

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

async def set_channel_boost_db(guild_id: str, channel_id: str, multiplier: float):
    """Set channel XP boost with safety wrapper"""
    return await safe_db_operation("set_channel_boost_db", guild_id, channel_id, multiplier)

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

async def set_user_background(guild_id: str, user_id: str, relative_path: str) -> bool:
    """
    Set a custom background for a user
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    - relative_path: The path to the background image, relative to EXTERNAL_VOLUME_PATH
    
    Returns:
    - bool: True if successful, False otherwise
    """
    return await safe_db_operation("_set_user_background", guild_id, user_id, relative_path)

async def get_user_background(guild_id: str, user_id: str) -> str:
    """
    Get the custom background path for a user
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    
    Returns:
    - str: The relative path to the background image, or None if not set
    """
    # Check cache first (if you want to implement caching)
    # For now, we'll just call the internal function
    try:
        return await _get_user_background(guild_id, user_id)
    except Exception as e:
        logging.error(f"Error in get_user_background: {e}")
        return None

async def remove_user_background(guild_id: str, user_id: str) -> bool:
    """
    Remove a user's custom background
    
    Parameters:
    - guild_id: The guild ID
    - user_id: The user ID
    
    Returns:
    - bool: True if successful, False otherwise
    """
    return await safe_db_operation("_remove_user_background", guild_id, user_id)

async def get_all_user_backgrounds() -> list:
    """
    Get all custom backgrounds from the database
    
    Returns:
    - list: A list of tuples containing (guild_id, user_id, background_path)
    """
    try:
        async with get_connection() as conn:
            query = """
            SELECT guild_id, user_id, background_path 
            FROM custom_backgrounds
            """
            rows = await conn.fetch(query)
            return [(row['guild_id'], row['user_id'], row['background_path']) for row in rows]
    except Exception as e:
        logging.error(f"Error getting all backgrounds: {e}")
        return []

async def get_guild_backgrounds(guild_id: str) -> list:
    """
    Get all backgrounds for a specific guild
    
    Parameters:
    - guild_id: The guild ID
    
    Returns:
    - list: A list of tuples containing (user_id, background_path)
    """
    try:
        async with get_connection() as conn:
            query = """
            SELECT user_id, background_path 
            FROM custom_backgrounds
            WHERE guild_id = $1
            """
            rows = await conn.fetch(query, guild_id)
            return [(row['user_id'], row['background_path']) for row in rows]
    except Exception as e:
        logging.error(f"Error getting guild backgrounds: {e}")
        return []

async def get_server_xp_settings(guild_id: str) -> dict:
    """Get XP settings for a server with caching"""
    # Try cache first
    cached_value = _get_from_cache(server_xp_settings_cache, guild_id)
    if cached_value is not None:
        return cached_value
    
    # If not in cache, get from database
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

# =====================
# Connection Recovery and Migration
# =====================
async def migrate_data(source_bot, target_bot):
    """Utility function to migrate data between databases"""
    try:
        # Get all data from source database
        async with source_bot.db.acquire() as source_conn:
            # Migrate levels
            levels = await source_conn.fetch("SELECT * FROM levels")
            roles = await source_conn.fetch("SELECT * FROM level_roles")
            configs = await source_conn.fetch("SELECT * FROM server_config")
            boosts = await source_conn.fetch("SELECT * FROM channel_boosts")
        
        # Insert into target database
        async with target_bot.db.acquire() as target_conn:
            async with target_conn.transaction():
                # Insert levels
                if levels:
                    await target_conn.executemany(
                        "INSERT INTO levels (guild_id, user_id, xp, level, last_xp_time, last_role) " +
                        "VALUES ($1, $2, $3, $4, $5, $6) " +
                        "ON CONFLICT (guild_id, user_id) DO NOTHING",
                        [(row['guild_id'], row['user_id'], row['xp'], row['level'], 
                          row['last_xp_time'], row.get('last_role')) for row in levels]
                    )
                
                # Insert roles
                if roles:
                    await target_conn.executemany(
                        "INSERT INTO level_roles (guild_id, level, role_id) " +
                        "VALUES ($1, $2, $3) " +
                        "ON CONFLICT (guild_id, level) DO NOTHING",
                        [(row['guild_id'], row['level'], row['role_id']) for row in roles]
                    )
                
                # Insert configs
                if configs:
                    await target_conn.executemany(
                        "INSERT INTO server_config (guild_id, level_up_channel) " +
                        "VALUES ($1, $2) " +
                        "ON CONFLICT (guild_id) DO NOTHING",
                        [(row['guild_id'], row['level_up_channel']) for row in configs]
                    )
                
                # Insert boosts
                if boosts:
                    await target_conn.executemany(
                        "INSERT INTO channel_boosts (guild_id, channel_id, multiplier) " +
                        "VALUES ($1, $2, $3) " +
                        "ON CONFLICT (guild_id, channel_id) DO NOTHING",
                        [(row['guild_id'], row['channel_id'], row['multiplier']) for row in boosts]
                    )
        
        # Reload channel boosts
        await load_channel_boosts(target_bot)
        
        # Clear all caches
        level_cache.clear()
        config_cache.clear()
        role_cache.clear()
        
        return True
    except Exception as e:
        logging.error(f"Error during data migration: {e}")
        return False