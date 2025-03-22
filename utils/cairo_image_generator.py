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
from PIL import Image, ImageFont, ImageDraw
from config import load_config
import bidi.algorithm
import unicodedata
import re

# Load configuration
config = load_config()
#FONT_PATH = config["PATHS"]["FONT_PATH"]
EXTERNAL_VOLUME_PATH = config.get("EXTERNAL_VOLUME_PATH", "/external_volume")

# Font paths - update these to match your system
FONT_PATHS = {
    'default': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSans-Regular.ttf'),
    'arabic': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSansArabic-Regular.ttf'),
    'cjk': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSansCJK-Regular.ttc'),
    'cyrillic': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSans-Regular.ttf'),
    'devanagari': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSansDevanagari-Regular.ttf'),
    'thai': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSansThai-Regular.ttf'),
    'hebrew': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSansHebrew-Regular.ttf'),
    'baybayin': os.path.join(EXTERNAL_VOLUME_PATH, 'fonts/NotoSansTagalog-Regular.ttf')
}

# Default colors
DEFAULT_BG_COLOR = (40/255, 40/255, 40/255)
DEFAULT_ACCENT_COLOR = (0/255, 200/255, 200/255)
DEFAULT_TEXT_COLOR = (255/255, 255/255, 255/255)

def detect_script(text):
    """
    Detect the script of the given text.
    Returns the detected script name (Arabic, CJK, Cyrillic, etc.)
    """
    # Define Unicode ranges for different scripts
    script_ranges = {
        'Arabic': [
            (0x0600, 0x06FF),  # Arabic
            (0x0750, 0x077F),  # Arabic Supplement
            (0x08A0, 0x08FF),  # Arabic Extended-A
        ],
        'CJK': [
            (0x4E00, 0x9FFF),  # CJK Unified Ideographs
            (0x3040, 0x309F),  # Hiragana
            (0x30A0, 0x30FF),  # Katakana
            (0x3130, 0x318F),  # Hangul Compatibility Jamo
            (0xAC00, 0xD7AF),  # Hangul Syllables
        ],
        'Cyrillic': [
            (0x0400, 0x04FF),  # Cyrillic
            (0x0500, 0x052F),  # Cyrillic Supplement
        ],
        'Devanagari': [
            (0x0900, 0x097F),  # Devanagari
        ],
        'Thai': [
            (0x0E00, 0x0E7F),  # Thai
        ],
        'Hebrew': [
            (0x0590, 0x05FF),  # Hebrew
        ],
        'Baybayin': [
            (0x1700, 0x171F),  # Tagalog (Baybayin) script block
        ],
        'Latin': [
            (0x0020, 0x007F),  # Basic Latin
            (0x00A0, 0x00FF),  # Latin-1 Supplement
            (0x0100, 0x017F),  # Latin Extended-A
            (0x0180, 0x024F),  # Latin Extended-B
        ]
    }
    
    # Count characters in each script
    script_counts = {script: 0 for script in script_ranges}
    
    for char in text:
        code_point = ord(char)
        for script, ranges in script_ranges.items():
            for start, end in ranges:
                if start <= code_point <= end:
                    script_counts[script] += 1
                    break
    
    # Find script with most characters
    max_script = max(script_counts.items(), key=lambda x: x[1])
    
    # If no script detected or mostly Latin, return None
    if max_script[1] == 0 or max_script[0] == 'Latin':
        return None
    
    return max_script[0]

def measure_text_size(text, font):
    """Measure text dimensions using PIL"""
    # Use PIL's getbbox for text measurement
    bbox = font.getbbox(text)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    return text_width, text_height

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
        print(f"Error loading image surface: {e}")
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
        print(f"Error loading image from bytes: {e}")
        return None

