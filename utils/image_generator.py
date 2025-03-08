import discord
import aiohttp
import io
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError, ImageFilter
from config import load_config

config = load_config()
FONT_PATH = config["PATHS"]["FONT_PATH"]

# Helper function for rounded rectangles
def rounded_rectangle(draw, bounds, radius, fill):
    """Draw a rounded rectangle"""
    x1, y1, x2, y2 = bounds
    
    # Check if the rectangle has valid dimensions
    if x2 <= x1 or y2 <= y1:
        return  # Skip drawing if dimensions are invalid
    
    # Ensure radius isn't too large for the rectangle
    radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    
    if radius > 0:  # Only draw rounded corners if radius is positive
        draw.pieslice((x1, y1, x1 + radius * 2, y1 + radius * 2), 180, 270, fill=fill)
        draw.pieslice((x2 - radius * 2, y1, x2, y1 + radius * 2), 270, 360, fill=fill)
        draw.pieslice((x2 - radius * 2, y2 - radius * 2, x2, y2), 0, 90, fill=fill)
        draw.pieslice((x1, y2 - radius * 2, x1 + radius * 2, y2), 90, 180, fill=fill)
    
    # Draw the main rectangles
    if x2 - x1 > radius * 2:
        draw.rectangle((x1 + radius, y1, x2 - radius, y2), fill=fill)
    if y2 - y1 > radius * 2:
        draw.rectangle((x1, y1 + radius, x2, y2 - radius), fill=fill)

