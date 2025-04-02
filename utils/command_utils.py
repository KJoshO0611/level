"""
Utility functions for command handling and message management.
"""
import functools
import logging
import discord
from discord.ext import commands

def auto_delete_command():
    """
    A decorator for text commands that automatically attempts to delete 
    the message that triggered the command.
    
    This keeps chat channels cleaner and reduces command spam.
    
    Example usage:
        @commands.command(name="example")
        @auto_delete_command()
        async def example_command(self, ctx):
            # Command implementation
            pass
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            # Try to delete the message, but don't stop execution if it fails
            try:
                # Check if the message exists and can be deleted
                if ctx.message and hasattr(ctx.message, "delete"):
                    await ctx.message.delete()
            except discord.errors.NotFound:
                # Message already deleted, just log and continue
                logging.debug(f"Command message already deleted: {ctx.command}")
            except discord.errors.Forbidden:
                # Missing permissions to delete the message
                logging.warning(f"Missing permissions to delete command message for: {ctx.command}")
            except Exception as e:
                # Log any other errors but let the command continue
                logging.warning(f"Error deleting command message for {ctx.command}: {str(e)}")
            
            # Execute the original command function
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator 