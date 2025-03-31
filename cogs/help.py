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
    "BackgroundCommands": {
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
    "AchievementCommands": {
        "emoji": "🏆",
        "description": "Manage and view achievements",
        "color": discord.Color.orange()
    },
    "CalendarCommands": {
        "emoji": "📅",
        "description": "Event scheduling and calendar commands",
        "color": discord.Color.teal()
    },
    "QuestCommands": {
        "emoji": "🎯",
        "description": "Complete quests and earn rewards",
        "color": discord.Color.dark_gold()
    },
    "No Category": {
        "emoji": "📁",
        "description": "Miscellaneous commands",
        "color": discord.Color.light_grey()
    }
}

class CategorySelect(discord.ui.Select):
    def __init__(self, help_command, is_admin=False):
        self.help_command = help_command
        options = []
        
        for cog_name, info in COG_EMOJI_MAP.items():
            # Skip admin commands for non-admins
            if cog_name == "AdminCommands" and not is_admin:
                continue
                
            # Skip "No Category" if it's empty
            if cog_name == "No Category":
                continue
                
            options.append(discord.SelectOption(
                label=cog_name.replace("Commands", ""),
                description=info["description"],
                emoji=info["emoji"],
                value=cog_name
            ))
            
        super().__init__(
            placeholder="Select a command category",
            min_values=1,
            max_values=1,
            options=options
        )
        
    async def callback(self, interaction: discord.Interaction):
        category_name = self.values[0]
        embed = await self.help_command.get_category_embed(category_name)
        await interaction.response.edit_message(embed=embed, view=self.view)

class HelpModal(discord.ui.Modal, title="Help Categories"):
    def __init__(self, help_command, is_admin=False):
        super().__init__()
        self.help_command = help_command
        self.is_admin = is_admin
        
        # Create options for each category
        categories = []
        for cog_name, info in COG_EMOJI_MAP.items():
            # Skip admin commands for non-admins
            if cog_name == "AdminCommands" and not is_admin:
                continue
                
            # Skip "No Category" if it's empty
            if cog_name == "No Category":
                continue
                
            categories.append(f"{info['emoji']} {cog_name.replace('Commands', '')}: {info['description']}")
        
        self.category = discord.ui.TextInput(
            label="Select a category by number",
            placeholder="Enter a number from the list below",
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.category)
        
        # Add category options as text
        self.category_text = discord.ui.TextInput(
            label="Available Categories",
            style=discord.TextStyle.paragraph,
            default="\n".join([f"{i+1}. {cat}" for i, cat in enumerate(categories)]),
            required=False
        )
        self.add_item(self.category_text)
        
        # Store category mapping for lookup
        self.category_map = {str(i+1): cog_name for i, cog_name in enumerate([
            c for c in COG_EMOJI_MAP.keys() 
            if c != "No Category" and (c != "AdminCommands" or is_admin)
        ])}
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Get category from number
            category_number = self.category.value.strip()
            if category_number in self.category_map:
                category_name = self.category_map[category_number]
                embed = await self.help_command.get_category_embed(category_name)
                view = HelpView(self.help_command, self.is_admin)
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                await interaction.response.send_message(
                    "Invalid category number. Please try again.",
                    ephemeral=True
                )
        except Exception as e:
            logging.error(f"Error in help modal: {e}")
            await interaction.response.send_message(
                "An error occurred while processing your request.",
                ephemeral=True
            )

class HelpView(discord.ui.View):
    def __init__(self, help_command, is_admin=False, timeout=60):
        super().__init__(timeout=timeout)
        self.help_command = help_command
        self.is_admin = is_admin
        
        # Add category selector dropdown menu
        self.add_item(CategorySelect(help_command, is_admin))
    
    @discord.ui.button(label="Home", style=discord.ButtonStyle.success, emoji="🏠", row=1)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_main_help(interaction)
    
    async def show_main_help(self, interaction):
        """Show the main help menu with categories"""
        embed = await self.help_command.get_main_help_embed(self.is_admin)
        await interaction.response.edit_message(embed=embed, view=self)

