import logging
import asyncio
import json
import sys
import os
import argparse
import asyncpg
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Add parent directory to path when running as standalone script
if __name__ == "__main__":
    # Get the directory containing this script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Get the parent directory (project root)
    parent_dir = os.path.dirname(current_dir)
    # Add the parent directory to sys.path if not already there
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        print(f"Added {parent_dir} to Python path")

# Import database.core module
from database.core import get_connection

# Database connection for standalone mode
_pool = None

async def setup_db():
    """
    Set up database connection pool for standalone mode
    This is only used when running the script directly
    """
    global _pool
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Try getting database credentials from environment variables
    db_host = os.getenv("HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "cluelesslevel")
    db_user = os.getenv("DB_USER", "clueless")
    db_pass = os.getenv("PASSWORD", "")
    
    # If not found in environment, try loading from config file
    if not all([db_host, db_name, db_user]):
        try:
            # Try to import config
            from config import DATABASE_CONFIG
            db_host = DATABASE_CONFIG.get("host", db_host)
            db_port = DATABASE_CONFIG.get("port", db_port)
            db_name = DATABASE_CONFIG.get("database", db_name)
            db_user = DATABASE_CONFIG.get("user", db_user)
            db_pass = DATABASE_CONFIG.get("password", db_pass)
        except ImportError:
            logging.warning("Could not import database config, using default values")
    
    try:
        # Create the connection pool
        logging.info(f"Connecting to database {db_name} on {db_host}")
        _pool = await asyncpg.create_pool(
            host=db_host,
            port=int(db_port),
            database=db_name,
            user=db_user,
            password=db_pass,
        )
        
        logging.info("Database connection established")
        return True
    except Exception as e:
        logging.error(f"Error connecting to database: {e}")
        return False

# Use asynccontextmanager to create a proper async context manager
@asynccontextmanager
async def with_connection():
    """Proper async context manager for database connections"""
    global _pool
    if _pool is None:
        raise RuntimeError("Database connection not initialized")
    
    conn = await _pool.acquire()
    try:
        yield conn
    finally:
        await _pool.release(conn)

async def update_achievement_schema(bot=None):
    """
    Add guild_id column to achievements table if it doesn't exist
    
    This function is called during database initialization to migrate
    the achievements table schema if needed.
    """
    try:
        # Use either bot's connection or get a new one
        if bot:
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
        else:
            # Standalone mode - use direct pool connection
            async with with_connection() as conn:
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

async def update_server_config_schema(bot=None):
    """
    Add achievement_channel and quest_channel columns to server_config table if they don't exist
    and modify level_up_channel to accept null values
    
    This function is called during database initialization to migrate
    the server_config table schema if needed.
    """
    try:
        if bot:
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
        else:
            # Standalone mode - use direct pool connection
            async with with_connection() as conn:
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

async def create_user_achievement_settings_table(bot=None):
    """Create the user_achievement_settings table if it doesn't exist.
    This table stores user preferences related to achievements, like selected title display.
    """
    try:
        if bot:
            async with bot.db.acquire() as conn:
                # Implementation with bot connection
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
        else:
            # Standalone mode - use direct pool connection
            async with with_connection() as conn:
                # Same implementation as above, without bot connection
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
        async with with_connection() as conn:
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
        # Ensure path is absolute if running standalone
        if __name__ == "__main__" and not os.path.isabs(migration_file_path):
            # Get project root directory
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            migration_file_path = os.path.join(root_dir, migration_file_path)
        
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
                 
        # Use direct pool connection for file migrations
        async with with_connection() as conn:
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
async def run_all_migrations(bot=None):
    """
    Run all database migrations
    
    This function is called during database initialization to ensure
    all required migrations have been applied.
    """
    logging.info("Running all database migrations...")
    
    try:
        # Run migrations in sequence
        migration_tasks = [
            update_achievement_schema(bot), # Migration 1
            update_server_config_schema(bot), # Migration 2
            create_user_achievement_settings_table(bot), # Migration 3
            # migration_version_4 - 7 seem missing based on numbering
            migration_version_8(), # Migration 8 (internal)
            apply_migration_from_file("database/migrations/003_add_event_integration_tables.py"), # Migration '003' (file-based)
            apply_migration_from_file("database/migrations/004_add_event_attendance_counter.py"), # Migration '004' (file-based)
            apply_migration_from_file("database/migrations/005_add_event_integration_columns.py"), # Migration '005' (file-based)
            apply_migration_from_file("database/migrations/006_add_quest_specific_progress.py"), # Migration '006' (file-based)
            apply_migration_from_file("database/migrations/007_fix_event_column_names.py"), # Migration '007' (file-based)
            apply_migration_from_file("database/migrations/008_fix_event_attendance_columns.py") # Migration '008' (file-based)
        ]
        
        results = await asyncio.gather(*migration_tasks, return_exceptions=True)
        
        # Check for any failures
        success = True
        for i, result in enumerate(results):
            # Adjust logging to better reflect migration source
            migration_name = f"Internal Migration {i+1}" 
            if i == 3: migration_name = "Migration 8 (Internal)"
            if i == 4: migration_name = "Migration 003 (File)"
            if i == 5: migration_name = "Migration 004 (File)" 
            if i == 6: migration_name = "Migration 005 (File)"
            if i == 7: migration_name = "Migration 006 (File)"
            if i == 8: migration_name = "Migration 007 (File)"
            if i == 9: migration_name = "Migration 008 (File)"
            
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
        
        return success
            
    except Exception as e:
        logging.error(f"Error during migration process: {e}", exc_info=True)
        return False

# Apply specific migrations by name
async def run_specific_migrations(migration_names, bot=None):
    """
    Run specific migrations by name
    
    Args:
        migration_names: List of migration names to run
        bot: Optional bot instance for database connection
    """
    logging.info(f"Running specific migrations: {migration_names}")
    
    # Map migration names to their functions
    migration_map = {
        "update_achievement_schema": update_achievement_schema,
        "update_server_config_schema": update_server_config_schema,
        "create_user_achievement_settings_table": create_user_achievement_settings_table,
        "migration_version_8": migration_version_8,
        "003_add_event_integration_tables": lambda: apply_migration_from_file("database/migrations/003_add_event_integration_tables.py"),
        "004_add_event_attendance_counter": lambda: apply_migration_from_file("database/migrations/004_add_event_attendance_counter.py"),
        "005_add_event_integration_columns": lambda: apply_migration_from_file("database/migrations/005_add_event_integration_columns.py"),
        "006_add_quest_specific_progress": lambda: apply_migration_from_file("database/migrations/006_add_quest_specific_progress.py"),
        "007_fix_event_column_names": lambda: apply_migration_from_file("database/migrations/007_fix_event_column_names.py"),
        "008_fix_event_attendance_columns": lambda: apply_migration_from_file("database/migrations/008_fix_event_attendance_columns.py"),
    }
    
    tasks = []
    for name in migration_names:
        if name in migration_map:
            if name.startswith("update_") or name.startswith("create_"):
                tasks.append(migration_map[name](bot))
            else:
                tasks.append(migration_map[name]())
        else:
            logging.error(f"Unknown migration: {name}")
    
    if not tasks:
        logging.warning("No valid migrations specified")
        return False
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for any failures
        success = True
        for i, result in enumerate(results):
            migration_name = migration_names[i]
            if isinstance(result, Exception):
                logging.error(f"Migration {migration_name} failed with error: {result}")
                success = False
            elif result is False:
                logging.error(f"Migration {migration_name} returned False")
                success = False
        
        if success:
            logging.info(f"Successfully completed {len(tasks)} migrations")
        else:
            logging.warning("Some migrations failed - check logs for details")
        
        return success
            
    except Exception as e:
        logging.error(f"Error during specific migrations: {e}", exc_info=True)
        return False

# Export the public functions
__all__ = [
    'update_achievement_schema',
    'update_server_config_schema',
    'create_user_achievement_settings_table',
    'run_all_migrations',
    'run_specific_migrations'
]

# Main function for standalone execution
async def main():
    """Main function when running as a standalone script"""
    # Configure argument parser
    parser = argparse.ArgumentParser(description="Database migration utility")
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                      default='INFO', help='Set the logging level')
    
    subparsers = parser.add_subparsers(dest='command', help='Migration command')
    
    # Add 'all' command
    all_parser = subparsers.add_parser('all', help='Run all migrations')
    
    # Add 'specific' command
    specific_parser = subparsers.add_parser('specific', help='Run specific migrations')
    specific_parser.add_argument('migrations', nargs='+', 
                               help='Names of migrations to run')
    
    # Add 'list' command
    list_parser = subparsers.add_parser('list', help='List available migrations')
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set up database connection when running standalone
    db_setup_success = await setup_db()
    if not db_setup_success:
        logging.error("Failed to set up database connection. Aborting.")
        return 1
    
    # Make sure the pool is not None after setup
    if _pool is None:
        logging.error("Database connection pool is None after setup. Aborting.")
        return 1
    
    try:
        # Execute command
        if args.command == 'all':
            success = await run_all_migrations()
            return 0 if success else 1
        
        elif args.command == 'specific':
            success = await run_specific_migrations(args.migrations)
            return 0 if success else 1
        
        elif args.command == 'list':
            migrations = [
                "update_achievement_schema", 
                "update_server_config_schema",
                "create_user_achievement_settings_table", 
                "migration_version_8",
                "003_add_event_integration_tables",
                "004_add_event_attendance_counter",
                "005_add_event_integration_columns",
                "006_add_quest_specific_progress",
                "007_fix_event_column_names",
                "008_fix_event_attendance_columns"
            ]
            print("Available migrations:")
            for migration in migrations:
                print(f"  - {migration}")
            return 0
        
        else:
            parser.print_help()
            return 1
    finally:
        # Close the database connection pool if it exists
        if _pool is not None:
            logging.info("Closing database connection pool")
            await _pool.close()  # Properly await the pool closure

# Run as script if executed directly
if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nMigration process interrupted")
        sys.exit(130)  # Standard exit code for Ctrl+C