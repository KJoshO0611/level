import discord
from discord.ext import commands
from modules.levels import xp_to_next_level
from modules.databasev2 import get_leaderboard, get_user_levels, get_user_rank
# Import the new Cairo-based image generator instead of the old one
from utils.cairo_image_generator import generate_level_card, generate_leaderboard_image
from utils.simple_image_handler import generate_image_nonblocking, update_with_image
import logging

class LevelingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="level", aliases=["lvl"])
    async def level(self, ctx, member: discord.Member = None):
        """Check the level and XP of a member with a visual card."""
        await ctx.message.delete()

        member = member or ctx.author
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        try:
            # Get user levels
            xp, level_value = await get_user_levels(guild_id, user_id)
            
            if xp == 0 and level_value == 1:
                embed = discord.Embed(
                    title="Level Info",
                    description=f"{member.display_name} hasn't earned any XP yet!",
                    color=discord.Color.red(),
                )
                embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                await ctx.send(embed=embed)
            else:
                next_level_xp = xp_to_next_level(level_value)
                
                # Create a loading message
                message, _ = await generate_image_nonblocking(ctx, "level card")
                
                # Generate the image (this won't block the bot)
                # This now uses the Cairo-based implementation but maintains the same interface
                image_bytes = await generate_level_card(member, level_value, xp, next_level_xp)
                
                # Update the message with the image
                await update_with_image(message, image_bytes, "level_card")

        except Exception as e:
            logging.error(f"Error in level command: {e}")
            await ctx.send("An error occurred while fetching level data.")

    @commands.command(name="leaderboard", aliases=["lb"])
    async def leaderboard(self, ctx, page: int = 1):
        """Display the top 10 users in this server based on their level and XP."""
        await ctx.message.delete()

        guild_id = str(ctx.guild.id)
        limit = 10
        offset = (page - 1) * limit

        try:
            rows = await get_leaderboard(guild_id, limit, offset)

            if not rows:
                if page > 1:
                    await ctx.send(f"No data available for page {page}. Try a lower page number.")
                else:
                    await ctx.send("No leaderboard data available yet!")
                return

            # Create a loading message
            message, _ = await generate_image_nonblocking(ctx, "leaderboard")
            
            # Generate the leaderboard image (this won't block)
            # This now uses the Cairo-based implementation but maintains the same interface
            image_bytes = await generate_leaderboard_image(ctx.guild, rows, start_rank=(offset + 1))
            
            # Update the message with the image
            await update_with_image(message, image_bytes, "leaderboard")
                
        except Exception as e:
            logging.error(f"Error in leaderboard command: {e}")
            await ctx.send("An error occurred while fetching leaderboard data.")
            
    @commands.command(name="rank", aliases=["r"])
    async def rank(self, ctx, member: discord.Member = None):
        """Check your rank in the server leaderboard."""
        member = member or ctx.author
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        
        try:
            # Get user's rank
            rank = await get_user_rank(guild_id, user_id)
            
            if rank is None:
                await ctx.send(f"{member.display_name} hasn't earned any XP yet!")
                return
                
            # Get level info as well
            xp, level = await get_user_levels(guild_id, user_id)
            
            if xp != 0 or level != 1:  # Check if they have earned XP
                embed = discord.Embed(
                    title="Rank Info",
                    description=f"{member.display_name} is rank **#{rank}** on the server leaderboard!",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Level", value=str(level), inline=True)
                embed.add_field(name="XP", value=str(xp), inline=True)
                embed.add_field(name="Next Level", value=f"{xp}/{xp_to_next_level(level)} XP", inline=True)
                embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"{member.display_name} is rank **#{rank}** on the server leaderboard!")
                
        except Exception as e:
            logging.error(f"Error in rank command: {e}")
            await ctx.send("An error occurred while fetching rank data.")