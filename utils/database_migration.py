import logging
import asyncio
import json
from database.core import get_connection

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
    and modify level_up_channel to accept null values
    
    This function is called during database initialization to migrate
    the server_config table schema if needed.
    """
    try:
        async with bot.db.acquire() as conn:
            # First, modify level_up_channel to accept null values
            logging.info("Migrating server_config table to allow null values for level_up_channel")
            await conn.execute("ALTER TABLE server_config ALTER COLUMN level_up_channel DROP NOT NULL")
            logging.info("Successfully modified level_up_channel column")
            
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

async def create_user_achievement_settings_table(bot):
    """Create the user_achievement_settings table if it doesn't exist.
    This table stores user preferences related to achievements, like selected title display.
    """
    try:
        async with bot.db.acquire() as conn:
            # First check if the update_updated_at_column function exists
            function_exists_query = """
            SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column';
            """
            function_exists = await conn.fetchval(function_exists_query)
            
            # Create the function if it doesn't exist
            if not function_exists:
                logging.info("Creating update_updated_at_column function...")
                create_function_query = """
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
                await conn.execute(create_function_query)
                logging.info("update_updated_at_column function created successfully")
            
            # Check if table exists
            check_query = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'user_achievement_settings'
            );
            """
            exists = await conn.fetchval(check_query)
            
            if not exists:
                logging.info("Creating user_achievement_settings table...")
                
                # Create the table
                create_query = """
                CREATE TABLE user_achievement_settings (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    selected_title TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, user_id)
                );
                
                -- Add trigger to update the updated_at column
                CREATE TRIGGER update_user_achievement_settings_updated_at
                BEFORE UPDATE ON user_achievement_settings
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
                """
                
                await conn.execute(create_query)
                logging.info("user_achievement_settings table created successfully")
            else:
                logging.info("user_achievement_settings table already exists")
                
        return True
    except Exception as e:
        logging.error(f"Error creating user_achievement_settings table: {e}")
        return False

async def migration_version_8():
    """
    Migration to add quest_cooldowns column to server_config table
    """
    try:
        async with get_connection() as conn:
            # Check if column exists already
            check_query = """
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'server_config' AND column_name = 'quest_cooldowns'
            """
            result = await conn.fetchval(check_query)
            
            if not result:
                # Add the column
                add_column_query = """
                ALTER TABLE server_config 
                ADD COLUMN IF NOT EXISTS quest_cooldowns JSONB DEFAULT NULL
                """
                await conn.execute(add_column_query)
                
                # Initialize with default values from config
                from config import QUEST_SETTINGS
                update_query = """
                UPDATE server_config 
                SET quest_cooldowns = $1
                WHERE quest_cooldowns IS NULL
                """
                # Serialize the dictionary to a JSON string
                cooldowns_json = json.dumps(QUEST_SETTINGS["COOLDOWNS"])
                await conn.execute(update_query, cooldowns_json)
                
                logging.info("Migration 8: Added quest_cooldowns column to server_config table")
            else:
                logging.info("Migration 8: server_config.quest_cooldowns column already exists")
            
            return True
    except Exception as e:
        logging.error(f"Migration 8 error: {e}")
        return False

# Helper function to apply migrations from files
async def apply_migration_from_file(migration_file_path: str):
    """Reads and applies SQL from a migration file."""
    try:
        with open(migration_file_path, 'r') as f:
            # We assume the file contains APPLY_SQL and REVERT_SQL blocks.
            # For simplicity, we execute everything for now, assuming APPLY_SQL is first.
            # A more robust implementation would parse this properly.
            # NOTE: This simple approach might fail if the file structure changes significantly.
            # We will read APPLY_SQL specifically
            content = f.read()
            apply_sql_start = content.find('APPLY_SQL = """')
            if apply_sql_start == -1:
                logging.error(f"Could not find APPLY_SQL block in {migration_file_path}")
                return False
            
            apply_sql_start += len('APPLY_SQL = """')
            apply_sql_end = content.find('"""', apply_sql_start)
            if apply_sql_end == -1:
                 logging.error(f"Could not find end of APPLY_SQL block in {migration_file_path}")
                 return False
                 
            apply_sql = content[apply_sql_start:apply_sql_end].strip()
            
            if not apply_sql:
                 logging.warning(f"APPLY_SQL block is empty in {migration_file_path}")
                 return True # Not an error, just nothing to apply
                 
        async with get_connection() as conn:
            await conn.execute(apply_sql)
        logging.info(f"Successfully applied migration from file: {migration_file_path}")
        return True
    except FileNotFoundError:
        logging.error(f"Migration file not found: {migration_file_path}")
        return False
    except Exception as e:
        logging.error(f"Error applying migration from file {migration_file_path}: {e}", exc_info=True)
        return False

# Add a function to run all migrations
async def run_all_migrations(bot):
    """
    Run all database migrations
    
    This function is called during database initialization to ensure
    all required migrations have been applied.
    """
    logging.info("Running all database migrations...")
    
    # We should use the bot's connection pool for consistency if possible
    # Modify internal migrations to accept bot or conn?
    # For now, keep internal migrations as they are, file migration uses get_connection()
    
    try:
        # Run migrations in sequence
        migration_tasks = [
            update_achievement_schema(bot), # Migration 1
            update_server_config_schema(bot), # Migration 2
            create_user_achievement_settings_table(bot), # Migration 3
            # migration_version_4 - 7 seem missing based on numbering
            migration_version_8(), # Migration 8 (internal)
            apply_migration_from_file("database/migrations/003_add_event_integration_tables.py"), # Migration '003' (file-based)
            apply_migration_from_file("database/migrations/004_add_event_attendance_counter.py") # Migration '004' (file-based)
        ]
        
        results = await asyncio.gather(*migration_tasks, return_exceptions=True)
        
        # Check for any failures
        success = True
        for i, result in enumerate(results):
            # Adjust logging to better reflect migration source
            migration_name = f"Internal Migration {i+1}" 
            if i == 3: migration_name = "Migration 8 (Internal)"
            if i == 4: migration_name = "Migration 003 (File)"
            if i == 5: migration_name = "Migration 004 (File)" # Updated index for logging
            
            if isinstance(result, Exception):
                logging.error(f"{migration_name} failed with error: {result}")
                success = False
            elif result is False:
                logging.error(f"{migration_name} returned False")
                success = False
        
        if success:
            logging.info("All migrations completed successfully")
        else:
            logging.warning("Some migrations failed - check logs for details")
            
    except Exception as e:
        logging.error(f"Error during migration process: {e}", exc_info=True)

    # Return overall success status? (Optional)
    # return success

# Export the public functions
__all__ = [
    'update_achievement_schema',
    'update_server_config_schema',
    'create_user_achievement_settings_table',
    'run_all_migrations'
]