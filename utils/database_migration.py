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