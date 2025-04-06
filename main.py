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
from datetime import datetime # Added for timezone awareness
from discord.ext import tasks
import json

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
    from modules.levels import handle_message_xp, handle_reaction_xp, award_xp_without_event_multiplier, send_level_up_notification, xp_to_next_level
    from modules.achievements import register_achievement_hooks
    from modules.quest_integration import initialize_quest_system, voice_handler_with_quests

    from utils.async_image_processor import start_image_processor
    from utils.image_templates import initialize_image_templates
    from utils.avatar_cache import avatar_cache
    from utils.background_api import BACKGROUNDS_DIR
    from utils.performance_monitoring import start_monitoring, stop_monitoring, time_function
    from utils.rate_limiter import RateLimiter, RateLimitExceeded
    from utils.database_migration import run_all_migrations
    
    # Database imports for event handling
    from database.event_db import (
        get_guild_event_settings,
        log_scheduled_event,
        update_scheduled_event_status,
        link_xp_boost_to_event,
        get_scheduled_event_by_id,
        record_event_attendance,
        get_event_attendees
    )
    from database.events import create_xp_boost_event, delete_xp_boost_event, update_xp_boost_start_time # Changed from database.xp_boost_events
    # Import dashboard sync functions
    from database.sync_dashboard import upsert_dashboard_user, upsert_dashboard_guild, sync_all_from_levels_table
    
    # Module imports for rewards
    from database.achievements import grant_achievement_db, check_event_attendance_achievements # Added the new check function
    
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
            "global": RateLimiter(max_calls=1000, period=60, name="global"),
            "quest": RateLimiter(max_calls=100, period=60, name="quest_progress")
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
            from cogs.event_commands import EventCommands

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

            await self.add_cog(EventCommands(self))
            root_logger.info("Added EventCommands cog")

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
    
    # Run database migrations
    root_logger.info("Running database migrations...")
    await run_all_migrations(bot)
    
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
    # Replace this import with one that will get the quest-aware handler
    from modules.quest_integration import voice_handler_with_quests
    
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
        else:
            # Run initial dashboard sync after services are up
            root_logger.info("Starting initial sync to dashboard tables...")
            await sync_all_from_levels_table(bot)
            root_logger.info("Initial dashboard sync complete.")
        
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
        
        # Use the quest-aware handler which will also call the original one
        await voice_handler_with_quests(bot, member, before, after)

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
    
    # ===== Scheduled Event Handlers =====

    @bot.event
    async def on_scheduled_event_create(event: discord.ScheduledEvent):
        """Handles creation of a new scheduled event and potentially creates the XP boost."""
        root_logger.info(f"Scheduled event created: {event.id} ({event.name}) in guild {event.guild_id}")
        guild_id = str(event.guild_id)
        event_id = str(event.id)
        
        try:
            # 1. Log the event first
            await log_scheduled_event(
                guild_id=guild_id,
                event_id=event_id,
                name=event.name,
                description=event.description or "",
                start_time=event.start_time.replace(tzinfo=None), # Store as naive UTC
                end_time=event.end_time.replace(tzinfo=None) if event.end_time else None, # Store as naive UTC
                event_type=str(event.entity_type.name).upper(),
                status=str(event.status.name).upper(),
                creator_id=str(event.creator_id)
            )
            
            # 2. Check settings and potentially create the associated XP boost immediately
            settings = await get_guild_event_settings(guild_id)
            if settings.get('enable_auto_boosts', False):
                multiplier = 1.0
                event_type_str = str(event.entity_type.name).lower()
                if event_type_str == 'voice':
                    multiplier = settings.get('default_boost_voice', 1.5)
                elif event_type_str == 'stage_instance':
                    multiplier = settings.get('default_boost_stage', 1.2)
                elif event_type_str == 'external':
                    multiplier = settings.get('default_boost_external', 1.1)
                
                # Ensure multiplier is > 1 and event has an end time
                if multiplier > 1.0 and event.end_time:
                    boost_name = f"Event Boost: {event.name[:50]}"
                    creator_id_str = str(event.creator_id) if event.creator_id else "SYSTEM"
                    
                    # Convert datetime objects to timestamps (float)
                    start_timestamp = event.start_time.timestamp()
                    end_timestamp = event.end_time.timestamp()
                    
                    boost_id = await create_xp_boost_event(
                        guild_id=guild_id,
                        start_time=start_timestamp, # Pass timestamp
                        end_time=end_timestamp,     # Pass timestamp
                        multiplier=multiplier,
                        name=boost_name,
                        created_by=creator_id_str
                    )
                    if boost_id:
                        await link_xp_boost_to_event(event_id, boost_id)
                        root_logger.info(f"Created XP boost {boost_id} ({multiplier:.2f}x) linked to scheduled event {event_id}")
                    else:
                         root_logger.error(f"Failed to create XP boost for scheduled event {event_id}")
                else:
                    root_logger.info(f"Skipping XP boost creation for scheduled event {event_id}: Auto-boosts enabled, but multiplier <= 1.0 or no end time.")
            else:
                 root_logger.info(f"Skipping XP boost creation for scheduled event {event_id}: Auto-boosts disabled for guild {guild_id}")

        except Exception as e:
            root_logger.error(f"Error handling created scheduled event {event.id}: {e}", exc_info=True)

    @bot.event
    async def on_scheduled_event_delete(event: discord.ScheduledEvent):
        """Handles deletion of a scheduled event."""
        root_logger.info(f"Scheduled event deleted: {event.id} ({event.name}) in guild {event.guild_id}")
        try:
            # Mark as cancelled in our DB
            await update_scheduled_event_status(str(event.id), "CANCELLED")
            # Optionally, end any associated XP boost if one was created prematurely
            logged_event = await get_scheduled_event_by_id(str(event.id))
            if logged_event and logged_event.get('associated_boost_id'):
                await delete_xp_boost_event(logged_event['associated_boost_id'])
                root_logger.info(f"Ended XP boost {logged_event['associated_boost_id']} associated with deleted event {event.id}")
        except Exception as e:
            root_logger.error(f"Error handling deleted scheduled event {event.id}: {e}", exc_info=True)

    @bot.event
    async def on_scheduled_event_update(before: discord.ScheduledEvent, after: discord.ScheduledEvent):
        """Handles updates to a scheduled event (status changes, edits, etc.)."""
        root_logger.info(f"Scheduled event updated: {after.id} ({after.name}) in guild {after.guild_id}. Status: {before.status.name} -> {after.status.name}")
        guild_id = str(after.guild_id)
        event_id = str(after.id)

        try:
            # Always log the latest event details
            await log_scheduled_event(
                guild_id=guild_id,
                event_id=event_id,
                name=after.name,
                description=after.description or "",
                start_time=after.start_time.replace(tzinfo=None),
                end_time=after.end_time.replace(tzinfo=None) if after.end_time else None,
                event_type=str(after.entity_type.name).upper(),
                status=str(after.status.name).upper(),
                creator_id=str(after.creator_id)
            )

            # Check for status changes to trigger actions
            if before.status != after.status:
                settings = await get_guild_event_settings(guild_id)
                logged_event = await get_scheduled_event_by_id(event_id)

                # --- Event Started ---                
                if after.status == discord.EventStatus.active:
                    # If event has an associated boost, update its start time to now
                    if logged_event and logged_event.get('associated_boost_id'):
                        current_time = time.time()
                        success = await update_xp_boost_start_time(logged_event['associated_boost_id'], current_time)
                        if success:
                            root_logger.info(f"Updated XP boost {logged_event['associated_boost_id']} start time to now for early-started event {event_id}")
                        else:
                            root_logger.error(f"Failed to update XP boost start time for event {event_id}")
                    root_logger.info(f"Scheduled event {event_id} is now ACTIVE.")

                # --- Event Completed ---                
                elif after.status == discord.EventStatus.completed:
                    # End the associated boost if it exists
                    if logged_event and logged_event.get('associated_boost_id'):
                        await delete_xp_boost_event(logged_event['associated_boost_id'])
                        root_logger.info(f"Ended XP boost {logged_event['associated_boost_id']} associated with completed event {event_id}")
                    
                    # Get attendees first
                    attendees = await get_event_attendees(event_id)
                    if attendees:
                        root_logger.info(f"Processing attendance for event {event_id} for {len(attendees)} users.")
                        
                        # Process each attendee
                        for attendee in attendees:
                            user_id = attendee['user_id']
                            member = after.guild.get_member(int(user_id))
                            if member and not member.bot:
                                try:
                                    # Check for GENERAL Event Attendance Achievements (counts) - Always do this
                                    await check_event_attendance_achievements(guild_id, user_id, bot)
                                    
                                    # Only process rewards if enabled
                                    if settings.get('enable_attendance_rewards', False):
                                        bonus_xp = settings.get('attendance_bonus_xp', 0)
                                        achievement_id_str = settings.get('attendance_achievement_id')

                                        # Award Bonus XP
                                        if bonus_xp > 0:
                                            await award_xp_without_event_multiplier(guild_id, user_id, bonus_xp, "event_attendance", bot)
                                            root_logger.debug(f"Awarded {bonus_xp} bonus XP to {member.name} ({user_id}) for attending event {event_id}")
                                        
                                        # Award SPECIFIC Attendance Achievement (if set)
                                        if achievement_id_str:
                                            try:
                                                achievement_id = int(achievement_id_str)
                                                granted = await grant_achievement_db(guild_id, user_id, achievement_id)
                                                if granted:
                                                    root_logger.info(f"Awarded achievement ID {achievement_id} to {member.name} ({user_id}) for attending event {event_id}")
                                                else:
                                                    root_logger.debug(f"Achievement ID {achievement_id} not newly granted to {user_id} (likely already possessed)." ) 
                                            except ValueError:
                                                root_logger.error(f"Invalid achievement ID format ({achievement_id_str}) configured for guild {guild_id}")
                                            except Exception as ach_error:
                                                root_logger.error(f"Error granting achievement {achievement_id_str} to {user_id}: {ach_error}")
                                except Exception as reward_error:
                                    root_logger.error(f"Error processing attendance for {user_id} for event {event_id}: {reward_error}")
                    else:
                        root_logger.info(f"No attendees found for completed event {event_id}")
                
                # --- Event Cancelled --- 
                elif after.status == discord.EventStatus.cancelled:
                    # End the associated boost if it exists
                    if logged_event and logged_event.get('associated_boost_id'):
                        await delete_xp_boost_event(logged_event['associated_boost_id'])
                        root_logger.info(f"Ended XP boost {logged_event['associated_boost_id']} associated with cancelled event {event_id}")

        except Exception as e:
            root_logger.error(f"Error handling updated scheduled event {event_id}: {e}", exc_info=True)

    @bot.event
    async def on_scheduled_event_user_add(event: discord.ScheduledEvent, user: discord.User):
        """Handles a user indicating interest or joining an event."""
        # We only care about actual users, not bots
        if user.bot:
            return
            
        root_logger.debug(f"User {user.id} ({user.name}) joined/interested in event {event.id} ({event.name}) in guild {event.guild_id}")
        try:
            # Record their attendance for potential rewards later
            await record_event_attendance(
                event_id=str(event.id),
                guild_id=str(event.guild_id),
                user_id=str(user.id),
                status="active"
            )
        except Exception as e:
             root_logger.error(f"Error recording attendance for user {user.id} at event {event.id}: {e}", exc_info=True)

    # (Optional) Add on_scheduled_event_user_remove if needed, but tracking additions is usually sufficient for rewards.
    
    root_logger.info("Scheduled event handlers registered successfully")

    root_logger.info("Event handlers registered successfully")

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        """Called when the bot joins a new guild."""
        root_logger.info(f"Joined new guild: {guild.name} ({guild.id})")
        # Add guild info to dashboard table, passing the bot object
        await upsert_dashboard_guild(bot, guild)

        # --- Add all existing members to the users table ---
        root_logger.info(f"Starting initial member sync for guild {guild.id} ({guild.name})...")
        members_synced = 0
        members_failed = 0
        admin_members_found = [] # Keep track of admins found during sync
        try:
            # Ensure member intent is loaded, might need fetch_members for large guilds
            # For now, assume guild.members is sufficiently populated upon join
            if not guild.chunked:
                 root_logger.warning(f"Guild {guild.id} is not chunked. Member list might be incomplete. Consider using fetch_members.")
                 # Optional: await guild.chunk() # Can be slow

            total_members = guild.member_count or len(guild.members) # Use member_count if available
            root_logger.info(f"Found {len(guild.members)} cached members (guild reports {total_members}). Upserting basic info...")

            for member in guild.members:
                try:
                    # Skip bots if desired (optional)
                    if member.bot:
                       continue
                    await upsert_dashboard_user(bot, member)
                    members_synced += 1

                    # Check for admin permissions
                    if member.guild_permissions.administrator:
                        admin_members_found.append(member.id)

                    # Optional: Add a small sleep for very large guilds to prevent overwhelming resources
                    # if members_synced % 100 == 0:
                    #    await asyncio.sleep(0.1)
                except Exception as member_error:
                    members_failed += 1
                    root_logger.error(f"Failed to upsert member {member.id} in guild {guild.id}: {member_error}")

            root_logger.info(f"Finished initial basic member sync for guild {guild.id}. Synced: {members_synced}, Failed: {members_failed}")

            # --- Update roles for admins found during sync ---
            if admin_members_found:
                root_logger.info(f"Attempting to assign 'admin' role to {len(admin_members_found)} members in guild {guild.id}...")
                admins_updated = 0
                admins_failed_update = 0
                # Use bot.db directly assuming it's the asyncpg pool
                if hasattr(bot, 'db') and bot.db:
                    try:
                        async with bot.db.acquire() as conn:
                            # Prepare the statement for efficiency
                            stmt = await conn.prepare("""
                                UPDATE users
                                SET role = $1::jsonb
                                WHERE discord_id = $2 AND role = $3::jsonb
                            """)
                            admin_role_json = json.dumps(["admin"])
                            user_role_json = json.dumps(["user"])

                            for admin_id in admin_members_found:
                                try:
                                    # Ensure ID is integer for the query
                                    result = await stmt.fetchval(admin_role_json, int(admin_id), user_role_json)
                                    # Note: asyncpg's execute/fetchval doesn't return rows affected easily for UPDATE
                                    # We assume success if no exception occurred for now.
                                    # A more robust check might involve a SELECT COUNT(*) before/after or using RETURNING clause if needed.
                                    admins_updated += 1 # Increment assuming success if no error
                                except Exception as role_update_error:
                                    admins_failed_update += 1
                                    root_logger.error(f"Failed to update role for admin {admin_id} in guild {guild.id}: {role_update_error}")
                        root_logger.info(f"Finished admin role assignment for guild {guild.id}. Attempted: {len(admin_members_found)}, Updated: {admins_updated}, Failed: {admins_failed_update}")
                    except Exception as db_conn_error:
                         root_logger.error(f"Database connection error during admin role update for guild {guild.id}: {db_conn_error}")
                else:
                     root_logger.error(f"Database pool (bot.db) not available for admin role update in guild {guild.id}.")
            else:
                root_logger.info(f"No admin members identified during sync for guild {guild.id}.")

        except Exception as e:
            root_logger.error(f"Error during bulk member sync or role assignment for guild {guild.id}: {e}")
        # --- End member sync ---

    @bot.event
    async def on_guild_update(before, after):
        """Called when a guild's details change."""
        if before.name != after.name or before.icon != after.icon or before.owner_id != after.owner_id:
            root_logger.info(f"Guild {after.id} updated. Syncing changes to dashboard table.")
            # Update guild info in dashboard table, passing the bot object
            await upsert_dashboard_guild(bot, after)

    @bot.event
    async def on_member_join(member):
        """Called when a new member joins a guild."""
        root_logger.info(f"Member {member.name} ({member.id}) joined guild {member.guild.name} ({member.guild.id})")
        if member.bot: # Skip bots
             return

        # Add user's basic info to dashboard table
        await upsert_dashboard_user(bot, member)
        # Ensure the guild is also present (idempotent)
        await upsert_dashboard_guild(bot, member.guild)

        # --- Assign admin role if applicable ---
        if member.guild_permissions.administrator:
            root_logger.info(f"New member {member.id} has admin permissions in guild {member.guild.id}. Attempting role update.")
            if hasattr(bot, 'db') and bot.db:
                try:
                    async with bot.db.acquire() as conn:
                        admin_role_json = json.dumps(["admin"])
                        user_role_json = json.dumps(["user"])
                        await conn.execute("""
                            UPDATE users SET role = $1::jsonb
                            WHERE discord_id = $2 AND role = $3::jsonb
                        """, admin_role_json, member.id, user_role_json)
                        root_logger.info(f"Assigned 'admin' role to new member {member.id}.")
                except Exception as e:
                    root_logger.error(f"Failed to update role for new admin member {member.id}: {e}")
            else:
                root_logger.error(f"Database pool (bot.db) not available for new member role update (member: {member.id}).")
        # --- End role assignment ---

    @bot.event
    async def on_member_update(before, after):
        """Called when a member's details change (username, avatar, etc.)."""
        # Upsert basic info on profile changes
        if before.name != after.name or before.discriminator != after.discriminator or before.display_avatar != after.display_avatar:
            root_logger.info(f"Member {after.id} updated profile in guild {after.guild.id}. Syncing changes to dashboard table.")
            await upsert_dashboard_user(bot, after)

        # --- Handle potential permission changes ---
        # Check if permissions might have changed (specifically gaining admin)
        # Note: This check is simplified. Role changes are a better indicator but more complex to track.
        if not before.guild_permissions.administrator and after.guild_permissions.administrator:
            root_logger.info(f"Member {after.id} gained admin permissions in guild {after.guild.id}. Attempting role update.")
            if hasattr(bot, 'db') and bot.db:
                 try:
                    async with bot.db.acquire() as conn:
                        admin_role_json = json.dumps(["admin"])
                        user_role_json = json.dumps(["user"])
                        await conn.execute("""
                            UPDATE users SET role = $1::jsonb
                            WHERE discord_id = $2 AND role = $3::jsonb
                        """, admin_role_json, after.id, user_role_json)
                        root_logger.info(f"Assigned 'admin' role to updated member {after.id}.")
                 except Exception as e:
                    root_logger.error(f"Failed to update role for updated admin member {after.id}: {e}")
            else:
                 root_logger.error(f"Database pool (bot.db) not available for member update role assignment (member: {after.id}).")
        # Optional: Handle losing admin permissions (could reset role to 'user')
        # elif before.guild_permissions.administrator and not after.guild_permissions.administrator:
        #     # Logic to potentially downgrade role from 'admin' back to 'user' if appropriate
        #     pass

    @bot.event
    async def on_user_update(before, after):
        """Called when a user's global details change (username, avatar)."""
        if before.name != after.name or before.discriminator != after.discriminator or before.avatar != after.avatar:
            root_logger.info(f"User {after.id} updated globally. Syncing changes to dashboard table.")
            # Update user info in dashboard table, passing the bot object
            await upsert_dashboard_user(bot, after)


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