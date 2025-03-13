import discord
from discord.ext import commands
from modules.database import set_channel_boost_db , remove_channel_boost_db, create_level_role, get_level_roles, delete_level_role
import logging

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Reference to the channel boosts dictionary in main.py
        # This ensures we're working with the same dictionary across the bot
        from modules.database import CHANNEL_XP_BOOSTS
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
        await self.bot.db.execute('''
            INSERT OR REPLACE INTO server_config (guild_id, level_up_channel)
            VALUES (?, ?)
        ''', (guild_id, channel_id))
        await self.bot.db.commit()
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
        
        # Set the boost
        self.channel_boosts[channel_id] = boost_multiplier
        
        logging.info(self.channel_boosts, boost_multiplier, channel)

        # Save to database for persistence
        await set_channel_boost_db(self.bot, str(ctx.guild.id), channel_id, boost_multiplier)
        
        channel_type = "voice" if isinstance(channel, discord.VoiceChannel) else "text"
        await ctx.send(f"✅ Set XP boost for {channel_type} channel '{channel.name}' to {boost_multiplier}x")

    @commands.command(name="remove_channel_boost", aliases=["rcboost"])
    @commands.has_permissions(administrator=True)
    async def remove_channel_boost(self, ctx, channel_id: str):
        """Remove an XP boost from a specific channel"""
        if channel_id in self.channel_boosts:
            del self.channel_boosts[channel_id]
            
            # Save to database for persistence
            await remove_channel_boost_db(self.bot, str(ctx.guild.id), channel_id)
            
            channel = self.bot.get_channel(int(channel_id))
            channel_name = channel.name if channel else "Unknown channel"
            
            await ctx.send(f"✅ Removed XP boost from {channel_name}")
        else:
            await ctx.send("⚠️ That channel doesn't have an XP boost set.")

    @commands.command(name="list_channel_boosts", aliases=["lcboost"])
    async def list_channel_boosts(self, ctx):
        """List all channels with XP boosts"""
        if not self.channel_boosts:
            await ctx.send("No channel XP boosts are currently set.")
            return
        
        embed = discord.Embed(
            title="Channel XP Boosts",
            description="These channels have XP multipliers applied:",
            color=discord.Color.blue()
        )
        
        voice_channels = []
        text_channels = []
        
        for channel_id, multiplier in self.channel_boosts.items():
            channel = self.bot.get_channel(int(channel_id))
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
        
        await ctx.send(embed=embed)

    @commands.command(name="set_level_roles", aliases=["slroles"])
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
        success = await create_level_role(self.bot, str(ctx.guild.id), level, str(role.id))
        
        if success:
            await ctx.send(f"✅ Role {role.name} will be awarded at level {level}")
        else:
            await ctx.send("❌ An error occurred while setting the level role")
    
    @commands.command(name="list_level_roles", aliases=["llroles"])
    async def list_level_roles(self, ctx):
        """List all level roles for this server"""
        guild_level_roles = await get_level_roles(self.bot, str(ctx.guild.id))
        
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
    
    @commands.command(name="delete_level_roles", aliases=["dlroles"])
    @commands.has_permissions(administrator=True)
    async def delete_level_role(self, ctx, level: int):
        """Delete a level role mapping"""
        success = await delete_level_role(self.bot, str(ctx.guild.id), level)
        
        if success:
            await ctx.send(f"✅ Level {level} role mapping has been deleted")
        else:
            await ctx.send(f"❌ No role mapping found for level {level}")

