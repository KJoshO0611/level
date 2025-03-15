import discord
import io
import logging
import aiohttp
from utils.simple_image_handler import run_in_executor
from modules.databasev2 import get_user_rank, get_user_background
import cairo
import math
import os
import random
import tempfile
from PIL import Image
from config import load_config

# Load configuration
config = load_config()
FONT_PATH = config["PATHS"]["FONT_PATH"]
EXTERNAL_VOLUME_PATH = config.get("EXTERNAL_VOLUME_PATH", "/external_volume")

# Default colors
DEFAULT_BG_COLOR = (40/255, 40/255, 40/255)
DEFAULT_ACCENT_COLOR = (0/255, 200/255, 200/255)
DEFAULT_TEXT_COLOR = (255/255, 255/255, 255/255)

def load_image_surface(img_path, width=None, height=None):
    """Load an image into a Cairo surface"""
    try:
        img = Image.open(img_path).convert('RGBA')
        
        # Resize if specified
        if width and height:
            img = img.resize((width, height), Image.LANCZOS)
        
        # Save to temporary file - this is the most reliable way to convert PIL to Cairo surfaces
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            img.save(tmp.name)
            tmp_path = tmp.name
        
        # Load with Cairo
        surface = cairo.ImageSurface.create_from_png(tmp_path)
        
        # Clean up
        os.unlink(tmp_path)
        
        return surface
    except Exception as e:
        logging.error(f"Error loading image surface: {e}")
        return None

def load_surface_from_bytes(bytes_io, width=None, height=None):
    """Load an image from bytes into a Cairo surface"""
    try:
        img = Image.open(bytes_io).convert('RGBA')
        
        # Resize if specified
        if width and height:
            img = img.resize((width, height), Image.LANCZOS)
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            img.save(tmp.name)
            tmp_path = tmp.name
        
        # Load with Cairo
        surface = cairo.ImageSurface.create_from_png(tmp_path)
        
        # Clean up
        os.unlink(tmp_path)
        
        return surface
    except Exception as e:
        logging.error(f"Error loading image from bytes: {e}")
        return None

