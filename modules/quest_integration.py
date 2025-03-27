"""
Quest system integration with bot events and background tasks.
"""
import discord
import asyncio
import logging
import random
from datetime import datetime, timedelta
from discord.ext import tasks

from config import load_config, QUEST_SETTINGS
from database import (
    get_guild_active_quests,
    mark_quests_inactive,
    check_quest_progress,
    award_quest_rewards,
    get_user_active_quests,
    create_quest,
    get_quest_channel,
    get_level_up_channel,
    get_quest_cooldowns
)

# ===== QUEST INTEGRATION FUNCTIONS =====

async def handle_message_quests(message, bot):
    """Handle quest progress for messages"""
    # Ignore messages from bots
    if message.author.bot:
        return

    # Only handle messages in guild channels
    if not message.guild:
        return

    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    
    # Check rate limiting for quest progress
    quest_key = f"quest:message:{user_id}"
    is_limited, wait_time = await bot.rate_limiters["quest"].check_rate_limit(quest_key)
    
    # Additional cooldown specific to message quests
    message_quest_key = f"quest_message:{user_id}"
    # Get server-specific cooldown settings
    quest_cooldowns = await get_quest_cooldowns(guild_id)
    cooldown = quest_cooldowns.get("total_messages", QUEST_SETTINGS["COOLDOWNS"]["total_messages"])
    is_message_limited = False
    
    if cooldown > 0:
        # Create a custom limiter for this specific quest type with the configured cooldown
        if not hasattr(bot, "_message_quest_limiter"):
            bot._message_quest_limiter = {}
        
        if guild_id not in bot._message_quest_limiter:
            from utils.rate_limiter import RateLimiter
            bot._message_quest_limiter[guild_id] = RateLimiter(max_calls=1, period=cooldown, name="message_quest")
            
        is_message_limited, _ = await bot._message_quest_limiter[guild_id].check_rate_limit(user_id)
    
    # If either limiter is triggered, skip quest progress
    if is_limited or is_message_limited:
        if is_limited:
            logging.debug(f"Message quest rate limited for user {user_id}, try again in {wait_time}s")
        else:
            logging.debug(f"Message quest cooldown active for user {user_id}")
        return
    
    # Update total_messages counter and check for completed quests
    from database import update_activity_counter_db
    new_value, _ = await update_activity_counter_db(guild_id, user_id, "total_messages", 1)
    
    # Check quest progress with new counter value
    newly_completed = await check_quest_progress(
        guild_id, user_id, "total_messages", new_value
    )
    
    # Award rewards for completed quests
    for quest in newly_completed:
        await award_quest_rewards(guild_id, user_id, quest['id'], message.author)
        await send_quest_completion_notification(message.channel, message.author, quest)

async def handle_reaction_quests(reaction, user):
    """Handle quest progress for reactions"""
    if user.bot or not reaction.message.guild:
        return
        
    guild_id = str(reaction.message.guild.id)
    user_id = str(user.id)
    
    # Check rate limiting for quest progress
    quest_key = f"quest:reaction:{user_id}"
    is_limited, wait_time = await reaction.message.guild.bot.rate_limiters["quest"].check_rate_limit(quest_key)
    
    # Additional cooldown specific to reaction quests
    reaction_quest_key = f"quest_reaction:{user_id}"
    # Get server-specific cooldown settings
    quest_cooldowns = await get_quest_cooldowns(guild_id)
    cooldown = quest_cooldowns.get("total_reactions", QUEST_SETTINGS["COOLDOWNS"]["total_reactions"])
    is_reaction_limited = False
    
    if cooldown > 0:
        # Create a custom limiter for this specific quest type with the configured cooldown
        bot = reaction.message.guild.bot
        if not hasattr(bot, "_reaction_quest_limiter"):
            bot._reaction_quest_limiter = {}
        
        if guild_id not in bot._reaction_quest_limiter:
            from utils.rate_limiter import RateLimiter
            bot._reaction_quest_limiter[guild_id] = RateLimiter(max_calls=1, period=cooldown, name="reaction_quest")
            
        is_reaction_limited, _ = await bot._reaction_quest_limiter[guild_id].check_rate_limit(user_id)
    
    # If either limiter is triggered, skip quest progress
    if is_limited or is_reaction_limited:
        if is_limited:
            logging.debug(f"Reaction quest rate limited for user {user_id}, try again in {wait_time}s")
        else:
            logging.debug(f"Reaction quest cooldown active for user {user_id}")
        return
    
    # Update total_reactions counter and check for completed quests
    from database import update_activity_counter_db
    new_value, _ = await update_activity_counter_db(guild_id, user_id, "total_reactions", 1)
    
    # Check quest progress with new counter value
    newly_completed = await check_quest_progress(
        guild_id, user_id, "total_reactions", new_value
    )
    
    # Award rewards for completed quests
    for quest in newly_completed:
        await award_quest_rewards(guild_id, user_id, quest['id'], user)
        if hasattr(reaction.message.channel, "send"):
            await send_quest_completion_notification(reaction.message.channel, user, quest)

