"""
Utility functions for command handling and message management.
"""
import functools
import logging
import discord
from discord.ext import commands

def auto_delete_command():
    """
    Decorator for command callbacks that automatically deletes the invoking message.
    
    Usage:
        @commands.command()
        @auto_delete_command()
        async def my_command(self, ctx):
            # Command implementation
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            try:
                # Try to delete the command message first
                await ctx.message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
                logging.debug(f"Could not delete command message: {e}")
            except Exception as e:
                logging.warning(f"Unexpected error when trying to delete command message: {e}")
            
            # Call the original command function
            return await func(self, ctx, *args, **kwargs)
        return wrapper
    return decorator 