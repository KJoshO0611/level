import discord
import time
from discord.ext import tasks
from modules.database import get_or_create_user_level, apply_channel_boost
from modules.levels import award_xp_and_handle_level_up
from config import load_config
import logging
import asyncio

config = load_config()
XP_RATES = config["XP_SETTINGS"]["RATES"]
IDLE_THRESHOLD = config["XP_SETTINGS"]["IDLE_THRESHOLD"]

# Tracking dictionaries
vc_timers = {}  # When a user joined a voice channel
vc_states = {}  # Current activity state of users (active, idle, muted, streaming, watching)
last_spoke = {}  # Last time a user was detected as speaking
voice_channels = {}  # Track which channel a user is in
stream_watchers = {}  # Track users who are watching streams

async def start_voice_tracking(bot):
    """Start voice activity tracking tasks"""
    check_idle_users.start(bot)
    return True

def determine_voice_state(voice_state):
    """Determine if a user is active, muted, streaming, watching or idle based on voice state"""
    # If the user is streaming, they're considered streaming
    if getattr(voice_state, 'self_stream', False):
        return "streaming"
    
    # If user is deafened or muted (either way), they're considered muted
    if voice_state.self_mute or voice_state.mute or voice_state.self_deaf or voice_state.deaf:
        return "muted"
    
    # Consider video as active regardless of idle time
    if getattr(voice_state, 'self_video', False):
        return "active"
    
    # Default to active when joining (will be updated to "watching" if applicable)
    return "active"

