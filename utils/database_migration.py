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

# Helper function to apply migrations from files
async def apply_migration_from_file(migration_file_path: str, bot=None):
    """Reads and applies SQL from a migration file."""
    try:
        # Get project root directory for resolving paths
        if __name__ == "__main__":
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            root_dir = os.getcwd()
            
        # Clean up the path format for Windows/Unix compatibility    
        migration_file_path = migration_file_path.replace('\\', '/')
        
        # Try the relative path (from current working directory)
        if not os.path.isabs(migration_file_path):
            full_path = os.path.join(root_dir, migration_file_path)
            if os.path.isfile(full_path):
                migration_file_path = full_path
            else:
                # Also try a path from the database directory
                database_path = os.path.join(root_dir, "database")
                migration_name = os.path.basename(migration_file_path)
                alt_path = os.path.join(database_path, "migrations", migration_name)
                if os.path.isfile(alt_path):
                    migration_file_path = alt_path
                else:
                    # If we can't find it, log details and return
                    logging.warning(f"Migration file not found: {migration_file_path}")
                    logging.warning(f"Tried paths: {full_path} and {alt_path}")
                    logging.warning(f"Current directory: {os.getcwd()}")
                    logging.warning(f"Root directory: {root_dir}")
                    return False
        
        logging.info(f"Reading migration from: {migration_file_path}")
        with open(migration_file_path, 'r') as f:
            # We assume the file contains APPLY_SQL and REVERT_SQL blocks.
            # For simplicity, we execute everything for now, assuming APPLY_SQL is first.
            # A more robust implementation would parse this properly.
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
        
        # Use bot's connection if available, otherwise use standalone pool
        if bot and hasattr(bot, 'db') and hasattr(bot.db, 'acquire'):
            logging.info(f"Using bot's database connection for migration: {migration_file_path}")
            async with bot.db.acquire() as conn:
                await conn.execute(apply_sql)
                logging.info(f"Successfully applied migration using bot connection: {migration_file_path}")
        else:
            # Use direct pool connection for standalone migrations
            global _pool
            if _pool is None:
                logging.warning(f"Database connection not initialized for migration: {migration_file_path}")
                logging.info("Attempting to set up database connection...")
                success = await setup_db()
                if not success:
                    logging.error("Failed to initialize database connection for migration")
                    return False
                
            async with with_connection() as conn:
                await conn.execute(apply_sql)
                logging.info(f"Successfully applied migration with standalone connection: {migration_file_path}")
                
        return True
    except FileNotFoundError:
        logging.error(f"Migration file not found: {migration_file_path}")
        return False
    except Exception as e:
        logging.error(f"Error applying migration from file {migration_file_path}: {e}", exc_info=True)
        return False

# Function to get all available migrations
def get_available_migrations(root_dir=None):
    """
    Scans the database/migrations directory and returns a sorted list of migration files.
    Files should be named in format: NNN_description.py where NNN is a number.
    """
    if root_dir is None:
        if __name__ == "__main__":
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            root_dir = os.getcwd()
    
    migrations_dir = os.path.join(root_dir, "database", "migrations")
    
    # Check if migrations directory exists
    if not os.path.isdir(migrations_dir):
        logging.warning(f"Migrations directory not found: {migrations_dir}")
        return []
    
    # Get all python files in the migrations directory
    migration_files = []
    try:
        for file in os.listdir(migrations_dir):
            if file.endswith('.py') and file[0].isdigit():
                migration_files.append(file)
    except Exception as e:
        logging.error(f"Error scanning migrations directory: {e}")
        return []
    
    # Sort migration files by their number prefix
    def get_migration_number(filename):
        # Extract the migration number from the filename (e.g., 001_migration.py -> 1)
        parts = filename.split('_', 1)
        if parts and parts[0].isdigit():
            return int(parts[0])
        return 0
    
    migration_files.sort(key=get_migration_number)
    
    # Return the full paths to the migration files
    return [os.path.join("database", "migrations", file) for file in migration_files]

# Add a function to run all migrations
async def run_all_migrations(bot=None):
    """
    Run all database migrations
    
    This function is called during database initialization to ensure
    all required migrations have been applied.
    """
    logging.info("Running all database migrations...")
    
    try:
        # Initialize the database connection pool for standalone mode if needed
        global _pool
        if _pool is None and bot is None:
            logging.info("Initializing database connection for migrations...")
            success = await setup_db()
            if not success:
                logging.error("Failed to initialize database connection for migrations")
                return False
        
        # Core migrations that must always run
        core_migration_tasks = [

        ]
        
        # Get all migration files from the migrations directory
        migration_files = get_available_migrations()
        file_migrations = []
        
        # Create tasks for each migration file
        for file_path in migration_files:
            file_migrations.append(apply_migration_from_file(file_path, bot))
            logging.info(f"Adding migration file to queue: {file_path}")
        
        # Combine all migration tasks
        migration_tasks = core_migration_tasks + file_migrations
        
        results = await asyncio.gather(*migration_tasks, return_exceptions=True)
        
        # Check for any failures
        success = True
        # First check core migrations
        for i, result in enumerate(results[:len(core_migration_tasks)]):
            migration_name = f"Internal Migration {i+1}"
            if i == 3: migration_name = "Migration 8 (Internal)"
            
            if isinstance(result, Exception):
                logging.error(f"{migration_name} failed with error: {result}")
                success = False
            elif result is False:
                logging.error(f"{migration_name} returned False")
                success = False
        
        # Then check file migrations
        for i, result in enumerate(results[len(core_migration_tasks):]):
            migration_name = os.path.basename(migration_files[i])
            
            if isinstance(result, Exception):
                logging.error(f"File migration {migration_name} failed with error: {result}")
                success = False
            elif result is False:
                logging.error(f"File migration {migration_name} returned False")
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

    }
    
    tasks = []
    for name in migration_names:
        # First check if it's a core migration
        if name in migration_map:
            if name.startswith("update_") or name.startswith("create_"):
                tasks.append(migration_map[name](bot))
            else:
                tasks.append(migration_map[name]())
        # Then check if it's a file migration
        elif os.path.exists(os.path.join("database", "migrations", name)):
            tasks.append(apply_migration_from_file(os.path.join("database", "migrations", name), bot))
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
    all_parser = subparsers.add_parser('all', help='Run all core schema migrations')
    
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
            # List core migrations
            core_migrations = [

            ]
            print("Available core migrations:")
            for migration in core_migrations:
                print(f"  - {migration}")
            
            # List file-based migrations
            print("\nFile-based migrations:")
            migration_files = get_available_migrations()
            if migration_files:
                for file_path in migration_files:
                    migration_name = os.path.basename(file_path)
                    print(f"  - {migration_name}")
            else:
                print("  No file-based migrations found in database/migrations directory")
            
            print("\nTo add a new migration, create a file in the database/migrations directory")
            print("Format: NNN_description.py where NNN is a number (e.g., 010_add_new_column.py)")
            print("Each migration file should contain APPLY_SQL and REVERT_SQL sections")
            
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