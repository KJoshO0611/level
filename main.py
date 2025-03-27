"""
Discord Bot for Server Leveling System
Main entry point for the bot application
"""
import os
import sys
import time
import signal
import logging
import asyncio
import concurrent.futures
from discord.ext import commands
import discord

# Set up logging first thing
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Console handler with stdout
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)

# File handler
file_handler = logging.FileHandler('bot.log', encoding='utf-8', mode='a')
file_handler.setFormatter(log_formatter)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

# Direct print for emergency output
print("Starting bot initialization...")
root_logger.info("Bot starting - Logger initialized")

# Continue with imports after logging is set up
try:
    # Local imports
    from config import load_config
    from database import init_db, close_db
    from modules.voice_activity import start_voice_tracking, stop_periodic_processing
    from modules.levels import handle_message_xp, handle_reaction_xp
    from modules.achievements import register_achievement_hooks
    from modules.quest_integration import initialize_quest_system

    from utils.async_image_processor import start_image_processor
    from utils.image_templates import initialize_image_templates
    from utils.avatar_cache import avatar_cache
    from utils.background_api import BACKGROUNDS_DIR
    from utils.performance_monitoring import start_monitoring, stop_monitoring
    from utils.rate_limiter import RateLimiter, RateLimitExceeded
    from utils.database_migration import run_all_migrations
    
    root_logger.info("All modules imported successfully")
except Exception as e:
    root_logger.critical(f"Error importing modules: {e}", exc_info=True)
    print(f"Critical import error: {e}")
    sys.exit(1)

class LevelingBot(commands.Bot):
    """Extended Bot class with custom functionality"""
    
    def __init__(self, command_prefix, intents):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.processed_reactions = set()
        self.initialize_rate_limiters()
        root_logger.info("LevelingBot instance created")
        
    async def setup_hook(self):
        """Discord.py 2.0+ setup hook that runs after login"""
        # Initialize voice clients for all guild voice channels
        root_logger.info("Running setup_hook")
        for guild in self.guilds:
            for vc in guild.voice_channels:
                vc.guild.voice_client
    
    def initialize_rate_limiters(self):
        """Initialize rate limiters for different bot subsystems"""
        self.rate_limiters = {
            "image": RateLimiter(max_calls=5, period=60, name="image_generation"),
            "voice_xp": RateLimiter(max_calls=10, period=60, name="voice_xp"),
            "command": RateLimiter(max_calls=30, period=60, name="general_commands"),
            "leaderboard": RateLimiter(max_calls=2, period=30, name="leaderboard"),
            "guild": RateLimiter(max_calls=200, period=60, name="guild_commands"),
            "global": RateLimiter(max_calls=1000, period=60, name="global")
        }
        root_logger.info("Rate limiters initialized")

    async def setup_cogs(self):
        """Load all cogs and sync commands"""
        root_logger.info("Setting up cogs...")
        try:
            # Import here to avoid circular imports
            from cogs.admin import AdminCommands
            from cogs.help import CustomHelpCommand
            from cogs.leveling import LevelingCommands
            from cogs.config_commands import ConfigCommands
            from cogs.card_customization import BackgroundCommands
            from cogs.calendar_commands import CalendarCommands
            from cogs.achievement_commands import AchievementCommands
            from cogs.quest_commands import QuestCommands

            # Add cogs one by one with logging
            await self.add_cog(LevelingCommands(self))
            root_logger.info("Added LevelingCommands cog")
            
            await self.add_cog(AdminCommands(self))
            root_logger.info("Added AdminCommands cog")
            
            await self.add_cog(AchievementCommands(self))
            root_logger.info("Added CalendarCommands cog")
            
            await self.add_cog(ConfigCommands(self))
            root_logger.info("Added ConfigCommands cog")
            
            await self.add_cog(BackgroundCommands(self))
            root_logger.info("Added BackgroundCommands cog")
            
            await self.add_cog(CalendarCommands(self))
            root_logger.info("Added CalendarCommands cog")

            await self.add_cog(CustomHelpCommand(self))
            root_logger.info("Added CustomHelpCommand cog")

            await self.add_cog(QuestCommands(self))
            root_logger.info("Added QuestCommands cog")

            # Sync the command tree
            await self.tree.sync()
            root_logger.info("Command tree synced successfully")
            
        except Exception as e:
            root_logger.error(f"Error setting up cogs: {e}", exc_info=True)
            print(f"Error setting up cogs: {e}")
            raise


