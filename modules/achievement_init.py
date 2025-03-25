import logging
from database import init_achievement_caches, log_achievement_cache_stats

async def initialize_achievement_system(bot):
    """Initialize the achievement system"""
    
    # Initialize achievement caches
    init_achievement_caches()
    logging.info("Achievement caches initialized")
    
    # Schedule periodic cache stats logging
    bot.loop.create_task(periodic_cache_stats_logging(bot))
    
    return True

async def periodic_cache_stats_logging(bot):
    """Periodically log cache statistics"""
    import asyncio
    
    await bot.wait_until_ready()
    
    while not bot.is_closed():
        # Log cache stats
        log_achievement_cache_stats()
        
        # Wait before logging again (1 hour)
        await asyncio.sleep(3600)