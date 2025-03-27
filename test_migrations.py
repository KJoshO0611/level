"""
Test script for database migrations
"""
import asyncio
import logging
import sys
from config import load_config
from database import init_db, close_db
from utils.database_migration import run_all_migrations

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

class MockBot:
    """Mock bot class for testing"""
    def __init__(self):
        self.db = None
        self.config = load_config()

async def test_migrations():
    """Test running all migrations"""
    bot = MockBot()
    
    # Initialize database
    print("Initializing database...")
    success = await init_db(bot)
    if not success:
        print("Database initialization failed!")
        return False
    
    # Run migrations
    print("Running migrations...")
    migration_success = await run_all_migrations(bot)
    if migration_success:
        print("All migrations completed successfully!")
    else:
        print("Some migrations failed!")
    
    # Close database
    await close_db()
    
    return migration_success

if __name__ == "__main__":
    result = asyncio.run(test_migrations())
    if not result:
        sys.exit(1) 