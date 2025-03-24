import cairo
import datetime
import calendar
import io
import math
import logging
import time
import os
import asyncio
import tempfile
from datetime import datetime, timedelta
from utils.cairo_image_generator import (
    get_font, optimized_draw_text, measure_text_size, TEMPLATE_CACHE
)

# Create a dedicated calendar cache directory
CALENDAR_CACHE_DIR = os.path.join(tempfile.gettempdir(), "calendar_cache")
os.makedirs(CALENDAR_CACHE_DIR, exist_ok=True)
print(f"Calendar cache location: {CALENDAR_CACHE_DIR}")

def _get_calendar_template_path(year, month):
    """Get the path for a cached calendar template"""
    return os.path.join(CALENDAR_CACHE_DIR, f"calendar_template_{year}_{month}.png")

def _is_template_cached(year, month):
    """Check if a template exists for this year/month"""
    template_path = _get_calendar_template_path(year, month)
    return os.path.exists(template_path) and os.path.getsize(template_path) > 0

def _generate_event_calendar_cairo_sync(guild_name, year, month, events, language="en"):
    """
    Generate a visual calendar for a specific month showing XP events with dynamic row heights
    
    This function uses template caching to improve performance for repeatedly
    generated calendars. It caches base templates for each month/year combination
    and reuses them when possible.
    
    Parameters:
    - guild_name: Name of the Discord guild
    - year: Year to display
    - month: Month to display (1-12)
    - events: List of event dictionaries, each containing:
        - id: Event ID
        - name: Event name
        - multiplier: XP multiplier
        - start_time: Start timestamp
        - end_time: End timestamp
    - language: Language code for month/day names
    
    Returns:
    - BytesIO: The generated calendar image
    """
    # For reference to fix variables
    cal = calendar.month_name[month] + " " + str(year)
    # Layout parameters for compact layout with dynamic row heights
    layout_params = {
        "width": 900,                   # Image width in pixels
        "margin": 30,                   # Margin around edges
        "header_height": 80,            # Height of the header section
        "footer_height": 60,            # Height of the footer section
        "day_header_height": 30,        # Height for weekday headers
        "title_font_size": 32,          # Font size for month/year title
        "subtitle_font_size": 18,       # Font size for subtitle (guild name)
        "weekday_font_size": 18,        # Font size for weekday names
        "day_font_size": 16,            # Font size for day numbers
        "event_font_size": 12,          # Font size for event text
        "legend_font_size": 14,         # Font size for legend text
        "event_height": 18,             # Height for each event indicator (compact)
        "event_spacing": 1,             # Space between events (compact)
        "day_number_padding": 8,        # Padding from edge to day number
        "day_number_top_padding": 8,    # Padding from top of cell to day number
        "event_start_y_offset": 35,     # How far below the top of cell events start
        "min_row_height": 80,           # Minimum height per row
        "max_row_height": 250,          # Maximum height per row
        "min_calendar_height": 600,     # Minimum total calendar height
        "max_calendar_height": 1200,    # Maximum total calendar height
        # Colors (R, G, B values, each between 0-1)
        "bg_color": (40/255, 40/255, 45/255),           # Background color
        "grid_color": (70/255, 70/255, 75/255),         # Grid line color
        "text_color": (225/255, 225/255, 225/255),      # Default text color
        "today_bg_color": (70/255, 70/255, 90/255),     # Today's highlight color
        "weekend_bg_color": (50/255, 50/255, 55/255),   # Weekend cell color
    }
    
    # Use the layout parameters
    p = layout_params
    
    # Check if we have a cached template for this month/year
    has_cached_template = _is_template_cached(year, month)
    
    # Event colors based on multiplier (from cooler to warmer colors)
    event_colors = {
        1.0: (0.2, 0.4, 0.6),  # Blue - lowest
        2.0: (0.2, 0.5, 0.2),  # Green
        3.0: (0.5, 0.5, 0.1),  # Yellow
        4.0: (0.6, 0.3, 0.1),  # Orange
        5.0: (0.7, 0.1, 0.1),  # Red - highest
    }
    
    calendar.setfirstweekday(6)  # 6 = Sunday

    # Get the calendar info for this month
    month_calendar = calendar.monthcalendar(year, month)
    num_weeks = len(month_calendar)
    
    # Process events to organize by day
    events_by_day = {}
    for event in events:
        start_time = datetime.fromtimestamp(event["start_time"])
        end_time = datetime.fromtimestamp(event["end_time"])
        
        # Skip events not in this month/year
        if (start_time.year > year or start_time.month > month) or \
           (end_time.year < year or end_time.month < month):
            continue
        
        # Calculate which days this event spans within this month
        current_date = max(start_time, datetime(year, month, 1))
        last_date = min(end_time, datetime(year, month + 1, 1) - timedelta(days=1))
        
        while current_date <= last_date:
            day = current_date.day
            
            if day not in events_by_day:
                events_by_day[day] = []
            
            # Add the event to this day
            event_info = {
                "id": event["id"],
                "name": event["name"],
                "multiplier": event["multiplier"],
                "is_start": current_date.date() == start_time.date(),
                "is_end": current_date.date() == end_time.date(),
                "start_time": start_time,
                "end_time": end_time
            }
            
            events_by_day[day].append(event_info)
            
            # Move to the next day
            current_date += timedelta(days=1)
    
    # ==================== CALCULATE ROW HEIGHTS DYNAMICALLY ====================
    # Count maximum events per day in each row
    max_events_per_row = []
    for week in month_calendar:
        max_events_in_week = 0
        for day in week:
            if day != 0 and day in events_by_day:
                max_events_in_week = max(max_events_in_week, len(events_by_day[day]))
        max_events_per_row.append(max_events_in_week)
    
    # Calculate row heights based on number of events
    # Base height plus additional height for each event
    row_heights = []
    for events_count in max_events_per_row:
        if events_count == 0:
            # Minimum height for rows with no events
            row_heights.append(p["min_row_height"])
        else:
            # Calculate height needed for events
            event_height_needed = p["event_start_y_offset"] + (events_count * p["event_height"]) + ((events_count - 1) * p["event_spacing"]) + 10
            # Ensure within min/max constraints
            row_height = max(p["min_row_height"], min(p["max_row_height"], event_height_needed))
            row_heights.append(row_height)
    
    # Calculate total grid height based on the row heights
    grid_height = sum(row_heights)
    
    # Adjust total image height based on grid height
    calendar_height = p["margin"] + p["header_height"] + p["day_header_height"] + grid_height + p["footer_height"] + p["margin"]
    
    # Ensure total height is within constraints
    calendar_height = max(p["min_calendar_height"], min(p["max_calendar_height"], calendar_height))
    
    # If calendar_height is constrained, adjust row heights proportionally
    if calendar_height != p["margin"] + p["header_height"] + p["day_header_height"] + grid_height + p["footer_height"] + p["margin"]:
        available_height = calendar_height - p["margin"] - p["header_height"] - p["day_header_height"] - p["footer_height"] - p["margin"]
        
        # Scale row heights to fit available height
        total_current_height = sum(row_heights)
        if total_current_height > 0:  # Avoid division by zero
            scale_factor = available_height / total_current_height
            row_heights = [h * scale_factor for h in row_heights]
    
    # If we have a cached template, use it as the base, otherwise create a new surface
    if has_cached_template:
        logging.info(f"Using cached calendar template for {month}/{year}")
        # Create a new surface from the cached template file
        try:
            # Load the template as a new surface
            template_path = _get_calendar_template_path(year, month)
            template_surface = cairo.ImageSurface.create_from_png(template_path)
            template_width = template_surface.get_width()
            template_height = template_surface.get_height()
            
            # Create our working surface with the adjusted height
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, p["width"], calendar_height)
            ctx = cairo.Context(surface)
            
            # Fill background first
            ctx.set_source_rgb(*p["bg_color"])
            ctx.rectangle(0, 0, p["width"], calendar_height)
            ctx.fill()
            
            # Draw the template onto our surface in the header area
            header_height = p["margin"] + p["header_height"] + p["day_header_height"]
            ctx.set_source_surface(template_surface, 0, 0)
            # Only copy the header portion from the template
            ctx.rectangle(0, 0, p["width"], header_height)
            ctx.fill()
            
            # Clean up the template surface
            del template_surface
        except Exception as e:
            logging.error(f"Error loading cached template: {e}")
            # Fall back to creating from scratch
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, p["width"], calendar_height)
            ctx = cairo.Context(surface)
            ctx.set_source_rgb(*p["bg_color"])
            ctx.rectangle(0, 0, p["width"], calendar_height)
            ctx.fill()
            has_cached_template = False  # Reset so we rebuild everything
    else:
        # Fill background and create from scratch
        logging.info(f"No cached template for {month}/{year}, creating new")
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, p["width"], calendar_height)
        ctx = cairo.Context(surface)
        ctx.set_source_rgb(*p["bg_color"])
        ctx.rectangle(0, 0, p["width"], calendar_height)
        ctx.fill()
    
    # Draw calendar title and header - only if we don't have a cached template or if it failed to load
    if not has_cached_template:
        # Create calendar title
        month_name = calendar.month_name[month]
        cal_title = f"{month_name} {year}"
        
        # Calculate text dimensions for proper centering
        title_font = get_font(None, p["title_font_size"])
        title_width, title_height = measure_text_size(cal_title, title_font)

        title_center_x = p["width"]/2
        title_start_x = title_center_x - title_width/2

        # Clear the title area to be safe
        ctx.set_source_rgb(*p["bg_color"])
        ctx.rectangle(0, 30, p["width"], 40)
        ctx.fill()

        # Draw calendar title with fixed vertical position
        optimized_draw_text(
            ctx,
            cal_title,
            title_start_x,  # Horizontally centered
            20,            # Fixed vertical position
            size=p["title_font_size"],
            rgb_color=p["text_color"],
            centered=False
        )
        
        # Draw weekday headers
        weekday_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]  
        # For localization, replace with appropriate names based on language parameter
        
        grid_top = p["margin"] + p["header_height"] + p["day_header_height"]
        grid_width = p["width"] - 2 * p["margin"]
        cell_width = grid_width / 7
        
        for i, day_name in enumerate(weekday_names):
            day_x = p["margin"] + i * cell_width + cell_width / 2
            day_y = p["margin"] + p["header_height"] + p["day_header_height"] / 2
            
            # Shortened day name to first 3 letters
            short_name = day_name[:3]
            
            optimized_draw_text(
                ctx,
                short_name,
                day_x,
                day_y,
                size=p["weekday_font_size"],
                rgb_color=p["text_color"],
                centered=True
            )
    
    # Draw subtitle with fixed position - split into two lines
    calendar_text = "XP Events Calendar"
    guild_text = guild_name

    # Calculate text dimensions to ensure proper centering
    calendar_text_font = get_font(None, p["subtitle_font_size"])
    guild_text_font = get_font(None, p["subtitle_font_size"])
    calendar_text_width, calendar_text_height = measure_text_size(calendar_text, calendar_text_font)
    guild_text_width, guild_text_height = measure_text_size(guild_text, guild_text_font)

    # Clear the entire subtitle area
    ctx.set_source_rgb(*p["bg_color"])
    ctx.rectangle(0, 65, p["width"], 50)
    ctx.fill()

    # Calculate true center positions
    calendar_center_x = p["width"]/2
    guild_center_x = p["width"]/2

    # For the first line - explicitly position for centering
    calendar_text_x = calendar_center_x - calendar_text_width/2
    optimized_draw_text(
        ctx,
        calendar_text,
        calendar_text_x,  # Start position is center minus half the width
        65,
        size=p["subtitle_font_size"],
        rgb_color=p["text_color"],
        centered=False  # We're handling centering manually
    )

    # For the second line - explicitly position for centering
    guild_text_x = guild_center_x - guild_text_width/2
    optimized_draw_text(
        ctx,
        guild_text,
        guild_text_x,  # Start position is center minus half the width
        85,
        size=p["subtitle_font_size"],
        rgb_color=p["text_color"],
        centered=False  # We're handling centering manually
    )
    
    # Calculate calendar grid dimensions 
    grid_top = p["margin"] + p["header_height"] + p["day_header_height"]
    grid_width = p["width"] - 2 * p["margin"]
    cell_width = grid_width / 7
    
    # Get current date to highlight today
    today = datetime.now()
    
    # Draw calendar grid and days with dynamic row heights
    row_start_y = grid_top
    for week_idx, week in enumerate(month_calendar):
        row_height = row_heights[week_idx]
        
        for day_idx, day in enumerate(week):
            # Calculate cell position
            cell_x = p["margin"] + day_idx * cell_width
            cell_y = row_start_y
            
            # Draw cell background
            if day != 0:  # Skip padding days (0)
                # Check if it's today
                is_today = (today.year == year and today.month == month and today.day == day)
                
                # Check if it's a weekend
                is_weekend = day_idx >= 5  # Saturday and Sunday
                
                # Set background color based on day type
                if is_today:
                    ctx.set_source_rgb(*p["today_bg_color"])
                elif is_weekend:
                    ctx.set_source_rgb(*p["weekend_bg_color"])
                else:
                    ctx.set_source_rgb(*p["bg_color"])
                
                # Draw cell background
                ctx.rectangle(cell_x, cell_y, cell_width, row_height)
                ctx.fill()
            
            # Draw grid lines
            ctx.set_source_rgb(*p["grid_color"])
            ctx.set_line_width(1)
            ctx.rectangle(cell_x, cell_y, cell_width, row_height)
            ctx.stroke()
            
            # Draw day number if this is a valid day
            if day != 0:
                day_text = str(day)
                
                # Position day number in top-left of cell with padding
                optimized_draw_text(
                    ctx,
                    day_text,
                    cell_x + p["day_number_padding"],
                    cell_y + p["day_number_top_padding"],
                    size=p["day_font_size"],
                    rgb_color=p["text_color"]
                )
                
                # Draw events for this day
                if day in events_by_day:
                    day_events = events_by_day[day]
                    
                    # Sort events by multiplier (highest first) then by name
                    day_events.sort(key=lambda e: (-e["multiplier"], e["name"]))
                    
                    event_y_offset = p["event_start_y_offset"]  # Start below day number
                    
                    for event in day_events:
                        # Skip drawing if event would be outside the cell
                        if cell_y + event_y_offset + p["event_height"] > cell_y + row_height:
                            break
                        
                        # Choose color based on multiplier
                        multiplier = event["multiplier"]
                        # Find the closest predefined multiplier color
                        closest_mult = min(event_colors.keys(), key=lambda x: abs(x - multiplier))
                        event_color = event_colors[closest_mult]
                        
                        # Draw event indicator
                        indicator_width = cell_width - 20
                        indicator_height = p["event_height"]
                        
                        # Determine if this is the start or end of an event
                        is_start = event["is_start"]
                        is_end = event["is_end"]
                        
                        # Adjust indicator shape based on event span
                        if is_start and is_end:
                            # Single-day event - normal rectangle
                            ctx.rectangle(
                                cell_x + 10, 
                                cell_y + event_y_offset, 
                                indicator_width, 
                                indicator_height
                            )
                        elif is_start:
                            # Start of multi-day event - rectangle with right side extended
                            ctx.move_to(cell_x + 10, cell_y + event_y_offset)
                            ctx.line_to(cell_x + 10, cell_y + event_y_offset + indicator_height)
                            ctx.line_to(cell_x + cell_width, cell_y + event_y_offset + indicator_height)
                            ctx.line_to(cell_x + cell_width, cell_y + event_y_offset)
                            ctx.close_path()
                        elif is_end:
                            # End of multi-day event - rectangle with left side extended
                            ctx.move_to(cell_x, cell_y + event_y_offset)
                            ctx.line_to(cell_x, cell_y + event_y_offset + indicator_height)
                            ctx.line_to(cell_x + 10 + indicator_width, cell_y + event_y_offset + indicator_height)
                            ctx.line_to(cell_x + 10 + indicator_width, cell_y + event_y_offset)
                            ctx.close_path()
                        else:
                            # Middle of multi-day event - full width rectangle
                            ctx.rectangle(
                                cell_x, 
                                cell_y + event_y_offset, 
                                cell_width, 
                                indicator_height
                            )
                        
                        # Fill event indicator
                        ctx.set_source_rgb(*event_color)
                        ctx.fill_preserve()
                        
                        # Add darker border
                        ctx.set_source_rgb(event_color[0] * 0.7, event_color[1] * 0.7, event_color[2] * 0.7)
                        ctx.set_line_width(1)
                        ctx.stroke()
                        
                        # Add event text and multiplier
                        event_text = f"{event['name']} ({event['multiplier']}x)"
                        
                        # Truncate text if too long for cell
                        max_chars = int(indicator_width / 6)  # Rough estimate of chars that fit
                        if len(event_text) > max_chars:
                            event_text = event_text[:max_chars-3] + "..."
                        
                        optimized_draw_text(
                            ctx,
                            event_text,
                            cell_x + 15,
                            cell_y + event_y_offset + indicator_height/2 - 13,
                            size=p["event_font_size"],
                            rgb_color=(1, 1, 1)  # White text
                        )
                        
                        # Increment y offset for next event
                        event_y_offset += indicator_height + p["event_spacing"]
        
        # Move to next row
        row_start_y += row_height
    
    # Draw legend in the footer
    legend_y = calendar_height - p["footer_height"]
    legend_x = p["margin"] + 10
    legend_item_width = 150
    
    # Title for legend
    optimized_draw_text(
        ctx,
        "XP Multipliers:",
        legend_x,
        legend_y,
        size=p["legend_font_size"],
        rgb_color=p["text_color"]
    )
    
    # Draw color boxes with fixed positions
    sorted_mults = sorted(event_colors.keys())
    color_positions = [
        (250, 1.0),   # Position for 1.0x
        (400, 2.0),   # Position for 1.5x
        (550, 3.0),   # Position for 2.0x
        (700, 4.0),   # Position for 2.5x
        (850, 5.0),   # Position for 3.0x
    ]
    
    # Draw only the multipliers that exist in our color scheme
    for pos_x, mult in color_positions:
        if mult in event_colors:
            color = event_colors[mult]
            
            # Color box
            ctx.set_source_rgb(*color)
            ctx.rectangle(pos_x - 5, legend_y + 5, 15, 15)
            ctx.fill_preserve()
            ctx.set_source_rgb(color[0] * 0.7, color[1] * 0.7, color[2] * 0.7)
            ctx.set_line_width(1)
            ctx.stroke()
            
            # Multiplier text with fixed position
            optimized_draw_text(
                ctx,
                f"{mult}x",
                pos_x - 40,
                legend_y,
                size=p["legend_font_size"],
                rgb_color=p["text_color"]
            )
    
    # Add generation timestamp
    timestamp_text = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    timestamp_font = get_font(None, 12)
    timestamp_width, _ = measure_text_size(timestamp_text, timestamp_font)
    
    optimized_draw_text(
        ctx,
        timestamp_text,
        p["width"] - p["margin"] - timestamp_width,
        calendar_height - p["margin"],
        size=12,
        rgb_color=(0.7, 0.7, 0.7)  # Light gray
    )
    
    # Save to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    
    # Clean up resources
    del surface
    del ctx
    
    # Cache the generated calendar template for future use if we created a new one
    # We don't cache the final image with events, but we cache the base template
    # with the empty grid, headers, etc. for this month/year combination
    if not has_cached_template:
        try:
            # Create a cloned surface without the events, just the base grid and styling
            template_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, p["width"], calendar_height)
            template_ctx = cairo.Context(template_surface)
            
            # Fill background
            template_ctx.set_source_rgb(*p["bg_color"])
            template_ctx.rectangle(0, 0, p["width"], calendar_height)
            template_ctx.fill()
            
            # Define calendar title
            month_name = calendar.month_name[month]
            cal_title = f"{month_name} {year}"

            # Calculate text dimensions for proper centering
            title_font = get_font(None, p["title_font_size"])
            title_width, title_height = measure_text_size(cal_title, title_font)
            
            # Calculate the starting position for true centering
            title_center_x = p["width"]/2
            title_start_x = title_center_x - title_width/2

            # Clear the title area to be safe
            template_ctx.set_source_rgb(*p["bg_color"])
            template_ctx.rectangle(0, 30, p["width"], 40)
            template_ctx.fill()

            # Draw calendar title with fixed position in template
            optimized_draw_text(
                template_ctx,
                cal_title,
                title_start_x,
                20,  # Fixed vertical position
                size=p["title_font_size"],
                rgb_color=p["text_color"],
                centered=False
            )
            
            # Draw weekday headers
            weekday_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"] 
            
            grid_top = p["margin"] + p["header_height"] + p["day_header_height"]
            grid_width = p["width"] - 2 * p["margin"]
            cell_width = grid_width / 7
            
            for i, day_name in enumerate(weekday_names):
                day_x = p["margin"] + i * cell_width + cell_width / 2
                day_y = p["margin"] + p["header_height"] + p["day_header_height"] / 2
                
                # Shortened day name to first 3 letters
                short_name = day_name[:3]
                
                optimized_draw_text(
                    template_ctx,
                    short_name,
                    day_x,
                    day_y,
                    size=p["weekday_font_size"],
                    rgb_color=p["text_color"],
                    centered=True
                )
            
            # Save the template to disk - only save part of the template (header area)
            # This way we can reuse the header even with dynamic row heights
            template_path = _get_calendar_template_path(year, month)
            template_surface.write_to_png(template_path)
            logging.info(f"Cached calendar template for {month}/{year} to {template_path}")
            
            # Clean up the template resources
            del template_surface
            del template_ctx
        except Exception as e:
            logging.warning(f"Failed to cache calendar template: {e}")
    
    return image_bytes

