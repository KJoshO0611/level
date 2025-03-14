import asyncio
import logging
import discord
import io
import time
from concurrent.futures import ThreadPoolExecutor

# Configure the thread pool for image generation
# Adjust max_workers based on your server's CPU capacity
image_thread_pool = ThreadPoolExecutor(max_workers=2)

# Queue for tracking pending image generation tasks
# Structure: (future, context, message_to_update, start_time)
pending_images = []

async def start_image_processor(bot):
    """Start the background task for processing images"""
    bot.image_processor_running = True
    bot.loop.create_task(process_image_queue(bot))
    logging.info("Image processor background task started")

async def process_image_queue(bot):
    """Background task that processes the image generation queue"""
    while bot.image_processor_running:
        try:
            # Check for completed image futures
            now = time.time()
            completed = []
            
            for i, (future, ctx, message, start_time, image_type) in enumerate(pending_images):
                if future.done():
                    # Mark this task for removal from the queue
                    completed.append(i)
                    
                    try:
                        # Get the result (will raise exception if the future failed)
                        image_bytes = future.result()
                        
                        if image_bytes:
                            # Create a discord File object from the bytes
                            file = discord.File(image_bytes, filename=f"{image_type}.png")
                            
                            # Update the original message with the image
                            if message:
                                try:
                                    await message.edit(content=None, file=file)
                                except discord.HTTPException:
                                    # If editing fails (e.g., can't edit with attachments), send a new message
                                    await ctx.send(file=file)
                            else:
                                # No message to update, send a new one
                                await ctx.send(file=file)
                        else:
                            # Image generation failed
                            await ctx.send("❌ Failed to generate the image. Please try again.")
                    
                    except Exception as e:
                        logging.error(f"Error processing image result: {e}")
                        await ctx.send(f"❌ Error generating image: {str(e)}")
                    
                    # Log performance metrics
                    generation_time = now - start_time
                    logging.info(f"Image generation completed in {generation_time:.2f} seconds")
                
                # Check for timeouts (images taking too long)
                elif now - start_time > 60:  # 60 second timeout
                    completed.append(i)
                    future.cancel()  # Try to cancel the task
                    await ctx.send("⚠️ Image generation timed out. Please try again later.")
                    logging.warning(f"Image generation task timed out after {now - start_time:.2f} seconds")
            
            # Remove completed tasks from the queue (in reverse order to avoid index issues)
            for index in sorted(completed, reverse=True):
                if index < len(pending_images):
                    pending_images.pop(index)
            
            # Sleep briefly before checking again
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logging.error(f"Error in image queue processor: {e}")
            await asyncio.sleep(5)  # Back off on errors

async def queue_image_generation(ctx, generate_func, *args, **kwargs):
    """
    Queue an image generation task and return a placeholder message
    
    Parameters:
    - ctx: The Discord context
    - generate_func: The image generation function (must be async)
    - *args, **kwargs: Arguments to pass to the generator function
    
    Returns:
    - The placeholder message that will be updated when the image is ready
    """
    # Extract image_type from kwargs or use default
    image_type = kwargs.pop('image_type', 'image')
    
    # Create a placeholder loading message
    message = await ctx.send(f"🔄 Generating {image_type}... This may take a moment.")
    
    # First get the image bytes in the main thread using the async function
    try:
        # Call the async function directly in the main thread
        image_bytes = await generate_func(*args, **kwargs)
        
        # If successful, create a thread pool task to process the image
        # This is just a simple function that returns the bytes we already have
        def return_bytes():
            return image_bytes
            
        future = image_thread_pool.submit(return_bytes)
        
        # Add to pending queue for the processor to handle
        pending_images.append((future, ctx, message, time.time(), image_type))
        
    except Exception as e:
        logging.error(f"Error in queue_image_generation: {e}")
        await message.edit(content=f"❌ Error generating image: {str(e)}")
    
    return message