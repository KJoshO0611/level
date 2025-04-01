"""
Cog for managing Discord Scheduled Event integration settings and viewing stats.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Literal, Optional

from database.event_db import get_guild_event_settings, update_guild_event_settings, DEFAULT_EVENT_SETTINGS, get_guild_event_stats, get_user_event_attendance_count

class EventCommands(commands.Cog):
    """Commands related to Discord Scheduled Event integration"""
    def __init__(self, bot):
        self.bot = bot
        logging.info("EventCommands Cog initialized")

    # Configuration Command Group
    config_group = app_commands.Group(name="event_config", description="Configure Discord event integration settings.")

    @config_group.command(name="show", description="Show current event integration settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def show_config(self, interaction: discord.Interaction):
        """Displays the current event integration settings for the guild."""
        guild_id = str(interaction.guild_id)
        settings = await get_guild_event_settings(guild_id)

        embed = discord.Embed(title="Event Integration Settings", color=discord.Color.blue())
        embed.description = f"Current settings for {interaction.guild.name}"

        embed.add_field(name="Auto XP Boosts Enabled", value=settings.get('enable_auto_boosts', DEFAULT_EVENT_SETTINGS['enable_auto_boosts']), inline=False)
        embed.add_field(name="Voice Event Boost", value=f"{settings.get('default_boost_voice', DEFAULT_EVENT_SETTINGS['default_boost_voice']):.2f}x", inline=True)
        embed.add_field(name="Stage Event Boost", value=f"{settings.get('default_boost_stage', DEFAULT_EVENT_SETTINGS['default_boost_stage']):.2f}x", inline=True)
        embed.add_field(name="External Event Boost", value=f"{settings.get('default_boost_external', DEFAULT_EVENT_SETTINGS['default_boost_external']):.2f}x", inline=True)
        embed.add_field(name="Attendance Rewards Enabled", value=settings.get('enable_attendance_rewards', DEFAULT_EVENT_SETTINGS['enable_attendance_rewards']), inline=False)
        embed.add_field(name="Attendance Bonus XP", value=settings.get('attendance_bonus_xp', DEFAULT_EVENT_SETTINGS['attendance_bonus_xp']), inline=True)
        # Add achievement display later if needed
        # embed.add_field(name="Attendance Achievement ID", value=settings.get('attendance_achievement_id', 'Not Set'), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="toggle_auto_boost", description="Enable or disable automatic XP boosts during events.")
    @app_commands.describe(enable="Set to True to enable, False to disable.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_auto_boost(self, interaction: discord.Interaction, enable: bool):
        """Sets whether XP boosts are automatically created for events."""
        guild_id = str(interaction.guild_id)
        await update_guild_event_settings(guild_id, {"enable_auto_boosts": enable})
        await interaction.response.send_message(f"Automatic event XP boosts have been **{'enabled' if enable else 'disabled'}**.", ephemeral=True)

    @config_group.command(name="set_boost_multiplier", description="Set the XP boost multiplier for a specific event type.")
    @app_commands.describe(event_type="The type of event to configure.", multiplier="The XP multiplier (e.g., 1.5 for 1.5x XP).")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_boost_multiplier(self, interaction: discord.Interaction, event_type: Literal['voice', 'stage', 'external'], multiplier: float):
        """Sets the XP boost multiplier for a given event type."""
        guild_id = str(interaction.guild_id)
        if multiplier <= 0:
            await interaction.response.send_message("Multiplier must be a positive number.", ephemeral=True)
            return

        setting_key = f"default_boost_{event_type}"
        await update_guild_event_settings(guild_id, {setting_key: multiplier})
        await interaction.response.send_message(f"XP multiplier for **{event_type.capitalize()}** events set to **{multiplier:.2f}x**.", ephemeral=True)

    @config_group.command(name="toggle_attendance_rewards", description="Enable or disable bonus XP/rewards for attending events.")
    @app_commands.describe(enable="Set to True to enable, False to disable.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_attendance_rewards(self, interaction: discord.Interaction, enable: bool):
        """Sets whether attendees receive rewards after an event."""
        guild_id = str(interaction.guild_id)
        await update_guild_event_settings(guild_id, {"enable_attendance_rewards": enable})
        await interaction.response.send_message(f"Event attendance rewards have been **{'enabled' if enable else 'disabled'}**.", ephemeral=True)

    @config_group.command(name="set_attendance_xp", description="Set the amount of bonus XP awarded for attending an event.")
    @app_commands.describe(xp="The amount of bonus XP.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_attendance_xp(self, interaction: discord.Interaction, xp: int):
        """Sets the bonus XP awarded for event attendance."""
        guild_id = str(interaction.guild_id)
        if xp < 0:
            await interaction.response.send_message("Bonus XP cannot be negative.", ephemeral=True)
            return

        await update_guild_event_settings(guild_id, {"attendance_bonus_xp": xp})
        await interaction.response.send_message(f"Event attendance bonus XP set to **{xp}**.", ephemeral=True)

    # Analytics/Stats Commands (can be expanded)
    event_stats_group = app_commands.Group(name="event_stats", description="View statistics related to Discord events.")

    @event_stats_group.command(name="guild", description="Show event participation stats for the server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def show_guild_stats(self, interaction: discord.Interaction):
        """Displays aggregate event statistics for the guild."""
        guild_id = str(interaction.guild_id)
        stats = await get_guild_event_stats(guild_id)

        embed = discord.Embed(title="Guild Event Statistics", color=discord.Color.purple())
        embed.description = f"Statistics for {interaction.guild.name}"

        embed.add_field(name="Total Events Logged", value=stats.get('total_events_logged', 0), inline=False)
        embed.add_field(name="Total Attendance Records (Joins)", value=stats.get('total_attendance_records', 0), inline=False)

        types_str = "\n".join([f"{k.capitalize()}: {v}" for k, v in stats.get('events_by_type', {}).items()]) or "No data"
        embed.add_field(name="Events by Type", value=types_str, inline=True)

        status_str = "\n".join([f"{k.capitalize()}: {v}" for k, v in stats.get('events_by_status', {}).items()]) or "No data"
        embed.add_field(name="Events by Status", value=status_str, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @event_stats_group.command(name="my_attendance", description="Show your personal event attendance count.")
    async def show_user_stats(self, interaction: discord.Interaction):
        """Displays your personal event attendance count."""
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        count = await get_user_event_attendance_count(guild_id, user_id)

        await interaction.response.send_message(f"You have attended **{count}** scheduled events in this server.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(EventCommands(bot)) 