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

def _generate_level_card_cairo_sync(avatar_bytes, username, user_id, level, xp, xp_needed, 
                                   background_path=None, rank=None, status="online", 
                                   status_pos_x=80, status_pos_y=90):
    """Generate a Discord-style level card image using Cairo with memory optimizations"""
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
            # Create cache key based on the background path and dimensions
            bg_cache_key = f"bg:{background_path}_{width}x{height}"
            
            # Use cached background if available
            background_surface = BACKGROUND_CACHE.get(bg_cache_key)
            
            if background_surface is None:
                # Load the background
                background_surface = load_image_surface(background_path, width, height)
                
                # Cache for future use if valid
                if background_surface:
                    BACKGROUND_CACHE.set(bg_cache_key, background_surface)
                
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
    
    # Use template background if available and needed
    if use_default_background:
        # Use pre-rendered background
        bg_surface = TEMPLATE_CACHE.get('level_card_bg')
        if bg_surface:
            ctx.set_source_surface(bg_surface, 0, 0)
            ctx.paint()
        else:
            # Fallback to creating background on-the-fly
            initialize_template_cache()
            bg_surface = TEMPLATE_CACHE.get('level_card_bg')
            if bg_surface:
                ctx.set_source_surface(bg_surface, 0, 0)
                ctx.paint()
            else:
                # Emergency fallback - just use a solid color
                ctx.set_source_rgb(*background_color)
                ctx.rectangle(0, 0, width, height)
                ctx.fill()
    
    # Avatar settings
    avatar_size = 80
    avatar_pos_x = 10
    avatar_pos_y = height // 2 - avatar_size // 2  # Centered vertically
    
    # Draw avatar
    draw_default_avatar = True
    if avatar_bytes:
        try:
            # Use cached avatar surface if this exact avatar was used recently
            avatar_hash = hash(str(avatar_bytes))
            avatar_cache_key = f"avatar_{avatar_hash}"
            
            avatar_surface = TEMPLATE_CACHE.get(avatar_cache_key)
            
            if avatar_surface is None:
                # Load avatar from bytes
                avatar_io = io.BytesIO(avatar_bytes)
                avatar_surface = load_surface_from_bytes(avatar_io, avatar_size, avatar_size)
                
                # Cache the avatar surface
                if avatar_surface:
                    TEMPLATE_CACHE.set(avatar_cache_key, avatar_surface)
            
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
        # Use cached default avatar
        default_avatar = TEMPLATE_CACHE.get('default_avatar')
        if default_avatar:
            ctx.save()
            ctx.set_source_surface(default_avatar, avatar_pos_x, avatar_pos_y)
            ctx.paint()
            ctx.restore()
        else:
            # Emergency fallback - create a simple circle
            ctx.save()
            ctx.arc(avatar_pos_x + avatar_size/2, avatar_pos_y + avatar_size/2, avatar_size/2, 0, 2 * math.pi)
            ctx.set_source_rgb(80/255, 80/255, 80/255)
            ctx.fill()
            ctx.restore()
    
    # Status indicator
    status_colors = {
        "online": (67/255, 181/255, 129/255),
        "idle": (250/255, 166/255, 26/255),
        "dnd": (240/255, 71/255, 71/255),
        "offline": (116/255, 127/255, 141/255)
    }
    
    # Use cached status indicator
    status_cache_key = f"status_{status.lower()}"
    status_surface = TEMPLATE_CACHE.get(status_cache_key)
    
    if status_surface:
        status_size = status_surface.get_width()
        
        # Use original status position if provided, otherwise calculate based on avatar
        if status_pos_x == 80 and status_pos_y == 90:  # If using default values
            status_pos_x = avatar_pos_x + avatar_size - status_size/2
            status_pos_y = avatar_pos_y + avatar_size - status_size/2
        
        # Draw the cached status indicator
        ctx.set_source_surface(status_surface, status_pos_x - status_size/2, status_pos_y - status_size/2)
        ctx.paint()
    else:
        # Fallback - initialize status indicators and try again
        initialize_status_indicators()
        status_surface = TEMPLATE_CACHE.get(status_cache_key)
        
        if status_surface:
            status_size = status_surface.get_width()
            
            # Calculate position
            if status_pos_x == 80 and status_pos_y == 90:
                status_pos_x = avatar_pos_x + avatar_size - status_size/2
                status_pos_y = avatar_pos_y + avatar_size - status_size/2
            
            # Draw the status indicator
            ctx.set_source_surface(status_surface, status_pos_x - status_size/2, status_pos_y - status_size/2)
            ctx.paint()
        else:
            # Emergency fallback - draw a simple circle
            status_size = 18
            border_size = 2
            status_color = status_colors.get(status.lower(), status_colors["offline"])
            
            # Calculate position
            if status_pos_x == 80 and status_pos_y == 90:
                status_pos_x = avatar_pos_x + avatar_size - status_size/2
                status_pos_y = avatar_pos_y + avatar_size - status_size/2
            
            # Draw outer circle (border)
            ctx.arc(status_pos_x, status_pos_y, status_size/2, 0, 2 * math.pi)
            ctx.set_source_rgb(30/255, 30/255, 30/255)
            ctx.fill()
            
            # Draw inner circle (status color)
            ctx.arc(status_pos_x, status_pos_y, (status_size - border_size)/2, 0, 2 * math.pi)
            ctx.set_source_rgb(*status_color)
            ctx.fill()
    
    # XP bar settings
    xp_bar_width = width - (avatar_pos_x + avatar_size + 20) - 20  # 20px padding from right edge
    xp_bar_height = 15
    xp_bar_x = avatar_pos_x + avatar_size + 20
    xp_bar_y = height // 2 + 20
    
    # Detect script based on username
    detected_script = detect_script(username)
    
    # Is the text right-to-left?
    is_rtl = detected_script in ["Arabic", "Hebrew"]
    
    # Process with python-bidi for RTL text if needed
    display_username = bidi.algorithm.get_display(username) if is_rtl else username
    
    # Font sizes for all text elements
    username_font_size = 22
    small_font_size = 16
    rank_font_size = 26
    
    # Get appropriate fonts (using cached versions)
    username_font = get_font(detected_script, username_font_size)
    default_font = get_font(None, small_font_size)
    rank_font = get_font(None, rank_font_size)
    
    # Draw username - positioned just above the XP bar
    # Get username position
    username_y = xp_bar_y - 35
    username_width, _ = optimized_draw_text(
        ctx, 
        display_username, 
        xp_bar_x, 
        username_y, 
        script=detected_script,
        size=username_font_size, 
        rgb_color=text_color
    )
    
    # Draw user ID - aligned with username and always in English
    optimized_draw_text(
        ctx, 
        user_id, 
        xp_bar_x + username_width + 3, 
        username_y + (username_font_size - small_font_size)/2 + 3, 
        script=None,
        size=small_font_size, 
        rgb_color=(180/255, 180/255, 180/255)
    )
    
    # Set up values for rank and level
    # Use the passed rank if available, otherwise use default
    rank_value = rank if rank is not None else 44
    rank_text = f"#{rank_value}"
    level_text = str(level)
    
    # Get text dimensions using cached measurements
    rank_width, _ = measure_text_size(rank_text, rank_font)
    level_width, _ = measure_text_size(level_text, rank_font)
    rank_label_width, _ = measure_text_size("RANK", default_font)
    level_label_width, _ = measure_text_size("LEVEL", default_font)
    
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
    optimized_draw_text(
        ctx, 
        "RANK", 
        rank_label_x, 
        1 + small_font_size/2, 
        script=None,
        size=small_font_size, 
        rgb_color=(180/255, 180/255, 180/255)
    )
    
    # Draw rank value - always in English
    optimized_draw_text(
        ctx, 
        rank_text, 
        rank_value_x, 
        -15 + rank_font_size/2, 
        script=None,
        size=rank_font_size, 
        rgb_color=(1, 1, 1)
    )
    
    # Draw LEVEL label - always in English
    optimized_draw_text(
        ctx, 
        "LEVEL", 
        level_label_x, 
        1 + small_font_size/2, 
        script=None,
        size=small_font_size, 
        rgb_color=(180/255, 180/255, 180/255)
    )
    
    # Draw level value - always in English
    optimized_draw_text(
        ctx, 
        level_text, 
        level_value_x, 
        -15 + rank_font_size/2, 
        script=None,
        size=rank_font_size, 
        rgb_color=(1, 1, 1)
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
    xp_text_width, _ = measure_text_size(xp_text, default_font)
    
    optimized_draw_text(
        ctx, 
        xp_text, 
        xp_bar_x + xp_bar_width - xp_text_width, 
        xp_bar_y - 30, 
        script=None,
        size=small_font_size, 
        rgb_color=(180/255, 180/255, 180/255)
    )
    
    # Save to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    
    # Force garbage collection to clean up Cairo objects
    del surface
    del ctx
    
    return image_bytes

# Async wrapper for the Cairo level card generator
async def generate_level_card(member, level, xp, xp_needed, bot=None):
    """
    Generate a level card for a Discord member with optimized performance and memory management
    
    Parameters:
    - member: discord.Member object
    - level: User's current level
    - xp: User's current XP
    - xp_needed: XP needed for next level
    - bot: Optional bot instance for accessing the image thread pool
    
    Returns:
    - BytesIO: The generated level card image
    """
    # Get user's background if any
    guild_id = str(member.guild.id)
    user_id = str(member.id)
    
    start_time = time.time()
    
    try:
        # Get background path
        from database import get_user_background
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
        from database import get_user_rank
        rank = await get_user_rank(guild_id, user_id)
        
        # Get status
        status = "online"
        if hasattr(member, "status"):
            status = str(member.status)
        
        # Format user ID with # prefix
        user_id_display = f"#{user_id[-4:]}"
        
        # Get avatar using the cached avatar service
        from utils.avatar_cache import get_cached_avatar
        avatar_bytes = await get_cached_avatar(member)
        
        # Use bot's thread pool if available, otherwise use default executor
        if bot and hasattr(bot, 'image_thread_pool'):
            # Use dedicated thread pool for image generation
            result = await asyncio.get_event_loop().run_in_executor(
                bot.image_thread_pool,
                _generate_level_card_cairo_sync,
                avatar_bytes, 
                member.display_name,
                user_id_display,
                level, 
                xp, 
                xp_needed,
                background_path,
                rank,
                status
            )
        else:
            # Fall back to default executor if thread pool not available
            from utils.simple_image_handler import run_in_executor
            result = await run_in_executor(_generate_level_card_cairo_sync)(
                avatar_bytes, 
                member.display_name,
                user_id_display,
                level, 
                xp, 
                xp_needed,
                background_path,
                rank,
                status
            )
        
        # Log time taken for monitoring purposes
        elapsed = time.time() - start_time
        logging.debug(f"Level card generation took {elapsed:.2f} seconds for {member.display_name}")
        
        # Collect memory stats
        if elapsed > 0.5:  # Log stats for slow generations
            logging.info(f"Memory usage after card generation: {get_text_rendering_stats()}")
            
            # If generation took more than 1 second, suggest garbage collection
            if elapsed > 1.0:
                import gc
                gc.collect()
                logging.info("Forced garbage collection after slow card generation")
            
        return result
        
    except Exception as e:
        logging.error(f"Error generating level card: {e}", exc_info=True)
        # Create a simple error card
        return create_error_card(f"Error generating card: {str(e)}")

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
                avatar_load_tasks.append((user_id, get_cached_avatar(member)))
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