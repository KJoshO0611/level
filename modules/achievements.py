import logging
import asyncio
import discord
from datetime import datetime
import time
from database import (
    update_activity_counter_db,
    get_user_achievements_db,
    create_achievement_db,
    get_achievement_leaderboard_db,
    get_achievement_stats_db,
    get_level_up_channel,
)
# Import the existing voice_sessions from voice_activity.
from modules.voice_activity import voice_sessions

# We'll use a key in each session to track the last time we awarded achievements.
# If not present, we fall back to the session's "state_start_time".

async def send_achievement_notification(guild, member, achievement_data):
    """
    Send a notification for a completed achievement.
    """
    try:
        embed = discord.Embed(
            title="🏆 Achievement Unlocked!",
            description=f"{member.mention} has earned **{achievement_data['name']}**!",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="Description",
            value=achievement_data['description'],
            inline=False
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        
        # Try to get the level up channel first
        level_up_channel_id = await get_level_up_channel(str(guild.id))
        if level_up_channel_id:
            channel = guild.get_channel(int(level_up_channel_id))
            if channel:
                await channel.send(embed=embed)
            else:
                # If channel not found, fall back to system channel
                if guild.system_channel:
                    await guild.system_channel.send(embed=embed)
        else:
            # If no level up channel set, use system channel
            if guild.system_channel:
                await guild.system_channel.send(embed=embed)
            
        logging.info(f"Sent achievement notification for {member.name}")
    except Exception as e:
        logging.error(f"Error sending achievement notification: {e}")

async def process_message_achievement(message):
    """
    Process message-related achievements.
    """
    if message.author.bot or not message.guild:
        return []
    
    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    new_value, completed_achievements = await update_activity_counter_db(
        guild_id, user_id, "total_messages", 1
    )
    
    if completed_achievements:
        for achievement in completed_achievements:
            await send_achievement_notification(message.guild, message.author, achievement)
    
    return completed_achievements

async def process_reaction_achievement(reaction, user):
    """
    Process reaction-related achievements.
    """
    if user.bot or not reaction.message.guild:
        return []
    
    guild_id = str(reaction.message.guild.id)
    user_id = str(user.id)
    new_value, completed_achievements = await update_activity_counter_db(
        guild_id, user_id, "total_reactions", 1
    )
    
    if completed_achievements:
        for achievement in completed_achievements:
            await send_achievement_notification(reaction.message.guild, user, achievement)
    
    return completed_achievements

async def process_command_achievement(ctx):
    """
    Process command-related achievements.
    """
    if ctx.author.bot or not ctx.guild:
        return []
    
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    new_value, completed_achievements = await update_activity_counter_db(
        guild_id, user_id, "commands_used", 1
    )
    
    if completed_achievements:
        for achievement in completed_achievements:
            await send_achievement_notification(ctx.guild, ctx.author, achievement)
    
    return completed_achievements

async def process_voice_time_achievement(guild_id, user_id, seconds, member):
    """
    Process voice time achievements by updating the voice_time_seconds counter.
    """
    new_value, completed_achievements = await update_activity_counter_db(
        guild_id, user_id, "voice_time_seconds", seconds
    )
    
    if completed_achievements:
        for achievement in completed_achievements:
            await send_achievement_notification(member.guild, member, achievement)
            
    return completed_achievements

async def voice_state_update_achievement_listener(member, before, after):
    """
    Listener for on_voice_state_update events to process voice time achievements.
    
    This listener uses the existing voice_sessions data. When a user leaves or switches channels,
    if a session start time is available in voice_sessions, it computes the session duration and updates achievements.
    """
    if member.bot:
        return

    guild_id = str(member.guild.id)
    user_id = str(member.id)

    # When a user leaves or switches channels:
    if before.channel and (not after.channel or before.channel != after.channel):
        session_info = voice_sessions.get(user_id)
        if session_info and session_info.get("state_start_time"):
            session_start = session_info["state_start_time"]
            session_end = time.time()
            session_duration = int(session_end - session_start)
            logging.info(f"{session_end} | {session_start}")
            logging.info(f"{member.name} left voice channel {before.channel.name} after {session_duration} seconds")
            
            await process_voice_time_achievement(guild_id, user_id, session_duration, member)
            
            # Remove the session info from voice_sessions if desired.
            # Note: If voice_activity.py manages cleanup, be cautious here.
            # voice_sessions.pop(user_id, None)

async def periodic_voice_achievement_update(bot):
    """
    A background task that periodically updates voice achievements for users still in voice sessions.
    
    This ensures that if a user remains in a channel (e.g. while streaming),
    their elapsed time is periodically added to their achievements.
    """
    await bot.wait_until_ready()
    while not bot.is_closed():
        current_time = datetime.utcnow().timestamp()
        # Iterate over a copy of the current sessions.
        for user_id, session in list(voice_sessions.items()):
            # Ensure that we have a start time and a reference to the member.
            state_start = session.get("state_start_time")
            member = session.get("member")
            if not state_start or not member:
                continue
            # Use a separate key to track the last update; if not set, default to state_start.
            last_update = session.get("last_achievement_update", state_start)
            elapsed = int(current_time - last_update)
            if elapsed >= 60:  # update every minute
                guild_id = str(member.guild.id)
                logging.info(f"Periodic update for {member.name}: awarding {elapsed} seconds of voice time")
                await process_voice_time_achievement(guild_id, user_id, elapsed, member)
                session["last_achievement_update"] = current_time
        await asyncio.sleep(60)

def register_achievement_hooks(bot):
    """
    Register achievement hooks with the bot.
    
    Instead of overriding on_voice_state_update, we add a listener so that
    the core voice tracking and achievement processing can coexist.
    Also wraps message, reaction, and command events.
    """
    bot.add_listener(voice_state_update_achievement_listener, "on_voice_state_update")
    
    original_on_message = getattr(bot, "on_message", None)
    async def on_message(message):
        if original_on_message:
            await original_on_message(message)
        await process_message_achievement(message)
    bot.on_message = on_message

    original_on_reaction_add = getattr(bot, "on_reaction_add", None)
    async def on_reaction_add(reaction, user):
        if original_on_reaction_add:
            await original_on_reaction_add(reaction, user)
        await process_reaction_achievement(reaction, user)
    bot.on_reaction_add = on_reaction_add

    @bot.event
    async def on_command_completion(ctx):
        await process_command_achievement(ctx)

    # Start the periodic voice achievement updater.
    bot.loop.create_task(periodic_voice_achievement_update(bot))

    logging.info("Achievement hooks registered successfully.")