async def initialize_services(bot):
    """Initialize all required services and components"""
    root_logger.info("Starting initialization of services...")
    print("Initializing services...")
    
    # Initialize database
    root_logger.info("Initializing database connection...")
    success = await init_db(bot)
    if success:
        root_logger.info("Database initialized successfully")
    else:
        root_logger.error("Failed to initialize database")
        return False
    
    # Start voice tracking
    root_logger.info("Starting voice tracking...")
    await start_voice_tracking(bot)
    
    root_logger.info("Registering achivement hooks...")    
    register_achievement_hooks(bot)

    # Initialize achievement system (caches)
    root_logger.info("Initializing achievement system...")
    from modules.achievement_init import initialize_achievement_system
    await initialize_achievement_system(bot)

    # Initialize quest system
    root_logger.info("Initializing quest system...")
    await initialize_quest_system(bot)

    # Start image processor
    root_logger.info("Starting image processor...")
    await start_image_processor(bot)
    
    # Initialize avatar cache
    root_logger.info("Initializing avatar cache...")
    avatar_cache.start_cleanup_task(bot.loop)
    
    # Preload image templates in background thread
    root_logger.info("Preloading image templates...")
    bot.loop.run_in_executor(
        bot.image_thread_pool,
        initialize_image_templates,
        bot
    )
    
    # Ensure background directory exists
    root_logger.info(f"Checking background directory: {BACKGROUNDS_DIR}")
    if not os.path.exists(BACKGROUNDS_DIR):
        try:
            os.makedirs(BACKGROUNDS_DIR, exist_ok=True)
            root_logger.info(f"Created backgrounds directory: {BACKGROUNDS_DIR}")
        except Exception as e:
            root_logger.error(f"Failed to create backgrounds directory: {e}")
    
    # Start rate limiter cleanup tasks
    root_logger.info("Starting rate limiter cleanup tasks...")
    for limiter in bot.rate_limiters.values():
        limiter.start_cleanup_task(bot)
    
    root_logger.info("All services initialized successfully")
    return True


