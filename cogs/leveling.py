import discord
from discord.ext import commands
from modules.levels import xp_to_next_level
from modules.database import get_leaderboard, get_user_levels
from utils.image_generator import generate_level_card, generate_leaderboard_image
import asyncpg  # Import asyncpg
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
            row = await get_user_levels(self.bot, guild_id, user_id)
            logging.info(row)

            if row is None:
                embed = discord.Embed(
                    title="Level Info",
                    description=f"{member.display_name} hasn't earned any XP yet!",
                    color=discord.Color.red(),
                )
                embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                await ctx.send(embed=embed)
            else:
                xp, level_value = row

                next_level_xp = xp_to_next_level(level_value)
                image = await generate_level_card(member, level_value, xp, next_level_xp)
                file = discord.File(image, filename="level_card.png")
                await ctx.send(file=file)

        except asyncpg.PostgresError as e:
            logging.info(f"PostgreSQL error in level command: {e}")
            await ctx.send("An error occurred while fetching level data.")

    @commands.command(name="leaderboard", aliases=["lb"])
    async def leaderboard(self, ctx):
        """Display the top 10 users in this server based on their level and XP."""
        await ctx.message.delete()

        guild_id = str(ctx.guild.id)

        try:
            rows = await get_leaderboard(self.bot,guild_id)

            if not rows:
                await ctx.send("No leaderboard data available yet!")
                return

            embed = discord.Embed(title=f"{ctx.guild.name}'s Leaderboard", color=discord.Color.blurple())
            embed.description = "Here's the Avengers!"

            leaderboard_image = await generate_leaderboard_image(ctx.guild, rows)
            file = discord.File(leaderboard_image, filename="leaderboard.png")
            embed.set_image(url="attachment://leaderboard.png")

            await ctx.send(embed=embed, file=file)

        except asyncpg.PostgresError as e:
            print(f"PostgreSQL error in leaderboard command: {e}")
            await ctx.send("An error occurred while fetching leaderboard data.")
