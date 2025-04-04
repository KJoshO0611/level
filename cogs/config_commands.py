import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal
import logging
import time
from datetime import datetime
from database import (
    set_level_up_channel, 
    get_level_up_channel, 
    remove_channel_boost_db,
    get_level_roles,
    create_level_role,
    delete_level_role,
    invalidate_guild_cache,
    get_server_xp_settings,
    update_server_xp_settings,
    reset_server_xp_settings,
    set_achievement_channel,
    set_quest_channel,
    get_quest_cooldowns,
    update_quest_cooldown,
    update_quest_cooldowns,
    set_quest_reset_time,
    set_quest_reset_day
)
from config import load_config, XP_SETTINGS, QUEST_SETTINGS
from utils.command_utils import auto_delete_command

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
        guild_id = str(interaction.guild.id)
        settings = await get_server_xp_settings(guild_id)
        
        embed = discord.Embed(
            title="XP Settings",
            description="Current XP configuration for this server",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Min XP per Message", value=f"{settings['min_xp']} XP", inline=True)
        embed.add_field(name="Max XP per Message", value=f"{settings['max_xp']} XP", inline=True)
        embed.add_field(name="XP Cooldown", value=f"{settings['cooldown']} seconds", inline=True)
        
        # Get the global settings for comparison
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
        
        # Get level-up channel info
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

    # New XP settings slash commands
    @app_commands.command(name="xpsettings", description="View current XP settings for the server")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_settings(self, interaction: discord.Interaction):
        """View current XP settings for the server"""
        guild_id = str(interaction.guild.id)
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
                "Use these slash commands to configure XP settings:\n"
                "`/setminxp` - Set minimum XP\n"
                "`/setmaxxp` - Set maximum XP\n"
                "`/setcooldown` - Set XP cooldown\n"
                "`/resetxpsettings` - Reset to defaults"
            ),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setminxp", description="Set the minimum XP awarded per message")
    @app_commands.describe(value="The minimum XP value (1-100)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_min_xp(self, interaction: discord.Interaction, value: int):
        """Set the minimum XP awarded per message"""
        if value < 1 or value > 100:
            return await interaction.response.send_message("⚠️ Min XP must be between 1 and 100", ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        
        # First get current settings to check max XP
        settings = await get_server_xp_settings(guild_id)
        
        if value > settings["max_xp"]:
            return await interaction.response.send_message(
                f"⚠️ Min XP cannot be greater than max XP ({settings['max_xp']})", ephemeral=True
            )
        
        # Update setting
        success = await update_server_xp_settings(guild_id, {"min_xp": value})
        
        if success:
            await interaction.response.send_message(f"✅ Minimum XP set to {value}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to update XP settings", ephemeral=True)

    @app_commands.command(name="setmaxxp", description="Set the maximum XP awarded per message")
    @app_commands.describe(value="The maximum XP value (1-500)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_max_xp(self, interaction: discord.Interaction, value: int):
        """Set the maximum XP awarded per message"""
        if value < 1 or value > 500:
            return await interaction.response.send_message("⚠️ Max XP must be between 1 and 500", ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        
        # First get current settings to check min XP
        settings = await get_server_xp_settings(guild_id)
        
        if value < settings["min_xp"]:
            return await interaction.response.send_message(
                f"⚠️ Max XP cannot be less than min XP ({settings['min_xp']})", ephemeral=True
            )
        
        # Update setting
        success = await update_server_xp_settings(guild_id, {"max_xp": value})
        
        if success:
            await interaction.response.send_message(f"✅ Maximum XP set to {value}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to update XP settings", ephemeral=True)

    @app_commands.command(name="setcooldown", description="Set the cooldown between XP awards (in seconds)")
    @app_commands.describe(seconds="Cooldown in seconds (5-600)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_cooldown(self, interaction: discord.Interaction, seconds: int):
        """Set the cooldown between XP awards (in seconds)"""
        if seconds < 5 or seconds > 600:
            return await interaction.response.send_message("⚠️ Cooldown must be between 5 and 600 seconds", ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        
        # Update setting
        success = await update_server_xp_settings(guild_id, {"cooldown": seconds})
        
        if success:
            await interaction.response.send_message(f"✅ XP cooldown set to {seconds} seconds", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to update XP settings", ephemeral=True)

    @app_commands.command(name="resetxpsettings", description="Reset XP settings to defaults")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_xp_settings(self, interaction: discord.Interaction):
        """Reset XP settings to defaults"""
        guild_id = str(interaction.guild.id)
        
        success = await reset_server_xp_settings(guild_id)
        
        if success:
            embed = discord.Embed(
                title="XP Settings Reset",
                description="Server XP settings have been reset to defaults",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Min XP per Message", value=f"{XP_SETTINGS['MIN']} XP", inline=True)
            embed.add_field(name="Max XP per Message", value=f"{XP_SETTINGS['MAX']} XP", inline=True)
            embed.add_field(name="XP Cooldown", value=f"{XP_SETTINGS['COOLDOWN']} seconds", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to reset XP settings", ephemeral=True)
    
    @app_commands.command(name="setachievementchannel", description="Set the channel for achievement notifications")
    @app_commands.describe(channel="The channel where achievement notifications will be sent")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_achievement_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the channel for achievement notifications using slash command"""
        guild_id = str(interaction.guild.id)
        channel_id = str(channel.id)
        
        await set_achievement_channel(guild_id, channel_id)
        await interaction.response.send_message(
            f"✅ Achievement notifications will now be sent to {channel.mention}",
            ephemeral=True
        )
    
    @app_commands.command(name="setquestchannel", description="Set the channel for quest notifications")
    @app_commands.describe(channel="The channel where quest notifications will be sent")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_quest_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the channel for quest notifications using slash command"""
        guild_id = str(interaction.guild.id)
        channel_id = str(channel.id)
        
        await set_quest_channel(guild_id, channel_id)
        await interaction.response.send_message(
            f"✅ Quest notifications will now be sent to {channel.mention}",
            ephemeral=True
        )

    @app_commands.command(name="questcooldowns", description="View and configure quest cooldown settings")
    @app_commands.checks.has_permissions(administrator=True)
    async def quest_cooldowns(self, interaction: discord.Interaction):
        """View current quest cooldown settings"""
        guild_id = str(interaction.guild.id)
        
        # Get current quest cooldown settings
        cooldowns = await get_quest_cooldowns(guild_id)
        
        embed = discord.Embed(
            title="Quest Cooldown Settings",
            description="Current cooldown configuration for quests in this server",
            color=discord.Color.blue()
        )
        
        # Format cooldowns nicely
        cooldown_text = (
            f"• Message quests: {cooldowns.get('total_messages', 0)} seconds\n"
            f"• Reaction quests: {cooldowns.get('total_reactions', 0)} seconds\n"
            f"• Command quests: {cooldowns.get('commands_used', 0)} seconds\n"
            f"• Voice quests: {cooldowns.get('voice_time_seconds', 0)} seconds"
        )
        
        embed.add_field(
            name="Current Cooldowns",
            value=cooldown_text,
            inline=False
        )
        
        # Show the default settings for comparison
        default_cooldowns = QUEST_SETTINGS["COOLDOWNS"]
        
        default_text = (
            f"• Message quests: {default_cooldowns.get('total_messages', 0)} seconds\n"
            f"• Reaction quests: {default_cooldowns.get('total_reactions', 0)} seconds\n"
            f"• Command quests: {default_cooldowns.get('commands_used', 0)} seconds\n"
            f"• Voice quests: {default_cooldowns.get('voice_time_seconds', 0)} seconds"
        )
        
        embed.add_field(
            name="Default Cooldowns",
            value=default_text,
            inline=False
        )
        
        embed.add_field(
            name="Commands",
            value=(
                "Use these slash commands to configure cooldowns:\n"
                "`/setquestcooldown` - Set cooldown for a specific quest type\n"
                "`/resetquestcooldowns` - Reset to default cooldowns"
            ),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="setquestcooldown", description="Set the cooldown for a specific quest type")
    @app_commands.describe(
        quest_type="The type of quest to configure",
        seconds="Cooldown time in seconds (0-300)"
    )
    @app_commands.choices(
        quest_type=[
            app_commands.Choice(name="Message quests", value="total_messages"),
            app_commands.Choice(name="Reaction quests", value="total_reactions"),
            app_commands.Choice(name="Command quests", value="commands_used"),
            app_commands.Choice(name="Voice quests", value="voice_time_seconds")
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_quest_cooldown(self, interaction: discord.Interaction, quest_type: str, seconds: int):
        """Set the cooldown for a specific quest type"""
        if seconds < 0 or seconds > 300:
            return await interaction.response.send_message("⚠️ Cooldown must be between 0 and 300 seconds", ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        
        # Update the cooldown setting
        success = await update_quest_cooldown(guild_id, quest_type, seconds)
        
        if success:
            # Get display name for the quest type
            quest_type_names = {
                "total_messages": "Message quests",
                "total_reactions": "Reaction quests",
                "commands_used": "Command quests",
                "voice_time_seconds": "Voice quests"
            }
            display_name = quest_type_names.get(quest_type, quest_type)
            
            await interaction.response.send_message(
                f"✅ Cooldown for {display_name} set to {seconds} seconds", 
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Failed to update quest cooldown settings", ephemeral=True)
    
    @app_commands.command(name="resetquestcooldowns", description="Reset quest cooldowns to default values")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_quest_cooldowns(self, interaction: discord.Interaction):
        """Reset quest cooldowns to default values"""
        guild_id = str(interaction.guild.id)
        
        # Get default cooldown settings
        default_cooldowns = QUEST_SETTINGS["COOLDOWNS"]
        
        # Update with defaults
        success = await update_quest_cooldowns(guild_id, default_cooldowns)
        
        if success:
            await interaction.response.send_message("✅ Quest cooldowns reset to default values", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to reset quest cooldown settings", ephemeral=True)
    
    @commands.command(name="setquestresettime", aliases=["sqrt"])
    @commands.has_permissions(administrator=True)
    @auto_delete_command()
    async def set_quest_reset_time_cmd(self, ctx, hour: int):
        """
        Set the hour of day (in UTC) when daily quests reset
        
        Usage: !setquestresettime 0
        
        The hour must be 0-23 in UTC time.
        0 = midnight UTC, 12 = noon UTC
        """
        if not 0 <= hour <= 23:
            await ctx.send("❌ Error: Hour must be between 0-23 (UTC time)")
            return
            
        guild_id = str(ctx.guild.id)
        
        # Update the reset hour
        success = await set_quest_reset_time(guild_id, hour)
        
        if success:
            await ctx.send(f"✅ Daily quest reset time set to {hour}:00 UTC")
        else:
            await ctx.send("❌ Failed to update quest reset time")
    
    @commands.command(name="setquestresetday", aliases=["sqrd"])
    @commands.has_permissions(administrator=True)
    @auto_delete_command()
    async def set_quest_reset_day_cmd(self, ctx, day: int):
        """
        Set the day of week when weekly quests reset
        
        Usage: !setquestresetday 0
        
        The day must be 0-6:
        0 = Monday, 1 = Tuesday, 2 = Wednesday, 3 = Thursday,
        4 = Friday, 5 = Saturday, 6 = Sunday
        """
        if not 0 <= day <= 6:
            await ctx.send("❌ Error: Day must be between 0-6 (0=Monday, 6=Sunday)")
            return
            
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_name = days[day]
        
        guild_id = str(ctx.guild.id)
        
        # Update the reset day
        success = await set_quest_reset_day(guild_id, day)
        
        if success:
            await ctx.send(f"✅ Weekly quest reset day set to {day_name}")
        else:
            await ctx.send("❌ Failed to update quest reset day")
    
    @app_commands.command(name="questresettimes", description="Set when quests reset")
    @app_commands.describe(
        reset_hour="Hour of day in UTC when daily quests reset (0-23)",
        reset_day="Day of week when weekly quests reset (0=Monday, 6=Sunday)"
    )
    @app_commands.choices(reset_day=[
        app_commands.Choice(name="Monday", value=0),
        app_commands.Choice(name="Tuesday", value=1),
        app_commands.Choice(name="Wednesday", value=2),
        app_commands.Choice(name="Thursday", value=3),
        app_commands.Choice(name="Friday", value=4),
        app_commands.Choice(name="Saturday", value=5),
        app_commands.Choice(name="Sunday", value=6)
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def set_quest_reset_times(self, interaction: discord.Interaction, reset_hour: int, reset_day: int):
        """Set the times when quests reset for this server"""
        guild_id = str(interaction.guild.id)
        
        # Validate hour
        if not 0 <= reset_hour <= 23:
            await interaction.response.send_message(
                "❌ Reset hour must be between 0-23 (UTC time)", 
                ephemeral=True
            )
            return
        
        # Update settings
        success_hour = await set_quest_reset_time(guild_id, reset_hour)
        success_day = await set_quest_reset_day(guild_id, reset_day)
        
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_name = days[reset_day]
        
        if success_hour and success_day:
            embed = discord.Embed(
                title="Quest Reset Times Updated",
                description="Quest reset settings have been updated for this server.",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Daily Quest Reset",
                value=f"**{reset_hour}:00 UTC**",
                inline=True
            )
            
            embed.add_field(
                name="Weekly Quest Reset",
                value=f"**{day_name}** at **{reset_hour}:00 UTC**",
                inline=True
            )
            
            # Add explanation about when it takes effect
            embed.add_field(
                name="When will this take effect?",
                value="The new reset times will be used the next time the hourly reset check runs.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Failed to update quest reset settings. Please try again later.",
                ephemeral=True
            )

# Setup function for the cog
async def setup(bot):
    await bot.add_cog(ConfigCommands(bot))