async def handle_command_quests(ctx):
    """Handle quest progress for commands"""
    if ctx.author.bot or not ctx.guild:
        return
    
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    # Check rate limiting for quest progress
    quest_key = f"quest:command:{user_id}"
    is_limited, wait_time = await ctx.bot.rate_limiters["quest"].check_rate_limit(quest_key)
    
    # Additional cooldown specific to command quests
    command_quest_key = f"quest_command:{user_id}"
    # Get server-specific cooldown settings
    quest_cooldowns = await get_quest_cooldowns(guild_id)
    cooldown = quest_cooldowns.get("commands_used", QUEST_SETTINGS["COOLDOWNS"]["commands_used"])
    is_command_limited = False
    
    if cooldown > 0:
        # Create a custom limiter for this specific quest type with the configured cooldown
        if not hasattr(ctx.bot, "_command_quest_limiter"):
            ctx.bot._command_quest_limiter = {}
        
        if guild_id not in ctx.bot._command_quest_limiter:
            from utils.rate_limiter import RateLimiter
            ctx.bot._command_quest_limiter[guild_id] = RateLimiter(max_calls=1, period=cooldown, name="command_quest")
            
        is_command_limited, _ = await ctx.bot._command_quest_limiter[guild_id].check_rate_limit(user_id)
    
    # If either limiter is triggered, skip quest progress
    if is_limited or is_command_limited:
        if is_limited:
            logging.debug(f"Command quest rate limited for user {user_id}, try again in {wait_time}s")
        else:
            logging.debug(f"Command quest cooldown active for user {user_id}")
        return
    
    # Update commands_used counter and check for completed quests
    from database import update_activity_counter_db
    new_value, _ = await update_activity_counter_db(guild_id, user_id, "commands_used", 1)
    
    # Check quest progress with new counter value
    newly_completed = await check_quest_progress(
        guild_id, user_id, "commands_used", new_value
    )
    
    # Award rewards for completed quests
    for quest in newly_completed:
        await award_quest_rewards(guild_id, user_id, quest['id'], ctx.author)
        await send_quest_completion_notification(ctx.channel, ctx.author, quest)