def update_stream_watchers(bot, channel, streamer_id=None):
    """
    Update the list of stream watchers in a channel.
    If streamer_id is provided, it means a new stream started. Otherwise, check if anyone is streaming.
    """
    if not channel:
        return
    
    # Find streamers in the channel
    streamers = []
    if streamer_id:
        streamers.append(streamer_id)
    else:
        for member in channel.members:
            if member.voice and getattr(member.voice, 'self_stream', False):
                streamers.append(str(member.id))
    
    # If there are streamers, mark other users as watchers
    if streamers:
        for member in channel.members:
            user_id = str(member.id)
            if user_id not in streamers and member.voice and not member.voice.self_deaf and not member.voice.deaf:
                # Mark as a watcher if they're not streaming themselves and not deafened
                if user_id in vc_states and vc_states[user_id]["state"] != "watching":
                    # Calculate XP for previous state before changing to "watching"
                    guild_id = str(channel.guild.id)
                    current_time = time.time()
                    previous_state = vc_states[user_id]["state"]
                    state_start_time = vc_states[user_id]["since"]
                    state_duration = current_time - state_start_time
                    minutes_spent = int(state_duration // 60)
                    
                    # Get the channel_id for applying the boost
                    channel_id = voice_channels.get(user_id)
                    
                    if minutes_spent > 0:
                        base_xp = minutes_spent * XP_RATES[previous_state]
                        
                        # Apply channel boost if channel_id is available
                        if channel_id:
                            xp_earned = apply_channel_boost(base_xp, channel_id)
                            logging.info(f"State change to watching with channel boost: Base XP: {base_xp}, Boosted XP: {xp_earned}, Channel: {channel_id}")
                        else:
                            xp_earned = base_xp
                        
                        # Get member object to pass to award_xp function
                        member_obj = channel.guild.get_member(int(user_id))
                        if member_obj:
                            asyncio.create_task(get_or_create_user_level(bot, guild_id, user_id))
                            asyncio.create_task(award_xp_and_handle_level_up(bot, guild_id, user_id, xp_earned, member_obj))
                    
                    # Update to watching state
                    vc_states[user_id] = {
                        "state": "watching",
                        "since": current_time
                    }
                    logging.info(f"User {member.name} is now watching a stream")
                stream_watchers[user_id] = True
    else:
        # No streamers in channel, update anyone who was a watcher
        for member in channel.members:
            user_id = str(member.id)
            if user_id in stream_watchers:
                del stream_watchers[user_id]
                
                # Change state from watching to active if needed
                if user_id in vc_states and vc_states[user_id]["state"] == "watching":
                    guild_id = str(channel.guild.id)
                    current_time = time.time()
                    
                    # Calculate XP for watching time
                    watching_start = vc_states[user_id]["since"]
                    watching_duration = current_time - watching_start
                    minutes_spent = int(watching_duration // 60)
                    
                    # Get the channel_id for applying the boost
                    channel_id = voice_channels.get(user_id)
                    
                    if minutes_spent > 0:
                        base_xp = minutes_spent * XP_RATES["watching"]
                        
                        # Apply channel boost if channel_id is available
                        if channel_id:
                            xp_earned = apply_channel_boost(base_xp, channel_id)
                            logging.info(f"Watching to active with channel boost: Base XP: {base_xp}, Boosted XP: {xp_earned}, Channel: {channel_id}")
                        else:
                            xp_earned = base_xp
                        
                        # Get member object
                        member_obj = channel.guild.get_member(int(user_id))
                        if member_obj:
                            asyncio.create_task(get_or_create_user_level(bot, guild_id, user_id))
                            asyncio.create_task(award_xp_and_handle_level_up(bot, guild_id, user_id, xp_earned, member_obj))
                    
                    # Determine new state based on voice properties
                    new_state = "active"
                    if member.voice:
                        if member.voice.self_mute or member.voice.mute or member.voice.self_deaf or member.voice.deaf:
                            new_state = "muted"
                    
                    # Update to new state
                    vc_states[user_id] = {
                        "state": new_state,
                        "since": current_time
                    }
                    logging.info(f"User {member.name} is no longer watching a stream, now {new_state}")

async def handle_voice_channel_exit(bot, guild_id, user_id, vc_states_dict, member):
    """Process XP for a user leaving voice channel, considering their various states"""
    current_time = time.time()
    total_xp = 0
    
    if user_id in vc_states_dict:
        # Calculate XP for the final state
        final_state = vc_states_dict[user_id]["state"]
        state_start_time = vc_states_dict[user_id]["since"]
        time_in_final_state = current_time - state_start_time
        minutes_in_final_state = int(time_in_final_state // 60)
        
        # Get the channel_id for applying the boost
        channel_id = voice_channels.get(user_id)
        
        if minutes_in_final_state > 0:
            base_xp = minutes_in_final_state * XP_RATES[final_state]
            
            # Apply channel boost if channel_id is available
            if channel_id:
                xp_for_final_state = apply_channel_boost(base_xp, channel_id)
                logging.info(f"Voice XP with channel boost: Base XP: {base_xp}, Boosted XP: {xp_for_final_state}, Channel: {channel_id}")
            else:
                xp_for_final_state = base_xp
                logging.info(f"Voice XP without boost: {xp_for_final_state}")
                
            total_xp += xp_for_final_state
            logging.info(f"Awarding {xp_for_final_state} XP for {minutes_in_final_state} minutes in {final_state} state")
    
    # Award the total XP if any was earned
    if total_xp > 0:
        logging.info(f"Awarding total of {total_xp} XP to {member.name} for voice activity")
        await get_or_create_user_level(bot, guild_id, user_id)
        await award_xp_and_handle_level_up(bot, guild_id, user_id, total_xp, member)
    else:
        logging.info(f"No XP awarded to {member.name} for voice activity (total_xp = {total_xp})")
    
    # Clean up the tracking
    if user_id in voice_channels:
        del voice_channels[user_id]
    if user_id in stream_watchers:
        del stream_watchers[user_id]

async def handle_voice_state_update(bot, member, before, after):
    """Handle voice state update events"""
    guild_id = str(member.guild.id)
    user_id = str(member.id)
    
    # User joins a voice channel
    if after.channel and not before.channel:
        vc_timers[user_id] = time.time()
        
        # Store the channel id
        voice_channels[user_id] = str(after.channel.id)
        
        # Initialize user's voice state
        state = determine_voice_state(after)
        vc_states[user_id] = {
            "state": state,
            "since": time.time()
        }
        
        # Initialize speaking timestamp
        last_spoke[user_id] = time.time()
        
        # Check if the user should be marked as watching a stream
        if state != "streaming" and state != "muted":
            # Check if there are any streamers in the channel
            for member_in_channel in after.channel.members:
                if member_in_channel.voice and getattr(member_in_channel.voice, 'self_stream', False):
                    # There's at least one streamer, mark this user as watching
                    vc_states[user_id] = {
                        "state": "watching",
                        "since": time.time()
                    }
                    stream_watchers[user_id] = True
                    logging.info(f"User {member.name} joined and is now watching a stream")
                    break
        
    # User leaves a voice channel
    elif before.channel and not after.channel:
        if user_id in vc_timers:
            # Remove the timer
            vc_timers.pop(user_id, None)
            
            # Calculate total time and award XP for the entire session
            await handle_voice_channel_exit(bot, guild_id, user_id, vc_states, member)
            
            # Clear other tracking data after processing
            if user_id in vc_states:
                del vc_states[user_id]
            if user_id in last_spoke:
                del last_spoke[user_id]
            
            # If user was streaming, update watchers in the channel they left
            if before.self_stream:
                # FIXED: Removed await
                update_stream_watchers(bot, before.channel)
    
    # User changes voice state (mute/deafen/stream/etc.) but stays in a channel
    elif after.channel and before.channel:
        # Update channel if they moved to a different channel
        if before.channel.id != after.channel.id:
            voice_channels[user_id] = str(after.channel.id)
            
            # If user was streaming and changed channels, update both channels
            if before.self_stream:
                # FIXED: Removed await
                update_stream_watchers(bot, before.channel)
            
            # Check streaming status in new channel
            if after.self_stream:
                # FIXED: Removed await
                update_stream_watchers(bot, after.channel, user_id)
            else:
                # Not streaming, check if should be watching someone else
                # FIXED: Removed await
                update_stream_watchers(bot, after.channel)
        
        # Check for stream start/stop
        if before.self_stream != after.self_stream:
            if after.self_stream:
                # User started streaming
                # FIXED: Removed await
                update_stream_watchers(bot, after.channel, user_id)
            else:
                # User stopped streaming
                # FIXED: Removed await
                update_stream_watchers(bot, after.channel)
            
        # Only process if it's a relevant state change
        if (before.self_mute != after.self_mute or 
            before.mute != after.mute or 
            before.self_deaf != after.self_deaf or 
            before.deaf != after.deaf or
            before.self_stream != after.self_stream or
            getattr(before, 'self_video', False) != getattr(after, 'self_video', False)):
            
            # State changed, finalize the previous state's XP
            if user_id in vc_states:
                previous_state = vc_states[user_id]["state"]
                state_start_time = vc_states[user_id]["since"]
                state_duration = time.time() - state_start_time
                minutes_spent = int(state_duration // 60)
                
                # Get the channel_id for applying the boost
                channel_id = voice_channels.get(user_id)
                
                if minutes_spent > 0:
                    await get_or_create_user_level(bot, guild_id, user_id)
                    base_xp = minutes_spent * XP_RATES[previous_state]
                    
                    # Apply channel boost if channel_id is available
                    if channel_id:
                        xp_earned = apply_channel_boost(base_xp, channel_id)
                        logging.info(f"Voice state change XP with channel boost: Base XP: {base_xp}, Boosted XP: {xp_earned}, Channel: {channel_id}")
                    else:
                        xp_earned = base_xp
                        logging.info(f"Voice state change XP without boost: {xp_earned}")
                        
                    await award_xp_and_handle_level_up(bot, guild_id, user_id, xp_earned, member)
            
            # Update to new state
            new_state = determine_voice_state(after)
            vc_states[user_id] = {
                "state": new_state,
                "since": time.time()
            }
            
            # If user is now deafened, they can't be watching a stream
            if new_state == "muted" and user_id in stream_watchers:
                del stream_watchers[user_id]

async def handle_voice_speaking_update(bot, member, speaking):
    """Handle voice speaking update events"""
    user_id = str(member.id)
    if speaking:
        # Update the last time this user spoke
        last_spoke[user_id] = time.time()
        
        # If they were idle, change state to active (but don't change if watching or streaming)
        if user_id in vc_states and vc_states[user_id]["state"] == "idle":
            # Calculate XP for idle time
            idle_start = vc_states[user_id]["since"]
            idle_duration = time.time() - idle_start
            idle_minutes = int(idle_duration // 60)
            
            # Get the channel_id for applying the boost
            channel_id = voice_channels.get(user_id)
            
            if idle_minutes > 0:
                guild_id = str(member.guild.id)
                await get_or_create_user_level(bot, guild_id, user_id)
                base_xp = idle_minutes * XP_RATES["idle"]
                
                # Apply channel boost if channel_id is available
                if channel_id:
                    xp_earned = apply_channel_boost(base_xp, channel_id)
                    logging.info(f"Idle to active XP with channel boost: Base XP: {base_xp}, Boosted XP: {xp_earned}, Channel: {channel_id}")
                else:
                    xp_earned = base_xp
                    logging.info(f"Idle to active XP without boost: {xp_earned}")
                    
                await award_xp_and_handle_level_up(bot, guild_id, user_id, xp_earned, member)
            
            # Update to active state (only if not watching a stream)
            if user_id not in stream_watchers:
                vc_states[user_id] = {
                    "state": "active",
                    "since": time.time()
                }

@tasks.loop(minutes=1)
async def check_idle_users(bot):
    """Check for users who have gone idle"""
    current_time = time.time()
    
    for user_id, state_info in list(vc_states.items()):
        # Skip users who are already idle, muted, streaming, or watching
        if state_info["state"] in ["idle", "muted", "streaming", "watching"]:
            continue
        
        # Check if user hasn't spoken in the threshold time
        if user_id in last_spoke:
            time_since_last_spoke = current_time - last_spoke[user_id]
            
            if time_since_last_spoke > IDLE_THRESHOLD:
                # Convert from active to idle
                guild_id = None
                member = None
                
                # Find the guild and member
                for guild in bot.guilds:
                    member = guild.get_member(int(user_id))
                    if member:
                        guild_id = str(guild.id)
                        break
                
                if guild_id and member:
                    # Calculate XP for active time
                    active_start = state_info["since"]
                    active_duration = current_time - active_start
                    active_minutes = int(active_duration // 60)
                    
                    # Get the channel_id for applying the boost
                    channel_id = voice_channels.get(user_id)
                    
                    if active_minutes > 0:
                        await get_or_create_user_level(bot, guild_id, user_id)
                        base_xp = active_minutes * XP_RATES["active"]
                        
                        # Apply channel boost if channel_id is available
                        if channel_id:
                            xp_earned = apply_channel_boost(base_xp, channel_id)
                            logging.info(f"Active to idle XP with channel boost: Base XP: {base_xp}, Boosted XP: {xp_earned}, Channel: {channel_id}")
                        else:
                            xp_earned = base_xp
                            logging.info(f"Active to idle XP without boost: {xp_earned}")
                            
                        await award_xp_and_handle_level_up(bot, guild_id, user_id, xp_earned, member)
                    
                    # Update to idle state
                    vc_states[user_id] = {
                        "state": "idle",
                        "since": current_time
                    }