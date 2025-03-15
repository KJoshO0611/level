import discord
from discord.ext import commands
import logging
from datetime import datetime
import time
from modules.databasev2 import (
    set_channel_boost_db, 
    remove_channel_boost_db, 
    create_level_role, 
    get_level_roles, 
    delete_level_role, 
    set_level_up_channel, 
    get_health_stats, 
    invalidate_guild_cache,
    create_xp_boost_event, 
    get_active_xp_boost_events, 
    get_upcoming_xp_boost_events,
    delete_xp_boost_event,
    get_xp_boost_event,
    get_server_xp_settings, 
    update_server_xp_settings, 
    reset_server_xp_settings,
    CHANNEL_XP_BOOSTS
)

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Reference to the channel boosts dictionary in database.py
        self.channel_boosts = CHANNEL_XP_BOOSTS

    @commands.command(name="list_channel_boosts", aliases=["lcboost"])
    async def list_channel_boosts(self, ctx):
        """List all channels with XP boosts for this guild"""
        guild_id = str(ctx.guild.id)
        
        # Query database directly instead of using the in-memory dictionary
        async with self.bot.db.acquire() as conn:
            query = "SELECT channel_id, multiplier FROM channel_boosts WHERE guild_id = $1"
            rows = await conn.fetch(query, guild_id)
            
            if not rows:
                await ctx.send("No channel XP boosts are currently set for this server.")
                return
            
            # Build the embed with boost information
            embed = discord.Embed(
                title="Channel XP Boosts",
                description="These channels have XP multipliers applied:",
                color=discord.Color.blue()
            )
            
            voice_channels = []
            text_channels = []
            
            for row in rows:
                channel_id = row['channel_id']
                multiplier = row['multiplier']
                
                channel = ctx.guild.get_channel(int(channel_id))
                if not channel:
                    continue
                    
                if isinstance(channel, discord.VoiceChannel):
                    voice_channels.append((channel, multiplier))
                elif isinstance(channel, discord.TextChannel):
                    text_channels.append((channel, multiplier))
            
            if voice_channels:
                voice_text = "\n".join([f"**{c.name}**: {m}x XP" for c, m in voice_channels])
                embed.add_field(name="Voice Channels", value=voice_text, inline=False)
            
            if text_channels:
                text_text = "\n".join([f"**{c.name}**: {m}x XP" for c, m in text_channels])
                embed.add_field(name="Text Channels", value=text_text, inline=False)
            
            if not voice_channels and not text_channels:
                await ctx.send("No valid channel XP boosts found for this server.")
                return
                
            await ctx.send(embed=embed)

    @commands.command(name="reload_channel_boosts", aliases=["rcb"])
    @commands.has_permissions(administrator=True)
    async def reload_channel_boosts(self, ctx):
        """Reload channel XP boosts from the database into memory and show debug info"""
        try:
            # Import the function directly for clarity
            from modules.databasev2 import load_channel_boosts, CHANNEL_XP_BOOSTS
            
            # Log the current state
            logging.info(f"Before reload: CHANNEL_XP_BOOSTS contains {len(CHANNEL_XP_BOOSTS)} boosts")
            logging.info(f"Current boost dictionary: {CHANNEL_XP_BOOSTS}")
            
            # Show status message to user
            status_msg = await ctx.send("🔄 Reloading channel boosts...")
            
            # Call the function to reload boosts
            loaded_count = await load_channel_boosts(self.bot)
            
            # Check the database directly to verify
            guild_id = str(ctx.guild.id)
            async with self.bot.db.acquire() as conn:
                all_boosts_query = "SELECT COUNT(*) FROM channel_boosts"
                all_count = await conn.fetchval(all_boosts_query)
                
                guild_boosts_query = "SELECT COUNT(*) FROM channel_boosts WHERE guild_id = $1"
                guild_count = await conn.fetchval(guild_boosts_query, guild_id)
                
                guild_boosts_detail_query = "SELECT channel_id, multiplier FROM channel_boosts WHERE guild_id = $1"
                guild_boosts = await conn.fetch(guild_boosts_detail_query, guild_id)
            
            # Build a detailed response
            embed = discord.Embed(
                title="Channel XP Boosts Reload Results",
                color=discord.Color.blue()
            )
            
            # Global stats
            embed.add_field(
                name="Global Stats", 
                value=(f"Total boosts in database: {all_count}\n"
                    f"Loaded into memory: {loaded_count if loaded_count >= 0 else 'Error'}\n"
                    f"Current in-memory count: {len(CHANNEL_XP_BOOSTS)}"),
                inline=False
            )
            
            # This guild's stats
            embed.add_field(
                name=f"This Server ({ctx.guild.name})", 
                value=f"Boosts for this server: {guild_count}",
                inline=False
            )
            
            # Show the actual channel boosts for this server
            if guild_boosts:
                boost_details = []
                for row in guild_boosts:
                    channel_id = row['channel_id']
                    multiplier = row['multiplier']
                    channel = ctx.guild.get_channel(int(channel_id))
                    channel_name = channel.name if channel else f"Unknown (ID: {channel_id})"
                    boost_details.append(f"• {channel_name}: {multiplier}x")
                
                embed.add_field(
                    name="Channel Boosts in Database", 
                    value="\n".join(boost_details),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Channel Boosts in Database", 
                    value="No channel boosts found for this server",
                    inline=False
                )
            
            # Memory dictionary status
            memory_boosts = []
            for channel_id, multiplier in CHANNEL_XP_BOOSTS.items():
                try:
                    channel = ctx.guild.get_channel(int(channel_id))
                    if channel:
                        memory_boosts.append(f"• {channel.name}: {multiplier}x")
                except:
                    pass
                    
            if memory_boosts:
                embed.add_field(
                    name="Boosts In Memory (this server only)", 
                    value="\n".join(memory_boosts[:10]) + 
                        ("\n..." if len(memory_boosts) > 10 else ""),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Boosts In Memory (this server only)", 
                    value="No boosts in memory for this server's channels",
                    inline=False
                )
            
            # Edit the status message
            await status_msg.edit(content=None, embed=embed)
            
        except Exception as e:
            logging.error(f"Error in reload_channel_boosts: {e}")
            await ctx.send(f"❌ Error reloading channel boosts: {str(e)}")
    
    @commands.command(name="delete_level_role", aliases=["dlrole"])
    @commands.has_permissions(administrator=True)
    async def delete_level_role(self, ctx, level: int):
        """Delete a level role mapping"""
        success = await delete_level_role(str(ctx.guild.id), level)
        
        if success:
            await ctx.send(f"✅ Level {level} role mapping has been deleted")
        else:
            await ctx.send(f"❌ No role mapping found for level {level}")
            
    @commands.command(name="dbstatus", aliases=["dbhealth"])
    @commands.has_permissions(administrator=True)
    async def database_status(self, ctx):
        """Display database health and status information"""
        stats = await get_health_stats()
        
        embed = discord.Embed(
            title="Database Status",
            color=discord.Color.green() if stats["is_healthy"] else discord.Color.red()
        )
        
        # Health status
        status = "✅ Healthy" if stats["is_healthy"] else "❌ Unhealthy"
        embed.add_field(name="Status", value=status, inline=False)
        
        # Additional info
        if stats["last_check_time"]:
            embed.add_field(name="Last Check", value=stats["last_check_time"], inline=True)
        
        if stats["last_recovery_time"]:
            embed.add_field(name="Last Recovery", value=stats["last_recovery_time"], inline=True)
        
        embed.add_field(name="Consecutive Failures", value=str(stats["consecutive_failures"]), inline=True)
        embed.add_field(name="Pending Operations", value=str(stats["pending_operations"]), inline=True)
        
        # Cache stats
        cache_info = stats["cache_stats"]
        embed.add_field(
            name="Cache Usage", 
            value=f"Users: {cache_info['level_cache_size']}\nConfig: {cache_info['config_cache_size']}\nRoles: {cache_info['role_cache_size']}",
            inline=False
        )
        
        # Failure reason if any
        if stats["last_failure_reason"]:
            embed.add_field(name="Last Error", value=stats["last_failure_reason"], inline=False)
        
        await ctx.send(embed=embed)
        
    @commands.command(name="create_event", aliases=["event"])
    @commands.has_permissions(administrator=True)
    async def create_event(self, ctx, name: str, multiplier: float, duration_hours: float):
        """Create a temporary XP boost event

        Args:
            name: Event name
            multiplier: XP multiplier (e.g., 1.5 for 50% more XP)
            duration_hours: How long the event will last in hours
        """
        if multiplier < 1.0 or multiplier > 5.0:
            return await ctx.send("⚠️ Multiplier must be between 1.0 and 5.0")
        
        if duration_hours <= 0 or duration_hours > 168:  # Max 1 week
            return await ctx.send("⚠️ Duration must be between 0 and 168 hours (1 week)")
        
        guild_id = str(ctx.guild.id)
        start_time = time.time()
        end_time = start_time + (duration_hours * 3600)
        created_by = str(ctx.author.id)
        
        # Create the event
        event_id = await create_xp_boost_event(
            guild_id, name, multiplier, start_time, end_time, created_by
        )
        
        if event_id:
            # Format times for display
            start_dt = datetime.fromtimestamp(start_time)
            end_dt = datetime.fromtimestamp(end_time)
            
            embed = discord.Embed(
                title="XP Boost Event Created",
                description=f"**{name}** is now active!",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Multiplier", value=f"{multiplier}x XP", inline=True)
            embed.add_field(name="Duration", value=f"{duration_hours} hours", inline=True)
            embed.add_field(name="Event ID", value=f"#{event_id}", inline=True)
            embed.add_field(name="Timeframe", value=f"From: {start_dt.strftime('%Y-%m-%d %H:%M')}\nTo: {end_dt.strftime('%Y-%m-%d %H:%M')}", inline=False)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to create XP boost event. Please try again.")

    @commands.command(name="schedule_event", aliases=["schevent"])
    @commands.has_permissions(administrator=True)
    async def schedule_event(self, ctx, name: str, multiplier: float, duration_hours: float, days_from_now: float = 0, hours_from_now: float = 0):
        """Schedule a future XP boost event

        Args:
            name: Event name
            multiplier: XP multiplier (e.g., 1.5 for 50% more XP)
            duration_hours: How long the event will last in hours
            days_from_now: Days until event starts
            hours_from_now: Hours until event starts
        """
        if multiplier < 1.0 or multiplier > 5.0:
            return await ctx.send("⚠️ Multiplier must be between 1.0 and 5.0")
        
        if duration_hours <= 0 or duration_hours > 168:  # Max 1 week
            return await ctx.send("⚠️ Duration must be between 0 and 168 hours (1 week)")
        
        if days_from_now < 0 or hours_from_now < 0:
            return await ctx.send("⚠️ Start time cannot be in the past")
        
        if days_from_now == 0 and hours_from_now < 1:
            return await ctx.send("⚠️ Event must be scheduled at least 1 hour in advance")
        
        guild_id = str(ctx.guild.id)
        start_offset = (days_from_now * 86400) + (hours_from_now * 3600)  # Convert to seconds
        
        start_time = time.time() + start_offset
        end_time = start_time + (duration_hours * 3600)
        created_by = str(ctx.author.id)
        
        # Create the event
        event_id = await create_xp_boost_event(
            guild_id, name, multiplier, start_time, end_time, created_by
        )
        
        if event_id:
            # Format times for display
            start_dt = datetime.fromtimestamp(start_time)
            end_dt = datetime.fromtimestamp(end_time)
            
            embed = discord.Embed(
                title="XP Boost Event Scheduled",
                description=f"**{name}** has been scheduled!",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="Multiplier", value=f"{multiplier}x XP", inline=True)
            embed.add_field(name="Duration", value=f"{duration_hours} hours", inline=True)
            embed.add_field(name="Event ID", value=f"#{event_id}", inline=True)
            embed.add_field(name="Starts In", value=f"{int(days_from_now)} days and {int(hours_from_now)} hours", inline=False)
            embed.add_field(name="Timeframe", value=f"From: {start_dt.strftime('%Y-%m-%d %H:%M')}\nTo: {end_dt.strftime('%Y-%m-%d %H:%M')}", inline=False)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to schedule XP boost event. Please try again.")

    @commands.command(name="active_events", aliases=["events"])
    async def active_events(self, ctx):
        """Show currently active XP boost events"""
        guild_id = str(ctx.guild.id)
        active_events = await get_active_xp_boost_events(guild_id)
        
        if not active_events:
            await ctx.send("No XP boost events are currently active.")
            return
        
        embed = discord.Embed(
            title="Active XP Boost Events",
            description=f"{len(active_events)} active event(s)",
            color=discord.Color.green()
        )
        
        for event in active_events:
            # Calculate remaining time
            remaining = event["end_time"] - time.time()
            hours_remaining = remaining / 3600
            
            if hours_remaining < 1:
                time_left = f"{int(remaining / 60)} minutes"
            else:
                time_left = f"{hours_remaining:.1f} hours"
            
            # Format values
            start_dt = datetime.fromtimestamp(event["start_time"])
            end_dt = datetime.fromtimestamp(event["end_time"])
            creator = ctx.guild.get_member(int(event["created_by"]))
            creator_name = creator.display_name if creator else "Unknown"
            
            # Add to embed
            embed.add_field(
                name=f"#{event['id']}: {event['name']}",
                value=f"Multiplier: **{event['multiplier']}x**\n"
                    f"Ends: {end_dt.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Time left: **{time_left}**\n"
                    f"Created by: {creator_name}",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @commands.command(name="upcoming_events", aliases=["uevents"])
    async def upcoming_events(self, ctx):
        """Show upcoming scheduled XP boost events"""
        guild_id = str(ctx.guild.id)
        upcoming_events = await get_upcoming_xp_boost_events(guild_id)
        
        if not upcoming_events:
            await ctx.send("No upcoming XP boost events are scheduled.")
            return
        
        embed = discord.Embed(
            title="Upcoming XP Boost Events",
            description=f"{len(upcoming_events)} scheduled event(s)",
            color=discord.Color.blue()
        )
        
        for event in upcoming_events:
            # Calculate time until start
            until_start = event["start_time"] - time.time()
            hours_until = until_start / 3600
            
            if hours_until < 1:
                time_until = f"{int(until_start / 60)} minutes"
            elif hours_until < 24:
                time_until = f"{hours_until:.1f} hours"
            else:
                days_until = hours_until / 24
                time_until = f"{days_until:.1f} days"
            
            # Format values
            start_dt = datetime.fromtimestamp(event["start_time"])
            end_dt = datetime.fromtimestamp(event["end_time"])
            duration_hours = (event["end_time"] - event["start_time"]) / 3600
            creator = ctx.guild.get_member(int(event["created_by"]))
            creator_name = creator.display_name if creator else "Unknown"
            
            # Add to embed
            embed.add_field(
                name=f"#{event['id']}: {event['name']}",
                value=f"Multiplier: **{event['multiplier']}x**\n"
                    f"Starts in: **{time_until}**\n"
                    f"Start: {start_dt.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Duration: {duration_hours:.1f} hours\n"
                    f"Created by: {creator_name}",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @commands.command(name="cancel_event", aliases=["cevent"])
    @commands.has_permissions(administrator=True)
    async def cancel_event(self, ctx, event_id: int):
        """Cancel an XP boost event

        Args:
            event_id: ID of the event to cancel
        """
        # First get the event to check it belongs to this guild
        event = await get_xp_boost_event(event_id)
        
        if not event:
            return await ctx.send("❌ Event not found. Check the event ID with `!active_events` or `!upcoming_events`.")
        
        # Check the event belongs to this guild
        if event["guild_id"] != str(ctx.guild.id):
            return await ctx.send("❌ Event not found in this server.")
        
        # Check if the event is already inactive
        if not event["active"]:
            return await ctx.send("❌ This event has already been cancelled.")
        
        # Delete the event
        success = await delete_xp_boost_event(event_id)
        
        if success:
            embed = discord.Embed(
                title="XP Boost Event Cancelled",
                description=f"Event #{event_id}: **{event['name']}** has been cancelled.",
                color=discord.Color.red()
            )
            
            # Format time information
            start_dt = datetime.fromtimestamp(event["start_time"])
            current_time = time.time()
            
            if event["start_time"] > current_time:
                status = "This event was scheduled to start in the future."
            else:
                status = "This event was active and has been stopped."
            
            embed.add_field(name="Status", value=status, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to cancel the event. Please try again.")

    @commands.command(name="xpsettings", aliases=["xps"])
    @commands.has_permissions(administrator=True)
    async def xp_settings(self, ctx):
        """View current XP settings for the server"""
        guild_id = str(ctx.guild.id)
        settings = await get_server_xp_settings(guild_id)
        
        embed = discord.Embed(
            title="Server XP Settings",
            description="Current XP configuration for this server",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Min XP per Message", value=f"{settings['min_xp']} XP", inline=True)
        embed.add_field(name="Max XP per Message", value=f"{settings['max_xp']} XP", inline=True)
        embed.add_field(name="XP Cooldown", value=f"{settings['cooldown']} seconds", inline=True)
        
        # Get the global settings for comparison
        from config import XP_SETTINGS
        
        # Only show if different from defaults
        if (settings['min_xp'] != XP_SETTINGS['MIN'] or 
            settings['max_xp'] != XP_SETTINGS['MAX'] or 
            settings['cooldown'] != XP_SETTINGS['COOLDOWN']):
            
            embed.add_field(
                name="Default Settings",
                value=(
                    f"Min XP: {XP_SETTINGS['MIN']} XP\n"
                    f"Max XP: {XP_SETTINGS['MAX']} XP\n"
                    f"Cooldown: {XP_SETTINGS['COOLDOWN']} seconds"
                ),
                inline=False
            )
        
        embed.add_field(
            name="Voice XP Rates", 
            value=(
                f"• Active: {XP_SETTINGS['RATES']['active']} XP/min\n"
                f"• Muted: {XP_SETTINGS['RATES']['muted']} XP/min\n"
                f"• Idle: {XP_SETTINGS['RATES']['idle']} XP/min\n"
                f"• Streaming: {XP_SETTINGS['RATES']['streaming']} XP/min\n"
                f"• Watching: {XP_SETTINGS['RATES']['watching']} XP/min"
            ), 
            inline=False
        )
        
        embed.add_field(
            name="Commands",
            value=(
                "`!setminxp <value>` - Set minimum XP\n"
                "`!setmaxxp <value>` - Set maximum XP\n"
                "`!setcooldown <seconds>` - Set XP cooldown\n"
                "`!resetxpsettings` - Reset to defaults"
            ),
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name="setminxp")
    @commands.has_permissions(administrator=True)
    async def set_min_xp(self, ctx, value: int):
        """Set the minimum XP awarded per message"""
        if value < 1 or value > 100:
            return await ctx.send("⚠️ Min XP must be between 1 and 100")
        
        guild_id = str(ctx.guild.id)
        
        # First get current settings to check max XP
        settings = await get_server_xp_settings(guild_id)
        
        if value > settings["max_xp"]:
            return await ctx.send(f"⚠️ Min XP cannot be greater than max XP ({settings['max_xp']})")
        
        # Update setting
        success = await update_server_xp_settings(guild_id, {"min_xp": value})
        
        if success:
            await ctx.send(f"✅ Minimum XP set to {value}")
        else:
            await ctx.send("❌ Failed to update XP settings")

    @commands.command(name="setmaxxp")
    @commands.has_permissions(administrator=True)
    async def set_max_xp(self, ctx, value: int):
        """Set the maximum XP awarded per message"""
        if value < 1 or value > 500:
            return await ctx.send("⚠️ Max XP must be between 1 and 500")
        
        guild_id = str(ctx.guild.id)
        
        # First get current settings to check min XP
        settings = await get_server_xp_settings(guild_id)
        
        if value < settings["min_xp"]:
            return await ctx.send(f"⚠️ Max XP cannot be less than min XP ({settings['min_xp']})")
        
        # Update setting
        success = await update_server_xp_settings(guild_id, {"max_xp": value})
        
        if success:
            await ctx.send(f"✅ Maximum XP set to {value}")
        else:
            await ctx.send("❌ Failed to update XP settings")

    @commands.command(name="setcooldown")
    @commands.has_permissions(administrator=True)
    async def set_cooldown(self, ctx, seconds: int):
        """Set the cooldown between XP awards (in seconds)"""
        if seconds < 5 or seconds > 600:
            return await ctx.send("⚠️ Cooldown must be between 5 and 600 seconds")
        
        guild_id = str(ctx.guild.id)
        
        # Update setting
        success = await update_server_xp_settings(guild_id, {"cooldown": seconds})
        
        if success:
            await ctx.send(f"✅ XP cooldown set to {seconds} seconds")
        else:
            await ctx.send("❌ Failed to update XP settings")

    @commands.command(name="resetxpsettings")
    @commands.has_permissions(administrator=True)
    async def reset_xp_settings(self, ctx):
        """Reset XP settings to defaults"""
        guild_id = str(ctx.guild.id)
        
        success = await reset_server_xp_settings(guild_id)
        
        if success:
            # Get the global settings for display
            from config import XP_SETTINGS
            
            embed = discord.Embed(
                title="XP Settings Reset",
                description="Server XP settings have been reset to defaults",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Min XP per Message", value=f"{XP_SETTINGS['MIN']} XP", inline=True)
            embed.add_field(name="Max XP per Message", value=f"{XP_SETTINGS['MAX']} XP", inline=True)
            embed.add_field(name="XP Cooldown", value=f"{XP_SETTINGS['COOLDOWN']} seconds", inline=True)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to reset XP settings")