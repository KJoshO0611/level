import discord
from discord import app_commands
from discord.ext import commands
import os
import aiohttp
import logging
import time
from typing import Optional, List, Literal
from database import (
    create_achievement_db,
    get_user_achievements_db,
    get_achievement_leaderboard_db,
    get_achievement_stats_db,
    get_user_selected_title_db,
    set_user_selected_title_db
)
from config import load_config

# Load the external volume path from config
config = load_config()
EXTERNAL_VOLUME_PATH = config.get("EXTERNAL_VOLUME_PATH", "/external_volume")
BADGES_DIR = os.path.join(EXTERNAL_VOLUME_PATH, "badges")

# Ensure badges directory exists
os.makedirs(BADGES_DIR, exist_ok=True)

# Valid achievement requirement types
REQUIREMENT_TYPES = [
    "total_messages",
    "total_reactions",
    "voice_time_seconds",
    "commands_used"
]

class AchievementCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.group(name="achievement", aliases=["achieve", "ach"])
    @commands.has_permissions(administrator=True)
    async def achievement(self, ctx):
        """Achievement management commands (Admin only)"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Achievement Commands",
                description="Available subcommands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="!!achievement create <name> <requirement_type> <value> <description>",
                value="Create a new achievement",
                inline=False
            )
            embed.add_field(
                name="!!achievement list",
                value="List all achievements",
                inline=False
            )
            embed.add_field(
                name="!!achievement edit <id> <field> <value>",
                value="Edit an achievement (field: name, description, type, value)",
                inline=False
            )
            embed.add_field(
                name="!!achievement badge <id>",
                value="Upload a badge for an achievement (attach image)",
                inline=False
            )
            embed.add_field(
                name="!!achievement stats",
                value="View achievement statistics",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @achievement.command(name="create")
    async def create_achievement(self, ctx, name: str, requirement_type: str, 
                                requirement_value: int, *, description: str):
        """
        Create a new achievement for this guild
        
        Example: !!achievement create "Message Master" total_messages 1000 Sent 1000 messages
        
        Valid requirement types:
        - total_messages: Total messages sent
        - total_reactions: Total reactions added
        - voice_time_seconds: Time spent in voice channels (in seconds)
        - commands_used: Number of commands used
        """
        # Validate requirement type
        if requirement_type not in REQUIREMENT_TYPES:
            valid_types = ', '.join(REQUIREMENT_TYPES)
            await ctx.send(f"❌ Invalid requirement type. Valid types are: {valid_types}")
            return
        
        # Validate requirement value
        if requirement_value <= 0:
            await ctx.send("❌ Requirement value must be greater than 0")
            return
            
        # Create the achievement for this guild
        guild_id = str(ctx.guild.id)
        achievement_id = await create_achievement_db(guild_id, name, description, requirement_type, requirement_value)
        
        if achievement_id > 0:
            embed = discord.Embed(
                title="✅ Achievement Created",
                description=f"**{name}** has been created with ID {achievement_id}",
                color=discord.Color.green()
            )
            embed.add_field(name="Description", value=description, inline=False)
            embed.add_field(name="Requirement", value=f"{requirement_type}: {requirement_value}", inline=True)
            embed.add_field(name="Badge", value="Not set (use the badge command to add)", inline=True)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to create achievement. Please try again.")
    
    @achievement.command(name="list")
    async def list_achievements(self, ctx):
        """List all achievements for this guild"""
        guild_id = str(ctx.guild.id)
        
        async with self.bot.db.acquire() as conn:
            query = """
            SELECT id, name, description, requirement_type, requirement_value, icon_path
            FROM achievements
            WHERE guild_id = $1
            ORDER BY requirement_type, requirement_value
            """
            rows = await conn.fetch(query, guild_id)
            
            if not rows:
                await ctx.send("No achievements have been created for this server yet.")
                return
            
            # Group achievements by type
            achievements_by_type = {}
            for row in rows:
                req_type = row['requirement_type']
                if req_type not in achievements_by_type:
                    achievements_by_type[req_type] = []
                achievements_by_type[req_type].append(row)
            
            # Create embed for each type
            for req_type, achievements in achievements_by_type.items():
                embed = discord.Embed(
                    title=f"Achievements: {req_type}",
                    color=discord.Color.blue()
                )
                
                for ach in achievements:
                    has_badge = "✅" if ach['icon_path'] else "❌"
                    embed.add_field(
                        name=f"#{ach['id']}: {ach['name']} ({ach['requirement_value']})",
                        value=f"{ach['description']}\nBadge: {has_badge}",
                        inline=False
                    )
                
                await ctx.send(embed=embed)
    
    @achievement.command(name="edit")
    async def edit_achievement(self, ctx, achievement_id: int, field: str, *, value: str):
        """
        Edit an achievement in this guild
        
        Fields:
        - name: The achievement name
        - description: The achievement description
        - type: The requirement type
        - value: The requirement value
        
        Example: !!achievement edit 1 name "New Achievement Name"
        """
        # Validate field
        valid_fields = ["name", "description", "type", "value"]
        if field.lower() not in valid_fields:
            await ctx.send(f"❌ Invalid field. Valid fields are: {', '.join(valid_fields)}")
            return
        
        # Get the current achievement data
        guild_id = str(ctx.guild.id)
        async with self.bot.db.acquire() as conn:
            query = """
            SELECT name, description, requirement_type, requirement_value, icon_path
            FROM achievements
            WHERE id = $1 AND guild_id = $2
            """
            achievement = await conn.fetchrow(query, achievement_id, guild_id)
            
            if not achievement:
                await ctx.send(f"❌ Achievement with ID {achievement_id} not found in this server.")
                return
            
            # Update the field
            if field.lower() == "name":
                update_field = "name"
                update_value = value
            elif field.lower() == "description":
                update_field = "description"
                update_value = value
            elif field.lower() == "type":
                if value not in REQUIREMENT_TYPES:
                    valid_types = ', '.join(REQUIREMENT_TYPES)
                    await ctx.send(f"❌ Invalid requirement type. Valid types are: {valid_types}")
                    return
                update_field = "requirement_type"
                update_value = value
            elif field.lower() == "value":
                try:
                    update_value = int(value)
                    if update_value <= 0:
                        await ctx.send("❌ Requirement value must be greater than 0")
                        return
                except ValueError:
                    await ctx.send("❌ Requirement value must be a positive number")
                    return
                update_field = "requirement_value"
            
            # Perform the update
            update_query = f"""
            UPDATE achievements
            SET {update_field} = $1
            WHERE id = $2
            RETURNING id
            """
            result = await conn.fetchval(update_query, update_value, achievement_id)
            
            if result:
                await ctx.send(f"✅ Achievement #{achievement_id} updated successfully.")
            else:
                await ctx.send("❌ Failed to update achievement. Please try again.")
    
    @achievement.command(name="badge")
    async def set_achievement_badge(self, ctx, achievement_id: int):
        """
        Set a badge for an achievement in this guild. Attach an image to your message.
        
        Example: !!achievement badge 1 (with an attached image)
        """
        # Check if an image was attached
        if not ctx.message.attachments:
            await ctx.send("❌ Please attach an image for the badge.")
            return
        
        attachment = ctx.message.attachments[0]
        
        # Check if it's an image
        if not (attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))):
            await ctx.send("❌ Please attach an image file (PNG, JPG, JPEG, GIF).")
            return
        
        # Verify the achievement exists in this guild
        guild_id = str(ctx.guild.id)
        async with self.bot.db.acquire() as conn:
            query = "SELECT 1 FROM achievements WHERE id = $1 AND guild_id = $2"
            exists = await conn.fetchval(query, achievement_id, guild_id)
            
            if not exists:
                await ctx.send(f"❌ Achievement with ID {achievement_id} not found in this server.")
                return
            
            # Create a unique filename
            file_ext = attachment.filename.split('.')[-1].lower()
            filename = f"achievement_{achievement_id}.{file_ext}"
            file_path = os.path.join(BADGES_DIR, filename)
            
            # Download the image
            try:
                await attachment.save(file_path)
            except Exception as e:
                logging.error(f"Error saving badge image: {e}")
                await ctx.send("❌ Failed to save badge image. Please try again.")
                return
            
            # Update the achievement record
            # Store the path relative to EXTERNAL_VOLUME_PATH for portability
            relative_path = os.path.join("badges", filename)
            
            update_query = """
            UPDATE achievements
            SET icon_path = $1
            WHERE id = $2 AND guild_id = $3
            RETURNING id
            """
            result = await conn.fetchval(update_query, relative_path, achievement_id, guild_id)
            
            if result:
                embed = discord.Embed(
                    title="✅ Badge Set",
                    description=f"Badge for achievement #{achievement_id} has been set.",
                    color=discord.Color.green()
                )
                embed.set_image(url=attachment.url)
                await ctx.send(embed=embed)
            else:
                await ctx.send("❌ Failed to update achievement badge. Please try again.")
    
    @achievement.command(name="viewbadge")
    async def view_achievement_badge(self, ctx, achievement_id: int):
        """
        View the badge for an achievement in this guild.
        
        Example: !!achievement viewbadge 1
        """
        guild_id = str(ctx.guild.id)
        
        async with self.bot.db.acquire() as conn:
            query = """
            SELECT name, description, icon_path
            FROM achievements
            WHERE id = $1 AND guild_id = $2
            """
            achievement = await conn.fetchrow(query, achievement_id, guild_id)
            
            if not achievement:
                await ctx.send(f"❌ Achievement with ID {achievement_id} not found in this server.")
                return
            
            if not achievement['icon_path']:
                await ctx.send(f"❌ Achievement #{achievement_id} ({achievement['name']}) does not have a badge set.")
                return
            
            # Construct the full path to the badge
            badge_path = os.path.join(EXTERNAL_VOLUME_PATH, achievement['icon_path'])
            
            # Check if the file exists
            if not os.path.exists(badge_path):
                await ctx.send(f"❌ Badge file for achievement #{achievement_id} not found.")
                return
            
            # Create embed with achievement info and badge
            embed = discord.Embed(
                title=f"Badge for {achievement['name']}",
                description=achievement['description'],
                color=discord.Color.blue()
            )
            
            # Create a file object from the badge
            file = discord.File(badge_path, filename=f"badge_{achievement_id}.png")
            embed.set_image(url=f"attachment://badge_{achievement_id}.png")
            
            await ctx.send(embed=embed, file=file)
    
    @achievement.command(name="stats")
    async def achievement_stats(self, ctx):
        """View achievement statistics for this server"""
        guild_id = str(ctx.guild.id)
        stats = await get_achievement_stats_db(guild_id)
        
        embed = discord.Embed(
            title="Achievement Statistics",
            description=f"Total Achievements: {stats['total_achievements']}",
            color=discord.Color.blue()
        )
        
        # Categories
        categories_text = ""
        for category, count in stats['categories'].items():
            categories_text += f"{category}: {count}\n"
        
        if categories_text:
            embed.add_field(name="Categories", value=categories_text, inline=False)
        
        # Most common achievements
        if stats['most_common']:
            common_text = ""
            for ach in stats['most_common']:
                common_text += f"{ach['name']}: {ach['earner_count']} users\n"
            embed.add_field(name="Most Popular", value=common_text, inline=True)
        
        # Rarest achievements
        if stats['rarest']:
            rare_text = ""
            for ach in stats['rarest']:
                rare_text += f"{ach['name']}: {ach['earner_count']} users\n"
            embed.add_field(name="Rarest", value=rare_text, inline=True)
        
        await ctx.send(embed=embed)
    
    # Slash command versions
    @app_commands.command(name="achievements", description="View your achievement progress")
    async def slash_achievements(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """View achievement progress for yourself or another member"""
        target_member = member or interaction.user
        guild_id = str(interaction.guild.id)
        user_id = str(target_member.id)
        
        # Get user's achievements
        achievements = await get_user_achievements_db(guild_id, user_id)
        
        # Create response embeds
        embed = discord.Embed(
            title=f"{target_member.display_name}'s Achievements",
            description=f"Completed: {len(achievements['completed'])}/{achievements['total_count']}",
            color=discord.Color.blue()
        )
        
        if target_member.avatar:
            embed.set_thumbnail(url=target_member.avatar.url)
        
        # Show completed achievements
        if achievements['completed']:
            completed_text = ""
            for ach in achievements['completed'][:5]:  # Show only first 5
                completed_text += f"• {ach['name']}\n"
            
            if len(achievements['completed']) > 5:
                completed_text += f"...and {len(achievements['completed']) - 5} more"
                
            embed.add_field(name="Completed Achievements", value=completed_text, inline=False)
        
        # Show in-progress achievements
        if achievements['in_progress']:
            progress_text = ""
            for ach in achievements['in_progress'][:5]:  # Show only first 5
                progress_text += f"• {ach['name']}: {ach['progress']}/{ach['requirement_value']} ({ach['percent']}%)\n"
                
            if len(achievements['in_progress']) > 5:
                progress_text += f"...and {len(achievements['in_progress']) - 5} more"
                
            embed.add_field(name="In Progress", value=progress_text, inline=False)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="achievementcreate", description="Create a new achievement (Admin only)")
    @app_commands.describe(
        name="Achievement name",
        requirement_type="Type of requirement to track",
        requirement_value="Value required to earn the achievement",
        description="Achievement description"
    )
    @app_commands.choices(requirement_type=[
        app_commands.Choice(name="Messages Sent", value="total_messages"),
        app_commands.Choice(name="Reactions Added", value="total_reactions"),
        app_commands.Choice(name="Voice Time (seconds)", value="voice_time_seconds"),
        app_commands.Choice(name="Commands Used", value="commands_used")
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def slash_create_achievement(
        self, 
        interaction: discord.Interaction,
        name: str,
        requirement_type: str,
        requirement_value: int,
        description: str
    ):
        """Create a new achievement with a slash command"""
        # Validate requirement value
        if requirement_value <= 0:
            await interaction.response.send_message("❌ Requirement value must be greater than 0", ephemeral=True)
            return
            
        # Create the achievement for this guild
        guild_id = str(interaction.guild.id)
        achievement_id = await create_achievement_db(guild_id, name, description, requirement_type, requirement_value)
        
        if achievement_id > 0:
            embed = discord.Embed(
                title="✅ Achievement Created",
                description=f"**{name}** has been created with ID {achievement_id}",
                color=discord.Color.green()
            )
            embed.add_field(name="Description", value=description, inline=False)
            embed.add_field(name="Requirement", value=f"{requirement_type}: {requirement_value}", inline=True)
            embed.add_field(name="Badge", value="Not set (use the badge command to add)", inline=True)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Failed to create achievement. Please try again.", ephemeral=True)
    
    @app_commands.command(name="achievementleaderboard", description="Show achievement leaderboard")
    @app_commands.describe(limit="Number of users to show (default: 10)")
    async def slash_achievement_leaderboard(self, interaction: discord.Interaction, limit: int = 10):
        """View the achievement leaderboard for the server"""
        guild_id = str(interaction.guild.id)
        leaderboard = await get_achievement_leaderboard_db(guild_id, limit)
        
        if not leaderboard:
            await interaction.response.send_message("No achievements have been earned yet.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Achievement Leaderboard",
            description=f"Top {len(leaderboard)} achievers in {interaction.guild.name}",
            color=discord.Color.gold()
        )
        
        for i, entry in enumerate(leaderboard):
            user_id = entry['user_id']
            completed = entry['completed_count']
            total = entry['total_achievements']
            
            # Try to get the user
            user = interaction.guild.get_member(int(user_id))
            user_name = user.display_name if user else f"User {user_id}"
            
            # Emoji for top 3
            medal = ""
            if i == 0:
                medal = "🥇 "
            elif i == 1:
                medal = "🥈 "
            elif i == 2:
                medal = "🥉 "
            else:
                medal = f"{i+1}. "
            
            embed.add_field(
                name=f"{medal}{user_name}",
                value=f"Completed: {completed}/{total} ({int(completed/total*100)}%)",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="achievementbadge", description="View the badge for an achievement")
    @app_commands.describe(achievement_id="The ID of the achievement to view")
    async def slash_view_achievement_badge(self, interaction: discord.Interaction, achievement_id: int):
        """View the badge for an achievement using slash command"""
        guild_id = str(interaction.guild.id)
        
        async with self.bot.db.acquire() as conn:
            query = """
            SELECT name, description, icon_path
            FROM achievements
            WHERE id = $1 AND guild_id = $2
            """
            achievement = await conn.fetchrow(query, achievement_id, guild_id)
            
            if not achievement:
                await interaction.response.send_message(
                    f"❌ Achievement with ID {achievement_id} not found in this server.",
                    ephemeral=True
                )
                return
            
            if not achievement['icon_path']:
                await interaction.response.send_message(
                    f"❌ Achievement #{achievement_id} ({achievement['name']}) does not have a badge set.",
                    ephemeral=True
                )
                return
            
            # Construct the full path to the badge
            badge_path = os.path.join(EXTERNAL_VOLUME_PATH, achievement['icon_path'])
            
            # Check if the file exists
            if not os.path.exists(badge_path):
                await interaction.response.send_message(
                    f"❌ Badge file for achievement #{achievement_id} not found.",
                    ephemeral=True
                )
                return
            
            # Create embed with achievement info and badge
            embed = discord.Embed(
                title=f"Badge for {achievement['name']}",
                description=achievement['description'],
                color=discord.Color.blue()
            )
            
            # Create a file object from the badge
            file = discord.File(badge_path, filename=f"badge_{achievement_id}.png")
            embed.set_image(url=f"attachment://badge_{achievement_id}.png")
            
            await interaction.response.send_message(embed=embed, file=file, ephemeral=True)

    @app_commands.command(name="settitle", description="Set your achievement title display for level cards")
    @app_commands.describe(
        title="The achievement title to display or leave empty to clear your title"
    )
    async def slash_set_title(self, interaction: discord.Interaction, title: str = None):
        """Set your achievement title display for level cards"""
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # If title is empty, clear the user's title
        if not title:
            success = await set_user_selected_title_db(guild_id, user_id, None)
            if success:
                await interaction.followup.send("Your title has been cleared.", ephemeral=True)
            else:
                await interaction.followup.send("Failed to clear your title. Please try again later.", ephemeral=True)
            return
        
        # Get user achievements to validate the title
        achievements_data = await get_user_achievements_db(guild_id, user_id)
        completed_achievements = achievements_data.get("completed", [])
        
        # Check if user has completed achievements
        if not completed_achievements:
            await interaction.followup.send(
                "You don't have any completed achievements yet. Complete achievements to set a title!",
                ephemeral=True
            )
            return
        
        # Check if title is too long
        if len(title) > 30:
            await interaction.followup.send(
                "Your title is too long. Please choose a shorter title (max 30 characters).",
                ephemeral=True
            )
            return
            
        # Set the title
        success = await set_user_selected_title_db(guild_id, user_id, title)
        
        if success:
            title_display = f"«{title}»"
            await interaction.followup.send(
                f"Your title has been set to {title_display}. It will be displayed on your level card.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "Failed to set your title. Please try again later.",
                ephemeral=True
            )
    
    @app_commands.command(name="viewtitle", description="View your current achievement title")
    async def slash_view_title(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """View your current achievement title"""
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild.id)
        
        # If member is specified, view their title
        target_member = member or interaction.user
        user_id = str(target_member.id)
        
        title = await get_user_selected_title_db(guild_id, user_id)
        
        if title:
            title_display = f"«{title}»"
            if member:
                await interaction.followup.send(
                    f"{target_member.display_name}'s current title is set to {title_display}.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Your current title is set to {title_display}.",
                    ephemeral=True
                )
        else:
            if member:
                await interaction.followup.send(
                    f"{target_member.display_name} doesn't have a title set.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "You don't have a title set. Use `/settitle` to set one!",
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(AchievementCommands(bot))