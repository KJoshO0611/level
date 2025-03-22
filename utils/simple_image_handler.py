import discord
import logging
from concurrent.futures import ThreadPoolExecutor
import asyncio
import functools
import time

# Set up a thread pool for handling image generation
# Adjust max_workers based on your server capacity
image_thread_pool = ThreadPoolExecutor(max_workers=2)
pending_tasks = {}

async def generate_image_nonblocking(ctx, image_type="image"):
    """
    Send a loading message and return a context for non-blocking image generation
    
    Returns:
        tuple: (message, completion_event)
        - message: The loading message that will be updated with the image
        - completion_event: An asyncio event to signal when ready to update
    """
    # Apply rate limiting
    user_id = str(ctx.author.id)
    guild_id = str(ctx.guild.id) if ctx.guild else "DM"

    # Check user rate limit
    is_limited, wait_time = await ctx.bot.rate_limiters["image"].check_rate_limit(user_id)
    if is_limited:
        await ctx.send(f"⏱️ Image generation limit reached. Please wait {wait_time} seconds.", delete_after=10)
        return None, None
    
    # Check guild rate limit (10 images per minute per guild)
    is_guild_limited, guild_wait = await ctx.bot.rate_limiters["guild"].check_rate_limit(f"img:{guild_id}")
    if is_guild_limited:
        await ctx.send("⚠️ This server has reached its image generation limit. Please try again later.", delete_after=10)
        return None, None    

    # Create and send a loading message
    message = await ctx.send(f"🔄 Generating {image_type}... This may take a moment.")
    
    # Create a completion event to signal when the image is ready
    completion_event = asyncio.Event()
    
    # Store in pending tasks with timestamp
    task_id = f"{ctx.guild.id}:{ctx.channel.id}:{message.id}"
    pending_tasks[task_id] = {
        "message": message,
        "event": completion_event,
        "start_time": time.time(),
        "image_type": image_type
    }
    
    return message, completion_event

async def update_with_image(message, image_bytes, image_type="image"):
    """
    Update a message with an image once it's generated
    """
    if image_bytes:
        try:
            # Create a discord File object
            file = discord.File(image_bytes, filename=f"{image_type}.png")
            
            # For Discord.py, we can't edit a message to add a file
            # So we delete the original message and send a new one
            try:
                channel = message.channel
                await message.delete()
                await channel.send(file=file)
            except Exception as e:
                # If that fails for any reason, just send a new message
                await message.channel.send(file=file)
        except Exception as e:
            logging.error(f"Error updating message with image: {e}")
            await message.edit(content=f"❌ Error with image: {str(e)}")
    else:
        await message.edit(content="❌ Failed to generate image. Please try again.")

def run_in_executor(func):
    """
    Decorator to run a synchronous function in a thread pool executor.
    This prevents blocking the main event loop.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Get event loop
        loop = asyncio.get_event_loop()
        
        # Use partial to bind the arguments
        pfunc = functools.partial(func, *args, **kwargs)
        
        # Run in executor and return the result
        return await loop.run_in_executor(image_thread_pool, pfunc)
    
    return wrapper