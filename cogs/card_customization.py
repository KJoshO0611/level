# Create a new file: cogs/card_customization.py

import discord
from discord.ext import commands
from discord import app_commands
import logging
import re
from modules.databasev2 import (
    get_level_card_settings,
    update_level_card_setting,
    reset_level_card_settings,
    validate_rgb_color
)

class CardCustomizationCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    # Setup slash commands when the cog is loaded
    async def cog_load(self):
        try:
            await self.bot.tree.sync()
            logging.info("Card customization slash commands registered")
        except Exception as e:
            logging.error(f"Error syncing card customization commands: {e}")
            
    @commands.command(name="cardcolors", aliases=["cc"])
    async def card_colors(self, ctx):
        """View your current level card color settings"""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        settings = await get_level_card_settings(guild_id, user_id)
        
        embed = discord.Embed(
            title="Your Level Card Settings",
            description="Here are your current level card color settings",
            color=discord.Color.blue()
        )
        
        # Parse the colors to use in the embed
        try:
            bg_r, bg_g, bg_b = map(int, settings["background_color"].split(','))
            accent_r, accent_g, accent_b = map(int, settings["accent_color"].split(','))
            text_r, text_g, text_b = map(int, settings["text_color"].split(','))
            
            embed.color = discord.Color.from_rgb(accent_r, accent_g, accent_b)
            
            embed.add_field(
                name="Background Color",
                value=f"RGB: {settings['background_color']}\nHex: #{bg_r:02x}{bg_g:02x}{bg_b:02x}",
                inline=True
            )
            
            embed.add_field(
                name="Accent Color",
                value=f"RGB: {settings['accent_color']}\nHex: #{accent_r:02x}{accent_g:02x}{accent_b:02x}",
                inline=True
            )
            
            embed.add_field(
                name="Text Color",
                value=f"RGB: {settings['text_color']}\nHex: #{text_r:02x}{text_g:02x}{text_b:02x}",
                inline=True
            )
            
            if settings["background_image"]:
                embed.add_field(
                    name="Background Image",
                    value=f"Custom background image set",
                    inline=False
                )
            
            embed.add_field(
                name="Customization Commands",
                value=(
                    "Use the following commands to customize your card:\n"
                    "`!setcardbg R,G,B` - Set background color\n"
                    "`!setcardaccent R,G,B` - Set accent color\n"
                    "`!setcardtext R,G,B` - Set text color\n"
                    "`!resetcard` - Reset to default\n\n"
                    "Example: `!setcardbg 50,50,50`"
                ),
                inline=False
            )
            
        except ValueError:
            embed.add_field(
                name="Error",
                value="There was an error parsing your color settings. Try resetting with `!resetcard`",
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name="setcardbg", aliases=["scbg"])
    async def set_card_background(self, ctx, color: str):
        """Set your level card background color (R,G,B format)
        
        Example: !setcardbg 50,50,50
        """
        if not validate_rgb_color(color):
            return await ctx.send("⚠️ Invalid color format. Use R,G,B format (e.g., 50,50,50)")
        
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        success = await update_level_card_setting(guild_id, user_id, "background_color", color)
        
        if success:
            # Parse the color to use in the embed
            r, g, b = map(int, color.split(','))
            
            embed = discord.Embed(
                title="Level Card Updated",
                description="Your level card background color has been updated.",
                color=discord.Color.from_rgb(r, g, b)
            )
            
            embed.add_field(
                name="New Background Color",
                value=f"RGB: {color}\nHex: #{r:02x}{g:02x}{b:02x}",
                inline=False
            )
            
            embed.set_footer(text="Use !level to see your updated card")
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to update level card settings. Please try again.")
    
    @commands.command(name="setcardaccent", aliases=["sca"])
    async def set_card_accent(self, ctx, color: str):
        """Set your level card accent color (R,G,B format)
        
        Example: !setcardaccent 0,150,200
        """
        if not validate_rgb_color(color):
            return await ctx.send("⚠️ Invalid color format. Use R,G,B format (e.g., 0,150,200)")
        
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        success = await update_level_card_setting(guild_id, user_id, "accent_color", color)
        
        if success:
            # Parse the color to use in the embed
            r, g, b = map(int, color.split(','))
            
            embed = discord.Embed(
                title="Level Card Updated",
                description="Your level card accent color has been updated.",
                color=discord.Color.from_rgb(r, g, b)
            )
            
            embed.add_field(
                name="New Accent Color",
                value=f"RGB: {color}\nHex: #{r:02x}{g:02x}{b:02x}",
                inline=False
            )
            
            embed.set_footer(text="Use !level to see your updated card")
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to update level card settings. Please try again.")
    
    @commands.command(name="setcardtext", aliases=["sct"])
    async def set_card_text(self, ctx, color: str):
        """Set your level card text color (R,G,B format)
        
        Example: !setcardtext 255,255,255
        """
        if not validate_rgb_color(color):
            return await ctx.send("⚠️ Invalid color format. Use R,G,B format (e.g., 255,255,255)")
        
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        success = await update_level_card_setting(guild_id, user_id, "text_color", color)
        
        if success:
            # Parse the color to use in the embed
            r, g, b = map(int, color.split(','))
            
            embed = discord.Embed(
                title="Level Card Updated",
                description="Your level card text color has been updated.",
                color=discord.Color.from_rgb(r, g, b)
            )
            
            embed.add_field(
                name="New Text Color",
                value=f"RGB: {color}\nHex: #{r:02x}{g:02x}{b:02x}",
                inline=False
            )
            
            embed.set_footer(text="Use !level to see your updated card")
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to update level card settings. Please try again.")
    
    @commands.command(name="resetcard")
    async def reset_card(self, ctx):
        """Reset your level card to the default settings"""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        success = await reset_level_card_settings(guild_id, user_id)
        
        if success:
            embed = discord.Embed(
                title="Level Card Reset",
                description="Your level card has been reset to default settings.",
                color=discord.Color.blue()
            )
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to reset level card settings. Please try again.")

    # Add a slash command version
    @app_commands.command(name="cardstyle", description="View and customize your level card")
    async def card_style(self, interaction: discord.Interaction):
        """View your level card style settings as a slash command"""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        settings = await get_level_card_settings(guild_id, user_id)
        
        embed = discord.Embed(
            title="Your Level Card Settings",
            description="Here are your current level card color settings",
            color=discord.Color.blue()
        )
        
        # Parse the colors to use in the embed
        try:
            bg_r, bg_g, bg_b = map(int, settings["background_color"].split(','))
            accent_r, accent_g, accent_b = map(int, settings["accent_color"].split(','))
            text_r, text_g, text_b = map(int, settings["text_color"].split(','))
            
            embed.color = discord.Color.from_rgb(accent_r, accent_g, accent_b)
            
            embed.add_field(
                name="Background Color",
                value=f"RGB: {settings['background_color']}\nHex: #{bg_r:02x}{bg_g:02x}{bg_b:02x}",
                inline=True
            )
            
            embed.add_field(
                name="Accent Color",
                value=f"RGB: {settings['accent_color']}\nHex: #{accent_r:02x}{accent_g:02x}{accent_b:02x}",
                inline=True
            )
            
            embed.add_field(
                name="Text Color",
                value=f"RGB: {settings['text_color']}\nHex: #{text_r:02x}{text_g:02x}{text_b:02x}",
                inline=True
            )
            
            if settings["background_image"]:
                embed.add_field(
                    name="Background Image",
                    value=f"Custom background image set",
                    inline=False
                )
            
            embed.add_field(
                name="Customization Commands",
                value=(
                    "Use the following commands to customize your card:\n"
                    "`!setcardbg R,G,B` - Set background color\n"
                    "`!setcardaccent R,G,B` - Set accent color\n"
                    "`!setcardtext R,G,B` - Set text color\n"
                    "`!resetcard` - Reset to default\n\n"
                    "Example: `!setcardbg 50,50,50`"
                ),
                inline=False
            )
            
        except ValueError:
            embed.add_field(
                name="Error",
                value="There was an error parsing your color settings. Try resetting with `!resetcard`",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Setup function for the cog
async def setup(bot):
    await bot.add_cog(CardCustomizationCommands(bot))