import random
import time
import logging

import discord

from config import load_config
from utils.performance_monitoring import time_function
from modules.databasev2 import (
    get_or_create_user_level, 
    update_user_xp, 
    get_level_up_channel, 
    apply_channel_boost, 
    get_level_roles, 
    get_or_create_user_level,
    get_active_xp_boost_events
)

config = load_config()
XP_SETTINGS = config["XP_SETTINGS"]

def xp_to_next_level(level: int) -> int:
    """Calculate XP required for next level using enhanced leveling algorithm"""
    # Formula: next level at 100 * (level ^ 1.5) XP
    return int(100 * (level ** 1.8))

async def get_event_xp_multiplier(guild_id: str) -> float:
    """
    Get the XP multiplier from all active events for a guild.
    If multiple events are active, we take the highest multiplier.
    """
    active_events = await get_active_xp_boost_events(guild_id)
    
    # Default multiplier is 1.0 (no change)
    if not active_events:
        return 1.0
    
    # Get the highest multiplier from active events
    max_multiplier = max(event["multiplier"] for event in active_events)
    return max_multiplier

@time_function
async def award_xp_and_handle_level_up(guild_id, user_id, xp_amount, member, update_last_xp_time=False):
    """
    Awards XP to a user, handles level-up logic, and sends level-up notifications.
    This function applies event multipliers to the XP.
    
    Returns a tuple of (new_xp, new_level, leveled_up)
    
    Parameters:
    - update_last_xp_time: If True, updates the last_xp_time; False will keep the existing timestamp
    """
    # Get current user level data - use cached version for better performance
    xp, level, last_xp_time, last_assigned_role_id = await get_or_create_user_level(guild_id, user_id)
    
    # Track if this is a new user (for level 1 role assignment)
    is_new_user = (xp == 0 and level == 1)

    # Apply event boost multiplier if any events are active
    event_multiplier = await get_event_xp_multiplier(guild_id)
    if event_multiplier > 1.0:
        # Apply the boost and round to integer
        xp_amount = int(xp_amount * event_multiplier)
        logging.info(f"Applied event boost multiplier of {event_multiplier}x, adjusted XP: {xp_amount}")

    # Add XP
    xp += xp_amount
    
    # Check for level up
    leveled_up = False
    while xp >= xp_to_next_level(level):
        xp -= xp_to_next_level(level)
        level += 1
        leveled_up = True
        
    # Update database - only update last_xp_time if specified
    current_time = time.time()
    if update_last_xp_time:
        await update_user_xp(guild_id, user_id, xp, level, current_time, last_assigned_role_id)
    else:
        # Keep the existing last_xp_time 
        await update_user_xp(guild_id, user_id, xp, level, last_xp_time, last_assigned_role_id)

    # Get level roles for this guild from the database - use cached version for better performance
    guild_level_roles = await get_level_roles(guild_id)

    # Handle level 1 role assignment for new users
    if is_new_user and 1 in guild_level_roles:
        role_id = guild_level_roles[1]
        guild = member.guild
        level_one_role = guild.get_role(int(role_id))
        
        if level_one_role:
            try:
                # Assign the level 1 role
                await member.add_roles(level_one_role)
                logging.info(f"Assigned initial role {level_one_role.name} to {member.name} (level 1)")
                
                # Update the last assigned role in the database
                await update_user_xp(guild_id, user_id, xp, level, 
                                    current_time if update_last_xp_time else last_xp_time, 
                                    str(role_id))
                last_assigned_role_id = str(role_id)  # Update the variable for later use
            except discord.Forbidden:
                logging.error(f"Bot lacks permissions to manage roles.")
            except discord.HTTPException as e:
                logging.error(f"Failed to manage roles: {e}")

    # Handle level-up notification if needed
    if leveled_up:
        await send_level_up_notification(guild_id, member, level)

        # Get level roles for this guild from the database - use cached version
        guild_level_roles = await get_level_roles(guild_id)

        # Check for role assignment
        if level in guild_level_roles:
            role_id = guild_level_roles[level]
            guild = member.guild
            new_role = guild.get_role(int(role_id))
            
            logging.info(f"Level up: last_role={last_assigned_role_id}, new_role={role_id}")
            logging.info(f"Role object: {new_role}, Type: {type(new_role)}")

            if new_role:
                try:
                    # Remove previous role if it exists
                    if last_assigned_role_id:
                        previous_role = guild.get_role(int(last_assigned_role_id))
                        if previous_role and previous_role in member.roles:
                            await member.remove_roles(previous_role)
                            logging.info(f"Removed role {previous_role.name} from {member.name}")

                    # Assign the new role
                    await member.add_roles(new_role)
                    logging.info(f"Assigned role {new_role.name} to {member.name} (level {level})")

                    # Update the last assigned role in the database.
                    await update_user_xp(guild_id, user_id, xp, level, current_time, str(role_id)) #update the database with new role id.

                except discord.Forbidden:
                    logging.error(f"Bot lacks permissions to manage roles.")
                except discord.HTTPException as e:
                    logging.error(f"Failed to manage roles: {e}")
            else:
                logging.info(f"Did not change role")
    
    return (xp, level, leveled_up)

