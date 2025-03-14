import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal
import logging
from modules.databasev2 import (
    set_level_up_channel, 
    get_level_up_channel, 
    set_channel_boost_db, 
    remove_channel_boost_db,
    get_level_roles,
    create_level_role,
    delete_level_role,
    invalidate_guild_cache
)
from config import load_config, XP_SETTINGS

# Load configuration
config = load_config()

class ConfigView(discord.ui.View):
    """Interactive view for server configuration settings"""
    def __init__(self, bot, timeout=180):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.config = config

    @discord.ui.button(label="XP Settings", style=discord.ButtonStyle.primary)
    async def xp_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show current XP settings"""
        embed = discord.Embed(
            title="XP Settings",
            description="Current XP configuration for this server",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="XP Cooldown", value=f"{XP_SETTINGS['COOLDOWN']} seconds", inline=True)
        embed.add_field(name="Min XP per Message", value=f"{XP_SETTINGS['MIN']} XP", inline=True)
        embed.add_field(name="Max XP per Message", value=f"{XP_SETTINGS['MAX']} XP", inline=True)
        
        embed.add_field(name="Voice XP Rates", value=(
            f"• Active: {XP_SETTINGS['RATES']['active']} XP/min\n"
            f"• Muted: {XP_SETTINGS['RATES']['muted']} XP/min\n"
            f"• Idle: {XP_SETTINGS['RATES']['idle']} XP/min\n"
            f"• Streaming: {XP_SETTINGS['RATES']['streaming']} XP/min\n"
            f"• Watching: {XP_SETTINGS['RATES']['watching']} XP/min"
        ), inline=False)
        
        # Get level-up channel info
        guild_id = str(interaction.guild.id)
        channel_id = await get_level_up_channel(guild_id)
        level_up_channel = "Not set" if not channel_id else f"<#{channel_id}>"
        
        embed.add_field(name="Level-up Notifications", value=level_up_channel, inline=False)
        
        # Get role rewards info
        level_roles = await get_level_roles(guild_id)
        roles_text = "No level roles configured"
        
        if level_roles:
            roles_text = "\n".join([
                f"Level {level}: <@&{role_id}>"
                for level, role_id in sorted(level_roles.items())
            ])
        
        embed.add_field(name="Level Role Rewards", value=roles_text, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Channel Boosts", style=discord.ButtonStyle.primary)
    async def channel_boosts(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show channel XP boosts"""
        guild_id = str(interaction.guild.id)
        
        # Query database directly instead of using the in-memory dictionary
        async with self.bot.db.acquire() as conn:
            query = "SELECT channel_id, multiplier FROM channel_boosts WHERE guild_id = $1"
            rows = await conn.fetch(query, guild_id)
            
            if not rows:
                await interaction.response.send_message(
                    "No channel XP boosts are currently set for this server.",
                    ephemeral=True
                )
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
                
                channel = interaction.guild.get_channel(int(channel_id))
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
                await interaction.response.send_message(
                    "No valid channel XP boosts found for this server.",
                    ephemeral=True
                )
                return
                
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Refresh Cache", style=discord.ButtonStyle.danger)
    async def refresh_cache(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh the server's cache"""
        guild_id = str(interaction.guild.id)
        invalidate_guild_cache(guild_id)
        await interaction.response.send_message("✅ Server configuration cache has been refreshed.", ephemeral=True)


class ConfigCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    # Setup slash commands when the cog is loaded
    async def cog_load(self):
        try:
            await self.bot.tree.sync()
            logging.info("Config slash commands registered")
        except Exception as e:
            logging.error(f"Error syncing config commands: {e}")
    
    @app_commands.command(name="config", description="Server configuration dashboard")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_dashboard(self, interaction: discord.Interaction):
        """Open the server configuration dashboard"""
        embed = discord.Embed(
            title="Server Configuration Dashboard",
            description="Use the buttons below to view and configure the leveling system.",
            color=discord.Color.blue()
        )
        
        view = ConfigView(self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="setxpchannel", description="Set the channel for level-up notifications")
    @app_commands.describe(channel="The channel where level-up messages will be sent")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_xp_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the channel for level-up notifications using slash command"""
        guild_id = str(interaction.guild.id)
        channel_id = str(channel.id)
        
        await set_level_up_channel(guild_id, channel_id)
        await interaction.response.send_message(
            f"✅ Level-up notifications will now be sent to {channel.mention}",
            ephemeral=True
        )
    
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
    
    @app_commands.command(name="removeboost", description="Remove an XP boost from a channel")
    @app_commands.describe(channel="The channel to remove the XP boost from")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_boost(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel):
        """Remove an XP boost from a specific channel"""
        guild_id = str(interaction.guild.id)
        channel_id = str(channel.id)
        
        # Check if the channel has a boost
        async with self.bot.db.acquire() as conn:
            query = "SELECT multiplier FROM channel_boosts WHERE guild_id = $1 AND channel_id = $2"
            result = await conn.fetchrow(query, guild_id, channel_id)
        
        if not result:
            await interaction.response.send_message(
                "⚠️ That channel doesn't have an XP boost set.",
                ephemeral=True
            )
            return
        
        # Remove the boost
        await remove_channel_boost_db(guild_id, channel_id)
        await interaction.response.send_message(
            f"✅ Removed XP boost from {channel.name}",
            ephemeral=True
        )
        
    @app_commands.command(name="levelrole", description="Set a role reward for reaching a level")
    @app_commands.describe(
        level="The level at which to award the role",
        role="The role to award",
        action="Whether to set or remove the role reward"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def level_role(
        self, 
        interaction: discord.Interaction, 
        level: int,
        role: Optional[discord.Role] = None,
        action: Literal["set", "remove"] = "set"
    ):
        """Set or remove a role reward for a specific level"""
        guild_id = str(interaction.guild.id)
        
        # Validate level
        if level < 1:
            await interaction.response.send_message(
                "⚠️ Level must be at least 1",
                ephemeral=True
            )
            return
        
        # Handle remove action
        if action == "remove":
            success = await delete_level_role(guild_id, level)
            
            if success:
                await interaction.response.send_message(
                    f"✅ Removed role reward for level {level}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ No role reward found for level {level}",
                    ephemeral=True
                )
            return
        
        # Handle set action
        if not role:
            await interaction.response.send_message(
                "⚠️ You must specify a role to set as a reward",
                ephemeral=True
            )
            return
        
        # Check bot permissions
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "❌ I don't have permission to manage roles",
                ephemeral=True
            )
            return
            
        # Check role hierarchy
        if role.position >= interaction.guild.me.top_role.position:
            await interaction.response.send_message(
                "❌ That role is higher than my highest role, I can't assign it",
                ephemeral=True
            )
            return
        
        # Set the role reward
        success = await create_level_role(guild_id, level, str(role.id))
        
        if success:
            await interaction.response.send_message(
                f"✅ Role {role.mention} will be awarded at level {level}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ An error occurred while setting the level role",
                ephemeral=True
            )


# Setup function for the cog
async def setup(bot):
    await bot.add_cog(ConfigCommands(bot))