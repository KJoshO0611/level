import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime
import time
from modules.databasev2 import (
    get_health_stats, 
    load_channel_boosts,
    set_channel_boost_db,
    create_xp_boost_event,
    get_active_xp_boost_events,
    get_upcoming_xp_boost_events,
    delete_xp_boost_event,
    get_xp_boost_event,
    delete_level_role,
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

        #slash command
        @app_commands.command(name="xpboost", description="Set an XP boost multiplier for a channel")
        @app_commands.describe(
            channel="The channel to apply the XP boost to",
            multiplier="The XP multiplier (0.1-5.0)"
        )
        @app_commands.checks.has_permissions(administrator=True)
        async def xp_boost(
            self, 
            interaction: discord.Interaction, 
            channel: discord.abc.GuildChannel,
            multiplier: float
        ):
            """Set an XP boost for a specific channel"""
            # Validate the channel type
            if not isinstance(channel, (discord.VoiceChannel, discord.TextChannel)):
                await interaction.response.send_message(
                    "⚠️ XP boosts can only be applied to text or voice channels.",
                    ephemeral=True
                )
                return
            
            # Validate the multiplier
            if multiplier < 0.1 or multiplier > 5.0:
                await interaction.response.send_message(
                    "⚠️ Boost multiplier must be between 0.1 and 5.0",
                    ephemeral=True
                )
                return
            
            # Set the boost
            guild_id = str(interaction.guild.id)
            channel_id = str(channel.id)
            await set_channel_boost_db(guild_id, channel_id, multiplier)
            
            channel_type = "voice" if isinstance(channel, discord.VoiceChannel) else "text"
            await interaction.response.send_message(
                f"✅ Set XP boost for {channel_type} channel '{channel.name}' to {multiplier}x",
                ephemeral=True
            )

        # New event-related slash commands
    @app_commands.command(name="createevent", description="Create a temporary XP boost event")
    @app_commands.describe(
        name="Event name",
        multiplier="XP multiplier (e.g., 1.5 for 50% more XP)",
        duration_hours="How long the event will last in hours"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_event(
        self,
        interaction: discord.Interaction,
        name: str,
        multiplier: float,
        duration_hours: float
    ):
        """Create a temporary XP boost event"""
        if multiplier < 1.0 or multiplier > 5.0:
            return await interaction.response.send_message("⚠️ Multiplier must be between 1.0 and 5.0", ephemeral=True)
        
        if duration_hours <= 0 or duration_hours > 168:  # Max 1 week
            return await interaction.response.send_message("⚠️ Duration must be between 0 and 168 hours (1 week)", ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        start_time = time.time()
        end_time = start_time + (duration_hours * 3600)
        created_by = str(interaction.user.id)
        
        # Create the event
        event_id = await create_xp_boost_event(
            guild_id, name, multiplier, start_time, end_time, created_by
        )
        
        if event_id:
            # Format Discord timestamps
            start_timestamp = int(start_time)
            end_timestamp = int(end_time)
            
            start_discord_time = f"<t:{start_timestamp}:F>"
            end_discord_time = f"<t:{end_timestamp}:F>"
            relative_end_time = f"<t:{end_timestamp}:R>"
            
            embed = discord.Embed(
                title="XP Boost Event Created",
                description=f"**{name}** is now active!",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Multiplier", value=f"{multiplier}x XP", inline=True)
            embed.add_field(name="Duration", value=f"{duration_hours} hours", inline=True)
            embed.add_field(name="Event ID", value=f"#{event_id}", inline=True)
            embed.add_field(name="Timeframe", value=f"From: {start_discord_time}\nTo: {end_discord_time}\nEnds: {relative_end_time}", inline=False)
            
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Failed to create XP boost event. Please try again.", ephemeral=True)

    @app_commands.command(name="scheduleevent", description="Schedule a future XP boost event")
    @app_commands.describe(
        name="Event name",
        multiplier="XP multiplier (e.g., 1.5 for 50% more XP)",
        duration_hours="How long the event will last in hours",
        days_from_now="Days until event starts",
        hours_from_now="Hours until event starts"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_event(
        self,
        interaction: discord.Interaction,
        name: str,
        multiplier: float,
        duration_hours: float,
        days_from_now: float = 0.0,
        hours_from_now: float = 0.0
    ):
        """Schedule a future XP boost event"""
        if multiplier < 1.0 or multiplier > 5.0:
            return await interaction.response.send_message("⚠️ Multiplier must be between 1.0 and 5.0", ephemeral=True)
        
        if duration_hours <= 0 or duration_hours > 168:  # Max 1 week
            return await interaction.response.send_message("⚠️ Duration must be between 0 and 168 hours (1 week)", ephemeral=True)
        
        if days_from_now < 0 or hours_from_now < 0:
            return await interaction.response.send_message("⚠️ Start time cannot be in the past", ephemeral=True)
        
        if days_from_now == 0 and hours_from_now < 1:
            return await interaction.response.send_message("⚠️ Event must be scheduled at least 1 hour in advance", ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        start_offset = (days_from_now * 86400) + (hours_from_now * 3600)  # Convert to seconds
        
        start_time = time.time() + start_offset
        end_time = start_time + (duration_hours * 3600)
        created_by = str(interaction.user.id)
        
        # Create the event
        event_id = await create_xp_boost_event(
            guild_id, name, multiplier, start_time, end_time, created_by
        )
        
        if event_id:
            # Convert timestamps to integers for Discord timestamp formatting
            start_timestamp = int(start_time)
            end_timestamp = int(end_time)
            
            # Format Discord timestamps (shows in user's local timezone)
            # f, F = full date/time format, R = relative time format (e.g., "in 2 days")
            start_discord_time = f"<t:{start_timestamp}:F>"
            end_discord_time = f"<t:{end_timestamp}:F>"
            relative_start_time = f"<t:{start_timestamp}:R>"
            
            embed = discord.Embed(
                title="XP Boost Event Scheduled",
                description=f"**{name}** has been scheduled!",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="Multiplier", value=f"{multiplier}x XP", inline=True)
            embed.add_field(name="Duration", value=f"{duration_hours} hours", inline=True)
            embed.add_field(name="Event ID", value=f"#{event_id}", inline=True)
            embed.add_field(name="Starts", value=f"{relative_start_time}", inline=False)
            embed.add_field(name="Timeframe", value=f"From: {start_discord_time}\nTo: {end_discord_time}", inline=False)
            
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Failed to schedule XP boost event. Please try again.", ephemeral=True)

    @app_commands.command(name="activeevents", description="Show currently active XP boost events")
    async def active_events(self, interaction: discord.Interaction):
        """Show currently active XP boost events"""
        guild_id = str(interaction.guild.id)
        active_events = await get_active_xp_boost_events(guild_id)
        
        if not active_events:
            await interaction.response.send_message("No XP boost events are currently active.", ephemeral=True)
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
            
            # Format Discord timestamps
            end_timestamp = int(event["end_time"])
            end_discord_time = f"<t:{end_timestamp}:F>"
            relative_end_time = f"<t:{end_timestamp}:R>"
            
            creator = interaction.guild.get_member(int(event["created_by"]))
            creator_name = creator.display_name if creator else "Unknown"
            
            # Add to embed
            embed.add_field(
                name=f"#{event['id']}: {event['name']}",
                value=f"Multiplier: **{event['multiplier']}x**\n"
                    f"Ends: {end_discord_time}\n"
                    f"Time left: {relative_end_time}\n"
                    f"Created by: {creator_name}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="upcomingevents", description="Show upcoming scheduled XP boost events")
    async def upcoming_events(self, interaction: discord.Interaction):
        """Show upcoming scheduled XP boost events"""
        guild_id = str(interaction.guild.id)
        upcoming_events = await get_upcoming_xp_boost_events(guild_id)
        
        if not upcoming_events:
            await interaction.response.send_message("No upcoming XP boost events are scheduled.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Upcoming XP Boost Events",
            description=f"{len(upcoming_events)} scheduled event(s)",
            color=discord.Color.blue()
        )
        
        for event in upcoming_events:
            # Format Discord timestamps
            start_timestamp = int(event["start_time"])
            end_timestamp = int(event["end_time"])
            
            start_discord_time = f"<t:{start_timestamp}:F>"
            relative_start_time = f"<t:{start_timestamp}:R>"
            
            # Calculate duration
            duration_hours = (event["end_time"] - event["start_time"]) / 3600
            
            creator = interaction.guild.get_member(int(event["created_by"]))
            creator_name = creator.display_name if creator else "Unknown"
            
            # Add to embed
            embed.add_field(
                name=f"#{event['id']}: {event['name']}",
                value=f"Multiplier: **{event['multiplier']}x**\n"
                    f"Starts: {relative_start_time}\n"
                    f"Start time: {start_discord_time}\n"
                    f"Duration: {duration_hours:.1f} hours\n"
                    f"Created by: {creator_name}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cancelevent", description="Cancel an XP boost event")
    @app_commands.describe(event_id="ID of the event to cancel")
    @app_commands.checks.has_permissions(administrator=True)
    async def cancel_event(self, interaction: discord.Interaction, event_id: int):
        """Cancel an XP boost event"""
        # First get the event to check it belongs to this guild
        event = await get_xp_boost_event(event_id)
        
        if not event:
            return await interaction.response.send_message(
                "❌ Event not found. Check the event ID with `/activeevents` or `/upcomingevents`.",
                ephemeral=True
            )
        
        # Check the event belongs to this guild
        if event["guild_id"] != str(interaction.guild.id):
            return await interaction.response.send_message("❌ Event not found in this server.", ephemeral=True)
        
        # Check if the event is already inactive
        if not event["active"]:
            return await interaction.response.send_message("❌ This event has already been cancelled.", ephemeral=True)
        
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
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to cancel the event. Please try again.", ephemeral=True)

    @app_commands.command(name="deletelevelrole", description="Delete a level role mapping")
    @app_commands.describe(level="The level to remove the role mapping from")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_level_role_cmd(self, interaction: discord.Interaction, level: int):
        """Delete a level role mapping"""
        success = await delete_level_role(str(interaction.guild.id), level)
        
        if success:
            await interaction.response.send_message(f"✅ Level {level} role mapping has been deleted", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ No role mapping found for level {level}", ephemeral=True)

def setup(bot):
    bot.add_cog(AdminCommands(bot)) 