@time_function
async def award_xp_without_event_multiplier(guild_id, user_id, xp_amount, member, update_last_xp_time=False):
    """
    Awards XP to a user, handles level-up logic, and sends level-up notifications.
    This function does NOT apply event multipliers to the XP since they should have already been applied.
    
    Returns a tuple of (new_xp, new_level, leveled_up)
    
    Parameters:
    - update_last_xp_time: If True, updates the last_xp_time; False will keep the existing timestamp
    """
    # Get current user level data - use cached version for better performance
    xp, level, last_xp_time, last_assigned_role_id = await get_or_create_user_level(guild_id, user_id)
    
    # Track if this is a new user (for level 1 role assignment)
    is_new_user = (xp == 0 and level == 1)

    # Add XP (no event multiplier applied)
    xp += xp_amount
    
    # Check for level up
    leveled_up = False
    while xp >= xp_to_next_level(level):
        xp -= xp_to_next_level(level)
        level += 1
        leveled_up = True
    
    # Update database - only update last_xp_time if specified
    current_time = time.time()
    if update_last_xp_time:
        await update_user_xp(guild_id, user_id, xp, level, current_time, last_assigned_role_id)
    else:
        # Keep the existing last_xp_time 
        await update_user_xp(guild_id, user_id, xp, level, last_xp_time, last_assigned_role_id)

    # Get level roles for this guild from the database - use cached version for better performance
    guild_level_roles = await get_level_roles(guild_id)

    # Handle level 1 role assignment for new users
    if is_new_user and 1 in guild_level_roles:
        role_id = guild_level_roles[1]
        guild = member.guild
        level_one_role = guild.get_role(int(role_id))
        
        if level_one_role:
            try:
                # Assign the level 1 role
                await member.add_roles(level_one_role)
                logging.info(f"Assigned initial role {level_one_role.name} to {member.name} (level 1)")
                
                # Update the last assigned role in the database
                await update_user_xp(guild_id, user_id, xp, level, 
                                    current_time if update_last_xp_time else last_xp_time, 
                                    str(role_id))
                last_assigned_role_id = str(role_id)  # Update the variable for later use
            except discord.Forbidden:
                logging.error(f"Bot lacks permissions to manage roles.")
            except discord.HTTPException as e:
                logging.error(f"Failed to manage roles: {e}")

    # Handle level-up notification if needed
    if leveled_up:
        await send_level_up_notification(guild_id, member, level)

        # Check for role assignment
        if level in guild_level_roles:
            role_id = guild_level_roles[level]
            guild = member.guild
            new_role = guild.get_role(int(role_id))
            
            if new_role:
                try:
                    # Remove previous role if it exists
                    if last_assigned_role_id:
                        previous_role = guild.get_role(int(last_assigned_role_id))
                        if previous_role and previous_role in member.roles:
                            await member.remove_roles(previous_role)
                            logging.info(f"Removed role {previous_role.name} from {member.name}")

                    # Assign the new role
                    await member.add_roles(new_role)
                    logging.info(f"Assigned role {new_role.name} to {member.name} (level {level})")

                    # Update the last assigned role in the database
                    await update_user_xp(guild_id, user_id, xp, level, 
                                        current_time if update_last_xp_time else last_xp_time, 
                                        str(role_id))

                except discord.Forbidden:
                    logging.error(f"Bot lacks permissions to manage roles.")
                except discord.HTTPException as e:
                    logging.error(f"Failed to manage roles: {e}")
    
    return (xp, level, leveled_up)

