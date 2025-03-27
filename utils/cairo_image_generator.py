import discord
import io
import re
import os
import cairo
import math
import time
import random
import weakref
import logging
import aiohttp
import asyncio
import os.path
import tempfile
import functools
import threading
import unicodedata
import bidi.algorithm
from config import load_config
from PIL import Image, ImageFont, ImageDraw
from utils.memory_cache import MemoryAwareCache
from utils.avatar_cache import get_cached_avatar
from utils.simple_image_handler import run_in_executor
from database import get_user_rank, get_user_background
from utils.background_api import BackgroundAPI

# Thread-safe LRU cache with TTL
class TTLCache:
    def __init__(self, maxsize=128, ttl=3600):
        self.cache = {}  # {key: (value, timestamp)}
        self.maxsize = maxsize
        self.ttl = ttl
        self.lock = threading.RLock()
        self._cleanup_counter = 0
    
    def get(self, key):
        with self.lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                # If expired, remove it
                del self.cache[key]
        return None
    
    def set(self, key, value):
        with self.lock:
            # Occasional cleanup to prevent memory leaks
            self._cleanup_counter += 1
            if self._cleanup_counter >= 100:
                self._cleanup()
                self._cleanup_counter = 0
            
            # If we're at capacity, remove the oldest items
            if len(self.cache) >= self.maxsize:
                # Sort by timestamp and remove oldest 10%
                oldest = sorted(self.cache.items(), key=lambda x: x[1][1])[:max(1, self.maxsize // 10)]
                for old_key, _ in oldest:
                    del self.cache[old_key]
            
            # Add the new item
            self.cache[key] = (value, time.time())
    
    def _cleanup(self):
        """Remove expired items"""
        current_time = time.time()
        expired_keys = [k for k, (_, ts) in self.cache.items() if current_time - ts > self.ttl]
        for k in expired_keys:
            del self.cache[k]

#cache
# Initialize memory-aware caches with appropriate limits
FONT_CACHE = MemoryAwareCache(
    name="font_cache", 
    maxsize=50, 
    max_memory_mb=10,  # Fonts are relatively small
    ttl=3600,          # 1 hour TTL
    weak_refs=False    # Fonts should be kept in memory
)

TEXT_MEASURE_CACHE = MemoryAwareCache(
    name="text_measure_cache", 
    maxsize=1000, 
    max_memory_mb=5,   # Text measurements are very small
    ttl=3600,          # 1 hour TTL
    weak_refs=False    # Measurements are simple tuples, keep in memory
)

# Script detection cache - remembers script of usernames # 24 hour TTL for script cache
SCRIPT_CACHE = MemoryAwareCache(
    name="script_cache", 
    maxsize=500, 
    max_memory_mb=2,   # Script detection results are tiny
    ttl=3600*24,       # 24 hour TTL
    weak_refs=False    # Script info is just strings, keep in memory
)

# Text measurement cache - stores width/height for specific text+font combinations
TEMPLATE_CACHE = MemoryAwareCache(
    name="template_cache", 
    maxsize=100, 
    max_memory_mb=50,  # Templates can be larger (Cairo surfaces)
    ttl=3600*2,        # 2 hour TTL
    weak_refs=True     # Use weak references for large Cairo surfaces
)
 
# Add a dedicated cache for user backgrounds
BACKGROUND_CACHE = MemoryAwareCache(
    name="background_cache", 
    maxsize=200, 
    max_memory_mb=100, # Backgrounds are larger images
    ttl=3600*3,        # 3 hour TTL
    weak_refs=True     # Use weak references for large images
)

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

@functools.lru_cache(maxsize=32)
def get_pil_font(font_path, size):
    """Cache PIL fonts to avoid reloading them"""
    if not os.path.exists(font_path):
        # Fallback to default font if the specific one doesn't exist
        font_path = FONT_PATHS['default']
    return ImageFont.truetype(font_path, size)

def get_text_rendering_stats():
    """Get statistics about text rendering caches"""
    return {
        "font_cache": FONT_CACHE.stats(),
        "text_measure_cache": TEXT_MEASURE_CACHE.stats(),
        "script_cache": SCRIPT_CACHE.stats(),
        "template_cache": TEMPLATE_CACHE.stats(),
        "background_cache": BACKGROUND_CACHE.stats(),
    }

def detect_script(text):
    """
    Detect the script of the given text.
    Returns the detected script name (Arabic, CJK, Cyrillic, etc.)
    """
    # Check cache first
    cached_script = SCRIPT_CACHE.get(text)
    if cached_script is not None:
        return cached_script
    
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

    # Only check the first 20 characters for performance
    check_text = text[:20]

    for char in check_text:
        code_point = ord(char)
        for script, ranges in script_ranges.items():
            for start, end in ranges:
                if start <= code_point <= end:
                    script_counts[script] += 1
                    break
    
    # Find script with most characters
    max_script = max(script_counts.items(), key=lambda x: x[1])
    
    # If no script detected or mostly Latin, return None
    result = None if max_script[1] == 0 or max_script[0] == 'Latin' else max_script[0]
    
    # Cache the result
    SCRIPT_CACHE.set(text, result)
    
    return result

def get_font(script, size, bold=False):
    """
    Get a PIL font for the specified script and size with caching
    """
    # Create a cache key based on parameters
    cache_key = f"{script}:{size}:{bold}"
    
    # Check cache first
    cached_font = FONT_CACHE.get(cache_key)
    if cached_font is not None:
        return cached_font
    
    # Select appropriate font based on script
    font_path = FONT_PATHS['default']
    
    if script:
        if script == "Arabic":
            font_path = FONT_PATHS['arabic']
        elif script == "Hebrew":
            font_path = FONT_PATHS['hebrew']
        elif script == "CJK":
            font_path = FONT_PATHS['cjk']
        elif script == "Cyrillic":
            font_path = FONT_PATHS['cyrillic']
        elif script == "Devanagari":
            font_path = FONT_PATHS['devanagari']
        elif script == "Thai":
            font_path = FONT_PATHS['thai']
        elif script == "Baybayin":
            font_path = FONT_PATHS['baybayin']
    
    try:
        # Load font from path
        pil_font = ImageFont.truetype(font_path, size)
        
        # Cache the loaded font
        FONT_CACHE.set(cache_key, pil_font)
        
        return pil_font
    except Exception as e:
        # Fallback to default font if there's an error
        logging.error(f"Error loading font {font_path}: {e}")
        try:
            pil_font = ImageFont.truetype(FONT_PATHS['default'], size)
            FONT_CACHE.set(cache_key, pil_font)
            return pil_font
        except:
            # Last resort - use default PIL font
            return ImageFont.load_default()

def measure_text_size(text, font):
    """
    Measure text dimensions using PIL with caching
    """
    # Create a cache key - use font object's id as a proxy for its identity
    cache_key = f"{text}:{id(font)}"
    
    # Check cache first
    cached_size = TEXT_MEASURE_CACHE.get(cache_key)
    if cached_size is not None:
        return cached_size
    
    # Measure text using PIL's getbbox
    try:
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Cache the result
        TEXT_MEASURE_CACHE.set(cache_key, (text_width, text_height))
        
        return text_width, text_height
    except Exception as e:
        logging.error(f"Error measuring text '{text}': {e}")
        # Return a reasonable default
        return (len(text) * font.size // 2, font.size)

def prerender_text_image(text, font, rgb_color=(1, 1, 1)):
    """
    Pre-render text to a PIL image for better performance
    """
    # Measure text to create appropriately sized image
    text_width, text_height = measure_text_size(text, font)
    
    # Add padding to prevent clipping
    padding = max(10, text_height // 4)
    img_width = text_width + padding * 2
    img_height = text_height + padding * 2
    
    # Convert RGB floats (0-1) to RGB ints (0-255)
    rgb_int = (int(rgb_color[0] * 255), int(rgb_color[1] * 255), int(rgb_color[2] * 255))
    
    # Create a transparent image
    img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw text at the padded position
    draw.text((padding, padding), text, font=font, fill=(*rgb_int, 255))
    
    return img, text_width, text_height

def initialize_status_indicators():
    """Pre-render all status indicators at module load time"""
    status_colors = {
        "online": (67/255, 181/255, 129/255),
        "idle": (250/255, 166/255, 26/255),
        "dnd": (240/255, 71/255, 71/255),
        "offline": (116/255, 127/255, 141/255)
    }
    status_size = 18
    border_size = 2
    
    # Create each status indicator once
    for status, color in status_colors.items():
        # Create a new surface for this indicator
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, status_size, status_size)
        ctx = cairo.Context(surface)
        
        # Fill with transparency first
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        
        # Draw outer circle (border)
        ctx.arc(status_size/2, status_size/2, status_size/2, 0, 2 * math.pi)
        ctx.set_source_rgb(30/255, 30/255, 30/255)  # Dark color for border
        ctx.fill()
        
        # Draw inner circle (status color)
        ctx.arc(status_size/2, status_size/2, (status_size - border_size)/2, 0, 2 * math.pi)
        ctx.set_source_rgb(*color)  # Status color
        ctx.fill()
        
        # Store in cache with unique key
        TEMPLATE_CACHE.set(f'status_{status}', surface)
        
    logging.info("Pre-rendered status indicators for online, idle, dnd, and offline states")

def optimized_draw_text(ctx, text, x, y, script=None, size=22, rgb_color=(1, 1, 1), centered=False):
    """
    Optimized text drawing function that handles script detection and text positioning
    """
    # Detect script if not provided
    if script is None:
        script = detect_script(text)
    
    # Check if RTL processing is needed
    is_rtl = script in ("Arabic", "Hebrew")
    
    # Process RTL text if needed
    display_text = bidi.algorithm.get_display(text) if is_rtl else text
    
    # Get font for this script and size
    font = get_font(script, size)
    
    # Measure text
    text_width, text_height = measure_text_size(display_text, font)
    
    # Calculate position based on alignment
    pos_x, pos_y = x, y
    if centered:
        pos_x = x - text_width // 2
        pos_y = y - text_height // 2
    
    # Pre-render text to PIL image
    text_img, _, _ = prerender_text_image(display_text, font, rgb_color)
    
    # Convert PIL image to Cairo surface
    return draw_text_with_pil(ctx, display_text, pos_x, pos_y, font, rgb_color, centered)

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

# Pre-render common elements at module load time
def initialize_template_cache():
    """Pre-render common elements like background gradients, frames, etc."""
    # Level card background template
    width, height = 500, 130
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    
    # Create dark gradient background 
    for y in range(height):
        # Dark gradient from top to bottom
        alpha = (180 - int(y * 0.5)) / 255.0
        ctx.set_source_rgba(DEFAULT_BG_COLOR[0], DEFAULT_BG_COLOR[1], DEFAULT_BG_COLOR[2], alpha)
        ctx.move_to(0, y)
        ctx.line_to(width, y)
        ctx.stroke()
    
    # Add some noise for texture
    for x in range(0, width, 3):
        for y in range(0, height, 3):
            if random.random() > 0.97:  # 3% chance
                alpha = random.randint(10, 50) / 255.0
                size = random.randint(1, 2)
                ctx.set_source_rgba(1, 1, 1, alpha)
                ctx.arc(x + size/2, y + size/2, size/2, 0, 2 * math.pi)
                ctx.fill()
    
    # Store in cache
    TEMPLATE_CACHE.set('level_card_bg', surface)

# Call initialization during module import
initialize_template_cache()

def rounded_rectangle(ctx, x, y, width, height, radius):
    """Helper function to draw rounded rectangle in Cairo"""
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

def draw_placeholder_badge(ctx, badge_x, badge_y, badge_size):
    """Draw a placeholder star when badge image cannot be loaded"""
    # Draw star inside
    ctx.set_source_rgb(1, 1, 1)
    star_size = badge_size * 0.6
    center_x = badge_x + badge_size/2
    center_y = badge_y + badge_size/2
    
    # Draw a simple star
    points = 5
    outer_radius = star_size/2
    inner_radius = outer_radius/2
    
    ctx.move_to(center_x, center_y - outer_radius)
    
    for i in range(points * 2):
        radius = inner_radius if i % 2 else outer_radius
        angle = math.pi * i / points - math.pi/2
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        ctx.line_to(x, y)
    
    ctx.close_path()
    ctx.fill()

def _generate_level_card_cairo_sync(avatar_bytes, username, user_id, level, xp, xp_needed, 
                                   background_path=None, rank=None, status="online", 
                                   status_pos_x=80, status_pos_y=90,
                                   achievements=None, selected_title=None):
    """
    Synchronous function to generate a Discord-style level card with Cairo
    Includes achievement badges and title display
    """
    # Default colors
    background_color = DEFAULT_BG_COLOR
    accent_color = DEFAULT_ACCENT_COLOR
    text_color = DEFAULT_TEXT_COLOR
    background_opacity = 0.7
    
    # Card dimensions
    width, height = 500, 180 # More compact height for cleaner design
    
    # Calculate space optimization for no badges/title
    has_completed_achievements = achievements and any(a.get("completed", False) for a in achievements)
    has_title = selected_title is not None
    
    # We'll adjust height and positions later based on these flags

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
            logging.info(f"Loading background from path: {background_path}")
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
                logging.info(f"Successfully loaded background image for user")
        except Exception as e:
            logging.error(f"Error loading background image: {e}")
            use_default_background = True
    elif background_path:
        logging.warning(f"Background path was provided but file doesn't exist: {background_path}")
    
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
    avatar_size = 90
    avatar_pos_x = 10
    avatar_pos_y = height // 1.6 - avatar_size // 2  # Centered vertically
    
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
    
    # XP bar settings - dynamic position based on content
    xp_bar_width = width - (avatar_pos_x + avatar_size + 20) - 20  # 20px padding from right edge
    xp_bar_height = 15
    xp_bar_x = avatar_pos_x + avatar_size + 20
    
    # Position XP bar based on whether badges/titles are present
    if not has_completed_achievements and not has_title:
        # If no badges or titles, position lower (more space at bottom)
        xp_bar_y = avatar_pos_y + avatar_size / 2 + 20  # Lower position when no content below
    else:
        # If badges or titles exist, position higher to make room for content below
        xp_bar_y = avatar_pos_y + avatar_size / 3 - 10  # Higher position for content below
    
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
    title_font_size = 14
    rank_font_size = 26
    
    # Create PIL fonts
    username_pil_font = get_pil_font(font_path, username_font_size)
    # Use default font for all English labels
    default_pil_font = get_pil_font(FONT_PATHS['default'], small_font_size)
    title_pil_font = get_pil_font(FONT_PATHS['default'], title_font_size)
    rank_pil_font = get_pil_font(FONT_PATHS['default'], rank_font_size)
    
    # Draw username - positioned just above the XP bar
    # Get username position
    username_y = xp_bar_y - 35  # Consistent spacing above XP bar
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
        10 + small_font_size/2, 
        default_pil_font, 
        (180/255, 180/255, 180/255)
    )
    
    # Draw rank value - always in English
    draw_text_with_pil(
        ctx, 
        rank_text, 
        rank_value_x, 
        -5 + rank_font_size/2, 
        rank_pil_font, 
        (1, 1, 1)
    )
    
    # Draw LEVEL label - always in English
    draw_text_with_pil(
        ctx, 
        "LEVEL", 
        level_label_x, 
        10 + small_font_size/2, 
        default_pil_font, 
        (180/255, 180/255, 180/255)
    )
    
    # Draw level value - always in English
    draw_text_with_pil(
        ctx, 
        level_text, 
        level_value_x, 
        -5 + rank_font_size/2, 
        rank_pil_font, 
        (1, 1, 1)
    )
    
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
        xp_bar_y - 25,  # Consistent spacing above XP bar
        default_pil_font, 
        (180/255, 180/255, 180/255)
    )
    
    # Draw mini achievement badges below XP bar (left side)
    if achievements:
        # Get completed achievements only
        completed_achievements = [a for a in achievements if a.get("completed", False)]
        
        # Only proceed if we have completed achievements
        if completed_achievements:
            mini_badge_size = 20
            mini_badge_spacing = 8
            mini_badges_x = avatar_pos_x + avatar_size + 20
            mini_badges_y = xp_bar_y + xp_bar_height
            
            # Move down for badges
            mini_badges_y = xp_bar_y + xp_bar_height + 15
            
            # If no title is selected but user has achievements, get a default title
            if selected_title is None:
                # Use the name of the first completed achievement as title by default
                selected_title = f"«{completed_achievements[0]['name']}»"
            
            # Draw title if available - position it between XP bar and achievements
            title_y = xp_bar_y + xp_bar_height + 10  # Just below XP bar
            if selected_title:
                # Draw a subtle background for the title
                title_width, title_height = measure_text_size(selected_title, title_pil_font)
                title_bg_padding = 8
                
                ctx.set_source_rgba(*accent_color, 0.3)  # Semi-transparent accent color
                rounded_rectangle(
                    ctx,
                    mini_badges_x - title_bg_padding/2,
                    title_y - title_bg_padding/2,
                    title_width + title_bg_padding,
                    title_height + title_bg_padding,
                    5  # Small radius for rounded corners
                )
                ctx.fill()
                
                # Draw the title text
                draw_text_with_pil(
                    ctx,
                    selected_title,
                    mini_badges_x - 5,
                    title_y - 10,  # Move up slightly to center properly
                    title_pil_font,
                    (1, 1, 1)  # White color
                )
                
                # Adjust the badges position to be below the title
                mini_badges_y = title_y + title_height + 10
            
            badge_count = min(len(completed_achievements), 10)  # Show max 10 mini badges
            
            # Draw mini achievement badges in a single row
            for i in range(badge_count):
                achievement = completed_achievements[i]
                badge_x = mini_badges_x + (i * (mini_badge_size + mini_badge_spacing))
                
                # Draw badge rounded square background
                radius = mini_badge_size / 5  # smaller radius for more square-like appearance
                rounded_rectangle(ctx, badge_x, mini_badges_y, mini_badge_size, mini_badge_size, radius)
                ctx.set_source_rgb(*accent_color)
                ctx.fill()
                
                # Try to load and draw the actual badge image from icon_path
                try:
                    if "icon_path" in achievement and achievement["icon_path"]:
                        # Construct the full path to the badge
                        badge_path = achievement["icon_path"]
                        # If the path is relative, join with EXTERNAL_VOLUME_PATH
                        if badge_path and not os.path.isabs(badge_path):
                            badge_path = os.path.join(EXTERNAL_VOLUME_PATH, badge_path)
                            
                        if os.path.exists(badge_path):
                            # Load the badge image
                            badge_surface = load_image_surface(badge_path, mini_badge_size, mini_badge_size)
                            
                            if badge_surface:
                                # Draw the badge image
                                ctx.save()
                                
                                # Create rounded square clipping path
                                rounded_rectangle(ctx, badge_x, mini_badges_y, mini_badge_size, mini_badge_size, radius)
                                ctx.clip()
                                
                                # Draw badge
                                ctx.set_source_surface(badge_surface, badge_x, mini_badges_y)
                                ctx.paint()
                                ctx.restore()
                            else:
                                # Fallback to drawing a placeholder if loading fails
                                draw_placeholder_badge(ctx, badge_x, mini_badges_y, mini_badge_size)
                        else:
                            # Fallback to drawing a placeholder if file doesn't exist
                            logging.debug(f"Badge file not found: {badge_path}")
                            draw_placeholder_badge(ctx, badge_x, mini_badges_y, mini_badge_size)
                    else:
                        # Fallback to drawing a placeholder if no icon_path
                        draw_placeholder_badge(ctx, badge_x, mini_badges_y, mini_badge_size)
                except Exception as e:
                    logging.error(f"Error loading badge image: {e}")
                    # Fallback to drawing a placeholder if loading fails
                    draw_placeholder_badge(ctx, badge_x, mini_badges_y, mini_badge_size)
        elif selected_title:  # Handle case where there's a title but no badges
            # Draw title only
            mini_badges_x = avatar_pos_x + avatar_size + 20
            title_y = xp_bar_y + xp_bar_height + 10  # Just below XP bar
            
            # Draw a subtle background for the title
            title_width, title_height = measure_text_size(selected_title, title_pil_font)
            title_bg_padding = 8
            
            ctx.set_source_rgba(*accent_color, 0.3)  # Semi-transparent accent color
            rounded_rectangle(
                ctx,
                mini_badges_x - title_bg_padding/2,
                title_y - title_bg_padding/2,
                title_width + title_bg_padding,
                title_height + title_bg_padding,
                5  # Small radius for rounded corners
            )
            ctx.fill()
            
            # Draw the title text
            draw_text_with_pil(
                ctx,
                selected_title,
                mini_badges_x - 5,
                title_y - 10,  # Move up slightly to center properly
                title_pil_font,
                (1, 1, 1)  # White color
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

async def generate_level_card(member, level, xp, xp_needed, bot=None):
    """
    Asynchronously generate a level card for a Discord member
    
    This version includes achievements and title display.
    """
    try:
        # Get member information
        username = member.display_name
        user_id = f"#{member.discriminator}" if member.discriminator != "0" else ""
        guild_id = str(member.guild.id)
        
        # Determine user status
        if isinstance(member, discord.Member):
            status = str(member.status)
        else:
            status = "offline"
        
        # Get user rank
        try:
            rank = await get_user_rank(guild_id, str(member.id))
        except Exception as e:
            logging.error(f"Error getting user rank: {e}")
            rank = None

        # Get user background
        background_path = await get_user_background(guild_id, str(member.id))
        
        # Convert relative path to full path if we have a valid background path
        if background_path:
            try:
                # Try to use BackgroundAPI's helper function if available
                full_path = await BackgroundAPI.get_background_full_path(guild_id, str(member.id))
                if full_path:
                    background_path = full_path
                    logging.info(f"Using background at full path (via API): {background_path}")
                else:
                    # Fall back to manual path joining
                    background_path = os.path.join(EXTERNAL_VOLUME_PATH, background_path)
                    logging.info(f"Using background at path (manual join): {background_path}")
            except Exception as e:
                # Fall back to manual path joining if import fails
                background_path = os.path.join(EXTERNAL_VOLUME_PATH, background_path)
                logging.info(f"Using background at path (fallback): {background_path}")
        
        # Get user achievements
        from database import get_user_achievements_db, get_user_selected_title_db
        try:
            achievements = await get_user_achievements_db(guild_id, str(member.id))
            # Fix: Use the correct key for achievements (completed instead of achievements)
            achievements_list = achievements.get("completed", [])
        except Exception as e:
            logging.error(f"Error getting user achievements: {e}")
            achievements_list = []
            
        # Get user selected title
        try:
            selected_title = await get_user_selected_title_db(guild_id, str(member.id))
        except Exception as e:
            logging.error(f"Error getting user selected title: {e}")
            selected_title = None
            
        # Format title with quotes if set
        if selected_title:
            selected_title = f"«{selected_title}»"

        # Get avatar from cache or fetch it
        avatar_bytes = await get_cached_avatar(member, bot)
         
        # Generate the card in a thread pool - this operation is CPU-bound
        image_bytes = await run_in_executor(_generate_level_card_cairo_sync)(
            avatar_bytes, username, user_id, level, xp, xp_needed,
            background_path, rank, status, 80, 90,
            achievements_list, selected_title  # Pass achievements and title
        )

        return image_bytes
        
    except Exception as e:
        logging.error(f"Error generating level card: {e}")
        return create_error_card(f"Error generating level card: {e}")

def create_error_card(error_message):
    """Create a simple error card when level card generation fails"""
    width, height = 500, 130
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    
    # Red background
    ctx.set_source_rgb(0.8, 0.1, 0.1)
    ctx.rectangle(0, 0, width, height)
    ctx.fill()
    
    # White text
    font = get_font(None, 18)
    optimized_draw_text(
        ctx,
        "Error Generating Level Card",
        width / 2,
        30,
        size=18,
        rgb_color=(1, 1, 1),
        centered=True
    )
    
    # Error details
    lines = []
    current_line = ""
    for word in error_message.split():
        test_line = current_line + " " + word if current_line else word
        if measure_text_size(test_line, font)[0] < (width - 40):
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    
    # Draw each line
    y_pos = 60
    for line in lines:
        optimized_draw_text(
            ctx,
            line,
            width / 2,
            y_pos,
            size=14,
            rgb_color=(1, 1, 1),
            centered=True
        )
        y_pos += 20
    
    # Save to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    
    # Clean up Cairo resources
    del surface
    del ctx
    
    return image_bytes

# Synchronous function to generate a leaderboard using Cairo
def _generate_leaderboard_cairo_sync(guild_name, member_data, rows, start_rank=1):
    """
    Generate a leaderboard image using Cairo with memory optimizations
    
    Parameters:
    - guild_name: Name of the Discord guild
    - member_data: Dictionary of {user_id: (username, avatar_bytes)}
    - rows: List of tuples containing (user_id, xp, level)
    - start_rank: Starting rank number (for pagination)
    
    Returns:
    - BytesIO: The generated leaderboard image
    """
    try:
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
        
        # Font sizes
        title_font_size = 36
        name_font_size = 27
        level_font_size = 22
        small_font_size = 18
        
        # Use our font cache for fonts
        title_font = get_font(None, title_font_size)
        level_font = get_font(None, level_font_size)
        small_font = get_font(None, small_font_size)
        
        # Draw title
        title_text = f"{guild_name} Leaderboard"
        title_width, _ = measure_text_size(title_text, title_font)
        title_x = (width - title_width) / 2
        
        optimized_draw_text(
            ctx,
            title_text,
            title_x,
            50 - title_font_size/2,
            script=None,
            size=title_font_size,
            rgb_color=(1, 1, 1)  # White
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
        
        # Cache for avatar surfaces to avoid redundant processing
        avatar_surfaces = {}
        
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
                    # Check if we've already processed this avatar
                    avatar_hash = hash(str(avatar_bytes))
                    avatar_key = f"lb_avatar_{avatar_hash}"
                    
                    # Try to get from cache first
                    avatar_surface = TEMPLATE_CACHE.get(avatar_key)
                    
                    if avatar_surface is None:
                        # Process avatar with circular mask
                        avatar_io = io.BytesIO(avatar_bytes)
                        avatar_surface = load_surface_from_bytes(avatar_io, avatar_size, avatar_size)
                        
                        # Cache the processed avatar
                        if avatar_surface:
                            TEMPLATE_CACHE.set(avatar_key, avatar_surface)
                    
                    if avatar_surface:
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
                        raise Exception("Failed to create avatar surface")
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
            rank_color = rank_colors.get(rank, (1, 1, 1))  # Default to white if not top 3
            rank_text = f"#{rank}"
            
            # Draw the rank
            optimized_draw_text(
                ctx,
                rank_text,
                text_x_offset,
                y_offset + 35 - name_font_size/2,
                script=None,
                size=name_font_size,
                rgb_color=rank_color
            )
            
            # Get rank text width for positioning the username
            rank_text_width, _ = measure_text_size(rank_text, get_font(None, name_font_size))
            username_x = text_x_offset + rank_text_width + 10  # Add some spacing
            
            # Detect script for username
            detected_script = detect_script(username)
            is_rtl = detected_script in ["Arabic", "Hebrew"]
            
            # Process RTL text if needed
            display_username = bidi.algorithm.get_display(username) if is_rtl else username
            
            # Draw the username with proper font for the script
            optimized_draw_text(
                ctx,
                display_username,
                username_x,
                y_offset + 35 - name_font_size/2,
                script=detected_script,
                size=name_font_size,
                rgb_color=(1, 1, 1)  # White
            )
            
            # Get username width to position level info
            username_width, _ = measure_text_size(display_username, get_font(detected_script, name_font_size))
            
            # Draw level text
            level_text = f" | LVL: {level}"
            optimized_draw_text(
                ctx,
                level_text,
                username_x + username_width,
                y_offset + 35 - level_font_size/2,
                script=None,
                size=level_font_size,
                rgb_color=(200/255, 200/255, 1)  # Light blue
            )
            
            # Move to next entry
            y_offset += entry_height + entry_spacing
        
        # Save to bytes
        image_bytes = io.BytesIO()
        surface.write_to_png(image_bytes)
        image_bytes.seek(0)
        
        # Clean up resources explicitly
        del surface
        del ctx
        
        return image_bytes
    
    except Exception as e:
        logging.error(f"Error in _generate_leaderboard_cairo_sync: {e}", exc_info=True)
        # Return a simple error image
        return create_error_image(f"Error generating leaderboard: {str(e)}")

def create_error_image(error_message):
    """Create a simple error image when leaderboard generation fails"""
    width, height = 800, 300
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    
    # Red background
    ctx.set_source_rgb(0.8, 0.1, 0.1)
    ctx.rectangle(0, 0, width, height)
    ctx.fill()
    
    # White text
    font = get_font(None, 24)
    optimized_draw_text(
        ctx,
        "Error Generating Leaderboard",
        width / 2,
        50,
        size=24,
        rgb_color=(1, 1, 1),
        centered=True
    )
    
    # Error details
    lines = []
    current_line = ""
    for word in error_message.split():
        test_line = current_line + " " + word if current_line else word
        if measure_text_size(test_line, font)[0] < (width - 80):
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    
    # Draw each line
    y_pos = 100
    for line in lines:
        optimized_draw_text(
            ctx,
            line,
            width / 2,
            y_pos,
            size=18,
            rgb_color=(1, 1, 1),
            centered=True
        )
        y_pos += 30
    
    # Add suggestion
    optimized_draw_text(
        ctx,
        "Please try again or contact the server administrator.",
        width / 2,
        height - 50,
        size=18,
        rgb_color=(1, 1, 1),
        centered=True
    )
    
    # Save to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    
    # Clean up
    del surface
    del ctx
    
    return image_bytes

# Async wrapper for the leaderboard generator
async def generate_leaderboard_image(guild, rows, start_rank=1):
    """
    Download avatars and generate leaderboard using Cairo with memory optimization
    
    Parameters:
    - guild: The Discord guild object
    - rows: List of tuples containing (user_id, xp, level)
    - start_rank: Starting rank number (for pagination)
    
    Returns:
    - BytesIO: The generated leaderboard image
    """
    start_time = time.time()
    
    try:
        # Prepare member data with optimized avatar loading
        member_data = {}
        avatar_load_tasks = []
        
        # Create tasks for parallel avatar loading
        for user_id, _, _ in rows:
            member = guild.get_member(int(user_id))
            if member:
                # Add a task to load the avatar asynchronously
                avatar_load_tasks.append((user_id, get_cached_avatar(member, None)))
                # Initialize the member name, we'll add the avatar later
                member_data[user_id] = (member.display_name, None)
            else:
                member_data[user_id] = (f"User {user_id}", None)
        
        # Wait for all avatar loading tasks to complete
        for user_id, avatar_task in avatar_load_tasks:
            try:
                avatar_bytes = await avatar_task
                if user_id in member_data:
                    member_data[user_id] = (member_data[user_id][0], avatar_bytes)
            except Exception as e:
                logging.error(f"Error loading avatar for {user_id}: {e}")
                # Keep the existing entry with None avatar
        
        # Generate the image in a thread
        result = await run_in_executor(_generate_leaderboard_cairo_sync)(
            guild.name, member_data, rows, start_rank
        )
        
        # Log time taken for monitoring
        elapsed = time.time() - start_time
        logging.debug(f"Leaderboard generation took {elapsed:.2f} seconds")
        
        # Collect memory stats for slow generations
        if elapsed > 1.0:
            logging.info(f"Memory usage after leaderboard generation: {get_text_rendering_stats()}")
            
            # If generation was particularly slow, force garbage collection
            if elapsed > 2.0:
                import gc
                gc.collect()
                logging.info("Forced garbage collection after slow leaderboard generation")
        
        return result
        
    except Exception as e:
        logging.error(f"Error generating leaderboard: {e}", exc_info=True)
        return create_error_image(f"Error generating leaderboard: {str(e)}")