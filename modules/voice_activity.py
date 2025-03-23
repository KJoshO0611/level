import time
import logging
import asyncio

import discord
from discord.ext import tasks

from config import load_config
from utils.performance_monitoring import time_function
from modules.databasev2 import get_or_create_user_level, apply_channel_boost
from modules.levels import award_xp_without_event_multiplier, send_level_up_notification, xp_to_next_level

config = load_config()
XP_RATES = config["XP_SETTINGS"]["RATES"]
IDLE_THRESHOLD = config["XP_SETTINGS"]["IDLE_THRESHOLD"]
LONG_SESSION_THRESHOLD = 30 * 60  # 30 minutes - process sessions longer than this
INACTIVE_SESSION_THRESHOLD = 3 * 60 * 60  # 3 hours - cleanup after this time
PERIODIC_PROCESSING_INTERVAL = 15 * 60  # 15 minutes - how often to run processing
MAX_STATE_HISTORY_ENTRIES = 100  # Maximum state history entries before compacting

# Enhanced tracking dictionaries
voice_sessions = {}  # Detailed voice session tracking
last_spoke = {}  # Last time a user was detected as speaking
voice_channels = {}  # Track which channel a user is in
stream_watchers = {}  # Track users who are watching streams
last_processed = {}

async def start_voice_tracking(bot):
    """Start voice activity tracking tasks"""
    check_idle_users.start(bot)
    await start_periodic_processing(bot)  # Add this line
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

async def get_all_xp_boost_events_for_guild(guild_id):
    """
    Get all XP boost events for a guild (active, past, and future)
    
    Returns a list of events with start_time, end_time, and multiplier
    """
    from modules.databasev2 import get_active_xp_boost_events, get_upcoming_xp_boost_events
    
    # Get active events
    active_events = await get_active_xp_boost_events(guild_id)
    upcoming_events = await get_upcoming_xp_boost_events(guild_id)
    
    # Combine all events
    all_events = active_events + upcoming_events
    
    return all_events

@time_function
async def calculate_event_adjusted_xp(base_xp, start_time, end_time, events):
    """Calculate XP with consideration for event multipliers during specific time periods"""
    
    # If no events, return base XP
    if not events:
        return base_xp
        
    # Create time slices based on event boundaries
    time_slices = []
    
    # Start with the whole period
    current_slices = [{"start": start_time, "end": end_time, "multiplier": 1.0}]
    
    # Split each slice by each event
    for event in events:
        event_start = event["start_time"]
        event_end = event["end_time"]
        event_multiplier = event["multiplier"]
        
        new_slices = []
        
        for slice in current_slices:
            slice_start = slice["start"]
            slice_end = slice["end"]
            slice_multiplier = slice["multiplier"]
            
            # Cases:
            # 1. Event doesn't overlap with this slice
            if event_end <= slice_start or event_start >= slice_end:
                new_slices.append(slice)
                continue
                
            # 2. Event completely covers this slice
            if event_start <= slice_start and event_end >= slice_end:
                new_slices.append({
                    "start": slice_start,
                    "end": slice_end,
                    "multiplier": max(slice_multiplier, event_multiplier)
                })
                continue
                
            # 3. Event starts during this slice
            if event_start > slice_start and event_start < slice_end:
                # Add pre-event part
                new_slices.append({
                    "start": slice_start,
                    "end": event_start,
                    "multiplier": slice_multiplier
                })
                
                # Add during-event part (if any)
                if event_end < slice_end:
                    new_slices.append({
                        "start": event_start,
                        "end": event_end,
                        "multiplier": max(slice_multiplier, event_multiplier)
                    })
                    
                    # Add post-event part
                    new_slices.append({
                        "start": event_end,
                        "end": slice_end,
                        "multiplier": slice_multiplier
                    })
                else:
                    # Event extends beyond slice end
                    new_slices.append({
                        "start": event_start,
                        "end": slice_end,
                        "multiplier": max(slice_multiplier, event_multiplier)
                    })
                continue
                
            # 4. Event ends during this slice
            if event_end > slice_start and event_end < slice_end:
                # Add during-event part
                new_slices.append({
                    "start": slice_start,
                    "end": event_end,
                    "multiplier": max(slice_multiplier, event_multiplier)
                })
                
                # Add post-event part
                new_slices.append({
                    "start": event_end,
                    "end": slice_end,
                    "multiplier": slice_multiplier
                })
        
        current_slices = new_slices
    
    # Calculate total XP based on duration and multiplier for each slice
    total_duration = end_time - start_time
    total_xp = 0
    
    for slice in current_slices:
        slice_duration = slice["end"] - slice["start"]
        slice_fraction = slice_duration / total_duration
        slice_xp = int(base_xp * slice_fraction * slice["multiplier"])
        total_xp += slice_xp
    
    return total_xp

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
                if user_id in voice_sessions:
                    # Record the end of the previous state
                    current_time = time.time()
                    previous_state = voice_sessions[user_id]["current_state"]
                    state_start_time = voice_sessions[user_id]["state_start_time"]
                    
                    # Add previous state to history
                    if "state_history" not in voice_sessions[user_id]:
                        voice_sessions[user_id]["state_history"] = []
                    
                    voice_sessions[user_id]["state_history"].append({
                        "state": previous_state,
                        "start": state_start_time,
                        "end": current_time,
                        "channel_id": voice_sessions[user_id]["channel_id"]
                    })
                    
                    # Update to watching state
                    voice_sessions[user_id]["current_state"] = "watching"
                    voice_sessions[user_id]["state_start_time"] = current_time
                    logging.info(f"User {member.name} is now watching a stream")
                
                stream_watchers[user_id] = True
    else:
        # No streamers in channel, update anyone who was a watcher
        for member in channel.members:
            user_id = str(member.id)
            if user_id in stream_watchers:
                del stream_watchers[user_id]
                
                # Change state from watching to active if needed
                if user_id in voice_sessions and voice_sessions[user_id]["current_state"] == "watching":
                    current_time = time.time()
                    
                    # Record the end of the watching state
                    if "state_history" not in voice_sessions[user_id]:
                        voice_sessions[user_id]["state_history"] = []
                    
                    voice_sessions[user_id]["state_history"].append({
                        "state": "watching",
                        "start": voice_sessions[user_id]["state_start_time"],
                        "end": current_time,
                        "channel_id": voice_sessions[user_id]["channel_id"]
                    })
                    
                    # Determine new state based on voice properties
                    new_state = "active"
                    if member.voice:
                        if member.voice.self_mute or member.voice.mute or member.voice.self_deaf or member.voice.deaf:
                            new_state = "muted"
                    
                    # Update to new state
                    voice_sessions[user_id]["current_state"] = new_state
                    voice_sessions[user_id]["state_start_time"] = current_time
                    logging.info(f"User {member.name} is no longer watching a stream, now {new_state}")