# Synchronous function to generate a level card using Cairo
def _generate_level_card_cairo_sync(avatar_bytes, username, user_id, level, xp, xp_needed, 
                                   background_path=None, rank=None, status="online", 
                                   status_pos_x=80, status_pos_y=90):
    """Generate a Discord-style level card image using Cairo"""
    # Default colors (no more card_settings object)
    background_color = DEFAULT_BG_COLOR
    accent_color = DEFAULT_ACCENT_COLOR
    text_color = DEFAULT_TEXT_COLOR
    background_opacity = 0.7
    
    # Card dimensions
    width, height = 500, 130
    
    # Create surface and context
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    
    # Fill with transparent background first
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    
    # Load and draw background if provided
    use_default_background = True
    if background_path and os.path.exists(background_path):
        try:
            background_surface = load_image_surface(background_path, width, height)
            if background_surface:
                ctx.save()
                ctx.set_source_surface(background_surface, 0, 0)
                ctx.paint_with_alpha(background_opacity)
                
                # Add a semi-transparent overlay to ensure text visibility
                ctx.set_source_rgba(30/255, 30/255, 30/255, 0.3)
                ctx.rectangle(0, 0, width, height)
                ctx.fill()
                
                ctx.restore()
                use_default_background = False
        except Exception as e:
            logging.error(f"Error loading background image: {e}")
            use_default_background = True
    
    # Create dark gradient background if needed
    if use_default_background:
        for y in range(height):
            # Dark gradient from top to bottom
            alpha = (180 - int(y * 0.5)) / 255.0
            ctx.set_source_rgba(background_color[0], background_color[1], background_color[2], alpha)
            ctx.move_to(0, y)
            ctx.line_to(width, y)
            ctx.stroke()
    
    # Add slight noise for texture (stars effect)
    for x in range(0, width, 3):
        for y in range(0, height, 3):
            if random.random() > 0.97:  # 3% chance for more stars
                alpha = random.randint(10, 50) / 255.0
                size = random.randint(1, 2)
                ctx.set_source_rgba(1, 1, 1, alpha)  # White color with random alpha
                ctx.arc(x + size/2, y + size/2, size/2, 0, 2 * math.pi)
                ctx.fill()
    
    # Avatar settings
    avatar_size = 80
    avatar_pos_x = 10
    avatar_pos_y = height // 2 - avatar_size // 2  # Centered vertically
    
    # Draw avatar
    draw_default_avatar = True
    if avatar_bytes:
        try:
            # Load avatar from bytes
            avatar_io = io.BytesIO(avatar_bytes)
            avatar_surface = load_surface_from_bytes(avatar_io, avatar_size, avatar_size)
            
            if avatar_surface:
                # Draw with circular mask
                ctx.save()
                
                # Create circular clipping path
                ctx.arc(avatar_pos_x + avatar_size/2, avatar_pos_y + avatar_size/2, 
                        avatar_size/2, 0, 2 * math.pi)
                ctx.clip()
                
                # Draw avatar
                ctx.set_source_surface(avatar_surface, avatar_pos_x, avatar_pos_y)
                ctx.paint()
                ctx.restore()
                
                # Add a thin border around avatar
                ctx.arc(avatar_pos_x + avatar_size/2, avatar_pos_y + avatar_size/2, 
                        avatar_size/2, 0, 2 * math.pi)
                ctx.set_source_rgb(80/255, 80/255, 80/255)
                ctx.set_line_width(2)
                ctx.stroke()
                
                draw_default_avatar = False
        except Exception as e:
            logging.error(f"Error processing avatar: {e}")
            draw_default_avatar = True
    
    # Draw default avatar if needed
    if draw_default_avatar:
        ctx.save()  # Save the current state
        ctx.translate(avatar_pos_x + avatar_size / 2, avatar_pos_y + avatar_size / 2)  # Move to center of avatar
        
        # Draw outer circle (gray)
        ctx.arc(0, 0, avatar_size / 2, 0, 2 * math.pi)
        ctx.set_source_rgb(80/255, 80/255, 80/255)  # Gray color
        ctx.fill()
        
        # Draw inner circle (white)
        border_width = 2
        ctx.arc(0, 0, (avatar_size - border_width) / 2, 0, 2 * math.pi)
        ctx.set_source_rgb(1, 1, 1)  # White color
        ctx.fill()
        
        ctx.restore()  # Restore the state
    
    # Status indicator
    status_colors = {
        "online": (67/255, 181/255, 129/255),
        "idle": (250/255, 166/255, 26/255),
        "dnd": (240/255, 71/255, 71/255),
        "offline": (116/255, 127/255, 141/255)
    }
    status_color = status_colors.get(status.lower(), status_colors["offline"])
    status_size = 18
    border_size = 2
    
    # Draw outer circle (border)
    ctx.arc(status_pos_x, status_pos_y, status_size/2, 0, 2 * math.pi)
    ctx.set_source_rgb(30/255, 30/255, 30/255)  # Dark color for border
    ctx.fill()
    
    # Draw inner circle (status color)
    ctx.arc(status_pos_x, status_pos_y, (status_size - border_size)/2, 0, 2 * math.pi)
    ctx.set_source_rgb(*status_color)  # Status color
    ctx.fill()
    
    # Set up fonts
    username_font_size = 22
    small_font_size = 16
    rank_font_size = 26
    
    # XP bar settings
    xp_bar_width = width - (avatar_pos_x + avatar_size + 20) - 20  # 20px padding from right edge
    xp_bar_height = 15
    xp_bar_x = avatar_pos_x + avatar_size + 20
    xp_bar_y = height // 2 + 20
    
    # Draw username - positioned just above the XP bar
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(username_font_size)
    ctx.set_source_rgb(*text_color)  # Use custom text color
    
    # New position - 8 pixels above the XP bar
    username_y = xp_bar_y - 8
    ctx.move_to(xp_bar_x, username_y)
    ctx.show_text(username)
    
    # Get text extents for proper positioning of user_id
    text_extents = ctx.text_extents(username)
    username_width = text_extents.width
    
    # Draw user ID - aligned with username
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(small_font_size)
    ctx.set_source_rgb(180/255, 180/255, 180/255)  # Gray color
    ctx.move_to(xp_bar_x + username_width + 5, username_y + (username_font_size - small_font_size)/2)
    ctx.show_text(user_id)
    
    # Set up font for measuring text
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(rank_font_size)
    
    # Calculate dynamic positions based on text widths
    # Use the passed rank if available, otherwise use default
    rank_value = rank if rank is not None else 44
    rank_text = f"#{rank_value}"
    level_text = str(level)
    
    # Get text dimensions
    rank_extents = ctx.text_extents(rank_text)
    level_extents = ctx.text_extents(level_text)
    
    # Set dynamic padding
    min_padding = 5  # Minimum padding between elements
    
    # Calculate positions from right to left
    current_x = width - 20  # Start from right edge with padding
    
    # Position for level value (rightmost element)
    level_value_x = current_x - level_extents.width
    current_x = level_value_x - min_padding
    
    # Position for "LEVEL" label
    ctx.set_font_size(small_font_size)
    level_label_extents = ctx.text_extents("LEVEL")
    level_label_x = current_x - level_label_extents.width
    current_x = level_label_x - min_padding * 2  # Extra padding between sections
    
    # Position for rank value
    ctx.set_font_size(rank_font_size)
    rank_value_x = current_x - rank_extents.width
    current_x = rank_value_x - min_padding
    
    # Position for "RANK" label
    ctx.set_font_size(small_font_size)
    rank_label_extents = ctx.text_extents("RANK")
    rank_label_x = current_x - rank_label_extents.width
    
    # Draw RANK label
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(small_font_size)
    ctx.set_source_rgb(180/255, 180/255, 180/255)  # Gray color
    ctx.move_to(rank_label_x, 25 + small_font_size/2)
    ctx.show_text("RANK")
    
    # Draw rank value
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(rank_font_size)
    ctx.set_source_rgb(1, 1, 1)  # White color
    ctx.move_to(rank_value_x, 20 + rank_font_size/2)
    ctx.show_text(rank_text)
    
    # Draw LEVEL label
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(small_font_size)
    ctx.set_source_rgb(180/255, 180/255, 180/255)  # Gray color
    ctx.move_to(level_label_x, 25 + small_font_size/2)
    ctx.show_text("LEVEL")
    
    # Draw level value
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(rank_font_size)
    ctx.set_source_rgb(1, 1, 1)  # White color
    ctx.move_to(level_value_x, 20 + rank_font_size/2)
    ctx.show_text(level_text)
    
    # Helper function to draw rounded rectangle
    def rounded_rectangle(ctx, x, y, width, height, radius):
        # Top left corner
        ctx.move_to(x + radius, y)
        # Top right corner
        ctx.line_to(x + width - radius, y)
        ctx.arc(x + width - radius, y + radius, radius, -math.pi/2, 0)
        # Bottom right corner
        ctx.line_to(x + width, y + height - radius)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, math.pi/2)
        # Bottom left corner
        ctx.line_to(x + radius, y + height)
        ctx.arc(x + radius, y + height - radius, radius, math.pi/2, math.pi)
        # Back to top left
        ctx.line_to(x, y + radius)
        ctx.arc(x + radius, y + radius, radius, math.pi, 3*math.pi/2)
        ctx.close_path()
    
    # XP bar background
    ctx.set_source_rgba(150/255, 150/255, 150/255, 140/255)
    rounded_rectangle(ctx, xp_bar_x, xp_bar_y, xp_bar_width, xp_bar_height, xp_bar_height//2)
    ctx.fill()
    
    # XP progress
    progress = min(1.0, float(xp) / float(xp_needed))
    if progress > 0:
        progress_width = int(xp_bar_width * progress)
        # Ensure minimum visible width
        progress_width = max(progress_width, xp_bar_height)
        
        ctx.set_source_rgba(1, 1, 1, 220/255)  # White with some transparency
        rounded_rectangle(ctx, xp_bar_x, xp_bar_y, progress_width, xp_bar_height, xp_bar_height//2)
        ctx.fill()
    
    # XP text
    xp_text = f"{xp}/{xp_needed} XP"
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(small_font_size)
    ctx.set_source_rgb(180/255, 180/255, 180/255)
    
    # Calculate text width for proper positioning
    text_extents = ctx.text_extents(xp_text)
    text_width = text_extents.width
    
    ctx.move_to(xp_bar_x + xp_bar_width - text_width, xp_bar_y - 5)
    ctx.show_text(xp_text)
    
    # Save to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    return image_bytes

# Async wrapper for the Cairo level card generator
# Replace the async wrapper for generate_level_card with this modified version
async def generate_level_card(member, level, xp, xp_needed):
    """Download avatar, get background, and generate level card using Cairo"""
    # Get user's background if any
    guild_id = str(member.guild.id)
    user_id = str(member.id)
    relative_path = await get_user_background(guild_id, user_id)
    
    # Convert relative path to full path if a background exists
    background_path = None
    if relative_path:
        background_path = os.path.join(EXTERNAL_VOLUME_PATH, relative_path)
        # Verify the file exists
        if not os.path.exists(background_path):
            logging.warning(f"Background file not found: {background_path}")
            background_path = None
    
    # Get user's rank if available
    rank = await get_user_rank(guild_id, user_id)
    
    # Get status
    status = "online"
    if hasattr(member, "status"):
        status = str(member.status)
    
    # Format user ID with # prefix
    user_id_display = f"#{user_id[-4:]}"
    
    # Download avatar
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            if resp.status == 200:
                avatar_bytes = await resp.read()
                
                # Run the synchronous Cairo part in a thread pool
                return await run_in_executor(_generate_level_card_cairo_sync)(
                    avatar_bytes, 
                    member.display_name,  # Use display_name instead of name
                    user_id_display,      # Pass formatted user ID
                    level, 
                    xp, 
                    xp_needed,
                    background_path,      # Use the full background path
                    rank,                 # Pass rank information
                    status                # Pass status
                )
            else:
                # If we can't get the avatar, still generate the card without it
                return await run_in_executor(_generate_level_card_cairo_sync)(
                    None,
                    member.display_name,
                    user_id_display,
                    level,
                    xp,
                    xp_needed,
                    background_path,
                    rank,
                    status
                )
    return None

# Synchronous function to generate a leaderboard using Cairo
def _generate_leaderboard_cairo_sync(guild_name, member_data, rows, start_rank=1):
    """Generate a leaderboard image using Cairo"""
    # Set image dimensions
    width = 800
    title_height = 80
    entry_height = 80
    entry_spacing = 20
    padding = 50
    height = title_height + (len(rows) * (entry_height + entry_spacing)) + padding
    
    # Create surface and context
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    
    # Fill with dark background
    ctx.set_source_rgb(30/255, 30/255, 30/255)
    ctx.paint()
    
    # Draw title
    ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(36)
    ctx.set_source_rgb(1, 1, 1)  # White
    
    title_text = f"{guild_name} Leaderboard"
    # Get text extents for centering
    text_extents = ctx.text_extents(title_text)
    title_x = (width - text_extents.width) / 2
    ctx.move_to(title_x, 50)
    ctx.show_text(title_text)
    
    # Rank colors
    rank_colors = {
        1: (255/255, 215/255, 0/255),     # Gold
        2: (192/255, 192/255, 192/255),   # Silver
        3: (205/255, 127/255, 50/255)     # Bronze
    }
    
    # Helper function to draw rounded rectangle
    def rounded_rectangle(ctx, x, y, width, height, radius):
        # Top left corner
        ctx.move_to(x + radius, y)
        # Top right corner
        ctx.line_to(x + width - radius, y)
        ctx.arc(x + width - radius, y + radius, radius, -math.pi/2, 0)
        # Bottom right corner
        ctx.line_to(x + width, y + height - radius)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, math.pi/2)
        # Bottom left corner
        ctx.line_to(x + radius, y + height)
        ctx.arc(x + radius, y + height - radius, radius, math.pi/2, math.pi)
        # Back to top left
        ctx.line_to(x, y + radius)
        ctx.arc(x + radius, y + radius, radius, math.pi, 3*math.pi/2)
        ctx.close_path()
    
    # Draw entries
    y_offset = title_height
    avatar_size = 50
    text_x_offset = 120
    rect_radius = 20
    
    for i, (user_id, xp, level) in enumerate(rows):
        rank = start_rank + i
        
        # Get user data
        username = "Unknown User"
        avatar_bytes = None
        
        if user_id in member_data:
            username, avatar_bytes = member_data[user_id]
        
        # Rectangle position
        rect_x1, rect_y1 = 40, y_offset
        rect_x2, rect_y2 = width - 40, y_offset + entry_height
        
        # Draw rounded rectangle for this entry
        ctx.set_source_rgb(50/255, 50/255, 50/255)
        rounded_rectangle(ctx, rect_x1, rect_y1, rect_x2 - rect_x1, rect_y2 - rect_y1, rect_radius)
        ctx.fill()
        
        # Draw avatar
        avatar_position = (50, y_offset + 15)
        try:
            if avatar_bytes:
                # Process avatar with circular mask
                avatar_io = io.BytesIO(avatar_bytes)
                avatar_surface = load_surface_from_bytes(avatar_io, avatar_size, avatar_size)
                
                # Draw with circular mask
                ctx.save()
                ctx.arc(avatar_position[0] + avatar_size//2, avatar_position[1] + avatar_size//2, 
                        avatar_size//2, 0, 2 * math.pi)
                ctx.clip()
                ctx.set_source_surface(avatar_surface, avatar_position[0], avatar_position[1])
                ctx.paint()
                ctx.restore()
                
                # Add a circle border
                ctx.arc(avatar_position[0] + avatar_size//2, avatar_position[1] + avatar_size//2, 
                        avatar_size//2, 0, 2 * math.pi)
                ctx.set_source_rgb(80/255, 80/255, 80/255)
                ctx.set_line_width(2)
                ctx.stroke()
            else:
                # Placeholder circle
                ctx.arc(avatar_position[0] + avatar_size//2, avatar_position[1] + avatar_size//2, 
                        avatar_size//2, 0, 2 * math.pi)
                ctx.set_source_rgb(80/255, 80/255, 80/255)
                ctx.fill()
        except Exception as e:
            logging.error(f"Error processing avatar for leaderboard entry: {e}")
            # Fallback to gray circle
            ctx.arc(avatar_position[0] + avatar_size//2, avatar_position[1] + avatar_size//2, 
                    avatar_size//2, 0, 2 * math.pi)
            ctx.set_source_rgb(80/255, 80/255, 80/255)
            ctx.fill()
        
        # Draw rank with appropriate color
        ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(30)
        
        rank_color = rank_colors.get(rank, (1, 1, 1))  # Default to white if not top 3
        ctx.set_source_rgb(*rank_color)
        
        rank_text = f"#{rank}"
        ctx.move_to(text_x_offset, y_offset + 45)
        ctx.show_text(rank_text)
        
        # Get text width to know where to start the username
        rank_text_extents = ctx.text_extents(rank_text)
        
        # Draw username
        ctx.set_source_rgb(1, 1, 1)  # White
        user_text = f" | {username} | LVL: {level}"
        ctx.move_to(text_x_offset + rank_text_extents.width, y_offset + 45)
        ctx.show_text(user_text)
        
        y_offset += entry_height + entry_spacing
    
    # Save to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    return image_bytes

# Async wrapper for the leaderboard generator
async def generate_leaderboard_image(guild, rows, start_rank=1):
    """Download avatars and generate leaderboard using Cairo"""
    # Prepare member data
    member_data = {}
    
    # Download all member avatars first
    async with aiohttp.ClientSession() as session:
        for user_id, _, _ in rows:
            member = guild.get_member(int(user_id))
            if member:
                try:
                    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
                    async with session.get(avatar_url) as resp:
                        if resp.status == 200:
                            avatar_bytes = await resp.read()
                            member_data[user_id] = (member.display_name, avatar_bytes)
                except Exception as e:
                    logging.error(f"Error downloading avatar for {user_id}: {e}")
                    member_data[user_id] = (member.display_name, None)
            else:
                member_data[user_id] = (f"User {user_id}", None)
    
    # Generate the image in a thread using Cairo
    return await run_in_executor(_generate_leaderboard_cairo_sync)(
        guild.name, member_data, rows, start_rank
    )