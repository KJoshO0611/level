import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal
import logging
import time
from datetime import datetime

from database import (
    create_quest,
    get_quest,
    update_quest,
    delete_quest,
    get_guild_active_quests,
    mark_quests_inactive,
    get_user_quest_progress,
    update_user_quest_progress,
    get_user_active_quests,
    get_user_quest_stats,
    check_quest_progress,
    award_quest_rewards
)
from utils.rate_limiter import rate_limit, guild_key, user_key

class QuestCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    # ===== GROUP COMMANDS =====
    @commands.group(name="quest", aliases=["quests", "q"])
    async def quest(self, ctx):
        """Quest system commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="📜 Quest Commands",
                description="Available subcommands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="!quest list",
                value="View your active quests",
                inline=False
            )
            embed.add_field(
                name="!quest info <id>",
                value="View details about a specific quest",
                inline=False
            )
            embed.add_field(
                name="!quest stats",
                value="View your quest statistics",
                inline=False
            )
            embed.add_field(
                name="!quest daily",
                value="View your daily quests",
                inline=False
            )
            embed.add_field(
                name="!quest weekly",
                value="View your weekly quests",
                inline=False
            )
            
            # Add admin commands if user has permissions
            if ctx.author.guild_permissions.administrator:
                embed.add_field(
                    name="Admin Commands",
                    value=(
                        "!quest create - Create a new quest\n"
                        "!quest edit <id> - Edit a quest\n"
                        "!quest delete <id> - Delete a quest\n"
                        "!quest reset - Reset daily/weekly quests"
                    ),
                    inline=False
                )
                
            await ctx.send(embed=embed)
    
    # ===== USER COMMANDS =====
    @quest.command(name="list")
    @rate_limit(calls=5, period=60)  # 5 calls per minute per user
    async def list_quests(self, ctx):
        """List all your active quests"""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        quests = await get_user_active_quests(guild_id, user_id)
        
        if not quests:
            await ctx.send("You don't have any active quests. Check back later!")
            return
        
        # Group quests by type
        daily_quests = []
        weekly_quests = []
        special_quests = []
        
        for quest in quests:
            if quest['quest_type'] == 'daily':
                daily_quests.append(quest)
            elif quest['quest_type'] == 'weekly':
                weekly_quests.append(quest)
            else:
                special_quests.append(quest)
        
        embed = discord.Embed(
            title="📜 Your Active Quests",
            description="Complete quests to earn XP rewards!",
            color=discord.Color.blue()
        )
        
        # Format and add each quest type
        self._add_quest_list_to_embed(embed, "Daily Quests", daily_quests)
        self._add_quest_list_to_embed(embed, "Weekly Quests", weekly_quests)
        self._add_quest_list_to_embed(embed, "Special Quests", special_quests)
        
        await ctx.send(embed=embed)
    
    def _add_quest_list_to_embed(self, embed, title, quests):
        """Helper to add a formatted quest list to an embed"""
        if not quests:
            return
            
        quest_text = ""
        for quest in quests:
            # Format progress bar (10 segments)
            progress_pct = min(100, int((quest['progress'] / quest['requirement_value']) * 100))
            segments = 10
            filled = int((progress_pct / 100) * segments)
            
            # Create progress bar with emojis
            progress_bar = "▰" * filled + "▱" * (segments - filled)
            
            # Format expires time if available
            expires = ""
            if quest['expires_at']:
                # Calculate time remaining
                now = datetime.now()
                remaining = quest['expires_at'] - now
                if remaining.total_seconds() > 0:
                    hours = int(remaining.total_seconds() / 3600)
                    if hours > 24:
                        expires = f"⏳ {hours // 24}d {hours % 24}h remaining"
                    else:
                        expires = f"⏳ {hours}h remaining"
            
            # Status emoji
            if quest['completed']:
                status = "✅"
            else:
                status = "🔄"
            
            # Add to text
            quest_text += f"**[{quest['id']}] {quest['name']}** {status}\n"
            quest_text += f"{quest['description']}\n"
            quest_text += f"Progress: {progress_bar} {quest['progress']}/{quest['requirement_value']} "
            quest_text += f"({progress_pct}%)\n"
            if expires:
                quest_text += f"{expires}\n"
            quest_text += f"Reward: {quest['reward_xp']} XP\n\n"
        
        embed.add_field(
            name=title,
            value=quest_text,
            inline=False
        )
    
    @quest.command(name="info")
    @rate_limit(calls=10, period=60)  # 10 calls per minute per user
    async def quest_info(self, ctx, quest_id: int):
        """View detailed information about a specific quest"""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        # Get quest details
        quest = await get_quest(quest_id)
        
        if not quest or quest['guild_id'] != guild_id:
            await ctx.send("Quest not found.")
            return
        
        # Get user's progress
        progress, completed, completed_at = await get_user_quest_progress(guild_id, user_id, quest_id)
        
        # Format requirement
        req_type_names = {
            "total_messages": "Send messages",
            "total_reactions": "Add reactions",
            "voice_time_seconds": "Spend time in voice",
            "commands_used": "Use commands"
        }
        
        requirement = req_type_names.get(quest['requirement_type'], quest['requirement_type'])
        
        # Format voice time if applicable
        if quest['requirement_type'] == 'voice_time_seconds':
            minutes = quest['requirement_value'] // 60
            requirement = f"Spend {minutes} minutes in voice"
            progress_display = f"{progress // 60}/{minutes} minutes"
        else:
            progress_display = f"{progress}/{quest['requirement_value']}"
        
        # Calculate progress percentage
        progress_pct = min(100, int((progress / quest['requirement_value']) * 100))
        
        # Create embed
        embed = discord.Embed(
            title=f"📜 {quest['name']}",
            description=quest['description'],
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Type", value=quest['quest_type'].capitalize(), inline=True)
        embed.add_field(name="Difficulty", value=quest['difficulty'].capitalize(), inline=True)
        embed.add_field(name="Status", value="✅ Completed" if completed else "🔄 In Progress", inline=True)
        
        embed.add_field(name="Requirement", value=requirement, inline=True)
        embed.add_field(name="Progress", value=progress_display, inline=True)
        embed.add_field(name="Completion", value=f"{progress_pct}%", inline=True)
        
        embed.add_field(name="Reward", value=f"{quest['reward_xp']} XP", inline=True)
        
        if quest['reward_multiplier'] > 1.0:
            embed.add_field(
                name="Bonus", 
                value=f"{quest['reward_multiplier']}x XP multiplier", 
                inline=True
            )
        
        if completed and completed_at:
            embed.add_field(
                name="Completed", 
                value=completed_at.strftime("%Y-%m-%d %H:%M"), 
                inline=True
            )
        
        await ctx.send(embed=embed)
    
    @quest.command(name="stats")
    @rate_limit(calls=5, period=60)  # 5 calls per minute per user
    async def quest_stats(self, ctx):
        """View your quest statistics"""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        stats = await get_user_quest_stats(guild_id, user_id)
        
        embed = discord.Embed(
            title="📊 Quest Statistics",
            description=f"Quest progress for {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Completed Quests",
            value=str(stats['completed_count']),
            inline=True
        )
        
        embed.add_field(
            name="Active Quests",
            value=str(stats['active_count']),
            inline=True
        )
        
        embed.add_field(
            name="XP Earned",
            value=f"{stats['total_xp_earned']} XP",
            inline=True
        )
        
        embed.add_field(
            name="Daily Quests",
            value=f"{stats['daily_completed']} completed",
            inline=True
        )
        
        embed.add_field(
            name="Weekly Quests",
            value=f"{stats['weekly_completed']} completed",
            inline=True
        )
        
        embed.add_field(
            name="Special Quests",
            value=f"{stats['special_completed']} completed",
            inline=True
        )
        
        if stats['last_completed']:
            embed.add_field(
                name="Last Completion",
                value=stats['last_completed'].strftime("%Y-%m-%d %H:%M"),
                inline=False
            )
            
        if ctx.author.avatar:
            embed.set_thumbnail(url=ctx.author.avatar.url)
        
        await ctx.send(embed=embed)
    
    @quest.command(name="daily")
    @rate_limit(calls=5, period=60)  # 5 calls per minute per user
    async def daily_quests(self, ctx):
        """View your daily quests"""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        # Get all active quests for the user
        quests = await get_user_active_quests(guild_id, user_id)
        
        # Filter to only daily quests
        daily_quests = [q for q in quests if q['quest_type'] == 'daily']
        
        if not daily_quests:
            await ctx.send("You don't have any active daily quests. Check back later!")
            return
        
        embed = discord.Embed(
            title="📅 Daily Quests",
            description="Complete these quests for XP rewards!",
            color=discord.Color.blue()
        )
        
        self._add_quest_list_to_embed(embed, "Daily Quests", daily_quests)
        
        await ctx.send(embed=embed)
    
    @quest.command(name="weekly")
    @rate_limit(calls=5, period=60)  # 5 calls per minute per user
    async def weekly_quests(self, ctx):
        """View your weekly quests"""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        # Get all active quests for the user
        quests = await get_user_active_quests(guild_id, user_id)
        
        # Filter to only weekly quests
        weekly_quests = [q for q in quests if q['quest_type'] == 'weekly']
        
        if not weekly_quests:
            await ctx.send("You don't have any active weekly quests. Check back later!")
            return
        
        embed = discord.Embed(
            title="📆 Weekly Quests",
            description="Complete these quests for XP rewards!",
            color=discord.Color.blue()
        )
        
        self._add_quest_list_to_embed(embed, "Weekly Quests", weekly_quests)
        
        await ctx.send(embed=embed)
    
    # ===== ADMIN COMMANDS =====
    @quest.command(name="create")
    @commands.has_permissions(administrator=True)
    async def create_quest_cmd(self, ctx):
        """Start the interactive quest creation process"""
        # This is just a stub - the actual creation would use a questionnaire
        # or a modal form with the Discord UI features
        await ctx.send("Use the slash command `/createquest` for an easier interface.")
    
    @quest.command(name="edit")
    @commands.has_permissions(administrator=True)
    async def edit_quest(self, ctx, quest_id: int):
        """Edit an existing quest"""
        await ctx.send("Use the slash command `/editquest` for an easier interface.")
    
    @quest.command(name="delete")
    @commands.has_permissions(administrator=True)
    async def delete_quest_cmd(self, ctx, quest_id: int):
        """Delete a quest"""
        guild_id = str(ctx.guild.id)
        
        # Get quest details first
        quest = await get_quest(quest_id)
        
        if not quest or quest['guild_id'] != guild_id:
            await ctx.send("Quest not found.")
            return
            
        # Confirm deletion
        confirm_msg = await ctx.send(
            f"Are you sure you want to delete quest: **{quest['name']}**? "
            "This will also remove all user progress. (yes/no)"
        )
        
        # Wait for confirmation
        try:
            response = await self.bot.wait_for(
                'message',
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                timeout=30.0
            )
            
            if response.content.lower() in ('yes', 'y'):
                # Delete the quest
                success = await delete_quest(quest_id, guild_id)
                
                if success:
                    await ctx.send(f"✅ Quest **{quest['name']}** has been deleted.")
                else:
                    await ctx.send("❌ Failed to delete the quest. Please try again.")
            else:
                await ctx.send("Quest deletion cancelled.")
                
        except asyncio.TimeoutError:
            await ctx.send("Quest deletion cancelled (timed out).")
    
    @quest.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def reset_quests(self, ctx, quest_type: Optional[str] = None):
        """
        Reset daily/weekly quests to prepare new ones
        
        Usage:
        !quest reset daily - Reset daily quests
        !quest reset weekly - Reset weekly quests
        !quest reset - Reset both daily and weekly
        """
        guild_id = str(ctx.guild.id)
        
        if quest_type and quest_type.lower() not in ('daily', 'weekly'):
            await ctx.send("Invalid quest type. Use 'daily' or 'weekly'.")
            return
            
        # Confirm reset
        if quest_type:
            confirm_msg = await ctx.send(
                f"Are you sure you want to reset all {quest_type} quests? (yes/no)"
            )
        else:
            confirm_msg = await ctx.send(
                "Are you sure you want to reset all daily and weekly quests? (yes/no)"
            )
        
        # Wait for confirmation
        try:
            response = await self.bot.wait_for(
                'message',
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                timeout=30.0
            )
            
            if response.content.lower() in ('yes', 'y'):
                # Reset the quests
                if quest_type:
                    success = await mark_quests_inactive(guild_id, quest_type.lower())
                    if success:
                        await ctx.send(f"✅ All {quest_type} quests have been reset.")
                    else:
                        await ctx.send(f"❌ Failed to reset {quest_type} quests.")
                else:
                    # Reset both daily and weekly
                    success_daily = await mark_quests_inactive(guild_id, 'daily')
                    success_weekly = await mark_quests_inactive(guild_id, 'weekly')
                    
                    if success_daily and success_weekly:
                        await ctx.send("✅ All daily and weekly quests have been reset.")
                    else:
                        await ctx.send("❌ Failed to reset some quests.")
            else:
                await ctx.send("Quest reset cancelled.")
                
        except asyncio.TimeoutError:
            await ctx.send("Quest reset cancelled (timed out).")
            
    # ===== SLASH COMMANDS =====
    @app_commands.command(name="quests", description="View your active quests")
    async def slash_quests(self, interaction: discord.Interaction, quest_type: Optional[Literal["daily", "weekly", "special", "all"]] = "all"):
        """Slash command to view quests"""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # Get all active quests for the user
        quests = await get_user_active_quests(guild_id, user_id)
        
        # Filter by type if specified
        if quest_type != "all":
            quests = [q for q in quests if q['quest_type'] == quest_type]
        
        if not quests:
            await interaction.response.send_message(
                f"You don't have any active {quest_type} quests. Check back later!",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title=f"📜 Your {quest_type.capitalize() if quest_type != 'all' else ''} Quests",
            description="Complete quests to earn XP rewards!",
            color=discord.Color.blue()
        )
        
        # Group quests by type
        daily_quests = [q for q in quests if q['quest_type'] == 'daily']
        weekly_quests = [q for q in quests if q['quest_type'] == 'weekly']
        special_quests = [q for q in quests if q['quest_type'] not in ('daily', 'weekly')]
        
        # Format and add each quest type
        if quest_type == "all" or quest_type == "daily":
            self._add_quest_list_to_embed(embed, "Daily Quests", daily_quests)
            
        if quest_type == "all" or quest_type == "weekly":
            self._add_quest_list_to_embed(embed, "Weekly Quests", weekly_quests)
            
        if quest_type == "all" or quest_type == "special":
            self._add_quest_list_to_embed(embed, "Special Quests", special_quests)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="questinfo", description="View details about a specific quest")
    @app_commands.describe(quest_id="The ID of the quest to view")
    async def slash_quest_info(self, interaction: discord.Interaction, quest_id: int):
        """Slash command to view quest details"""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # Get quest details
        quest = await get_quest(quest_id)
        
        if not quest or quest['guild_id'] != guild_id:
            await interaction.response.send_message("Quest not found.", ephemeral=True)
            return
        
        # Get user's progress
        progress, completed, completed_at = await get_user_quest_progress(guild_id, user_id, quest_id)
        
        # Format requirement
        req_type_names = {
            "total_messages": "Send messages",
            "total_reactions": "Add reactions",
            "voice_time_seconds": "Spend time in voice",
            "commands_used": "Use commands"
        }
        
        requirement = req_type_names.get(quest['requirement_type'], quest['requirement_type'])
        
        # Format voice time if applicable
        if quest['requirement_type'] == 'voice_time_seconds':
            minutes = quest['requirement_value'] // 60
            requirement = f"Spend {minutes} minutes in voice"
            progress_display = f"{progress // 60}/{minutes} minutes"
        else:
            progress_display = f"{progress}/{quest['requirement_value']}"
        
        # Calculate progress percentage
        progress_pct = min(100, int((progress / quest['requirement_value']) * 100))
        
        # Create embed
        embed = discord.Embed(
            title=f"📜 {quest['name']}",
            description=quest['description'],
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Type", value=quest['quest_type'].capitalize(), inline=True)
        embed.add_field(name="Difficulty", value=quest['difficulty'].capitalize(), inline=True)
        embed.add_field(name="Status", value="✅ Completed" if completed else "🔄 In Progress", inline=True)
        
        embed.add_field(name="Requirement", value=requirement, inline=True)
        embed.add_field(name="Progress", value=progress_display, inline=True)
        embed.add_field(name="Completion", value=f"{progress_pct}%", inline=True)
        
        embed.add_field(name="Reward", value=f"{quest['reward_xp']} XP", inline=True)
        
        if quest['reward_multiplier'] > 1.0:
            embed.add_field(
                name="Bonus", 
                value=f"{quest['reward_multiplier']}x XP multiplier", 
                inline=True
            )
        
        if completed and completed_at:
            embed.add_field(
                name="Completed", 
                value=completed_at.strftime("%Y-%m-%d %H:%M"), 
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="queststats", description="View your quest statistics")
    async def slash_quest_stats(self, interaction: discord.Interaction):
        """Slash command to view quest stats"""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        stats = await get_user_quest_stats(guild_id, user_id)
        
        embed = discord.Embed(
            title="📊 Quest Statistics",
            description=f"Quest progress for {interaction.user.display_name}",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Completed Quests",
            value=str(stats['completed_count']),
            inline=True
        )
        
        embed.add_field(
            name="Active Quests",
            value=str(stats['active_count']),
            inline=True
        )
        
        embed.add_field(
            name="XP Earned",
            value=f"{stats['total_xp_earned']} XP",
            inline=True
        )
        
        embed.add_field(
            name="Daily Quests",
            value=f"{stats['daily_completed']} completed",
            inline=True
        )
        
        embed.add_field(
            name="Weekly Quests",
            value=f"{stats['weekly_completed']} completed",
            inline=True
        )
        
        embed.add_field(
            name="Special Quests",
            value=f"{stats['special_completed']} completed",
            inline=True
        )
        
        if stats['last_completed']:
            embed.add_field(
                name="Last Completion",
                value=stats['last_completed'].strftime("%Y-%m-%d %H:%M"),
                inline=False
            )
            
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.avatar.url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="createquest", description="Create a new quest (Admin only)")
    @app_commands.describe(
        name="Quest name",
        description="Quest description",
        quest_type="Type of quest",
        requirement_type="What needs to be done",
        requirement_value="Amount required",
        reward_xp="XP awarded for completion",
        difficulty="Quest difficulty",
        reward_multiplier="XP multiplier awarded (1.0 = no boost)",
        refresh_cycle="When the quest resets"
    )
    @app_commands.choices(
        quest_type=[
            app_commands.Choice(name="Daily", value="daily"),
            app_commands.Choice(name="Weekly", value="weekly"),
            app_commands.Choice(name="Special", value="special"),
            app_commands.Choice(name="Event", value="event"),
            app_commands.Choice(name="Challenge", value="challenge")
        ],
        requirement_type=[
            app_commands.Choice(name="Send messages", value="total_messages"),
            app_commands.Choice(name="Add reactions", value="total_reactions"),
            app_commands.Choice(name="Time in voice (minutes)", value="voice_time_seconds"),
            app_commands.Choice(name="Use commands", value="commands_used")
        ],
        difficulty=[
            app_commands.Choice(name="Easy", value="easy"),
            app_commands.Choice(name="Medium", value="medium"),
            app_commands.Choice(name="Hard", value="hard")
        ],
        refresh_cycle=[
            app_commands.Choice(name="Daily", value="daily"),
            app_commands.Choice(name="Weekly", value="weekly"),
            app_commands.Choice(name="Monthly", value="monthly"),
            app_commands.Choice(name="Never", value="once")
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def slash_create_quest(
        self, 
        interaction: discord.Interaction,
        name: str,
        description: str,
        quest_type: str,
        requirement_type: str,
        requirement_value: int,
        reward_xp: int,
        difficulty: str = "medium",
        reward_multiplier: float = 1.0,
        refresh_cycle: Optional[str] = None
    ):
        """Slash command to create a new quest"""
        guild_id = str(interaction.guild.id)
        
        # Adjust requirement value for voice time (convert minutes to seconds)
        if requirement_type == "voice_time_seconds":
            requirement_value = requirement_value * 60  # Convert minutes to seconds
        
        # Create the quest
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        quest_id = await create_quest(
            guild_id=guild_id,
            name=name,
            description=description,
            quest_type=quest_type,
            requirement_type=requirement_type,
            requirement_value=requirement_value,
            reward_xp=reward_xp,
            reward_multiplier=reward_multiplier,
            difficulty=difficulty,
            refresh_cycle=refresh_cycle
        )
        
        if quest_id > 0:
            embed = discord.Embed(
                title="✅ Quest Created",
                description=f"**{name}** has been created with ID {quest_id}",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Description", value=description, inline=False)
            embed.add_field(name="Type", value=quest_type.capitalize(), inline=True)
            embed.add_field(name="Difficulty", value=difficulty.capitalize(), inline=True)
            
            # Format requirement
            req_display = requirement_value
            if requirement_type == "voice_time_seconds":
                req_display = f"{requirement_value // 60} minutes"
                
            req_type_names = {
                "total_messages": f"Send {req_display} messages",
                "total_reactions": f"Add {req_display} reactions",
                "voice_time_seconds": f"Spend {req_display} in voice",
                "commands_used": f"Use {req_display} commands"
            }
            
            embed.add_field(
                name="Requirement", 
                value=req_type_names.get(requirement_type, requirement_type),
                inline=False
            )
            
            embed.add_field(name="Reward", value=f"{reward_xp} XP", inline=True)
            
            if reward_multiplier > 1.0:
                embed.add_field(
                    name="Multiplier", 
                    value=f"{reward_multiplier}x XP", 
                    inline=True
                )
                
            if refresh_cycle:
                embed.add_field(name="Refresh Cycle", value=refresh_cycle.capitalize(), inline=True)
                
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to create quest. Please try again.", ephemeral=True)
    
    @app_commands.command(name="editquest", description="Edit an existing quest (Admin only)")
    @app_commands.describe(
        quest_id="ID of the quest to edit",
        field="Field to edit",
        value="New value for the field"
    )
    @app_commands.choices(
        field=[
            app_commands.Choice(name="Name", value="name"),
            app_commands.Choice(name="Description", value="description"),
            app_commands.Choice(name="Active status", value="active"),
            app_commands.Choice(name="Quest type", value="quest_type"),
            app_commands.Choice(name="Requirement type", value="requirement_type"),
            app_commands.Choice(name="Requirement value", value="requirement_value"),
            app_commands.Choice(name="Reward XP", value="reward_xp"),
            app_commands.Choice(name="Reward multiplier", value="reward_multiplier"),
            app_commands.Choice(name="Difficulty", value="difficulty"),
            app_commands.Choice(name="Refresh cycle", value="refresh_cycle")
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def slash_edit_quest(
        self,
        interaction: discord.Interaction,
        quest_id: int,
        field: str,
        value: str
    ):
        """Slash command to edit a quest"""
        guild_id = str(interaction.guild.id)
        
        # Get quest details first
        quest = await get_quest(quest_id)
        
        if not quest or quest['guild_id'] != guild_id:
            await interaction.response.send_message("Quest not found.", ephemeral=True)
            return
        
        # Convert value based on field type
        try:
            if field in ["requirement_value", "reward_xp"]:
                # Integer fields
                typed_value = int(value)
            elif field in ["reward_multiplier"]:
                # Float fields
                typed_value = float(value)
            elif field in ["active"]:
                # Boolean fields
                typed_value = value.lower() in ["true", "yes", "1", "on"]
            else:
                # String fields
                typed_value = value
                
            # Special handling for voice time
            if field == "requirement_type" and value == "voice_time_seconds" and quest['requirement_type'] != "voice_time_seconds":
                # Converting to voice time - multiply by 60 to convert minutes to seconds
                await update_quest(quest_id, guild_id, "requirement_value", quest['requirement_value'] * 60)
            elif field == "requirement_type" and quest['requirement_type'] == "voice_time_seconds" and value != "voice_time_seconds":
                # Converting from voice time - divide by 60 to convert seconds to minutes
                await update_quest(quest_id, guild_id, "requirement_value", quest['requirement_value'] // 60)
                
            # Special handling for requirement_value
            if field == "requirement_value" and quest['requirement_type'] == "voice_time_seconds":
                # Converting minutes to seconds
                typed_value = typed_value * 60
                
        except ValueError:
            await interaction.response.send_message(
                f"Invalid value for field '{field}'. Please provide a valid {field} value.",
                ephemeral=True
            )
            return
        
        # Update the quest
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        success = await update_quest(quest_id, guild_id, field, typed_value)
        
        if success:
            # Get updated quest
            updated_quest = await get_quest(quest_id)
            
            embed = discord.Embed(
                title="✅ Quest Updated",
                description=f"Quest **{quest['name']}** has been updated",
                color=discord.Color.green()
            )
            
            embed.add_field(name="Field", value=field, inline=True)
            embed.add_field(name="Old Value", value=str(quest[field]), inline=True)
            embed.add_field(name="New Value", value=str(updated_quest[field]), inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to update quest. Please try again.", ephemeral=True)
            
    @app_commands.command(name="deletequest", description="Delete a quest (Admin only)")
    @app_commands.describe(quest_id="ID of the quest to delete")
    @app_commands.checks.has_permissions(administrator=True)
    async def slash_delete_quest(self, interaction: discord.Interaction, quest_id: int):
        """Slash command to delete a quest"""
        guild_id = str(interaction.guild.id)
        
        # Get quest details first
        quest = await get_quest(quest_id)
        
        if not quest or quest['guild_id'] != guild_id:
            await interaction.response.send_message("Quest not found.", ephemeral=True)
            return
            
        # Confirm deletion
        embed = discord.Embed(
            title="⚠️ Confirm Deletion",
            description=f"Are you sure you want to delete quest: **{quest['name']}**?\n"
                       "This will also remove all user progress.",
            color=discord.Color.red()
        )
        
        # Create confirm/cancel buttons
        class ConfirmView(discord.ui.View):
            def __init__(self, *, timeout=30):
                super().__init__(timeout=timeout)
                self.value = None
                
            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = True
                self.stop()
                
            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = False
                self.stop()
        
        view = ConfirmView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        # Wait for the user to interact with the buttons
        await view.wait()
        
        if view.value is None:
            await interaction.followup.send("Quest deletion cancelled (timed out).", ephemeral=True)
        elif view.value:
            # Delete the quest
            success = await delete_quest(quest_id, guild_id)
            
            if success:
                await interaction.followup.send(f"✅ Quest **{quest['name']}** has been deleted.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to delete the quest. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("Quest deletion cancelled.", ephemeral=True)
    
    @app_commands.command(name="resetquests", description="Reset daily/weekly quests (Admin only)")
    @app_commands.describe(quest_type="Type of quests to reset")
    @app_commands.choices(
        quest_type=[
            app_commands.Choice(name="Daily Quests", value="daily"),
            app_commands.Choice(name="Weekly Quests", value="weekly"),
            app_commands.Choice(name="Both Daily and Weekly", value="both")
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def slash_reset_quests(self, interaction: discord.Interaction, quest_type: str):
        """Slash command to reset quests"""
        guild_id = str(interaction.guild.id)
        
        # Confirm reset
        embed = discord.Embed(
            title="⚠️ Confirm Reset",
            description=f"Are you sure you want to reset {quest_type} quests?",
            color=discord.Color.yellow()
        )
        
        # Create confirm/cancel buttons
        class ConfirmView(discord.ui.View):
            def __init__(self, *, timeout=30):
                super().__init__(timeout=timeout)
                self.value = None
                
            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = True
                self.stop()
                
            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.value = False
                self.stop()
        
        view = ConfirmView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        # Wait for the user to interact with the buttons
        await view.wait()
        
        if view.value is None:
            await interaction.followup.send("Quest reset cancelled (timed out).", ephemeral=True)
        elif view.value:
            # Reset the quests
            if quest_type == "both":
                success_daily = await mark_quests_inactive(guild_id, 'daily')
                success_weekly = await mark_quests_inactive(guild_id, 'weekly')
                
                if success_daily and success_weekly:
                    await interaction.followup.send("✅ All daily and weekly quests have been reset.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Failed to reset some quests.", ephemeral=True)
            else:
                success = await mark_quests_inactive(guild_id, quest_type)
                
                if success:
                    await interaction.followup.send(f"✅ All {quest_type} quests have been reset.", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Failed to reset {quest_type} quests.", ephemeral=True)
        else:
            await interaction.followup.send("Quest reset cancelled.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(QuestCommands(bot))