@time_function
async def handle_voice_channel_exit(guild_id, user_id, member):
    """Process XP for a user leaving voice channel, considering their various states"""
    if user_id not in voice_sessions:
        return
    
    current_time = time.time()
    
    # Finalize current state by adding it to history
    current_state = voice_sessions[user_id]["current_state"]
    start_time = voice_sessions[user_id]["state_start_time"]
    
    # Make sure state_history exists
    if "state_history" not in voice_sessions[user_id]:
        voice_sessions[user_id]["state_history"] = []
    
    # Add current state to history
    voice_sessions[user_id]["state_history"].append({
        "state": current_state,
        "start": start_time,
        "end": current_time,
        "channel_id": voice_sessions[user_id]["channel_id"]
    })
    
    # Get all XP boost events for this guild
    all_events = await get_all_xp_boost_events_for_guild(guild_id)
    
    # Calculate XP for each state period
    total_xp = 0
    for state_period in voice_sessions[user_id]["state_history"]:
        state = state_period["state"]
        period_start = state_period["start"]
        period_end = state_period["end"]
        channel_id = state_period["channel_id"]
        
        # Calculate duration in minutes
        duration_seconds = period_end - period_start
        minutes_in_state = int(duration_seconds // 60)
        
        if minutes_in_state <= 0:
            continue
        
        # Get the basic XP for this time
        base_xp = minutes_in_state * XP_RATES[state]
        
        # Apply channel boost if channel_id is available
        if channel_id:
            boosted_xp = apply_channel_boost(base_xp, channel_id)
            logging.info(f"Voice state {state} with channel boost: Base XP: {base_xp}, Boosted XP: {boosted_xp}, Channel: {channel_id}")
        else:
            boosted_xp = base_xp
            logging.info(f"Voice state {state} without boost: {boosted_xp}")
        
        # Calculate event-adjusted XP for this period
        period_xp = await calculate_event_adjusted_xp(
            boosted_xp,
            period_start,
            period_end,
            all_events
        )
        
        total_xp += period_xp
        logging.info(f"Added {period_xp} XP for {minutes_in_state} minutes in {state} state (after event adjustments)")
    
    # Award the total XP if any was earned
    if total_xp > 0:
        logging.info(f"Awarding total of {total_xp} XP to {member.name} for voice activity")
        await award_xp_without_event_multiplier(guild_id, user_id, total_xp, member)
    else:
        logging.info(f"No XP awarded to {member.name} for voice activity (total_xp = {total_xp})")
    
    # Clean up the tracking
    del voice_sessions[user_id]
    if user_id in voice_channels:
        del voice_channels[user_id]
    if user_id in stream_watchers:
        del stream_watchers[user_id]
    if user_id in last_spoke:
        del last_spoke[user_id]

@time_function(name="Voice_StateUpdate", log_always=True)
async def handle_voice_state_update(bot, member, before, after):
    """Handle voice state update events"""
    guild_id = str(member.guild.id)
    user_id = str(member.id)
    current_time = time.time()
    
    # User joins a voice channel
    if after.channel and not before.channel:
        voice_action_key = f"voice_join:{user_id}"
        is_limited, _ = await bot.rate_limiters["voice_xp"].check_rate_limit(voice_action_key)
        
        if is_limited:
            # Still track but log the rate limit
            logging.info(f"Rate limited voice join for user {user_id}")
            
        # Store the channel id
        voice_channels[user_id] = str(after.channel.id)
        
        # Initialize user's voice session
        state = determine_voice_state(after)
        voice_sessions[user_id] = {
            "channel_id": str(after.channel.id),
            "current_state": state,
            "state_start_time": current_time,
            "state_history": []
        }
        
        # Initialize speaking timestamp
        last_spoke[user_id] = current_time
        
        # Check if the user should be marked as watching a stream
        if state != "streaming" and state != "muted":
            # Check if there are any streamers in the channel
            for member_in_channel in after.channel.members:
                if member_in_channel.voice and getattr(member_in_channel.voice, 'self_stream', False):
                    # There's at least one streamer, mark this user as watching
                    voice_sessions[user_id]["current_state"] = "watching"
                    stream_watchers[user_id] = True
                    logging.info(f"User {member.name} joined and is now watching a stream")
                    break
        
    # User leaves a voice channel
    elif before.channel and not after.channel:
        # Process accumulated XP with event awareness
        await handle_voice_channel_exit(guild_id, user_id, member)
        
        # If user was streaming, update watchers in the channel they left
        if before.self_stream:
            update_stream_watchers(bot, before.channel)
    
    # User changes voice state (mute/deafen/stream/etc.) but stays in a channel
    elif after.channel and before.channel:
        # Update channel if they moved to a different channel
        if before.channel.id != after.channel.id:
            if user_id in voice_sessions:
                # Record the end of the state in the previous channel
                previous_state = voice_sessions[user_id]["current_state"]
                previous_start_time = voice_sessions[user_id]["state_start_time"]
                previous_channel = voice_sessions[user_id]["channel_id"]
                
                # Add to state history
                if "state_history" not in voice_sessions[user_id]:
                    voice_sessions[user_id]["state_history"] = []
                
                voice_sessions[user_id]["state_history"].append({
                    "state": previous_state,
                    "start": previous_start_time,
                    "end": current_time,
                    "channel_id": previous_channel
                })
                
                # Update channel
                voice_sessions[user_id]["channel_id"] = str(after.channel.id)
                voice_channels[user_id] = str(after.channel.id)
                
                # Reset state with new start time (state may be the same but we're in a new channel)
                voice_sessions[user_id]["state_start_time"] = current_time
            
            # If user was streaming and changed channels, update both channels
            if before.self_stream:
                update_stream_watchers(bot, before.channel)
            
            # Check streaming status in new channel
            if after.self_stream:
                update_stream_watchers(bot, after.channel, user_id)
            else:
                # Not streaming, check if should be watching someone else
                update_stream_watchers(bot, after.channel)
        
        # Check for stream start/stop
        if before.self_stream != after.self_stream:
            if after.self_stream:
                # User started streaming
                update_stream_watchers(bot, after.channel, user_id)
            else:
                # User stopped streaming
                update_stream_watchers(bot, after.channel)
            
        # Only process if it's a relevant state change
        if (before.self_mute != after.self_mute or 
            before.mute != after.mute or 
            before.self_deaf != after.self_deaf or 
            before.deaf != after.deaf or
            before.self_stream != after.self_stream or
            getattr(before, 'self_video', False) != getattr(after, 'self_video', False)):
            
            # State changed, record the previous state's duration
            if user_id in voice_sessions:
                previous_state = voice_sessions[user_id]["current_state"]
                state_start_time = voice_sessions[user_id]["state_start_time"]
                
                # Add to state history
                if "state_history" not in voice_sessions[user_id]:
                    voice_sessions[user_id]["state_history"] = []
                
                voice_sessions[user_id]["state_history"].append({
                    "state": previous_state,
                    "start": state_start_time,
                    "end": current_time,
                    "channel_id": voice_sessions[user_id]["channel_id"]
                })
            
                # Update to new state
                new_state = determine_voice_state(after)
                voice_sessions[user_id]["current_state"] = new_state
                voice_sessions[user_id]["state_start_time"] = current_time
                
                # If user is now deafened, they can't be watching a stream
                if new_state == "muted" and user_id in stream_watchers:
                    del stream_watchers[user_id]

async def handle_voice_speaking_update(member, speaking):
    """Handle voice speaking update events"""
    user_id = str(member.id)
    current_time = time.time()
    
    if speaking:
        # Update the last time this user spoke
        last_spoke[user_id] = current_time
        
        # If they were idle, change state to active (but don't change if watching or streaming)
        if user_id in voice_sessions and voice_sessions[user_id]["current_state"] == "idle":
            # Record the idle state duration
            if "state_history" not in voice_sessions[user_id]:
                voice_sessions[user_id]["state_history"] = []
            
            voice_sessions[user_id]["state_history"].append({
                "state": "idle",
                "start": voice_sessions[user_id]["state_start_time"],
                "end": current_time,
                "channel_id": voice_sessions[user_id]["channel_id"]
            })
            
            # Update to active state (only if not watching a stream)
            if user_id not in stream_watchers:
                voice_sessions[user_id]["current_state"] = "active"
                voice_sessions[user_id]["state_start_time"] = current_time

@tasks.loop(minutes=1)
async def check_idle_users(bot):
    """Check for users who have gone idle"""
    current_time = time.time()
    
    for user_id, session in list(voice_sessions.items()):
        # Skip users who are already idle, muted, streaming, or watching
        if session["current_state"] in ["idle", "muted", "streaming", "watching"]:
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
                    # Record the active state duration
                    if "state_history" not in session:
                        session["state_history"] = []
                    
                    session["state_history"].append({
                        "state": "active",
                        "start": session["state_start_time"],
                        "end": current_time,
                        "channel_id": session["channel_id"]
                    })
                    
                    # Update to idle state
                    session["current_state"] = "idle"
                    session["state_start_time"] = current_time
                    logging.info(f"User {member.display_name} is now idle after {time_since_last_spoke:.1f} seconds of inactivity")

@tasks.loop(seconds=PERIODIC_PROCESSING_INTERVAL)
async def periodic_voice_processing(bot):
    """
    Periodically process long voice sessions and clean up inactive ones
    This task runs every PERIODIC_PROCESSING_INTERVAL seconds
    """
    try:
        current_time = time.time()
        logging.info(f"Starting periodic voice session processing at {current_time}")
        
        # Process long sessions first
        await process_long_voice_sessions(bot, current_time)
        
        # Then clean up inactive sessions
        cleanup_inactive_sessions(current_time)
        
        # Compact oversized session histories
        compact_large_histories()
        
        logging.info(f"Completed periodic voice processing. Active sessions: {len(voice_sessions)}")
        
    except Exception as e:
        logging.error(f"Error in periodic voice processing: {e}")

async def process_long_voice_sessions(bot, current_time):
    """
    Award XP for long voice sessions without ending them
    This allows users to continue their sessions while still earning XP periodically
    """
    processed_count = 0
    
    for user_id, session in list(voice_sessions.items()):
        try:
            # Skip sessions that were recently processed
            if user_id in last_processed and current_time - last_processed[user_id] < PERIODIC_PROCESSING_INTERVAL:
                continue
                
            # Get the duration of the current state
            current_state = session["current_state"]
            state_start_time = session["state_start_time"]
            state_duration = current_time - state_start_time
            
            # Process long sessions
            if state_duration > LONG_SESSION_THRESHOLD:
                # Find guild and member
                guild_id = None
                member = None
                
                for guild in bot.guilds:
                    member = guild.get_member(int(user_id))
                    if member:
                        guild_id = str(guild.id)
                        break
                
                if not guild_id or not member:
                    continue
                
                # Create a temporary state period for current state
                temp_state_period = {
                    "state": current_state,
                    "start": state_start_time,
                    "end": current_time,
                    "channel_id": session["channel_id"]
                }
                
                # Get all event information
                all_events = await get_all_xp_boost_events_for_guild(guild_id)
                
                # Calculate XP for the period
                duration_minutes = int(state_duration // 60)
                if duration_minutes <= 0:
                    continue
                    
                # Calculate base XP
                base_xp = duration_minutes * XP_RATES[current_state]
                
                # Apply channel boost if applicable
                channel_id = session["channel_id"]
                boosted_xp = apply_channel_boost(base_xp, channel_id)
                
                # Calculate event-adjusted XP
                period_xp = await calculate_event_adjusted_xp(
                    boosted_xp,
                    state_start_time,
                    current_time,
                    all_events
                )
                
                if period_xp > 0:
                    # Award XP without ending the session
                    await award_xp_without_event_multiplier(guild_id, user_id, period_xp, member)
                    logging.info(f"Periodic XP: Awarded {period_xp} XP to {member.name} for long {current_state} session")
                    
                    # Update last processed time
                    last_processed[user_id] = current_time
                    
                    # Reset the state start time to now to avoid double-counting
                    session["state_start_time"] = current_time
                    
                    # Add the processed period to history
                    if "state_history" not in session:
                        session["state_history"] = []
                    
                    session["state_history"].append(temp_state_period)
                    
                    processed_count += 1
        
        except Exception as e:
            logging.error(f"Error processing long voice session for user {user_id}: {e}")
    
    logging.info(f"Processed {processed_count} long voice sessions")
    
def cleanup_inactive_sessions(current_time):
    """
    Remove voice sessions that appear to be inactive or stale
    This handles cases where voice_state_update events were missed
    """
    removed_count = 0
    
    for user_id in list(voice_sessions.keys()):
        try:
            session = voice_sessions[user_id]
            state_start_time = session["state_start_time"]
            
            # Check if session is too old (inactive)
            if current_time - state_start_time > INACTIVE_SESSION_THRESHOLD:
                # Clean up all tracking for this user
                del voice_sessions[user_id]
                if user_id in voice_channels:
                    del voice_channels[user_id]
                if user_id in stream_watchers:
                    del stream_watchers[user_id]
                if user_id in last_spoke:
                    del last_spoke[user_id]
                if user_id in last_processed:
                    del last_processed[user_id]
                    
                removed_count += 1
                logging.info(f"Removed inactive voice session for user {user_id} (inactive for {(current_time - state_start_time) / 3600:.1f} hours)")
        
        except Exception as e:
            logging.error(f"Error cleaning up voice session for user {user_id}: {e}")
    
    logging.info(f"Removed {removed_count} inactive voice sessions")

def compact_large_histories():
    """
    Compact large state histories to prevent memory issues
    This combines consecutive states of the same type
    """
    compacted_count = 0
    
    for user_id, session in voice_sessions.items():
        try:
            # Skip if no history or history is small
            if "state_history" not in session or len(session["state_history"]) < MAX_STATE_HISTORY_ENTRIES:
                continue
            
            history = session["state_history"]
            new_history = []
            
            # Try to compact by combining consecutive identical states
            if len(history) > 0:
                current_group = history[0].copy()
                
                for i in range(1, len(history)):
                    entry = history[i]
                    
                    # If same state and channel, combine them
                    if (entry["state"] == current_group["state"] and 
                        entry["channel_id"] == current_group["channel_id"]):
                        # Extend the end time
                        current_group["end"] = entry["end"]
                    else:
                        # Different state or channel, add the current group and start a new one
                        new_history.append(current_group)
                        current_group = entry.copy()
                
                # Add the last group
                new_history.append(current_group)
            
            # Replace with compacted history if we saved space
            if len(new_history) < len(history):
                session["state_history"] = new_history
                compacted_count += 1
                logging.debug(f"Compacted voice history for user {user_id}: {len(history)} → {len(new_history)} entries")
        
        except Exception as e:
            logging.error(f"Error compacting voice history for user {user_id}: {e}")
    
    if compacted_count > 0:
        logging.info(f"Compacted {compacted_count} voice session histories")

async def start_periodic_processing(bot):
    """Start the periodic processing task"""
    periodic_voice_processing.start(bot)
    logging.info("Started periodic voice session processing task")

def stop_periodic_processing():
    """Stop the periodic processing task"""
    if periodic_voice_processing.is_running():
        periodic_voice_processing.cancel()
        logging.info("Stopped periodic voice session processing task")