async def handle_voice_quests(guild_id, user_id, seconds, member):
    """Handle quest progress for voice activity"""
    if seconds <= 0 or not member or member.bot:
        return
    
    logging.info(f"Processing voice quests for {member.name}: {seconds} seconds")
    
    # Check rate limiting for quest progress
    quest_key = f"quest:voice:{user_id}"
    is_limited, wait_time = await member.guild.bot.rate_limiters["quest"].check_rate_limit(quest_key)
    
    # Additional cooldown specific to voice quests - usually set to 0 as voice already has inherent rate limiting
    # Get server-specific cooldown settings
    quest_cooldowns = await get_quest_cooldowns(guild_id)
    cooldown = quest_cooldowns.get("voice_time_seconds", QUEST_SETTINGS["COOLDOWNS"]["voice_time_seconds"])
    is_voice_limited = False
    
    if cooldown > 0:
        # Create a custom limiter for this specific quest type with the configured cooldown
        bot = member.guild.bot
        if not hasattr(bot, "_voice_quest_limiter"):
            bot._voice_quest_limiter = {}
        
        if guild_id not in bot._voice_quest_limiter:
            from utils.rate_limiter import RateLimiter
            bot._voice_quest_limiter[guild_id] = RateLimiter(max_calls=1, period=cooldown, name="voice_quest")
            
        is_voice_limited, _ = await bot._voice_quest_limiter[guild_id].check_rate_limit(user_id)
    
    # If either limiter is triggered, skip quest progress
    if is_limited or is_voice_limited:
        if is_limited:
            logging.debug(f"Voice quest rate limited for user {user_id}, try again in {wait_time}s")
        else:
            logging.debug(f"Voice quest cooldown active for user {user_id}")
        return
    
    # Update voice_time_seconds counter and check for completed quests
    from database import update_activity_counter_db
    try:
        new_value, newly_completed = await update_activity_counter_db(guild_id, user_id, "voice_time_seconds", seconds)
        
        logging.info(f"Updated voice_time_seconds for {member.name}: new total={new_value} seconds ({new_value//60} minutes)")
        
        if newly_completed:
            logging.info(f"User {member.name} completed {len(newly_completed)} voice quests: {[q['name'] for q in newly_completed]}")
        
        # Award rewards for completed quests
        for quest in newly_completed:
            await award_quest_rewards(guild_id, user_id, quest['id'], member)
            
            # Try to find an appropriate channel to send the notification
            channel = None
            
            # Try to get quest channel first
            quest_channel_id = await get_quest_channel(guild_id)
            if quest_channel_id:
                try:
                    channel = member.guild.get_channel(int(quest_channel_id))
                except:
                    channel = None
            
            # Try to get level-up channel as fallback
            if not channel:
                level_channel_id = await get_level_up_channel(guild_id)
                if level_channel_id:
                    try:
                        channel = member.guild.get_channel(int(level_channel_id))
                    except:
                        channel = None
            
            # Fallback to system channel
            if not channel and member.guild.system_channel:
                channel = member.guild.system_channel
            
            # Send notification if we found a channel
            if channel:
                await send_quest_completion_notification(channel, member, quest)
    except Exception as e:
        logging.error(f"Error processing voice quest data: {e}")

async def send_quest_completion_notification(channel, user, quest):
    """Send a notification when a quest is completed"""
    embed = discord.Embed(
        title="🎯 Quest Completed!",
        description=f"{user.mention} has completed a quest!",
        color=discord.Color.gold()
    )
    
    embed.add_field(name="Quest", value=quest['name'], inline=False)
    embed.add_field(name="Reward", value=f"{quest['reward_xp']} XP", inline=True)
    
    if 'reward_multiplier' in quest and quest['reward_multiplier'] > 1.0:
        embed.add_field(
            name="Bonus", 
            value=f"{quest['reward_multiplier']}x XP multiplier", 
            inline=True
        )
    
    if user.avatar:
        embed.set_thumbnail(url=user.avatar.url)
    
    try:
        # Try to get quest channel first
        quest_channel_id = await get_quest_channel(str(channel.guild.id))
        
        if quest_channel_id:
            quest_channel = channel.guild.get_channel(int(quest_channel_id))
            if quest_channel:
                await quest_channel.send(embed=embed)
            else:
                # If quest channel not found, fall back to level up channel
                level_up_channel_id = await get_level_up_channel(str(channel.guild.id))
                if level_up_channel_id:
                    level_channel = channel.guild.get_channel(int(level_up_channel_id))
                    if level_channel:
                        await level_channel.send(embed=embed)
                    else:
                        # If level up channel not found, fall back to system channel
                        if channel.guild.system_channel:
                            await channel.guild.system_channel.send(embed=embed)
                else:
                    # If no level up channel set, use system channel
                    if channel.guild.system_channel:
                        await channel.guild.system_channel.send(embed=embed)
        else:
            # If no quest channel set, try level up channel
            level_up_channel_id = await get_level_up_channel(str(channel.guild.id))
            if level_up_channel_id:
                level_channel = channel.guild.get_channel(int(level_up_channel_id))
                if level_channel:
                    await level_channel.send(embed=embed)
                else:
                    # If level up channel not found, fall back to system channel
                    if channel.guild.system_channel:
                        await channel.guild.system_channel.send(embed=embed)
            else:
                # If no level up channel set, use system channel
                if channel.guild.system_channel:
                    await channel.guild.system_channel.send(embed=embed)
    except Exception as e:
        logging.error(f"Failed to send quest completion notification: {e}")

# ===== QUEST LIFECYCLE MANAGEMENT =====

