import discord
import os
import sys
import time
import signal
import logging
import asyncio
import concurrent.futures
from config import load_config
from discord.ext import commands
from collections import OrderedDict
from cogs.admin import AdminCommands
from cogs.help import CustomHelpCommand
from utils import cairo_image_generator
from utils.image_templates import initialize_image_templates
from cogs.leveling import LevelingCommands
from utils.avatar_cache import avatar_cache
from cogs.config_commands import ConfigCommands
from cogs.card_customization import BackgroundCommands
from utils.rate_limiter import RateLimiter, RateLimitExceeded
from modules.levels import handle_message_xp
from modules.levels import handle_reaction_xp
from modules.databasev2 import init_db, close_db
from utils.background_api import BACKGROUNDS_DIR
from modules.voice_activity import handle_voice_state_update
from utils.async_image_processor import start_image_processor
from modules.voice_activity import start_voice_tracking, handle_voice_state_update

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)

# Initialize the bot
def setup_bot():
    # Define bot intents
    intents = discord.Intents.all()
    intents.messages = True
    intents.guilds = True
    intents.voice_states = True
    intents.reactions = True  # Explicitly enable reaction intents
    intents.message_content = True  # Enable message content if needed

    # Create a custom bot class that handles speaking
    class LevelingBot(commands.Bot):
        async def setup_hook(self):
            for guild in self.guilds:
                for vc in guild.voice_channels:
                    vc.guild.voice_client

        async def on_voice_state_update(self, member, before, after):
            await handle_voice_state_update(self, member, before, after)  
            
    # Create the bot instance
    bot = commands.Bot(command_prefix="!!", intents=intents)
    bot.processed_reactions = set()

    # Add cogs
    async def setup_cogs():
        await bot.add_cog(LevelingCommands(bot))
        await bot.add_cog(AdminCommands(bot))
        await bot.add_cog(CustomHelpCommand(bot))
        await bot.add_cog(ConfigCommands(bot)) 
        await bot.add_cog(BackgroundCommands(bot)) 
        await bot.tree.sync()

    # Make this method accessible
    bot.setup_cogs = setup_cogs

    # Add rate limiters for different subsystems
    bot.rate_limiters = {
        "image": RateLimiter(max_calls=5, period=60, name="image_generation"),  # 5 images per minute per user
        "voice_xp": RateLimiter(max_calls=10, period=60, name="voice_xp"),      # 10 voice XP awards per minute per user
        "command": RateLimiter(max_calls=30, period=60, name="general_commands"), # 30 commands per minute per user
        "leaderboard": RateLimiter(max_calls=2, period=30, name="leaderboard"),   # 2 leaderboard commands per 30 sec
        "guild": RateLimiter(max_calls=200, period=60, name="guild_commands"),    # 200 commands per minute per guild
        "global": RateLimiter(max_calls=1000, period=60, name="global")           # 1000 total commands per minute
    }
    
    return bot