async def generate_level_card(member: discord.Member, level: int, xp: int, xp_needed: int):
    """Generate a level card image for a user"""
    # Define badge path based on level
    if 0 <= level <= 9:
        BADGE_IMAGE_PATH = "assets/badge/0.PNG"
    elif 10 <= level <= 19:
        BADGE_IMAGE_PATH = "assets/badge/1.PNG"
    elif 20 <= level <= 29:
        BADGE_IMAGE_PATH = "assets/badge/2.PNG"
    elif 30 <= level <= 39:
        BADGE_IMAGE_PATH = "assets/badge/3.PNG"
    elif 40 <= level <= 49:
        BADGE_IMAGE_PATH = "assets/badge/4.PNG"
    elif level >= 50:
        BADGE_IMAGE_PATH = "assets/badge/5.PNG"
        
    # Define card size
    width, height = 700, 150  # Increased width to accommodate badge
    background_color = (40, 40, 40)
    accent_color = (0, 200, 200)

    # Create an image with a dark background
    img = Image.new("RGB", (width, height), background_color)
    draw = ImageDraw.Draw(img)

    # Draw a colored rectangle on the right side
    draw.rectangle((width - 150, 0, width, height), fill="#1c1c1c")
    draw.line((width -150, 0, width-150, height), fill=accent_color, width=2)

    # Load and draw user avatar
    avatar_size = 80
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(avatar_url) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()
                    try:
                        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                        avatar = avatar.resize((avatar_size, avatar_size))

                        mask = Image.new("L", (avatar_size, avatar_size), 0)
                        mask_draw = ImageDraw.Draw(mask)
                        mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
                        img.paste(avatar, (20, height // 2 - avatar_size // 2), mask)

                        # Create glow effect
                        glow_radius = 100  # Adjust glow radius
                        glow_color = (133, 212, 255, 200) # RGBA value. last number is opacity
                        glow_mask = avatar.copy().convert("L")  # Convert to grayscale
                        glow_mask = glow_mask.filter(ImageFilter.GaussianBlur(glow_radius))
                        glow_img = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0)) #transparent image
                        glow_draw = ImageDraw.Draw(glow_img)
                        glow_draw.bitmap((0, 0), glow_mask, fill=glow_color)
                        img.paste(glow_img, (20, height // 2 - avatar_size // 2), mask)

                        img.paste(avatar, (20, height // 2 - avatar_size // 2), mask)

                    except UnidentifiedImageError as e:
                        print(f"Error processing image: {e}")
                        return None
                else:
                    print(f"Failed to download avatar. Status: {resp.status}")
                    return None
        except aiohttp.ClientError as e:
            print(f"Error downloading avatar: {e}")
            return None

    # Load a font
    try:
        font_large = ImageFont.truetype(FONT_PATH, 30)
        font_small = ImageFont.truetype(FONT_PATH, 20)
    except IOError:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Draw user info
    username_text = f"{member.name}"
    draw.text((120, 30), username_text, font=font_large, fill="white")

    # Draw level and XP
    level_text = f"Level: {level}"
    xp_text = f"XP: {xp} / {xp_needed}"
    draw.text((120, 65), level_text, font=font_small, fill="white")
    draw.text((250, 65), xp_text, font=font_small, fill="white")

    # Draw XP bar background (rounded)
    bar_x, bar_y = 120, 100
    bar_width, bar_height = 350, 20
    radius = bar_height // 2
    rounded_rectangle(draw, (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height), radius, (60, 60, 60))

    # Draw XP progress (rounded)
    progress = xp / xp_needed
    progress_width = max(1, int(bar_width * progress))  # Ensure at least 1px width
    
    # Only draw progress bar if there's actual progress
    if progress > 0:
        rounded_rectangle(draw, (bar_x, bar_y, bar_x + progress_width, bar_y + bar_height), radius, accent_color)

    # Draw badge (right side)
    try:
        badge_img = Image.open(BADGE_IMAGE_PATH).convert("RGBA")
        badge_img = badge_img.resize((90, 130))  # Resize badge image
        img.paste(badge_img, (width - 120, height // 2 - 65), badge_img) #paste badge image

    except FileNotFoundError:
        print(f"Badge image not found at: {BADGE_IMAGE_PATH}")
    except Exception as e:
        print(f"Error loading badge image: {e}")

    # Save image to a BytesIO object
    image_bytes = io.BytesIO()
    img.save(image_bytes, format="PNG")
    image_bytes.seek(0)
    return image_bytes

async def generate_leaderboard_image(guild: discord.Guild, rows):
    """Generate a leaderboard image for the top users"""
    # Set image dimensions dynamically
    width = 800
    title_height = 80
    entry_height = 80  # Box height
    entry_spacing = 20  # Extra space between entries
    padding = 50
    height = title_height + (len(rows) * (entry_height + entry_spacing)) + padding

    # Create image
    img = Image.new("RGB", (width, height), (30, 30, 30))
    draw = ImageDraw.Draw(img)

    # Load font
    try:
        font = ImageFont.truetype(FONT_PATH, 30)
    except IOError:
        font = ImageFont.load_default()

    # Rank colors
    rank_colors = {1: (255, 215, 0), 2: (192, 192, 192), 3: (205, 127, 50)}

    # Draw leaderboard entries
    y_offset = title_height
    avatar_size = 50
    text_x_offset = 120
    rect_padding = 15
    rect_radius = 20

    for rank, (user_id, xp, level) in enumerate(rows, start=1):
        member = guild.get_member(int(user_id))
        user_name = member.display_name if member else f"User {user_id}"

        rank_color = rank_colors.get(rank, (255, 255, 255))

        # Rectangle position
        rect_x1, rect_y1 = 40, y_offset
        rect_x2, rect_y2 = width - 40, y_offset + entry_height

        # Draw rounded rectangle
        draw_rounded_rectangle(draw, (rect_x1, rect_y1, rect_x2, rect_y2), rect_radius, (50, 50, 50))

        # Draw circular avatar
        avatar_position = (50, y_offset + 15)
        if member:
            avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()
                        avatar_image = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                        draw_circular_avatar(img, avatar_image, avatar_position, avatar_size)
        else:
            # Default gray placeholder if user not found
            draw.ellipse(
                (avatar_position[0], avatar_position[1], avatar_position[0] + avatar_size, avatar_position[1] + avatar_size),
                fill="gray",
            )

        # Rank text
        rank_text = f"#{rank}"
        rank_text_width = draw.textlength(rank_text, font=font)
        draw.text((text_x_offset, y_offset + 25), rank_text, fill=rank_color, font=font)

        # User text
        user_text = f" |{user_name} | LVL: {level}"
        draw.text((text_x_offset + rank_text_width, y_offset + 25), user_text, fill="white", font=font)

        y_offset += entry_height + entry_spacing  # Add extra spacing

    # Save image to a BytesIO object
    image_bytes = io.BytesIO()
    img.save(image_bytes, format="PNG")
    image_bytes.seek(0)
    return image_bytes

def draw_rounded_rectangle(draw, xy, radius, fill):
    """Draw a rounded rectangle"""
    x1, y1, x2, y2 = xy
    draw.rectangle((x1 + radius, y1, x2 - radius, y2), fill=fill)
    draw.rectangle((x1, y1 + radius, x2, y2 - radius), fill=fill)
    draw.pieslice((x1, y1, x1 + radius * 2, y1 + radius * 2), 180, 270, fill=fill)
    draw.pieslice((x2 - radius * 2, y1, x2, y1 + radius * 2), 270, 360, fill=fill)
    draw.pieslice((x1, y2 - radius * 2, x1 + radius * 2, y2), 90, 180, fill=fill)
    draw.pieslice((x2 - radius * 2, y2 - radius * 2, x2, y2), 0, 90, fill=fill)

def draw_circular_avatar(img, avatar_image, position, size):
    """Draw a circular avatar on the image"""
    avatar = avatar_image.convert("RGBA")
    avatar = avatar.resize((size, size), Image.LANCZOS)

    # Create circular mask
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)

    # Apply mask
    avatar.putalpha(mask)
    img.paste(avatar, position, avatar)