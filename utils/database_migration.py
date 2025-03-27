import logging
import asyncio

async def update_achievement_schema(bot):
    """
    Add guild_id column to achievements table if it doesn't exist
    
    This function is called during database initialization to migrate
    the achievements table schema if needed.
    """
    try:
        async with bot.db.acquire() as conn:
            # Check if guild_id column exists
            check_query = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'achievements' AND column_name = 'guild_id'
            """
            
            has_guild_id = await conn.fetchval(check_query)
            
            # If guild_id column doesn't exist, add it
            if not has_guild_id:
                logging.info("Migrating achievements table to add guild_id column")
                
                async with conn.transaction():
                    # Add the guild_id column
                    await conn.execute("ALTER TABLE achievements ADD COLUMN guild_id TEXT")
                    
                    # Set a default guild_id for existing achievements
                    # This assigns '0' to all existing achievements
                    await conn.execute("UPDATE achievements SET guild_id = '0' WHERE guild_id IS NULL")
                    
                    # Make the column not nullable
                    await conn.execute("ALTER TABLE achievements ALTER COLUMN guild_id SET NOT NULL")
                    
                    # Add an index for performance
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_achievements_guild_id ON achievements(guild_id)")
                    
                logging.info("Successfully migrated achievements table")
                return True
            
            logging.info("Achievements table already has guild_id column - no migration needed")
            return True
            
    except Exception as e:
        logging.error(f"Error migrating achievements table: {e}")
        return False

async def update_server_config_schema(bot):
    """
    Add achievement_channel and quest_channel columns to server_config table if they don't exist
    
    This function is called during database initialization to migrate
    the server_config table schema if needed.
    """
    try:
        async with bot.db.acquire() as conn:
            # Check if achievement_channel column exists
            check_query = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'server_config' AND column_name = 'achievement_channel'
            """
            
            has_achievement_channel = await conn.fetchval(check_query)
            
            # If achievement_channel column doesn't exist, add it
            if not has_achievement_channel:
                logging.info("Migrating server_config table to add achievement_channel column")
                
                async with conn.transaction():
                    # Add the achievement_channel column
                    await conn.execute("ALTER TABLE server_config ADD COLUMN achievement_channel TEXT")
                    
                logging.info("Successfully added achievement_channel column")
            
            # Check if quest_channel column exists
            check_query = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'server_config' AND column_name = 'quest_channel'
            """
            
            has_quest_channel = await conn.fetchval(check_query)
            
            # If quest_channel column doesn't exist, add it
            if not has_quest_channel:
                logging.info("Migrating server_config table to add quest_channel column")
                
                async with conn.transaction():
                    # Add the quest_channel column
                    await conn.execute("ALTER TABLE server_config ADD COLUMN quest_channel TEXT")
                    
                logging.info("Successfully added quest_channel column")
            
            return True
            
    except Exception as e:
        logging.error(f"Error migrating server_config table: {e}")
        return False