def setup_event_handlers(bot):
    """Register all event handlers"""
    root_logger.info("Setting up event handlers...")
    from modules.voice_activity import handle_voice_state_update
    
    @bot.event
    async def on_ready():
        """Called when the bot has successfully connected to Discord"""
        ready_msg = f"===== {bot.user} is now online! ====="
        root_logger.info(ready_msg)
        print(ready_msg)
        
        # Log additional information
        guild_count = len(bot.guilds)
        user_count = sum(g.member_count for g in bot.guilds)
        root_logger.info(f"Connected to {guild_count} guilds with {user_count} users")
        
        # Initialize all services
        root_logger.info("Beginning service initialization...")
        success = await initialize_services(bot)
        if not success:
            root_logger.error("Failed to initialize some services. Bot may not function correctly.")
            print("ERROR: Failed to initialize services - check logs")
        
        # Load cogs
        root_logger.info("Loading cogs...")
        await bot.setup_cogs()
        
        # Start performance monitoring last, after everything is initialized
        root_logger.info("Starting performance monitoring...")
        await start_monitoring(bot)
        
        root_logger.info(f"Bot is fully ready in {guild_count} guilds")
        print(f"Bot is fully ready in {guild_count} guilds")

    @bot.event
    async def on_message(message):
        """Handle incoming messages"""
        # Don't respond to bots
        if message.author.bot:
            return
        
        # Global rate limiting check
        is_global_limited, _ = await bot.rate_limiters["global"].check_rate_limit("commands")
        
        if is_global_limited:
            # If globally rate limited, only process critical commands
            ctx = await bot.get_context(message)
            
            if ctx.valid and ctx.command:
                critical_commands = ['help', 'dbstatus', 'ping', 'info']
                if ctx.command.name not in critical_commands:
                    return
        
        # Process commands first
        await bot.process_commands(message)
        
        # Then handle XP for messages
        await handle_message_xp(message, bot)

    @bot.event
    async def on_voice_state_update(member, before, after):
        """Handle voice state changes"""
        if member.bot:
            return
            
        channel_before = before.channel.name if before.channel else "None"
        channel_after = after.channel.name if after.channel else "None"
        root_logger.info(f"Voice state update: {member.name} moved from {channel_before} to {channel_after}")
        
        await handle_voice_state_update(bot, member, before, after)

    @bot.event
    async def on_reaction_add(reaction, user):
        """Handle reaction add events"""
        if user.bot:
            return
            
        root_logger.info(f"Reaction detected: {user.name} reacted with {reaction.emoji}")
        
        # Create a unique identifier for this reaction
        reaction_id = f"{reaction.message.id}:{user.id}:{reaction.emoji}"
        
        # Prevent duplicate processing
        if reaction_id in bot.processed_reactions:
            return
        
        # Add to processed reactions set
        bot.processed_reactions.add(reaction_id)
        await handle_reaction_xp(reaction, user)
    
    @bot.event 
    async def on_raw_reaction_add(payload):
        """Handle raw reaction events (for reactions to old messages)"""
        root_logger.info(f"Raw reaction detected: User ID {payload.user_id} added reaction {payload.emoji}")
        
        # Get the necessary objects from the payload
        guild = bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(payload.message_id)
            user = guild.get_member(payload.user_id)
            
            if not user or user.bot:
                return
            
            reaction_id = f"{payload.message_id}:{payload.user_id}:{str(payload.emoji)}"
            
            if reaction_id in bot.processed_reactions:
                return
            
            # Add to processed reactions set
            bot.processed_reactions.add(reaction_id)
            
            # Get the reaction from the message
            for reaction in message.reactions:
                if str(reaction.emoji) == str(payload.emoji):
                    await handle_reaction_xp(reaction, user)
                    break
        except Exception as e:
            root_logger.error(f"Error processing raw reaction: {e}")
    
    @bot.event
    async def on_disconnect():
        root_logger.warning("Bot disconnected from Discord")
        print("WARNING: Bot disconnected from Discord")
    
    @bot.event
    async def on_resumed():
        root_logger.info("Bot connection resumed")
        print("Bot connection resumed")
        # Call resume function in database module if it exists
        if hasattr(bot.db, 'on_resumed'):
            await bot.db.on_resumed()
            
    @bot.event
    async def on_error(event, *args, **kwargs):
        root_logger.error(f"Error in event {event}", exc_info=True)
        print(f"ERROR in event {event}")
        
    @bot.event
    async def on_command_error(ctx, error):
        """Handle command errors"""
        # Handle rate limit errors
        if isinstance(error, commands.CommandInvokeError) and isinstance(error.original, RateLimitExceeded):
            # Error is already handled in the decorator
            return
        
        # Handle other errors
        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown commands
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"⚠️ Missing required argument: {error.param.name}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"⚠️ Invalid argument: {str(error)}")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("❌ I don't have the necessary permissions to execute this command.")
        else:
            # Log unexpected errors
            root_logger.error(f"Command error: {error}", exc_info=error)
            await ctx.send("❌ An error occurred while processing your command.")
    
    root_logger.info("Event handlers registered successfully")


