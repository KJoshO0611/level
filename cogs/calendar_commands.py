from discord import app_commands
from discord import File
from discord.ext import commands
import discord
import calendar
from datetime import datetime
import io
import logging
from typing import Optional
from database import get_active_xp_boost_events, get_upcoming_xp_boost_events
from utils.rate_limiter import rate_limit, guild_key
from utils.calendar_generator import generate_event_calendar
from utils.minimal_calendar import generate_minimal_calendar
from utils.calendar_image import generate_calendar_image
from database.events import get_events_for_month
from utils.command_utils import auto_delete_command

class CalendarCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="eventcalendar", aliases=["events", "calendar"])
    @rate_limit(calls=2, period=60, key_func=guild_key)  # 2 calls per minute per guild
    @auto_delete_command()
    async def event_calendar(self, ctx, month: Optional[int] = None, year: Optional[int] = None):
        """
        Display a calendar showing all XP boost events
        
        Usage:
          !!eventcalendar            - Shows current month
          !!eventcalendar 12         - Shows December of current year
          !!eventcalendar 3 2024     - Shows March 2024
        """
        guild_id = str(ctx.guild.id)
        
        # Validate month/year if provided
        now = datetime.now()
        
        if month is None:
            month = now.month
        elif month < 1 or month > 12:
            await ctx.send("⚠️ Month must be between 1 and 12!")
            return
            
        if year is None:
            year = now.year
        elif year < now.year - 1 or year > now.year + 2:
            await ctx.send("⚠️ Year must be between last year and 2 years from now!")
            return
        
        # Send initial response
        month_name = calendar.month_name[month]
        loading_msg = await ctx.send(f"🔄 Generating event calendar for {month_name} {year}...")
        
        try:
            # Generate the calendar image
            image_bytes = await generate_event_calendar(
                guild_id=guild_id,
                guild_name=ctx.guild.name,
                year=year,
                month=month,
                bot=self.bot
            )
            
            # Create Discord file object
            file = File(fp=image_bytes, filename=f"calendar_{month}_{year}.png")
            
            # Create embed with navigation instructions
            embed = discord.Embed(
                title=f"XP Boost Event Calendar - {month_name} {year}",
                description="Calendar showing all active and upcoming XP boost events.",
                color=discord.Color.blue()
            )
            
            # Add navigation instructions
            embed.add_field(
                name="Navigation",
                value=(
                    "**View another month:**\n"
                    f"`!!eventcalendar {month-1 if month > 1 else 12} {year if month > 1 else year-1}` - Previous Month\n"
                    f"`!!eventcalendar {month+1 if month < 12 else 1} {year if month < 12 else year+1}` - Next Month"
                ),
                inline=False
            )
            
            # Add event management reminder for admins
            if ctx.author.guild_permissions.administrator:
                embed.add_field(
                    name="Admin Controls",
                    value=(
                        "Create events with `/createevent` or `/scheduleevent`\n"
                        "View active events with `/activeevents`\n"
                        "Cancel events with `/cancelevent`"
                    ),
                    inline=False
                )
            
            # Set the image
            embed.set_image(url=f"attachment://calendar_{month}_{year}.png")
            
            # Send the calendar with embed
            await ctx.send(file=file, embed=embed)
            
            # Delete the loading message
            await loading_msg.delete()
            
        except Exception as e:
            logging.error(f"Error in event_calendar command: {e}", exc_info=True)
            await loading_msg.edit(content=f"❌ Error generating calendar: {str(e)}")
    
    @app_commands.command(name="calendar", description="Display a calendar of XP boost events")
    @app_commands.describe(
        month="Month to display (1-12, defaults to current month)",
        year="Year to display (defaults to current year)"
    )
    @auto_delete_command()
    async def slash_calendar(self, interaction: discord.Interaction, month: Optional[int] = None, year: Optional[int] = None):
        """Slash command version of the event calendar"""
        guild_id = str(interaction.guild.id)
        
        # Validate month/year if provided
        now = datetime.now()
        
        if month is None:
            month = now.month
        elif month < 1 or month > 12:
            await interaction.response.send_message("⚠️ Month must be between 1 and 12!", ephemeral=True)
            return
            
        if year is None:
            year = now.year
        elif year < now.year - 1 or year > now.year + 2:
            await interaction.response.send_message("⚠️ Year must be between last year and 2 years from now!", ephemeral=True)
            return
        
        # Send initial response
        month_name = calendar.month_name[month]
        await interaction.response.defer(thinking=True)
        
        try:
            # Generate the calendar image
            image_bytes = await generate_event_calendar(
                guild_id=guild_id,
                guild_name=interaction.guild.name,
                year=year,
                month=month,
                bot=self.bot
            )
            
            # Create Discord file object
            file = File(fp=image_bytes, filename=f"calendar_{month}_{year}.png")
            
            # Create embed with navigation instructions
            embed = discord.Embed(
                title=f"XP Boost Event Calendar - {month_name} {year}",
                description="Calendar showing all active and upcoming XP boost events.",
                color=discord.Color.blue()
            )
            
            # Add navigation instructions
            prev_month = month - 1 if month > 1 else 12
            prev_year = year if month > 1 else year - 1
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            
            embed.add_field(
                name="Navigation",
                value=(
                    "**View another month:**\n"
                    f"Previous: `/calendar month:{prev_month} year:{prev_year}`\n"
                    f"Next: `/calendar month:{next_month} year:{next_year}`"
                ),
                inline=False
            )
            
            # Add event management reminder for admins
            if interaction.user.guild_permissions.administrator:
                embed.add_field(
                    name="Admin Controls",
                    value=(
                        "Create events with `/createevent` or `/scheduleevent`\n"
                        "View active events with `/activeevents`\n"
                        "Cancel events with `/cancelevent`"
                    ),
                    inline=False
                )
            
            # Set the image
            embed.set_image(url=f"attachment://calendar_{month}_{year}.png")
            
            # Send the calendar with embed
            await interaction.followup.send(file=file, embed=embed)
            
        except Exception as e:
            logging.error(f"Error in slash_calendar command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error generating calendar: {str(e)}")

def setup(bot):
    bot.add_cog(CalendarCommands(bot))