async def send_level_up_notification(guild_id, member, level):
    """
    Sends a level-up notification to the configured channel.
    """
    avatar_url = None
    # Try to get server-specific (guild) avatar first
    if hasattr(member, 'guild_avatar') and member.guild_avatar:
        avatar_url = member.guild_avatar.url
    # Then fall back to global avatar
    elif member.avatar:
        avatar_url = member.avatar.url
    # Finally, use default avatar as last resort
    else:
        avatar_url = member.default_avatar.url

    embed = discord.Embed(
        title="Level Up!",
        description=f"Congratulations {member.mention}, you've reached level {level}!",
        color=discord.Color.gold()
    )
    # Set the author's avatar as the thumbnail
    embed.set_thumbnail(url=avatar_url)
    
    # Check if a level-up channel is configured - use cached version
    level_up_channel_id = await get_level_up_channel(guild_id)
        
    if level_up_channel_id:
        channel = member.guild.get_channel(int(level_up_channel_id))
        if channel:
            await channel.send(embed=embed)
        else:
            logging.info(f"Configured channel with ID {level_up_channel_id} not found.")
    else:
        # Fallback: send to the member's guild's system channel if available
        if member.guild.system_channel:
            await member.guild.system_channel.send(embed=embed)
        else:
            logging.info(f"No level-up channel configured and no system channel available for guild {guild_id}")

@time_function
async def handle_message_xp(message, bot=None):
    """Handle XP awarding for messages"""
    # Ignore messages from bots
    if message.author.bot:
        return

    # Only handle messages in guild channels
    if not message.guild:
        return

    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    channel_id = str(message.channel.id)
    current_time = time.time()

    # Check message rate limiting
    message_key = f"msg:{user_id}"
    is_limited, _ = await bot.rate_limiters["command"].check_rate_limit(message_key)
    
    if is_limited:
        # Skip XP award but don't tell the user (to avoid spam)
        return    

    # Get or create user level - use cached version
    xp, level, last_xp_time, last_role = await get_or_create_user_level(guild_id, user_id)

    # Award XP only if enough time has passed since the last award
    if current_time - last_xp_time >= XP_SETTINGS["COOLDOWN"]:
        # Generate base XP amount
        base_xp = random.randint(XP_SETTINGS["MIN"], XP_SETTINGS["MAX"])
        
        # Apply channel boost if applicable
        boosted_xp = apply_channel_boost(base_xp, channel_id)
        
        # Check for event boost
        event_multiplier = await get_event_xp_multiplier(guild_id)
        
        # Calculate final XP
        awarded_xp = boosted_xp
        if event_multiplier > 1.0:
            awarded_xp = int(boosted_xp * event_multiplier)
            
            # Show event boost notification occasionally (1 in 20 chance)
            if random.random() < 0.05:  
                event_boost_msg = f"🎉 **XP Boost Event Active!** {message.author.mention} earned {awarded_xp}XP ({event_multiplier}x bonus)"
                try:
                    await message.channel.send(event_boost_msg, delete_after=10)
                except:
                    pass  # Silently fail if message can't be sent
        
        # Award the boosted XP and update the last_xp_time
        logging.info(f"Awarded {awarded_xp}xp to {message.author.name}")
        await award_xp_and_handle_level_up(guild_id, user_id, awarded_xp, message.author, update_last_xp_time=True)

async def handle_reaction_xp(reaction, user):
    """Handle XP awarding for reactions"""
    if user.bot or not reaction.message.guild:
        return
        
    guild_id = str(reaction.message.guild.id)
    user_id = str(user.id)
    
    # Ensure user exists in database - use cached version
    await get_or_create_user_level(guild_id, user_id)
    
    # Award a small amount of XP for reactions, but DON'T update the last_xp_time
    await award_xp_and_handle_level_up(guild_id, user_id, 1, user, update_last_xp_time=False)
    logging.info(f"Awarded 1 XP to {user.name} for reaction without updating cooldown")