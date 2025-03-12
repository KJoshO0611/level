import asyncpg
import time
from config import load_config
import asyncio
import logging

config = load_config()
DATABASE = config["DATABASE"]
# Update config to include PostgreSQL connection info
# DB_PATH is replaced with connection parameters


# Dictionary to store channel XP boosts
CHANNEL_XP_BOOSTS = {}
pending_operations = []
MAX_RETRIES = 5
db_lock = asyncio.Lock()


async def init_db(bot):
    """Initialize the database connection and create tables if they don't exist"""
    # Connect to PostgreSQL
    bot.db = await asyncpg.create_pool(
        host=DATABASE["HOST"],
        database=DATABASE["NAME"],
        user=DATABASE["USER"],
        password=DATABASE["PASSWORD"],
        port=DATABASE["PORT"]
    )
    
    # Table for user leveling data, stored per guild
    await bot.db.execute('''
        CREATE TABLE IF NOT EXISTS levels (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            xp INTEGER NOT NULL,
            level INTEGER NOT NULL,
            last_xp_time DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )
    ''')
    
    # Table for per-guild configuration (e.g., level-up channel)
    await bot.db.execute('''
        CREATE TABLE IF NOT EXISTS server_config (
            guild_id TEXT PRIMARY KEY,
            level_up_channel TEXT NOT NULL
        )
    ''')

    # Table for channel XP boosts
    await bot.db.execute('''
        CREATE TABLE IF NOT EXISTS channel_boosts (
            guild_id TEXT,
            channel_id TEXT,
            multiplier REAL,
            PRIMARY KEY (guild_id, channel_id))
    ''')
    
    # Load channel boosts from database
    await load_channel_boosts(bot)

async def on_resumed(bot):
    """Handle reconnection events"""
    logging.info("Bot RESUMED connection. Checking for pending database operations...")
    if pending_operations:
        logging.info(f"Found {len(pending_operations)} pending operations to process")
        await retry_pending_operations(bot)

async def retry_pending_operations(bot):
    """Process any pending database operations"""
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
                
                # Call the appropriate function
                if func_name == "update_user_xp":
                    await update_user_xp(bot, *args, **kwargs)
                elif func_name == "set_level_up_channel":
                    await set_level_up_channel(bot, *args, **kwargs)
                elif func_name == "set_channel_boost_db":
                    await set_channel_boost_db(bot, *args, **kwargs)
                elif func_name == "remove_channel_boost_db":
                    await remove_channel_boost_db(bot, *args, **kwargs)
                elif func_name == "remove_channel_boost_db":
                    await remove_channel_boost_db(bot, *args, **kwargs)
                
                # Mark as successful
                successful_ops.append(operation)
                logging.info(f"Successfully processed pending {func_name} operation")
                
            except Exception as e:
                logging.error(f"Failed to process pending operation: {e}")
                # Keep in queue for next retry
        
        # Remove successful operations
        for op in successful_ops:
            if op in pending_operations:
                pending_operations.remove(op)

async def safe_db_operation(bot, func_name, *args, **kwargs):
    """
    Execute a database operation with retry logic.
    If it fails, store it for later retry.
    """
    retries = 0
    while retries < MAX_RETRIES:
        try:
            # Call the original function based on name
            if func_name == "update_user_xp":
                return await _update_user_xp(bot, *args, **kwargs)
            elif func_name == "set_level_up_channel":
                return await _set_level_up_channel(bot, *args, **kwargs)
            elif func_name == "set_channel_boost_db":
                return await _set_channel_boost_db(bot, *args, **kwargs)
            elif func_name == "remove_channel_boost_db":
                return await _remove_channel_boost_db(bot, *args, **kwargs)
            elif func_name == "get_or_create_user_level":
                return await _get_or_create_user_level(bot, *args, **kwargs)
            else:
                logging.error(f"Unknown function name: {func_name}")
                return None

        except asyncpg.exceptions.PostgresError as e:
            logging.error(f"Database error in {func_name}: {e}")
            # Handle specific database issues
            if isinstance(e, asyncpg.exceptions.DeadlockDetectedError):
                logging.warning(f"Deadlock detected, retrying {func_name} (attempt {retries+1}/{MAX_RETRIES})")
            elif isinstance(e, asyncpg.exceptions.ConnectionDoesNotExistError) or \
                 isinstance(e, asyncpg.exceptions.InterfaceError):
                logging.error(f"Lost database connection during {func_name}, attempting reconnect...")
                await init_db(bot)  # Ensure the bot reconnects to the DB
            else:
                pending_operations.append({
                    "function": func_name,
                    "args": args,
                    "kwargs": kwargs
                })
                return None

            # Retry logic with exponential backoff
            retries += 1
            await asyncio.sleep(0.5 * (2 ** retries))

        except Exception as e:
            # Unexpected error, queue for later
            logging.error(f"Unexpected error in {func_name}: {e}")
            pending_operations.append({
                "function": func_name,
                "args": args,
                "kwargs": kwargs
            })
            return None

    # If we exhausted retries, queue the operation
    logging.warning(f"Max retries reached for {func_name}, queueing for later")
    pending_operations.append({
        "function": func_name,
        "args": args,
        "kwargs": kwargs
    })
    return None

