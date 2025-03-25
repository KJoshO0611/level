import discord
import time
import logging
import psutil
import os
from datetime import datetime
from discord import app_commands
from discord.ext import commands, tasks
from utils.performance_monitoring import performance_data
from utils.cairo_image_generator import get_text_rendering_stats
from database import (
    get_health_stats, 
    load_channel_boosts,
    set_channel_boost_db,
    create_xp_boost_event,
    get_active_xp_boost_events,
    get_upcoming_xp_boost_events,
    delete_xp_boost_event,
    get_xp_boost_event,
    delete_level_role,
    get_level_up_channel,
    CHANNEL_XP_BOOSTS
)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Reference to the channel boosts dictionary in database.py
        self.channel_boosts = CHANNEL_XP_BOOSTS
        self.bot.loop.create_task(self.start_event_announcer())
    
    def cog_unload(self):
        """Called when the cog is unloaded"""
        # Stop the background task when cog is unloaded
        self.stop_event_announcer()

    @tasks.loop(minutes=2)  # Check every 2 minutes
    async def check_and_announce_events(self):
        """Check for recently started events and announce them"""
        try:
            # Get all guilds the bot is in
            for guild in self.bot.guilds:
                guild_id = str(guild.id)
                
                # Get all active events for this guild - using the cached function
                # This will use the cache if available and valid
                active_events = await get_active_xp_boost_events(guild_id)
                
                # Also check upcoming events that might have just started
                # Since the active_events cache might not be updated yet
                upcoming_events = await get_upcoming_xp_boost_events(guild_id)
                
                current_time = time.time()
                just_started_events = []
                recently_started_threshold = 120  # 2 minutes
                
                # Check which active events have just started (within the last 2 minutes)
                for event in active_events:
                    if current_time - recently_started_threshold <= event["start_time"] <= current_time:
                        just_started_events.append(event)
                
                # Also check if any upcoming events have just started but aren't in active_events yet
                for event in upcoming_events:
                    if current_time - recently_started_threshold <= event["start_time"] <= current_time:
                        # Only add if not already in the list
                        if not any(e["id"] == event["id"] for e in just_started_events):
                            just_started_events.append(event)
                
                if just_started_events:
                    # Try to find best channel to announce in
                    # First check for a dedicated event announcement channel
                    announce_channel = None
                    
                    # Get dedicated event channel if set
                    async with self.bot.db.acquire() as conn:
                        query = "SELECT event_channel FROM server_config WHERE guild_id = $1"
                        row = await conn.fetchrow(query, guild_id)
                        
                        if row and row['event_channel']:
                            event_channel_id = row['event_channel']
                            announce_channel = guild.get_channel(int(event_channel_id))
                    
                    # If no event channel, fall back to level-up channel
                    if not announce_channel:
                        level_up_channel_id = await get_level_up_channel(guild_id)
                        if level_up_channel_id:
                            announce_channel = guild.get_channel(int(level_up_channel_id))
                    
                    # If no level-up channel, try system channel
                    if not announce_channel and guild.system_channel:
                        announce_channel = guild.system_channel
                    
                    # If still no channel, try to find a general channel
                    if not announce_channel:
                        for channel in guild.text_channels:
                            if channel.permissions_for(guild.me).send_messages:
                                if channel.name.lower() in ["general", "main", "chat", "lobby", "lounge"]:
                                    announce_channel = channel
                                    break
                    
                    # Announce each event that just started
                    if announce_channel:
                        for event in just_started_events:
                            # Create an embed for the announcement
                            embed = discord.Embed(
                                title="🎉 XP Boost Event Started! 🎉",
                                description=f"**{event['name']}** is now active!",
                                color=discord.Color.gold()
                            )
                            
                            # Format timestamps
                            end_timestamp = int(event["end_time"])
                            end_discord_time = f"<t:{end_timestamp}:F>"
                            relative_end_time = f"<t:{end_timestamp}:R>"
                            
                            # Add event details
                            embed.add_field(name="Boost", value=f"**{event['multiplier']}x** XP multiplier", inline=True)
                            
                            # Calculate duration in hours
                            duration_hours = (event["end_time"] - event["start_time"]) / 3600
                            embed.add_field(name="Duration", value=f"{duration_hours:.1f} hours", inline=True)
                            
                            embed.add_field(name="Ends", value=f"{end_discord_time}\n({relative_end_time})", inline=False)
                            
                            # Add a footer with event ID
                            embed.set_footer(text=f"Event #{event['id']}")
                            
                            try:
                                await announce_channel.send(embed=embed)
                                logging.info(f"Announced event #{event['id']} in {guild.name}")
                            except Exception as e:
                                logging.error(f"Failed to announce event in {guild.name}: {e}")
                    else:
                        logging.warning(f"No suitable channel found to announce event in {guild.name}")
                        
        except Exception as e:
            logging.error(f"Error in check_and_announce_events: {e}")

    @check_and_announce_events.before_loop
    async def before_event_check(self):
        """Wait until the bot is ready before starting the task"""
        await self.bot.wait_until_ready()

    async def start_event_announcer(self):
        """Start the XP event announcement background task"""
        self.check_and_announce_events.start()
        logging.info("Started XP event announcement background task")

    def stop_event_announcer(self):
        """Stop the XP event announcement background task"""
        if self.check_and_announce_events.is_running():
            self.check_and_announce_events.cancel()
            logging.info("Stopped XP event announcement background task")

    @app_commands.command(name="seteventchannel", description="Set the channel for XP event announcements")
    @app_commands.describe(channel="The channel where XP event announcements will be sent")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_event_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the channel for XP event announcements using slash command"""
        guild_id = str(interaction.guild.id)
        channel_id = str(channel.id)
        
        # Reuse the level-up channel setting in database, but with a different key
        async with self.bot.db.acquire() as conn:
            query = """
            UPDATE server_config 
            SET event_channel = $1
            WHERE guild_id = $2
            """
            rows_affected = await conn.execute(query, channel_id, guild_id)
            
            # If server_config entry doesn't exist for this guild yet, create it
            if rows_affected == "0":
                query = """
                INSERT INTO server_config (guild_id, level_up_channel, event_channel)
                VALUES ($1, '', $2)
                """
                await conn.execute(query, guild_id, channel_id)
        
        await interaction.response.send_message(
            f"✅ XP event announcements will now be sent to {channel.mention}",
            ephemeral=True
        )

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

    @commands.command(name="textstats", aliases=["ts"])
    @commands.has_permissions(administrator=True)
    async def text_stats(self, ctx):
        """Display text rendering cache statistics with memory usage"""
        
        stats = get_text_rendering_stats()
        
        embed = discord.Embed(
            title="Text Rendering Statistics",
            color=discord.Color.blue()
        )
        
        # Add fields for each cache
        for cache_name, cache_stats in stats.items():
            embed.add_field(
                name=f"{cache_stats['name']} Cache",
                value=(
                    f"Items: {cache_stats['items']}/{cache_stats['max_items']}\n"
                    f"Memory: {cache_stats['memory_mb']:.2f}MB/{cache_stats['max_memory_mb']:.2f}MB\n"
                    f"Hit Ratio: {cache_stats['hit_ratio']*100:.1f}%"
                ),
                inline=True
            )
        
        # Add total memory usage
        total_memory = sum(cache_stats['memory_mb'] for cache_stats in stats.values())
        embed.add_field(
            name="Total Memory Usage",
            value=f"{total_memory:.2f}MB",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    @commands.command(name="clearcache", aliases=["cc"])
    @commands.has_permissions(administrator=True)
    async def clear_cache(self, ctx, cache_name=None):
        """Clear specific or all image caches"""
        from utils.cairo_image_generator import (
            FONT_CACHE, TEXT_MEASURE_CACHE, SCRIPT_CACHE, 
            TEMPLATE_CACHE, BACKGROUND_CACHE
        )
        
        caches = {
            "font": FONT_CACHE,
            "text": TEXT_MEASURE_CACHE,
            "script": SCRIPT_CACHE,
            "template": TEMPLATE_CACHE,
            "background": BACKGROUND_CACHE
        }
        
        if cache_name and cache_name.lower() in caches:
            # Clear specific cache
            cache = caches[cache_name.lower()]
            before_items = len(cache)
            before_memory = cache.current_memory / (1024 * 1024)
            
            cache.clear()
            
            await ctx.send(
                f"✅ Cleared {cache_name} cache. "
                f"Freed {before_items} items and {before_memory:.2f}MB of memory."
            )
        elif cache_name and cache_name.lower() == "all":
            # Clear all caches
            total_items = 0
            total_memory = 0
            
            for cache in caches.values():
                total_items += len(cache)
                total_memory += cache.current_memory / (1024 * 1024)
                cache.clear()
            
            # Force garbage collection
            import gc
            gc.collect()
            
            await ctx.send(
                f"✅ Cleared ALL caches. "
                f"Freed {total_items} items and {total_memory:.2f}MB of memory."
            )
            
        else:
            # Show cache sizes
            embed = discord.Embed(
                title="Cache Sizes",
                description="Use `!!clearcache [cache_name]` to clear a specific cache, or `!!clearcache all` to clear all caches.",
                color=discord.Color.blue()
            )
            
            for name, cache in caches.items():
                embed.add_field(
                    name=f"{name.capitalize()} Cache",
                    value=f"{len(cache)} items, {cache.current_memory / (1024 * 1024):.2f}MB",
                    inline=True
                )
            
            await ctx.send(embed=embed)

    @commands.command(name="perfstats", aliases=["botstats"], hidden=True)
    @commands.has_permissions(administrator=True)
    async def performance_status(self, ctx):
        """Show performance metrics for the bot"""
        if not PSUTIL_AVAILABLE:
            psutil_status = "⚠️ psutil not installed (memory metrics unavailable)"
        else:
            psutil_status = "✅ psutil available (memory metrics enabled)"
            
        # Create an embed with performance data
        embed = discord.Embed(
            title="🔍 Performance Monitoring",
            description="Current performance metrics for the bot",
            color=discord.Color.blue()
        )
        
        # Memory metrics
        if PSUTIL_AVAILABLE:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            embed.add_field(
                name="Memory Usage",
                value=f"Current: {memory_mb:.2f} MB\nPeak: {performance_data['peak_memory']:.2f} MB",
                inline=True
            )
            
            # CPU usage
            cpu_percent = process.cpu_percent(interval=0.5)
            embed.add_field(
                name="CPU Usage",
                value=f"Current: {cpu_percent:.1f}%",
                inline=True
            )
        
        # Voice session metrics
        try:
            # Import voice_sessions here to avoid circular imports
            from modules import voice_activity
            voice_sessions = voice_activity.voice_sessions
            
            total_sessions = len(voice_sessions)
            total_history = sum(
                len(session.get("state_history", [])) 
                for session in voice_sessions.values()
            )
            
            embed.add_field(
                name="Voice Sessions",
                value=f"Active: {total_sessions}\nHistory entries: {total_history}",
                inline=True
            )
        except:
            embed.add_field(
                name="Voice Sessions",
                value="Unable to retrieve voice session data",
                inline=True
            )
        
        # Function timing metrics
        if performance_data["function_times"]:
            # Sort by average time
            sorted_funcs = sorted(
                performance_data["function_times"].items(),
                key=lambda x: x[1]["total_ms"] / x[1]["count"],
                reverse=True
            )
            
            # Show top 5 slowest functions
            timing_text = "\n".join([
                f"`{name}`: {data['total_ms']/data['count']:.1f}ms avg ({data['count']} calls)"
                for name, data in sorted_funcs[:5]
            ])
            
            embed.add_field(
                name="Slowest Functions (Average)",
                value=timing_text,
                inline=False
            )
        
        # Recent slow operations
        if performance_data["slow_operations"]:
            recent_slow = sorted(
                performance_data["slow_operations"],
                key=lambda x: x["timestamp"],
                reverse=True
            )[:5]
            
            slow_text = "\n".join([
                f"`{op['function']}`: {op['time_ms']:.1f}ms"
                for op in recent_slow
            ])
            
            embed.add_field(
                name="Recent Slow Operations",
                value=slow_text,
                inline=False
            )
        
        # Add footer with dependencies
        embed.set_footer(text=f"Monitoring status: {psutil_status}")
        
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
        start_date="Start date in YYYY-MM-DD format (e.g., 2025-04-15)",
        start_time="Start time in 24-hour format HH:MM (e.g., 18:30)",
        days_from_now="Days until event starts (ignored if start_date is provided)",
        hours_from_now="Hours until event starts (ignored if start_date is provided)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule_event(
        self,
        interaction: discord.Interaction,
        name: str,
        multiplier: float,
        duration_hours: float,
        start_date: str = None,
        start_time: str = None,
        days_from_now: float = 0.0,
        hours_from_now: float = 0.0
    ):
        """Schedule a future XP boost event with option for specific date and time"""
        if multiplier < 1.0 or multiplier > 5.0:
            return await interaction.response.send_message("⚠️ Multiplier must be between 1.0 and 5.0", ephemeral=True)
        
        if duration_hours <= 0 or duration_hours > 168:  # Max 1 week
            return await interaction.response.send_message("⚠️ Duration must be between 0 and 168 hours (1 week)", ephemeral=True)
        
        # Determine start time based on provided parameters
        current_time = time.time()
        start_timestamp = None
        
        # If specific date/time is provided, use it
        if start_date:
            try:
                # Parse date and optionally time
                from datetime import datetime
                
                # Default time to midnight if not provided
                if not start_time:
                    start_time = "00:00"
                    
                # Parse the date and time string into a datetime object
                dt_str = f"{start_date} {start_time}"
                event_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                
                # Convert to timestamp
                start_timestamp = event_dt.timestamp()
                
                # Ensure event is in the future
                if start_timestamp <= current_time:
                    return await interaction.response.send_message("⚠️ Event start time must be in the future", ephemeral=True)
                
                # Ensure event is at least 10 minutes in the future to avoid immediate starts
                if start_timestamp < current_time + 600:  # 600 seconds = 10 minutes
                    return await interaction.response.send_message("⚠️ Event must be scheduled at least 10 minutes in advance", ephemeral=True)
                    
            except ValueError as e:
                return await interaction.response.send_message(f"⚠️ Invalid date or time format: {str(e)}", ephemeral=True)
        else:
            # Use relative time if specific date not provided
            if days_from_now < 0 or hours_from_now < 0:
                return await interaction.response.send_message("⚠️ Start time cannot be in the past", ephemeral=True)
            
            if days_from_now == 0 and hours_from_now < 1:
                return await interaction.response.send_message("⚠️ Event must be scheduled at least 1 hour in advance", ephemeral=True)
            
            start_offset = (days_from_now * 86400) + (hours_from_now * 3600)  # Convert to seconds
            start_timestamp = current_time + start_offset
        
        # Calculate end time
        end_timestamp = start_timestamp + (duration_hours * 3600)
        guild_id = str(interaction.guild.id)
        created_by = str(interaction.user.id)
        
        # Create the event
        event_id = await create_xp_boost_event(
            guild_id, name, multiplier, start_timestamp, end_timestamp, created_by
        )
        
        if event_id:
            # Convert timestamps to integers for Discord timestamp formatting
            start_timestamp = int(start_timestamp)
            end_timestamp = int(end_timestamp)
            
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