def draw_text_with_pil(ctx, text, x, y, pil_font, rgb_color=(1, 1, 1), centered=False):
    """
    Draw text using PIL for font handling and Cairo for rendering
    
    Parameters:
    - ctx: Cairo context
    - text: Text to draw
    - x, y: Position to draw text
    - pil_font: PIL ImageFont object
    - rgb_color: RGB color tuple in range 0-1
    - centered: If True, center the text at (x,y)
    """
    # Measure text using PIL
    text_width, text_height = measure_text_size(text, pil_font)
    
    # Calculate position for centered text if needed
    position_x = x
    position_y = y
    if centered:
        position_x = x - text_width // 2
        position_y = y - text_height // 2
    
    # Convert the text to a temporary PIL image with transparency
    # This is needed because Cairo cannot directly use PIL fonts
    temp_img = Image.new('RGBA', (text_width + 10, text_height + 20), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    temp_draw.text((5, 5), text, font=pil_font, fill=(255, 255, 255, 255))
    
    # Create a numpy array from the PIL image
    import numpy as np
    arr = np.array(temp_img)
    
    # Create a Cairo surface from the numpy array
    h, w, _ = arr.shape
    
    # Create temporary Cairo surface to hold the text
    text_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    text_ctx = cairo.Context(text_surface)
    
    # Cairo uses ARGB format, PIL uses RGBA - we need to swap the channels
    # Extract alpha channel and RGB channels
    alpha = arr[:, :, 3] / 255.0
    r = arr[:, :, 0] / 255.0
    g = arr[:, :, 1] / 255.0
    b = arr[:, :, 2] / 255.0
    
    # Apply the color tint
    r = r * rgb_color[0]
    g = g * rgb_color[1]
    b = b * rgb_color[2]
    
    # For each pixel, set the color and alpha
    for y_pos in range(h):
        for x_pos in range(w):
            a = alpha[y_pos, x_pos]
            text_ctx.set_source_rgba(r[y_pos, x_pos], g[y_pos, x_pos], b[y_pos, x_pos], a)
            text_ctx.rectangle(x_pos, y_pos, 1, 1)
            text_ctx.fill()
    
    # Draw the text surface on the main surface
    ctx.set_source_surface(text_surface, position_x, position_y)
    ctx.paint()
    
    return text_width, text_height

# Synchronous function to generate a level card using Cairo
def _generate_level_card_cairo_sync(avatar_bytes, username, user_id, level, xp, xp_needed, 
                                   background_path=None, rank=None, status="online", 
                                   status_pos_x=80, status_pos_y=90):
    """Generate a Discord-style level card image using Cairo"""
    # Default colors
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
            print(f"Error loading background image: {e}")
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
            print(f"Error processing avatar: {e}")
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
    
    # Use original status position if provided, otherwise calculate based on avatar
    if status_pos_x == 80 and status_pos_y == 90:  # If using default values
        status_pos_x = avatar_pos_x + avatar_size - status_size/2
        status_pos_y = avatar_pos_y + avatar_size - status_size/2
    
    # Draw outer circle (border)
    ctx.arc(status_pos_x, status_pos_y, status_size/2, 0, 2 * math.pi)
    ctx.set_source_rgb(30/255, 30/255, 30/255)  # Dark color for border
    ctx.fill()
    
    # Draw inner circle (status color)
    ctx.arc(status_pos_x, status_pos_y, (status_size - border_size)/2, 0, 2 * math.pi)
    ctx.set_source_rgb(*status_color)  # Status color
    ctx.fill()
    
    # XP bar settings
    xp_bar_width = width - (avatar_pos_x + avatar_size + 20) - 20  # 20px padding from right edge
    xp_bar_height = 15
    xp_bar_x = avatar_pos_x + avatar_size + 20
    xp_bar_y = height // 2 + 20
    
    # Detect script based on username
    detected_script = detect_script(username)
    
    # Select appropriate font based on script
    font_path = FONT_PATHS['default']
    is_rtl = False
    
    if detected_script:
        if detected_script == "Arabic" or detected_script == "Hebrew":
            is_rtl = True
            if detected_script == "Arabic":
                font_path = FONT_PATHS['arabic']
            else:  # Hebrew
                font_path = FONT_PATHS['hebrew']
        elif detected_script == "CJK":
            font_path = FONT_PATHS['cjk']
        elif detected_script == "Cyrillic":
            font_path = FONT_PATHS['cyrillic']
        elif detected_script == "Devanagari":
            font_path = FONT_PATHS['devanagari']
        elif detected_script == "Thai":
            font_path = FONT_PATHS['thai']
        elif detected_script == "Baybayin":
            font_path = FONT_PATHS['baybayin']
    
    # Process with python-bidi for RTL text if needed
    display_username = username
    if is_rtl:
        display_username = bidi.algorithm.get_display(username)
    
    # Font sizes for all text elements
    username_font_size = 22
    small_font_size = 16
    rank_font_size = 26
    
    # Create PIL fonts
    username_pil_font = ImageFont.truetype(font_path, username_font_size)
    # Use default font for all English labels
    default_pil_font = ImageFont.truetype(FONT_PATHS['default'], small_font_size)
    rank_pil_font = ImageFont.truetype(FONT_PATHS['default'], rank_font_size)
    
    # Draw username - positioned just above the XP bar
    # Get username position
    username_y = xp_bar_y - 35
    # Draw username with appropriate font
    draw_text_with_pil(ctx, display_username, xp_bar_x, username_y, username_pil_font, text_color)
    
    # Get text extents for proper positioning of user_id
    username_width, _ = measure_text_size(display_username, username_pil_font)
    
    # Draw user ID - aligned with username and always in English
    draw_text_with_pil(
        ctx, 
        user_id, 
        xp_bar_x + username_width + 3, 
        username_y + (username_font_size - small_font_size)/2 + 3, 
        default_pil_font, 
        (180/255, 180/255, 180/255)
    )
    
    # Set up values for rank and level
    # Use the passed rank if available, otherwise use default
    rank_value = rank if rank is not None else 44
    rank_text = f"#{rank_value}"
    level_text = str(level)
    
    # Get text dimensions using PIL
    rank_width, _ = measure_text_size(rank_text, rank_pil_font)
    level_width, _ = measure_text_size(level_text, rank_pil_font)
    rank_label_width, _ = measure_text_size("RANK", default_pil_font)
    level_label_width, _ = measure_text_size("LEVEL", default_pil_font)
    
    # Set dynamic padding
    min_padding = 5  # Minimum padding between elements
    
    # Calculate positions from right to left
    current_x = width - 20  # Start from right edge with padding
    
    # Position for level value (rightmost element)
    level_value_x = current_x - level_width
    current_x = level_value_x - min_padding
    
    # Position for "LEVEL" label
    level_label_x = current_x - level_label_width
    current_x = level_label_x - min_padding * 2  # Extra padding between sections
    
    # Position for rank value
    rank_value_x = current_x - rank_width
    current_x = rank_value_x - min_padding
    
    # Position for "RANK" label
    rank_label_x = current_x - rank_label_width
    
    # Draw RANK label - always in English
    draw_text_with_pil(
        ctx, 
        "RANK", 
        rank_label_x, 
        1 + small_font_size/2, 
        default_pil_font, 
        (180/255, 180/255, 180/255)
    )
    
    # Draw rank value - always in English
    draw_text_with_pil(
        ctx, 
        rank_text, 
        rank_value_x, 
        -15 + rank_font_size/2, 
        rank_pil_font, 
        (1, 1, 1)
    )
    
    # Draw LEVEL label - always in English
    draw_text_with_pil(
        ctx, 
        "LEVEL", 
        level_label_x, 
        1 + small_font_size/2, 
        default_pil_font, 
        (180/255, 180/255, 180/255)
    )
    
    # Draw level value - always in English
    draw_text_with_pil(
        ctx, 
        level_text, 
        level_value_x, 
        -15 + rank_font_size/2, 
        rank_pil_font, 
        (1, 1, 1)
    )
    
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
    
    # XP text - always in English
    xp_text = f"{xp}/{xp_needed} XP"
    xp_text_width, _ = measure_text_size(xp_text, default_pil_font)
    
    draw_text_with_pil(
        ctx, 
        xp_text, 
        xp_bar_x + xp_bar_width - xp_text_width, 
        xp_bar_y - 30, 
        default_pil_font, 
        (180/255, 180/255, 180/255)
    )
    
    # Add a subtle indicator for which script we detected (for debugging/testing)
    if detected_script:
        script_indicator = f"{detected_script}"
        indicator_width, _ = measure_text_size(script_indicator, default_pil_font)
        draw_text_with_pil(
            ctx,
            script_indicator,
            width - indicator_width - 5,
            height - 15,
            default_pil_font,
            (100/255, 100/255, 100/255)
        )
    
    # Save to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    return image_bytes

# Async wrapper for the Cairo level card generator
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
    
    avatar_url = None
    # Try to get server-specific (guild) avatar first
    if hasattr(member, 'guild_avatar') and member.guild_avatar:
        avatar_url = member.guild_avatar.url
    # Then fall back to global avatar
    elif member.avatar:
        avatar_url = member.avatar.url
    # Finally, use default avatar as last resort
    else:
        avatar_url = member.default_avatar.url

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
    
    # Create PIL fonts
    title_font_size = 36
    name_font_size = 27
    level_font_size = 22
    small_font_size = 18
    
    # Use default font for title and labels
    title_pil_font = ImageFont.truetype(FONT_PATHS['default'], title_font_size)
    level_pil_font = ImageFont.truetype(FONT_PATHS['default'], level_font_size)
    small_pil_font = ImageFont.truetype(FONT_PATHS['default'], small_font_size)
    
    # Draw title
    title_text = f"{guild_name} Leaderboard"
    title_width, _ = measure_text_size(title_text, title_pil_font)
    title_x = (width - title_width) / 2
    
    draw_text_with_pil(
        ctx,
        title_text,
        title_x,
        50 - title_font_size/2,
        title_pil_font,
        (1, 1, 1)  # White
    )
    
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
    y_offset = title_height + 5
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
            print(f"Error processing avatar for leaderboard entry: {e}")
            # Fallback to gray circle
            ctx.arc(avatar_position[0] + avatar_size//2, avatar_position[1] + avatar_size//2, 
                    avatar_size//2, 0, 2 * math.pi)
            ctx.set_source_rgb(80/255, 80/255, 80/255)
            ctx.fill()
        
        # Draw rank with appropriate color
        rank_color = rank_colors.get(rank, (1, 1, 1))  # Default to white if not top 3
        rank_text = f"#{rank}"
        
        # Create a PIL font for the rank
        rank_pil_font = ImageFont.truetype(FONT_PATHS['default'], name_font_size)
        
        # Draw the rank
        draw_text_with_pil(
            ctx,
            rank_text,
            text_x_offset,
            y_offset + 35 - name_font_size/2,
            rank_pil_font,
            rank_color
        )
        
        # Get rank text width for positioning the username
        rank_text_width, _ = measure_text_size(rank_text, rank_pil_font)
        username_x = text_x_offset + rank_text_width + 10  # Add some spacing
        
        # Detect script and create appropriate font for username
        detected_script = detect_script(username)
        username_font_path = FONT_PATHS['default']
        is_rtl = False
        
        # Select appropriate font based on script
        if detected_script:
            if detected_script == "Arabic" or detected_script == "Hebrew":
                is_rtl = True
                if detected_script == "Arabic":
                    username_font_path = FONT_PATHS['arabic']
                else:  # Hebrew
                    username_font_path = FONT_PATHS['hebrew']
            elif detected_script == "CJK":
                username_font_path = FONT_PATHS['cjk']
            elif detected_script == "Cyrillic":
                username_font_path = FONT_PATHS['cyrillic']
            elif detected_script == "Devanagari":
                username_font_path = FONT_PATHS['devanagari']
            elif detected_script == "Thai":
                username_font_path = FONT_PATHS['thai']
            elif detected_script == "Baybayin":
                username_font_path = FONT_PATHS['baybayin']
        
        # Process RTL text if needed
        display_username = username
        if is_rtl:
            display_username = bidi.algorithm.get_display(username)
        
        # Create font for username with appropriate script support
        username_pil_font = ImageFont.truetype(username_font_path, name_font_size)
        
        # Draw the username
        draw_text_with_pil(
            ctx,
            display_username,
            username_x,
            y_offset + 35 - name_font_size/2,
            username_pil_font,
            (1, 1, 1)  # White
        )
        
        # Get username width to position level info
        username_width, _ = measure_text_size(display_username, username_pil_font)
        
        # Draw level text
        level_text = f" | LVL: {level}"
        draw_text_with_pil(
            ctx,
            level_text,
            username_x + username_width,
            y_offset + 35 - level_font_size/2,
            level_pil_font,
            (200/255, 200/255, 1)  # Light blue
        )
        
        # Add script indicator for testing
        script_text = f"Script: {detected_script or 'Latin'}"
        script_width, _ = measure_text_size(script_text, small_pil_font)
        draw_text_with_pil(
            ctx,
            script_text,
            width - 50 - script_width,
            y_offset + 65 - small_font_size/2,
            small_pil_font,
            (150/255, 150/255, 150/255)  # Light gray
        )
        
        # Move to next entry
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