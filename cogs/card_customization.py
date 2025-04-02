import discord
from discord.ext import commands
import os
import aiohttp
import logging
from database import set_user_background, get_user_background, remove_user_background
from config import load_config
from utils.rate_limiter import rate_limit
from utils.command_utils import auto_delete_command

# Load the external volume path from config
config = load_config()
# This should be added to your config.py or config.json file
EXTERNAL_VOLUME_PATH = config.get("EXTERNAL_VOLUME_PATH", "/external_volume")
BACKGROUNDS_DIR = os.path.join(EXTERNAL_VOLUME_PATH, "backgrounds")

class BackgroundCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Ensure backgrounds directory exists
        os.makedirs(BACKGROUNDS_DIR, exist_ok=True)
        logging.info(f"Using background directory: {BACKGROUNDS_DIR}")

    @commands.command(name="setbackground", aliases=["setbg"])
    @rate_limit(calls=3, period=60)  # 3 calls per minute per user 
    @auto_delete_command()
    async def set_background(self, ctx, *, url: str = None):
        """Set a custom background for your level card. Upload an image or provide a URL."""
        # Check if an image was attached
        if not url and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        
        if not url:
            await ctx.send("Please provide a URL or attach an image for your custom background!", delete_after=10)
            return
        
        # Download and save the image
        try:
            # Create a unique filename based on user ID
            guild_id = str(ctx.guild.id)
            user_id = str(ctx.author.id)
            file_ext = url.split('.')[-1].lower()
            
            # Validate extension
            if file_ext not in ['png', 'jpg', 'jpeg', 'gif']:
                file_ext = 'png'  # Default to png if unrecognized
                
            # Create directory structure if it doesn't exist
            guild_dir = os.path.join(BACKGROUNDS_DIR, guild_id)
            os.makedirs(guild_dir, exist_ok=True)
            
            # Create a meaningful filename
            filename = f"{user_id}.{file_ext}"
            file_path = os.path.join(guild_dir, filename)
            
            # Download the image
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await ctx.send("Failed to download the image. Please try another image URL.", delete_after=10)
                        return
                    
                    # Save the image
                    with open(file_path, 'wb') as f:
                        f.write(await resp.read())
            
            # Save to database - store the path relative to EXTERNAL_VOLUME_PATH
            # This makes it portable if the external volume gets mounted elsewhere
            relative_path = os.path.relpath(file_path, EXTERNAL_VOLUME_PATH)
            success = await set_user_background(guild_id, user_id, relative_path)
            
            if success:
                embed = discord.Embed(
                    title="Background Set",
                    description="Your custom level card background has been set!",
                    color=discord.Color.green()
                )
                embed.set_image(url=url)
                await ctx.send(embed=embed)
            else:
                await ctx.send("There was an error setting your background. Please try again later.", delete_after=10)
                
        except Exception as e:
            logging.error(f"Error setting background: {e}")
            await ctx.send("Failed to set your background. Please try again with a different image.", delete_after=10)

    @commands.command(name="removebackground", aliases=["removebg", "resetbg"])
    @rate_limit(calls=3, period=60)  # 3 calls per minute per user
    @auto_delete_command()
    async def remove_background(self, ctx):
        """Remove your custom level card background."""
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        # Get current background path
        relative_path = await get_user_background(guild_id, user_id)
        
        if not relative_path:
            await ctx.send("You don't have a custom background set!", delete_after=10)
            return
        
        # Delete file if it exists
        try:
            full_path = os.path.join(EXTERNAL_VOLUME_PATH, relative_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                logging.info(f"Removed background file: {full_path}")
        except Exception as e:
            logging.error(f"Error removing background file: {e}")
        
        # Remove from database
        success = await remove_user_background(guild_id, user_id)
        
        if success:
            await ctx.send("Your custom background has been removed!", delete_after=10)
        else:
            await ctx.send("There was an error removing your background. Please try again later.", delete_after=10)

    @commands.command(name="showbackground", aliases=["showbg", "mybg"])
    @rate_limit(calls=3, period=60)  # 3 calls per minute per user
    @auto_delete_command()
    async def show_background(self, ctx, member: discord.Member = None):
        """Show the current background for your level card or another member's."""
        member = member or ctx.author
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        
        # Get background path
        relative_path = await get_user_background(guild_id, user_id)
        
        if not relative_path:
            await ctx.send(f"{member.mention} doesn't have a custom background set!", delete_after=10)
            return
        
        # Get full path
        full_path = os.path.join(EXTERNAL_VOLUME_PATH, relative_path)
        
        if not os.path.exists(full_path):
            await ctx.send(f"Background file not found! The file may have been moved or deleted.", delete_after=10)
            return
        
        # Show the background
        try:
            file = discord.File(full_path, filename="background.png")
            embed = discord.Embed(
                title=f"{member.display_name}'s Background",
                color=discord.Color.blue()
            )
            embed.set_image(url="attachment://background.png")
            await ctx.send(file=file, embed=embed)
        except Exception as e:
            logging.error(f"Error showing background: {e}")
            await ctx.send("An error occurred while trying to show the background image.", delete_after=10)

def setup(bot):
    bot.add_cog(BackgroundCommands(bot))