class QuestManager:
    """Manager for quest lifecycle"""
    
    def __init__(self, bot):
        self.bot = bot
        self.daily_reset_time = 0  # Hour of day for daily reset (UTC)
        self.weekly_reset_day = 0  # Day of week for weekly reset (0 = Monday)
        
    def start(self):
        """Start all background tasks"""
        self.check_quest_resets.start()
        logging.info("Started quest reset background task")
        
    def stop(self):
        """Stop all background tasks"""
        if self.check_quest_resets.is_running():
            self.check_quest_resets.cancel()
            logging.info("Stopped quest reset background task")
    
    @tasks.loop(hours=1)
    async def check_quest_resets(self):
        """Check if it's time to reset daily or weekly quests"""
        now = datetime.utcnow()
        
        # Check for daily reset
        if now.hour == self.daily_reset_time:
            logging.info("Performing daily quest reset")
            await self.reset_daily_quests()
        
        # Check for weekly reset (default: Monday)
        if now.weekday() == self.weekly_reset_day and now.hour == self.daily_reset_time:
            logging.info("Performing weekly quest reset")
            await self.reset_weekly_quests()
    
    @check_quest_resets.before_loop
    async def before_check_quest_resets(self):
        """Wait until the bot is ready before starting the loop"""
        await self.bot.wait_until_ready()
        
        # Calculate time until next hour to sync with clock
        now = datetime.utcnow()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        wait_seconds = (next_hour - now).total_seconds()
        
        # Wait until the next hour exactly
        await asyncio.sleep(wait_seconds)
    
    async def reset_daily_quests(self):
        """Reset daily quests across all guilds"""
        try:
            # Reset each guild's daily quests
            for guild in self.bot.guilds:
                guild_id = str(guild.id)
                
                # Mark old daily quests as inactive
                await mark_quests_inactive(guild_id, "daily")
                logging.info(f"Daily quests reset for guild {guild.name} ({guild_id})")
                
                # Auto-create new daily quests if enabled
                await self.create_daily_quests(guild_id)
                
        except Exception as e:
            logging.error(f"Error in daily quest reset: {e}")
    
    async def reset_weekly_quests(self):
        """Reset weekly quests across all guilds"""
        try:
            # Reset each guild's weekly quests
            for guild in self.bot.guilds:
                guild_id = str(guild.id)
                
                # Mark old weekly quests as inactive
                await mark_quests_inactive(guild_id, "weekly")
                logging.info(f"Weekly quests reset for guild {guild.name} ({guild_id})")
                
                # Auto-create new weekly quests if enabled
                await self.create_weekly_quests(guild_id)
                
        except Exception as e:
            logging.error(f"Error in weekly quest reset: {e}")
    
    async def create_daily_quests(self, guild_id):
        """Auto-create new daily quests for a guild"""
        # This would be configured per guild
        # For now, just create some sample quests
        
        # Daily quest templates
        daily_quests = [
            {
                "name": "Daily Messenger",
                "description": "Send messages in any channel",
                "requirement_type": "total_messages",
                "requirement_value": 10,
                "reward_xp": 100,
                "difficulty": "easy"
            },
            {
                "name": "Daily Reactor",
                "description": "Add reactions to messages",
                "requirement_type": "total_reactions",
                "requirement_value": 5,
                "reward_xp": 75,
                "difficulty": "easy"
            },
            {
                "name": "Daily Voice",
                "description": "Spend time in voice channels",
                "requirement_type": "voice_time_seconds",
                "requirement_value": 5 * 60,  # 5 minutes in seconds
                "reward_xp": 150,
                "difficulty": "medium"
            },
            {
                "name": "Daily Commander",
                "description": "Use bot commands",
                "requirement_type": "commands_used",
                "requirement_value": 3,
                "reward_xp": 50,
                "difficulty": "easy"
            }
        ]
        
        # Choose 2-3 random quests from the templates
        num_quests = random.randint(2, 3)
        selected_quests = random.sample(daily_quests, num_quests)
        
        for quest in selected_quests:
            await create_quest(
                guild_id=guild_id,
                name=quest["name"],
                description=quest["description"],
                quest_type="daily",
                requirement_type=quest["requirement_type"],
                requirement_value=quest["requirement_value"],
                reward_xp=quest["reward_xp"],
                difficulty=quest["difficulty"],
                refresh_cycle="daily"
            )
        
        logging.info(f"Created {len(selected_quests)} daily quests for guild {guild_id}")
    
    async def create_weekly_quests(self, guild_id):
        """Auto-create new weekly quests for a guild"""
        # Weekly quest templates
        weekly_quests = [
            {
                "name": "Weekly Communicator",
                "description": "Send messages throughout the week",
                "requirement_type": "total_messages",
                "requirement_value": 50,
                "reward_xp": 500,
                "difficulty": "medium"
            },
            {
                "name": "Weekly Engager",
                "description": "React to lots of messages",
                "requirement_type": "total_reactions",
                "requirement_value": 20,
                "reward_xp": 250,
                "difficulty": "easy"
            },
            {
                "name": "Weekly Voice Chatter",
                "description": "Spend time in voice channels with friends",
                "requirement_type": "voice_time_seconds",
                "requirement_value": 30 * 60,  # 30 minutes in seconds
                "reward_xp": 750,
                "difficulty": "hard"
            },
            {
                "name": "Weekly Commander",
                "description": "Make good use of bot commands",
                "requirement_type": "commands_used",
                "requirement_value": 10,
                "reward_xp": 300,
                "difficulty": "medium"
            }
        ]
        
        # Choose 2-3 random quests from the templates
        num_quests = random.randint(2, 3)
        selected_quests = random.sample(weekly_quests, num_quests)
        
        for quest in selected_quests:
            await create_quest(
                guild_id=guild_id,
                name=quest["name"],
                description=quest["description"],
                quest_type="weekly",
                requirement_type=quest["requirement_type"],
                requirement_value=quest["requirement_value"],
                reward_xp=quest["reward_xp"],
                difficulty=quest["difficulty"],
                refresh_cycle="weekly"
            )
        
        logging.info(f"Created {len(selected_quests)} weekly quests for guild {guild_id}")

# ===== SETUP FUNCTIONS =====

def register_quest_hooks(bot):
    """Register quest system hooks with the bot"""
    quest_manager = QuestManager(bot)
    bot.quest_manager = quest_manager
    
    # Store the original event handlers
    original_on_message = getattr(bot, "on_message", None)
    original_on_reaction_add = getattr(bot, "on_reaction_add", None)
    original_on_command_completion = getattr(bot, "on_command_completion", None)
    
    # Create new event handlers that include quest processing
    async def on_message(message):
        # Call the original handler first
        if original_on_message:
            await original_on_message(message)
        
        # Process message for quests
        await handle_message_quests(message, bot)
    
    async def on_reaction_add(reaction, user):
        # Call the original handler first
        if original_on_reaction_add:
            await original_on_reaction_add(reaction, user)
        
        # Process reaction for quests
        await handle_reaction_quests(reaction, user)
    
    async def on_command_completion(ctx):
        # Call the original handler first
        if original_on_command_completion:
            await original_on_command_completion(ctx)
        
        # Process command for quests
        await handle_command_quests(ctx)
    
    # Override the event handlers
    bot.on_message = on_message
    bot.on_reaction_add = on_reaction_add
    bot.on_command_completion = on_command_completion
    
    # Register with voice activity system
    from modules.voice_activity import handle_voice_state_update as original_voice_handler
    
    # Preserve the original voice handler but add quest processing
    async def voice_handler_with_quests(bot, member, before, after):
        # Call the original handler first
        await original_voice_handler(bot, member, before, after)
        
        # If user is leaving a channel, process voice time for quests
        if before.channel and not after.channel:
            logging.info(f"Quest system: User {member.name} left voice channel {before.channel.name}, checking voice sessions")
            
            # Use voice_sessions from voice_activity to get session duration
            from modules.voice_activity import voice_sessions
            
            if str(member.id) in voice_sessions:  # Convert member.id to string for key lookup
                guild_id = str(member.guild.id)
                user_id = str(member.id)
                
                # Calculate session duration
                if "state_history" in voice_sessions[user_id]:
                    # Sum up all state durations
                    total_seconds = 0
                    states_summary = []
                    
                    for state in voice_sessions[user_id]["state_history"]:
                        duration = state["end"] - state["start"]
                        state_name = state["state"]
                        
                        # Log each state
                        states_summary.append(f"{state_name}: {int(duration)}s")
                        
                        # Only count time when not muted/deafened
                        if state_name in ["active", "streaming", "watching"]:
                            total_seconds += duration
                    
                    logging.info(f"Quest system: Voice session states for {member.name}: {', '.join(states_summary)}")
                    
                    # Process voice time for quests
                    if total_seconds > 0:
                        logging.info(f"Quest system: Processing {int(total_seconds)} seconds of active voice time for {member.name}")
                        await handle_voice_quests(guild_id, user_id, int(total_seconds), member)
                    else:
                        logging.info(f"Quest system: No active voice time to process for {member.name} (user was muted/deafened)")
                else:
                    logging.warning(f"Quest system: No state history for {member.name} in voice sessions")
            else:
                logging.warning(f"Quest system: User {member.name} not found in voice sessions when leaving channel")
    
    # Update the voice handler in voice_activity module
    from modules import voice_activity
    voice_activity.handle_voice_state_update = voice_handler_with_quests

    # Start the quest manager
    quest_manager.start()
    
    logging.info("Quest system hooks registered successfully")
    return quest_manager