# Run the bot
def run_bot():
    # Load configuration
    config = load_config()

    # Setup bot
    bot = setup_bot()

    # This keeps heavy image operations off the main event loop
    image_thread_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=2,  # Adjust based on your server's CPU cores
        thread_name_prefix="img_"
    )

    # Make the thread pool available to the bot object
    bot.image_thread_pool = image_thread_pool

    # Register event handlers
    @bot.event
    async def on_ready():
        logging.info(f"{bot.user} is now online!")
        success = await init_db(bot)
        if success:
            logging.info("Database initialized successfully")
        else:
            logging.error("Failed to initialize database")
            
        await start_voice_tracking(bot)
        
        # Start the image processor
        await start_image_processor(bot)
        logging.info("Image processor started")

        avatar_cache.start_cleanup_task(bot.loop)
        logging.info(f"Avatar cache initialized (max size: {avatar_cache.max_size})")
        
        bot.loop.run_in_executor(
            bot.image_thread_pool, 
            initialize_image_templates,
            bot
        )

        # Ensure background directory exists and is accessible
        if not os.path.exists(BACKGROUNDS_DIR):
            try:
                os.makedirs(BACKGROUNDS_DIR, exist_ok=True)
                logging.info(f"Created backgrounds directory: {BACKGROUNDS_DIR}")
            except Exception as e:
                logging.error(f"Failed to create backgrounds directory: {e}")
        
        # Start rate limiter cleanup tasks
        for limiter in bot.rate_limiters.values():
            limiter.start_cleanup_task(bot)
        logging.info("Rate limiters initialized")
        
        await bot.setup_cogs()
        await bot.tree.sync()
        logging.info(f"Bot is ready in {len(bot.guilds)} guilds")

    @bot.event
    async def on_message(message):
        # Don't respond to bots
        if message.author.bot:
            return
        
        # Global rate limiting check
        is_global_limited, _ = await bot.rate_limiters["global"].check_rate_limit("commands")
        
        if is_global_limited:
            # If we're globally rate limited, only process certain critical commands
            # Parse the command so we can check its name
            ctx = await bot.get_context(message)
            
            if ctx.valid and ctx.command:
                # Allow certain critical commands even during global rate limiting
                critical_commands = ['help', 'dbstatus', 'ping', 'info']
                if ctx.command.name not in critical_commands:
                    # Silently ignore non-critical commands during global rate limiting
                    return
                
        # Process commands first
        await bot.process_commands(message)

        # Then handle XP for messages
        await handle_message_xp(message, bot)

    @bot.event
    async def on_voice_state_update(member, before, after):
        
        logging.info(f"Voice state update: {member.name} moved from {before.channel} to {after.channel}")
        await handle_voice_state_update(bot, member, before, after)

    @bot.event
    async def on_reaction_add(reaction, user):
        logging.info(f"Reaction detected: {user.name} reacted with {reaction.emoji} to a message")

        # Create a unique identifier for this reaction
        reaction_id = f"{reaction.message.id}:{user.id}:{reaction.emoji}"

        # Check if this reaction has already been processed
        if reaction_id in bot.processed_reactions:
            return  # Skip processing if already handled
        
        # Add to processed reactions set
        bot.processed_reactions.add(reaction_id)
        await handle_reaction_xp(reaction, user)
        logging.info(f"Reaction XP processed for {user.name}")
    
    @bot.event 
    async def on_raw_reaction_add(payload):
        logging.info(f"Raw reaction detected: User ID {payload.user_id} added reaction {payload.emoji}")
        
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
                return  # Skip processing if already handled
        
            # Add to processed reactions set
            bot.processed_reactions.add(reaction_id)

            # Get the reaction from the message
            for reaction in message.reactions:
                if str(reaction.emoji) == str(payload.emoji):
                    await handle_reaction_xp(reaction, user)
                    logging.info(f"Raw reaction XP processed for {user.name}")
                    break
        except Exception as e:
            logging.error(f"Error processing raw reaction: {e}")
    
    @bot.event
    async def on_disconnect():
        logging.warning("Bot disconnected from Discord")
    
    @bot.event
    async def on_resumed():
        logging.info("Bot connection resumed")
        # Call resume function in database module if it exists
        if hasattr(bot.db, 'on_resumed'):
            await bot.db.on_resumed()
            
    @bot.event
    async def on_error(event, *args, **kwargs):
        logging.error(f"Error in event {event}", exc_info=True)
        
    @bot.event
    async def on_command_error(ctx, error):
        # Handle rate limit errors
        if isinstance(error, commands.CommandInvokeError) and isinstance(error.original, RateLimitExceeded):
            # Error is already handled in the decorator by sending a message
            return
        
        # Handle other errors
        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown commands
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"⚠️ Missing required argument: {error.param.name}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"⚠️ Invalid argument: {str(error)}")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(f"❌ You don't have permission to use this command.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"❌ I don't have the necessary permissions to execute this command.")
        else:
            # Log unexpected errors
            logging.error(f"Command error: {error}", exc_info=error)
            await ctx.send("❌ An error occurred while processing your command.")
            
    # Clean shutdown handler
    def signal_handler(sig, frame):
        async def cleanup():
            # Log the cleanup start
            logging.info("Executing graceful shutdown sequence...")
            
            # Cancel any running background tasks
            for task in asyncio.all_tasks(asyncio.get_event_loop()):
                if task != asyncio.current_task():
                    task.cancel()
            
            # Close database connection
            logging.info("Closing database connections...")
            await close_db()
            
            # Shutdown image thread pool gracefully if it exists
            if hasattr(bot, 'image_thread_pool'):
                logging.info("Shutting down image thread pool...")
                try:
                    # Give pending tasks a chance to complete (timeout after 5 seconds)
                    bot.image_thread_pool.shutdown(wait=True, timeout=5)
                    logging.info("Image thread pool shut down successfully")
                except Exception as e:
                    logging.warning(f"Error during image thread pool shutdown: {e}")
            
            # Stop voice tracking if active
            if hasattr(bot, 'voice_processor_running') and bot.voice_processor_running:
                logging.info("Stopping voice tracking...")
                bot.voice_processor_running = False
            
            # Close any open aiohttp sessions
            if hasattr(bot, 'session') and not bot.session.closed:
                logging.info("Closing HTTP sessions...")
                await bot.session.close()
            
            # Log completion
            logging.info("Cleanup process complete. Exiting gracefully.")
        
        try:
            # Run the cleanup coroutine
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, create a task
                asyncio.create_task(cleanup())
                # Give cleanup tasks a moment to complete
                time.sleep(2)
            else:
                # If loop is not running, run cleanup directly
                loop.run_until_complete(cleanup())
        except Exception as e:
            logging.error(f"Error during shutdown cleanup: {e}")
        
        # Exit with success code
        logging.info("Exiting now.")
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run bot with token
    bot.run(config["TOKEN"], reconnect=True)

if __name__ == "__main__":
    run_bot()