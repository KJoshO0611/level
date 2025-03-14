import discord
from discord.ext import commands
from modules.databasev2 import set_channel_boost_db, remove_channel_boost_db, create_level_role, get_level_roles, delete_level_role, set_level_up_channel, get_health_stats, invalidate_guild_cache, CHANNEL_XP_BOOSTS
import logging

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Reference to the channel boosts dictionary in database.py
        self.channel_boosts = CHANNEL_XP_BOOSTS

    @commands.command(name="setlevelupchannel", aliases=["setlc"])
    @commands.has_permissions(manage_guild=True)
    async def setlevelupchannel(self, ctx, channel: discord.TextChannel):
        """
        Sets the channel where level-up notifications will be sent.
        Only administrators with the Manage Server permission can use this command.
        """
        await ctx.message.delete()

        guild_id = str(ctx.guild.id)
        channel_id = str(channel.id)
        
        # Use the improved database function
        await set_level_up_channel(guild_id, channel_id)
        await ctx.send(f"Level-up notifications will now be sent to {channel.mention}")

    @commands.command(name="set_channel_boost", aliases=["boost"])
    @commands.has_permissions(administrator=True)
    async def set_channel_boost(self, ctx, channel_id: str, boost_multiplier: float):
        """Set an XP boost multiplier for a specific channel (voice or text)"""
        # Validate the channel exists
        channel = self.bot.get_channel(int(channel_id))
        if not channel or not isinstance(channel, (discord.VoiceChannel, discord.TextChannel)):
            await ctx.send("⚠️ That doesn't appear to be a valid channel ID.")
            return
        
        # Validate the multiplier is reasonable
        if boost_multiplier < 0.1 or boost_multiplier > 5.0:
            await ctx.send("⚠️ Boost multiplier must be between 0.1 and 5.0")
            return
        
        # Set the boost in database
        await set_channel_boost_db(str(ctx.guild.id), channel_id, boost_multiplier)
        
        channel_type = "voice" if isinstance(channel, discord.VoiceChannel) else "text"
        await ctx.send(f"✅ Set XP boost for {channel_type} channel '{channel.name}' to {boost_multiplier}x")

    @commands.command(name="remove_channel_boost", aliases=["rcboost"])
    @commands.has_permissions(administrator=True)
    async def remove_channel_boost(self, ctx, channel_id: str):
        """Remove an XP boost from a specific channel"""
        if channel_id in self.channel_boosts:
            # Remove from database
            await remove_channel_boost_db(str(ctx.guild.id), channel_id)
            
            channel = self.bot.get_channel(int(channel_id))
            channel_name = channel.name if channel else "Unknown channel"
            
            await ctx.send(f"✅ Removed XP boost from {channel_name}")
        else:
            await ctx.send("⚠️ That channel doesn't have an XP boost set.")

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
    
    @commands.command(name="set_level_role", aliases=["slrole"])
    @commands.has_permissions(administrator=True)
    async def set_level_role(self, ctx, level: int, role: discord.Role):
        """Set a role to be awarded at a specific level"""
        if level < 1:
            return await ctx.send("Level must be at least 1")
        
        # Check bot permissions
        if not ctx.guild.me.guild_permissions.manage_roles:
            return await ctx.send("I don't have permission to manage roles")
            
        # Check role hierarchy
        if role.position >= ctx.guild.me.top_role.position:
            return await ctx.send("That role is higher than my highest role, I can't assign it")
        
        # Store in database
        success = await create_level_role(str(ctx.guild.id), level, str(role.id))
        
        if success:
            await ctx.send(f"✅ Role {role.name} will be awarded at level {level}")
        else:
            await ctx.send("❌ An error occurred while setting the level role")
    
    @commands.command(name="list_level_roles", aliases=["llroles"])
    async def list_level_roles(self, ctx):
        """List all level roles for this server"""
        # Use cached version for better performance
        guild_level_roles = await get_level_roles(str(ctx.guild.id))
        
        if not guild_level_roles:
            return await ctx.send("No level roles are configured for this server")
        
        embed = discord.Embed(
            title="Level Roles",
            description="Roles awarded at specific levels",
            color=discord.Color.blue()
        )
        
        for level, role_id in sorted(guild_level_roles.items()):
            role = ctx.guild.get_role(int(role_id))
            role_name = role.name if role else f"Unknown Role (ID: {role_id})"
            embed.add_field(name=f"Level {level}", value=role_name, inline=False)
        
        await ctx.send(embed=embed)
    
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
        
    @commands.command(name="clearcache", aliases=["cc"])
    @commands.has_permissions(administrator=True)
    async def clear_cache(self, ctx, guild_id: str = None):
        """Clear the bot's cache for this guild or a specific guild"""
        guild_id_to_clear = guild_id or str(ctx.guild.id)
        
        # Invalidate cache for the guild
        invalidate_guild_cache(guild_id_to_clear)
        
        await ctx.send(f"✅ Cache cleared for guild ID: {guild_id_to_clear}")