class CommandDetailsView(discord.ui.View):
    def __init__(self, help_command, command_name, is_admin=False, timeout=60):
        super().__init__(timeout=timeout)
        self.help_command = help_command
        self.command_name = command_name
        self.is_admin = is_admin
    
    @discord.ui.button(label="Back to Categories", style=discord.ButtonStyle.secondary, emoji="◀️")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Create a new main help view
        main_view = HelpView(self.help_command, self.is_admin)
        embed = await self.help_command.get_main_help_embed(self.is_admin)
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
    
    async def get_main_help_embed(self, is_admin=False):
        """Generate the main help embed with categories"""
        embed = discord.Embed(
            title="📚 Bot Help Menu",
            description="Use the dropdown menu below to browse command categories.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        # Group commands by cog and count them
        cogs = {}
        for command in self.bot.commands:
            if command.hidden:
                continue
                
            cog_name = command.cog.qualified_name if command.cog else "No Category"
            
            # Skip admin commands for non-admins
            if cog_name == "AdminCommands" and not is_admin:
                continue
                
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
        
        command_count = sum(len(cmds) for cmds in cogs.values())
        embed.set_footer(text=f"Select a category from the dropdown • {command_count} commands total")
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
        
        commands_list = []
        
        # Get a list of all commands for this cog
        if hasattr(cog_instance, "get_commands"):
            commands_list = list(cog_instance.get_commands())
        elif hasattr(cog_instance, "get_app_commands"):
            commands_list = list(cog_instance.get_app_commands())
        
        if not commands_list:
            embed.add_field(
                name="No Commands",
                value="This category doesn't have any commands yet.",
                inline=False
            )
            return embed
            
        for cmd in commands_list:
            if cmd.hidden:
                continue
                
            # Format command with aliases if it's a standard command
            if hasattr(cmd, "aliases") and cmd.aliases:
                aliases = f" (alias: {cmd.aliases[0]})"
            else:
                aliases = ""
            
            # Get short description
            short_desc = None
            if hasattr(cmd, "help") and cmd.help:
                short_desc = cmd.help.split('\n')[0]
            elif hasattr(cmd, "description") and cmd.description:
                short_desc = cmd.description
                
            if not short_desc:
                short_desc = "No description"
            
            # Get command name with proper prefix
            if hasattr(cmd, "name"):
                # For normal commands
                cmd_name = f"!!{cmd.name}"
            elif hasattr(cmd, "qualified_name"):
                # For app commands
                cmd_name = f"/{cmd.qualified_name}"
            else:
                cmd_name = str(cmd)
            
            embed.add_field(
                name=f"`{cmd_name}`{aliases}",
                value=short_desc,
                inline=False
            )
        
        embed.set_footer(text="Use the dropdown to select a different category")
        return embed
    
    async def get_command_embed(self, command_name):
        """Generate an embed for a specific command"""
        command = self.bot.get_command(command_name)
        if not command:
            # Check if it might be a slash command
            for cmd in self.bot.tree.get_commands():
                if cmd.name == command_name:
                    return await self.get_app_command_embed(cmd)
                    
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
    
    async def get_app_command_embed(self, command):
        """Generate an embed for a slash command"""
        cog_name = getattr(command, "binding", None)
        cog_name = getattr(cog_name, "__cog_name__", "No Category") if cog_name else "No Category"
        info = self.get_cog_info(cog_name)
        
        embed = discord.Embed(
            title=f"`/{command.name}`",
            color=info['color'],
            timestamp=datetime.now()
        )
        
        # Add command description
        if command.description:
            embed.description = command.description
        else:
            embed.description = "No description provided."
        
        # Add parameters and examples
        params = []
        for param in getattr(command, "parameters", []):
            param_desc = f"`{param.name}`"
            if param.description:
                param_desc += f": {param.description}"
            if not param.required:
                param_desc = f"[{param_desc}]"
            else:
                param_desc = f"<{param_desc}>"
            params.append(param_desc)
            
        usage = f"/{command.name} {' '.join(params)}"
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
        
        embed.set_footer(text=f"Use the Back button to return to categories")
        return embed
    
    @commands.command(name="help")
    async def help_command(self, ctx, *, command_name: typing.Optional[str] = None):
        """Interactive help menu - browse commands by category"""
        # Check if user has admin permissions
        is_admin = ctx.author.guild_permissions.administrator if ctx.guild else False
        
        if command_name:
            # Show detailed help for a specific command
            embed = await self.get_command_embed(command_name)
            view = CommandDetailsView(self, command_name, is_admin)
            await ctx.send(embed=embed, view=view, ephemeral=True)
        else:
            # Show the main help menu with category selector
            embed = await self.get_main_help_embed(is_admin)
            view = HelpView(self, is_admin)
            await ctx.send(embed=embed, view=view, ephemeral=True)

    # Add proper slash command support
    @app_commands.command(name="help", description="Interactive help menu with command information")
    async def slash_help(self, interaction: discord.Interaction, command_name: str = None):
        """Interactive help menu (slash command version)"""
        # Check if user has admin permissions
        is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
        
        if command_name:
            # Show detailed help for a specific command
            embed = await self.get_command_embed(command_name)
            view = CommandDetailsView(self, command_name, is_admin)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # Show the main help menu with category selector
            embed = await self.get_main_help_embed(is_admin)
            view = HelpView(self, is_admin)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)