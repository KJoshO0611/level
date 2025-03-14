import discord
from discord import app_commands
from discord.ext import commands
import typing
from datetime import datetime
import logging

# Dictionary mapping cog names to emojis and descriptions
COG_EMOJI_MAP = {
    "AdminCommands": {
        "emoji": "⚙️",
        "description": "Server administration and configuration commands",
        "color": discord.Color.red()
    },
    "LevelingCommands": {
        "emoji": "📊",
        "description": "Commands for checking levels and XP",
        "color": discord.Color.green()
    },
    "CardCustomizationCommands": {
        "emoji": "🎨",
        "description": "Customize your level card appearance",
        "color": discord.Color.purple()
    },
    "ConfigCommands": {
        "emoji": "🔧",
        "description": "Server configuration settings",
        "color": discord.Color.gold()
    },
    "CustomHelpCommand": {
        "emoji": "❓",
        "description": "Help and information commands",
        "color": discord.Color.blue()
    },
    "No Category": {
        "emoji": "📁",
        "description": "Miscellaneous commands",
        "color": discord.Color.light_grey()
    }
}

class HelpView(discord.ui.View):
    def __init__(self, help_command, timeout=60):
        super().__init__(timeout=timeout)
        self.help_command = help_command
        self.current_page = "main"
        self.current_category = None
        self.current_command = None
        
    # Main category buttons
    @discord.ui.button(label="Admin", style=discord.ButtonStyle.red, emoji="⚙️", row=0)
    async def admin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_category(interaction, "AdminCommands")
    
    @discord.ui.button(label="Leveling", style=discord.ButtonStyle.green, emoji="📊", row=0)
    async def leveling_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_category(interaction, "LevelingCommands")
    
    @discord.ui.button(label="Customization", style=discord.ButtonStyle.blurple, emoji="🎨", row=0)
    async def customization_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_category(interaction, "CardCustomizationCommands")
    
    @discord.ui.button(label="Config", style=discord.ButtonStyle.gray, emoji="🔧", row=1)
    async def config_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_category(interaction, "ConfigCommands")
    
    @discord.ui.button(label="Help", style=discord.ButtonStyle.gray, emoji="❓", row=1)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_category(interaction, "CustomHelpCommand")
    
    # Navigation buttons
    @discord.ui.button(label="Home", style=discord.ButtonStyle.green, emoji="🏠", row=2)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_main_help(interaction)
    
    async def show_main_help(self, interaction):
        """Show the main help menu with categories"""
        self.current_page = "main"
        self.current_category = None
        self.current_command = None
        
        embed = await self.help_command.get_main_help_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def show_category(self, interaction, category_name):
        """Show commands for a specific category"""
        self.current_page = "category"
        self.current_category = category_name
        
        embed = await self.help_command.get_category_embed(category_name)
        await interaction.response.edit_message(embed=embed, view=self)


class CommandDetailsView(discord.ui.View):
    def __init__(self, help_command, command_name, timeout=60):
        super().__init__(timeout=timeout)
        self.help_command = help_command
        self.command_name = command_name
    
    @discord.ui.button(label="Back to Categories", style=discord.ButtonStyle.gray, emoji="◀️")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Create a new main help view
        main_view = HelpView(self.help_command)
        embed = await self.help_command.get_main_help_embed()
        await interaction.response.edit_message(embed=embed, view=main_view)


class CustomHelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Replace the default help command
        bot.remove_command('help')
    
    def get_command_signature(self, command):
        """Returns the command signature"""
        params = []
        
        for key, value in command.params.items():
            # Skip 'self' and 'ctx' parameters
            if key in ('self', 'ctx'):
                continue
                
            if value.default is not value.empty:
                # Optional argument
                params.append(f'[{key}]')
            else:
                # Required argument
                params.append(f'<{key}>')
                
        return f"{' '.join(params)}"
    
    def get_cog_info(self, cog_name):
        """Get emoji and color for a cog"""
        info = COG_EMOJI_MAP.get(cog_name, {
            "emoji": "📁",
            "description": "Commands",
            "color": discord.Color.blue()
        })
        return info
    
    async def get_main_help_embed(self):
        """Generate the main help embed with categories"""
        embed = discord.Embed(
            title="📚 Bot Help Menu",
            description="Click a button below to view commands in that category.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        # Group commands by cog and count them
        cogs = {}
        for command in self.bot.commands:
            if command.hidden:
                continue
                
            cog_name = command.cog.qualified_name if command.cog else "No Category"
            if cog_name not in cogs:
                cogs[cog_name] = []
                
            cogs[cog_name].append(command)
        
        # Add fields for each category
        for cog_name, cog_commands in cogs.items():
            info = self.get_cog_info(cog_name)
            embed.add_field(
                name=f"{info['emoji']} {cog_name} ({len(cog_commands)} commands)",
                value=f"{info['description']}",
                inline=False
            )
        
        embed.set_footer(text=f"Select a category using the buttons below • {len(self.bot.commands)} commands total")
        return embed
    
    async def get_category_embed(self, category_name):
        """Generate an embed for a specific category"""
        cog_instance = self.bot.get_cog(category_name)
        if not cog_instance:
            return discord.Embed(
                title="Category Not Found",
                description=f"Category `{category_name}` not found.",
                color=discord.Color.red()
            )
        
        info = self.get_cog_info(category_name)
        embed = discord.Embed(
            title=f"{info['emoji']} {category_name} Commands",
            description=info['description'],
            color=info['color'],
            timestamp=datetime.now()
        )
        
        for cmd in cog_instance.get_commands():
            if cmd.hidden:
                continue
                
            # Format command with aliases
            if cmd.aliases:
                aliases = f" (alias: {cmd.aliases[0]})"
            else:
                aliases = ""
            
            # Add short description
            short_desc = cmd.help.split('\n')[0] if cmd.help else "No description"
            
            embed.add_field(
                name=f"`!!{cmd.name}`{aliases}",
                value=short_desc,
                inline=False
            )
        
        embed.set_footer(text="Click on a button to navigate • Use !!help <command> for command details")
        return embed
    
    async def get_command_embed(self, command_name):
        """Generate an embed for a specific command"""
        command = self.bot.get_command(command_name)
        if not command:
            return discord.Embed(
                title="Command Not Found",
                description=f"Command `{command_name}` not found.",
                color=discord.Color.red()
            )
        
        cog_name = command.cog.qualified_name if command.cog else "No Category"
        info = self.get_cog_info(cog_name)
        
        embed = discord.Embed(
            title=f"`!!{command.name}`",
            color=info['color'],
            timestamp=datetime.now()
        )
        
        # Add command description
        if command.help:
            embed.description = command.help
        else:
            embed.description = "No description provided."
        
        # Add usage with examples
        signature = self.get_command_signature(command)
        usage = f"!!{command.name} {signature}"
        embed.add_field(
            name="📝 Usage",
            value=f"`{usage}`",
            inline=False
        )
        
        # Add command category
        embed.add_field(
            name="📁 Category",
            value=f"{info['emoji']} {cog_name}",
            inline=True
        )
        
        # Add command aliases if any
        if command.aliases:
            embed.add_field(
                name="🔄 Aliases",
                value=", ".join(f"`!!{alias}`" for alias in command.aliases),
                inline=True
            )
        
        # Add subcommands if this is a group command
        if isinstance(command, commands.Group):
            subcommand_list = []
            for sub in command.commands:
                # Get first line of help text
                short_desc = sub.help.split('\n')[0] if sub.help else "No description"
                subcommand_list.append(f"`!!{command.name} {sub.name}` - {short_desc}")
            
            embed.add_field(
                name="📋 Subcommands",
                value="\n".join(subcommand_list) or "No subcommands",
                inline=False
            )
        
        embed.set_footer(text=f"Use the Back button to return to categories")
        return embed
    
    @commands.command(name="help")
    async def help_command(self, ctx, *, command_name: typing.Optional[str] = None):
        """Interactive help menu - click buttons to navigate commands"""
        if command_name:
            # Show detailed help for a specific command
            embed = await self.get_command_embed(command_name)
            view = CommandDetailsView(self, command_name)
            await ctx.send(embed=embed, view=view, ephemeral=True)
        else:
            # Show the main help menu with category buttons
            embed = await self.get_main_help_embed()
            view = HelpView(self)
            await ctx.send(embed=embed, view=view, ephemeral=True)

    # Add proper slash command support
    @app_commands.command(name="helpme", description="Interactive help menu with command information")
    async def slash_help(self, interaction: discord.Interaction, command_name: str = None):
        """Interactive help menu (slash command version)"""
        if command_name:
            # Show detailed help for a specific command
            embed = await self.get_command_embed(command_name)
            view = CommandDetailsView(self, command_name)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # Show the main help menu with category buttons
            embed = await self.get_main_help_embed()
            view = HelpView(self)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)