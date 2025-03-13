import discord
from discord.ext import commands
import typing

class CustomHelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Replace the default help command
        bot.remove_command('help')
    
    def get_command_signature(self, command):
        """Returns the command signature (e.g. !command <arg1> [arg2])"""
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
                
        return f"{self.bot.command_prefix}{command.name} {' '.join(params)}"
    
    @commands.command(name="help")
    async def help_command(self, ctx, *, command_name: typing.Optional[str] = None):
        """Shows help for a specific command or lists all commands"""
        # If no command specified, list all commands grouped by cog
        if command_name is None:
            embed = discord.Embed(
                title="Bot Commands",
                description=f"Use `{self.bot.command_prefix}help <command>` for more info on a command",
                color=discord.Color.blue()
            )
            
            # Group commands by cog
            cogs = {}
            for command in self.bot.commands:
                if command.hidden:
                    continue
                    
                cog_name = command.cog.qualified_name if command.cog else "No Category"
                if cog_name not in cogs:
                    cogs[cog_name] = []
                    
                cogs[cog_name].append(command)
            
            # Add fields for each cog
            for cog_name, cog_commands in cogs.items():
                command_list = ", ".join(f"`{cmd.name}`" for cmd in cog_commands)
                embed.add_field(name=cog_name, value=command_list, inline=False)
                
            await ctx.send(embed=embed)
            return
        
        # If a command is specified, show detailed help for it
        command = self.bot.get_command(command_name)
        if command is None:
            await ctx.send(f"Command '{command_name}' not found.")
            return
            
        embed = discord.Embed(
            title=f"Command: {command.name}",
            color=discord.Color.blue()
        )
        
        # Add command description
        if command.help:
            embed.description = command.help
        else:
            embed.description = "No description provided."
            
        # Add command signature/usage
        embed.add_field(
            name="Usage",
            value=f"`{self.get_command_signature(command)}`",
            inline=False
        )
        
        # Add command aliases if any
        if command.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`{alias}`" for alias in command.aliases),
                inline=False
            )
            
        # Add subcommands if this is a group command
        if isinstance(command, commands.Group):
            subcommand_list = "\n".join(
                f"`{self.bot.command_prefix}{command.name} {sub.name}` - {sub.short_doc or 'No description'}"
                for sub in command.commands
            )
            embed.add_field(name="Subcommands", value=subcommand_list, inline=False)
            
        await ctx.send(embed=embed)
