import aiosqlite
import time
from config import load_config

config = load_config()
DB_PATH = config["PATHS"]["DATABASE_PATH"]

# Dictionary to store channel XP boosts
CHANNEL_XP_BOOSTS = {}

async def init_db(bot):

    print(DB_PATH)
    """Initialize the database and create tables if they don't exist"""
    bot.db = await aiosqlite.connect(DB_PATH)
    
    # Table for user leveling data, stored per guild
    await bot.db.execute('''
        CREATE TABLE IF NOT EXISTS levels (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            xp INTEGER NOT NULL,
            level INTEGER NOT NULL,
            last_xp_time REAL NOT NULL,
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

    await bot.db.commit()
    
    # Load channel boosts from database
    await load_channel_boosts(bot)

async def get_or_create_user_level(bot, guild_id, user_id):
    """
    Retrieves a user's level info from the database or creates a new entry if none exists.
    Returns a tuple of (xp, level, last_xp_time)
    """
    async with bot.db.execute(
        "SELECT xp, level, last_xp_time FROM levels WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id)
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        # Create new user record
        xp = 0
        level = 1
        last_xp_time = 0
        await bot.db.execute(
            "INSERT INTO levels (guild_id, user_id, xp, level, last_xp_time) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, xp, level, last_xp_time)
        )
        await bot.db.commit()
        return (xp, level, last_xp_time)
    else:
        return row

async def update_user_xp(bot, guild_id, user_id, xp, level, last_xp_time=None):
    """Update a user's XP, level, and optionally last_xp_time"""
    if last_xp_time is None:
        last_xp_time = time.time()
        
    await bot.db.execute(
        "UPDATE levels SET xp = ?, level = ?, last_xp_time = ? WHERE guild_id = ? AND user_id = ?",
        (xp, level, last_xp_time, guild_id, user_id)
    )
    await bot.db.commit()

async def get_leaderboard(bot, guild_id, limit=10):
    """Get the top users by level and XP"""
    async with bot.db.execute(
        "SELECT user_id, xp, level FROM levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ?",
        (guild_id, limit)
    ) as cursor:
        rows = await cursor.fetchall()
    return rows

async def set_level_up_channel(bot, guild_id, channel_id):
    """Set the channel where level-up notifications will be sent"""
    await bot.db.execute(
        "INSERT OR REPLACE INTO server_config (guild_id, level_up_channel) VALUES (?, ?)",
        (guild_id, channel_id)
    )
    await bot.db.commit()

async def get_level_up_channel(bot, guild_id):
    """Get the channel ID where level-up notifications should be sent"""
    async with bot.db.execute(
        "SELECT level_up_channel FROM server_config WHERE guild_id = ?", 
        (guild_id,)
    ) as cursor:
        row = await cursor.fetchone()
    
    if row:
        return row[0]
    return None

async def set_channel_boost_db(bot, guild_id, channel_id, multiplier):
    """Set an XP boost multiplier for a specific channel"""
    # Update in-memory storage
    CHANNEL_XP_BOOSTS[channel_id] = multiplier
    
    # Update database
    await bot.db.execute(
        "INSERT OR REPLACE INTO channel_boosts (guild_id, channel_id, multiplier) VALUES (?, ?, ?)",
        (guild_id, channel_id, multiplier)
    )
    await bot.db.commit()

async def remove_channel_boost_db(bot, guild_id, channel_id):
    """Remove an XP boost from a specific channel"""
    # Remove from in-memory storage
    if channel_id in CHANNEL_XP_BOOSTS:
        del CHANNEL_XP_BOOSTS[channel_id]
    
    # Remove from database
    await bot.db.execute(
        "DELETE FROM channel_boosts WHERE guild_id = ? AND channel_id = ?",
        (guild_id, channel_id)
    )
    await bot.db.commit()

async def load_channel_boosts(bot):
    """Load channel boosts from database"""
    global CHANNEL_XP_BOOSTS
    
    async with bot.db.execute("SELECT channel_id, multiplier FROM channel_boosts") as cursor:
        rows = await cursor.fetchall()
    
    CHANNEL_XP_BOOSTS = {row[0]: row[1] for row in rows}

def apply_channel_boost(base_xp, channel_id):
    """Apply channel-specific XP boost if applicable"""
    if channel_id and channel_id in CHANNEL_XP_BOOSTS:
        return int(base_xp * CHANNEL_XP_BOOSTS[channel_id])
    return base_xp