async def create_special_quests(guild_id):
    """Create special quests that don't expire/reset automatically"""
    special_quests = [
        {
            "name": "Voice Veteran",
            "description": "Spend a total of 10 hours in voice channels",
            "quest_type": "special",
            "requirement_type": "voice_time_seconds",
            "requirement_value": 10 * 60 * 60,  # 10 hours in seconds
            "reward_xp": 2000,
            "difficulty": "hard",
            "refresh_cycle": "once"
        },
        {
            "name": "Reaction Master",
            "description": "Add 100 reactions to messages",
            "quest_type": "special",
            "requirement_type": "total_reactions",
            "requirement_value": 100,
            "reward_xp": 500,
            "difficulty": "medium",
            "refresh_cycle": "once"
        },
        {
            "name": "Message Milestone",
            "description": "Send 1000 messages in the server",
            "quest_type": "special",
            "requirement_type": "total_messages",
            "requirement_value": 1000,
            "reward_xp": 1500,
            "difficulty": "hard",
            "refresh_cycle": "once"
        },
        {
            "name": "Command Connoisseur",
            "description": "Use 50 different bot commands",
            "quest_type": "special",
            "requirement_type": "commands_used",
            "requirement_value": 50,
            "reward_xp": 1000,
            "difficulty": "medium",
            "refresh_cycle": "once"
        }
    ]
    
    # Create all special quests
    for quest in special_quests:
        await create_quest(
            guild_id=guild_id,
            name=quest["name"],
            description=quest["description"],
            quest_type=quest["quest_type"],
            requirement_type=quest["requirement_type"],
            requirement_value=quest["requirement_value"],
            reward_xp=quest["reward_xp"],
            difficulty=quest["difficulty"],
            refresh_cycle=quest["refresh_cycle"]
        )
    
    logging.info(f"Created {len(special_quests)} special quests for guild {guild_id}")

async def initialize_guild_quests(bot):
    """Create initial quests for guilds if they don't have any"""
    for guild in bot.guilds:
        guild_id = str(guild.id)
        
        # Check if guild has any active quests
        active_quests = await get_guild_active_quests(guild_id)
        
        # If no active quests, create initial ones
        if not active_quests:
            logging.info(f"Creating initial quests for guild {guild.name} ({guild_id})")
            
            # Create daily quests
            await bot.quest_manager.create_daily_quests(guild_id)
            
            # Create weekly quests
            await bot.quest_manager.create_weekly_quests(guild_id)
            
            # Create some special quests
            await create_special_quests(guild_id)

async def start_quest_system(bot):
    """Initialize the quest system"""
    try:
        # Register event hooks first to create the quest manager
        quest_manager = register_quest_hooks(bot)
        
        # Create initial quests for guilds if needed
        await initialize_guild_quests(bot)
        
        logging.info("Quest system initialized successfully")
        return True
    except Exception as e:
        logging.error(f"Error initializing quest system: {e}")
        return False

# Add quest tracking to the main bot initialization in main.py
async def initialize_quest_system(bot):
    """Function to be called during bot initialization"""
    return await start_quest_system(bot)