async def generate_event_calendar(guild_id, guild_name, year=None, month=None, bot=None):
    """
    Async wrapper to generate a calendar image for XP boost events with dynamic row heights
    
    Parameters:
    - guild_id: ID of the Discord guild
    - guild_name: Name of the Discord guild
    - year: Year to display (defaults to current year)
    - month: Month to display (1-12, defaults to current month)
    - bot: Bot instance for thread pool usage
    
    Returns:
    - BytesIO: The generated calendar image
    """
    from utils.simple_image_handler import run_in_executor
    from modules.databasev2 import get_active_xp_boost_events, get_upcoming_xp_boost_events
    
    # Default to current month if not specified
    if year is None or month is None:
        now = datetime.now()
        year = year or now.year
        month = month or now.month
    
    try:
        # Get guild events
        active_events = await get_active_xp_boost_events(guild_id)
        upcoming_events = await get_upcoming_xp_boost_events(guild_id)
        all_events = active_events + upcoming_events
        
        # Log events found
        logging.info(f"Generating calendar for {guild_name} ({guild_id}): found {len(all_events)} events")
        
        # Use bot's thread pool if available
        if bot and hasattr(bot, 'image_thread_pool'):
            result = await asyncio.get_event_loop().run_in_executor(
                bot.image_thread_pool,
                _generate_event_calendar_cairo_sync,
                guild_name,
                year,
                month,
                all_events
            )
        else:
            # Fall back to default executor
            result = await run_in_executor(_generate_event_calendar_cairo_sync)(
                guild_name,
                year,
                month,
                all_events
            )
        
        return result
        
    except Exception as e:
        logging.error(f"Error generating event calendar: {e}", exc_info=True)
        # Return simple error image
        from utils.cairo_image_generator import create_error_image
        return create_error_image(f"Error generating calendar: {str(e)}")