async def cleanup_resources(bot):
    """Clean up all resources during shutdown"""
    # Log the cleanup start
    root_logger.info("Executing graceful shutdown sequence...")
    print("Executing graceful shutdown sequence...")
    
    # Cancel any running background tasks
    for task in asyncio.all_tasks(asyncio.get_event_loop()):
        if task != asyncio.current_task():
            task.cancel()
    
    # Close database connection
    root_logger.info("Closing database connections...")
    await close_db()
    
    # Shutdown image thread pool
    if hasattr(bot, 'image_thread_pool'):
        root_logger.info("Shutting down image thread pool...")
        try:
            # Give pending tasks a chance to complete (timeout after 5 seconds)
            bot.image_thread_pool.shutdown(wait=True, timeout=5)
            root_logger.info("Image thread pool shut down successfully")
        except Exception as e:
            root_logger.warning(f"Error during image thread pool shutdown: {e}")
    
    # Stop voice tracking if active
    if hasattr(bot, 'voice_processor_running') and bot.voice_processor_running:
        root_logger.info("Stopping voice tracking...")
        bot.voice_processor_running = False
    
    # Close any open aiohttp sessions
    if hasattr(bot, 'session') and not bot.session.closed:
        root_logger.info("Closing HTTP sessions...")
        await bot.session.close()
    
    # Stop quest system
    if hasattr(bot, 'quest_manager'):
        root_logger.info("Stopping quest system...")
        await bot.quest_manager.stop()

    # Stop periodic processing
    stop_periodic_processing()
    root_logger.info("Stopping periodic processing...")
    
    # Stop performance monitoring
    stop_monitoring()
    root_logger.info("Stopping performance monitoring...")
    
    # Log completion
    root_logger.info("Cleanup process complete. Exiting gracefully.")
    print("Cleanup process complete. Exiting gracefully.")


def setup_signal_handlers(bot):
    """Set up signal handlers for graceful shutdown"""
    root_logger.info("Setting up signal handlers...")
    
    def signal_handler(sig, frame):
        print(f"Received signal {sig}. Starting shutdown...")
        try:
            # Run the cleanup coroutine
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, create a task
                asyncio.create_task(cleanup_resources(bot))
                # Give cleanup tasks a moment to complete
                time.sleep(2)
            else:
                # If loop is not running, run cleanup directly
                loop.run_until_complete(cleanup_resources(bot))
        except Exception as e:
            root_logger.error(f"Error during shutdown cleanup: {e}")
            print(f"Error during shutdown cleanup: {e}")
        
        # Exit with success code
        root_logger.info("Exiting now.")
        print("Exiting now.")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    root_logger.info("Signal handlers registered successfully")


def run_bot():
    """Main function to run the bot"""
    print("=== STARTING BOT ===")
    root_logger.info("=== STARTING BOT ===")
    root_logger.info(f"Python version: {sys.version}")
    root_logger.info(f"Discord.py version: {discord.__version__}")
    
    try:
        # Load configuration
        root_logger.info("Loading configuration...")
        config = load_config()
        root_logger.info("Configuration loaded successfully")
        
        # Define bot intents
        root_logger.info("Setting up intents...")
        intents = discord.Intents.all()
        intents.messages = True
        intents.guilds = True
        intents.voice_states = True
        intents.reactions = True
        intents.message_content = True
        
        # Create the bot instance
        root_logger.info("Creating bot instance...")
        bot = LevelingBot(command_prefix="!!", intents=intents)
        
        # This keeps heavy image operations off the main event loop
        root_logger.info("Creating image thread pool...")
        image_thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="img_"
        )
        bot.image_thread_pool = image_thread_pool
        
        # Register event handlers
        setup_event_handlers(bot)
        
        # Set up signal handlers for graceful shutdown
        setup_signal_handlers(bot)
        
        # Run bot with token
        root_logger.info("Connecting to Discord...")
        print("Connecting to Discord...")
        
        # Prevent Discord.py from setting up its own handler
        bot.run(config["TOKEN"], reconnect=True, log_handler=None)
        
    except Exception as e:
        root_logger.critical(f"Fatal error in run_bot: {e}", exc_info=True)
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Capture uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            # Let default handler handle KeyboardInterrupt
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
            
        root_logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        print(f"CRITICAL UNCAUGHT EXCEPTION: {exc_value}")
        
    # Set the exception hook
    sys.excepthook = handle_exception
    
    # Run the bot
    run_bot()