async def _get_or_create_user_level(bot, guild_id, user_id):
    """
    Retrieves a user's level info from the database or creates a new entry if none exists.
    Returns a tuple of (xp, level, last_xp_time)
    """
    # First try to get the user
    row = await bot.db.fetchrow(
        "SELECT xp, level, last_xp_time, last_role FROM levels WHERE guild_id = $1 AND user_id = $2",
        guild_id, user_id
    )

    if row is None:
        # Create new user record
        xp = 0
        level = 1
        last_xp_time = 0
        role = 1349303634906841128
        
        # In PostgreSQL, we use INSERT ... ON CONFLICT for upsert operations
        await bot.db.execute(
            "INSERT INTO levels (guild_id, user_id, xp, level, last_xp_time, last_role) VALUES ($1, $2, $3, $4, $5, $6)",
            guild_id, user_id, xp, level, last_xp_time, role
        )
        return (xp, level, last_xp_time)
    else:
        # Return the row as a tuple (PostgreSQL returns a Record, which can be unpacked like a tuple)
        return (row['xp'], row['level'], row['last_xp_time'], row['last_role'])

async def get_or_create_user_level(bot, guild_id, user_id): # Public API functions with safety wrappers
    """Update a user's XP, level, and optionally last_xp_time with safety"""
    return await safe_db_operation(bot, "get_or_create_user_level", guild_id, user_id)

async def _update_user_xp(bot, guild_id, user_id, xp, level, new_role, last_xp_time=None):
    """Update a user's XP, level, and optionally last_xp_time"""
    if last_xp_time is None:
        last_xp_time = time.time()
        
    await bot.db.execute(
        "UPDATE levels SET xp = $1, level = $2, last_xp_time = $3, last_role = $4 WHERE guild_id = $5 AND user_id = $6",
        xp, level, last_xp_time, new_role, guild_id, user_id
    )

async def update_user_xp(bot, guild_id, user_id, xp, level, new_role, last_xp_time=None): # Public API functions with safety wrappers
    """Update a user's XP, level, and optionally last_xp_time with safety"""
    return await safe_db_operation(bot, "update_user_xp", guild_id, user_id, xp, level, last_xp_time, new_role)

async def get_leaderboard(bot, guild_id, limit=10):
    """Get the top users by level and XP"""
    rows = await bot.db.fetch(
        "SELECT user_id, xp, level FROM levels WHERE guild_id = $1 ORDER BY level DESC, xp DESC LIMIT $2",
        guild_id, limit
    )
    # Convert rows to a list of tuples for compatibility with the current code
    return [(row['user_id'], row['xp'], row['level']) for row in rows]

async def get_user_levels(bot,guild_id,user_id):
    rows = await bot.db.fetchrow(
        "SELECT xp, level FROM levels WHERE guild_id = $1 AND user_id = $2",
                guild_id,
                user_id,
    )
    return (rows['xp'], rows['level'])

async def _set_level_up_channel(bot, guild_id, channel_id):
    """Set the channel where level-up notifications will be sent"""
    await bot.db.execute(
        "INSERT INTO server_config (guild_id, level_up_channel) VALUES ($1, $2) " +
        "ON CONFLICT (guild_id) DO UPDATE SET level_up_channel = $2",
        guild_id, channel_id
    )

async def set_level_up_channel(bot, guild_id, channel_id): # Public API with safety wrapper
    """Set the channel where level-up notifications will be sent with safety"""
    return await safe_db_operation(bot, "set_level_up_channel", guild_id, channel_id)

async def get_level_up_channel(bot, guild_id):
    """Get the channel ID where level-up notifications should be sent"""
    row = await bot.db.fetchrow(
        "SELECT level_up_channel FROM server_config WHERE guild_id = $1", 
        guild_id
    )
    
    if row:
        return row['level_up_channel']
    return None

async def _set_channel_boost_db(bot, guild_id, channel_id, multiplier):
    """Set an XP boost multiplier for a specific channel"""
    # Update in-memory storage
    CHANNEL_XP_BOOSTS[channel_id] = multiplier
    
    # Update database
    await bot.db.execute(
        "INSERT INTO channel_boosts (guild_id, channel_id, multiplier) VALUES ($1, $2, $3) " +
        "ON CONFLICT (guild_id, channel_id) DO UPDATE SET multiplier = $3",
        guild_id, channel_id, multiplier
    )

async def set_channel_boost_db(bot, guild_id, channel_id, multiplier): # Public API with safety wrapper
    """Set an XP boost multiplier for a specific channel with safety"""
    return await safe_db_operation(bot, "set_channel_boost_db", guild_id, channel_id, multiplier)    

async def _remove_channel_boost_db(bot, guild_id, channel_id):
    """Remove an XP boost from a specific channel"""
    # Remove from in-memory storage
    if channel_id in CHANNEL_XP_BOOSTS:
        del CHANNEL_XP_BOOSTS[channel_id]
    
    # Remove from database
    await bot.db.execute(
        "DELETE FROM channel_boosts WHERE guild_id = $1 AND channel_id = $2",
        guild_id, channel_id
    )

async def remove_channel_boost_db(bot, guild_id, channel_id): # Public API with safety wrapper
    """Remove an XP boost from a specific channel with safety"""
    return await safe_db_operation(bot, "remove_channel_boost_db", guild_id, channel_id)

async def load_channel_boosts(bot):
    """Load channel boosts from database"""
    global CHANNEL_XP_BOOSTS
    
    rows = await bot.db.fetch("SELECT channel_id, multiplier FROM channel_boosts")
    
    CHANNEL_XP_BOOSTS = {row['channel_id']: row['multiplier'] for row in rows}

def apply_channel_boost(base_xp, channel_id):
    """Apply channel-specific XP boost if applicable"""
    if channel_id and channel_id in CHANNEL_XP_BOOSTS:
        return int(base_xp * CHANNEL_XP_BOOSTS[channel_id])
    return base_xp