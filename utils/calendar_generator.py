import cairo
import datetime
import calendar
import io
import math
import logging
import asyncio
import time
from datetime import datetime, timedelta
from utils.cairo_image_generator import (
    get_font, optimized_draw_text, measure_text_size, TEMPLATE_CACHE
)

def _generate_event_calendar_cairo_sync(guild_name, year, month, events, language="en"):
    """
    Generate a visual calendar for a specific month showing XP events
    
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
    # Check if we have a cached template for this month/year
    cache_key = f"calendar_template_{year}_{month}"
    cached_template = TEMPLATE_CACHE.get(cache_key)
    # Calendar dimensions and settings
    width = 900
    height = 720
    margin = 30
    header_height = 80
    footer_height = 60
    
    # Colors
    bg_color = (40/255, 40/255, 45/255)  # Dark background
    grid_color = (70/255, 70/255, 75/255)  # Slightly lighter grid lines
    text_color = (225/255, 225/255, 225/255)  # Off-white text
    today_bg_color = (70/255, 70/255, 90/255)  # Highlight for today
    weekend_bg_color = (50/255, 50/255, 55/255)  # Slightly darker for weekends
    
    # Event colors based on multiplier (from cooler to warmer colors)
    event_colors = {
        1.0: (0.2, 0.4, 0.6),  # Blue - lowest
        1.5: (0.2, 0.5, 0.2),  # Green
        2.0: (0.5, 0.5, 0.1),  # Yellow
        2.5: (0.6, 0.3, 0.1),  # Orange
        3.0: (0.7, 0.1, 0.1),  # Red - highest
    }
    
    # Font sizes
    title_font_size = 32
    weekday_font_size = 18
    day_font_size = 16
    event_font_size = 14
    
    # Create surface and context
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    
    # If we have a cached template, use it as the base
    if cached_template:
        logging.info(f"Using cached calendar template for {month}/{year}")
        # Create a new surface from the cached template bytes
        try:
            # Reset the BytesIO position
            cached_template.seek(0)
            # Load the template as a new surface
            template_surface = cairo.ImageSurface.create_from_png(cached_template)
            # Draw it onto our current surface
            ctx.set_source_surface(template_surface, 0, 0)
            ctx.paint()
            # Clean up the template surface
            del template_surface
        except Exception as e:
            logging.error(f"Error loading cached template: {e}")
            # Fall back to creating from scratch
            ctx.set_source_rgb(*bg_color)
            ctx.rectangle(0, 0, width, height)
            ctx.fill()
            cached_template = None  # Reset so we rebuild everything
    else:
        # Fill background and create from scratch
        logging.info(f"No cached template for {month}/{year}, creating new")
        ctx.set_source_rgb(*bg_color)
        ctx.rectangle(0, 0, width, height)
        ctx.fill()
    
    # Draw calendar title (Month Year) - only if we don't have a cached template
    cal = calendar.month_name[month] + " " + str(year)
    title_font = get_font(None, title_font_size)
    title_width, _ = measure_text_size(cal, title_font)
    
    if not cached_template:
        optimized_draw_text(
            ctx,
            cal,
            width/2 - title_width/2,
            margin + title_font_size/2,
            size=title_font_size,
            rgb_color=text_color
        )
    
    # Always draw guild name (this might change between requests)
    guild_subtitle = f"XP Events Calendar - {guild_name}"
    subtitle_font = get_font(None, weekday_font_size)
    subtitle_width, _ = measure_text_size(guild_subtitle, subtitle_font)
    
    # Clear the area where the subtitle will go
    ctx.set_source_rgb(*bg_color)
    ctx.rectangle(width/2 - subtitle_width/2 - 10, margin + title_font_size + 10, 
                 subtitle_width + 20, weekday_font_size + 10)
    ctx.fill()
    
    optimized_draw_text(
        ctx,
        guild_subtitle,
        width/2 - subtitle_width/2,
        margin + title_font_size + 25,
        size=weekday_font_size,
        rgb_color=text_color
    )
    
    # Calculate calendar grid dimensions
    grid_top = margin + header_height
    grid_width = width - 2 * margin
    grid_height = height - grid_top - footer_height - margin
    cell_width = grid_width / 7
    
    # Get the calendar info for this month
    cal = calendar.monthcalendar(year, month)
    num_weeks = len(cal)
    cell_height = grid_height / num_weeks
    
    # Draw weekday headers - only if we don't have a cached template
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]  
    # For localization, replace with appropriate names based on language parameter
    
    if not cached_template:
        for i, day_name in enumerate(weekday_names):
            day_x = margin + i * cell_width + cell_width / 2
            day_y = grid_top - 15
            
            # Shortened day name to first 3 letters
            short_name = day_name[:3]
            
            optimized_draw_text(
                ctx,
                short_name,
                day_x,
                day_y,
                size=weekday_font_size,
                rgb_color=text_color,
                centered=True
            )
    
    # Get current date to highlight today
    today = datetime.now()
    
    # Process events to organize by day
    # Create a dict mapping day numbers to events that occur on that day
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
    
    # Draw calendar grid and days - only handling special cases if we have a cached template
    for week_idx, week in enumerate(cal):
        for day_idx, day in enumerate(week):
            # Calculate cell position
            cell_x = margin + day_idx * cell_width
            cell_y = grid_top + week_idx * cell_height
            
            if not cached_template:
                # Draw cell background
                if day != 0:  # Skip padding days (0)
                    # Check if it's a weekend
                    is_weekend = day_idx >= 5  # Saturday and Sunday
                    
                    # Set background color based on day type
                    if is_weekend:
                        ctx.set_source_rgb(*weekend_bg_color)
                    else:
                        ctx.set_source_rgb(*bg_color)
                    
                    # Draw cell background
                    ctx.rectangle(cell_x, cell_y, cell_width, cell_height)
                    ctx.fill()
                
                # Draw grid lines
                ctx.set_source_rgb(*grid_color)
                ctx.set_line_width(1)
                ctx.rectangle(cell_x, cell_y, cell_width, cell_height)
                ctx.stroke()
            
            # Always handle today highlighting since it changes every day
            if day != 0:
                # Check if it's today
                is_today = (today.year == year and today.month == month and today.day == day)
                
                if is_today:
                    # Draw today highlight on top of existing cell
                    ctx.set_source_rgb(*today_bg_color)
                    ctx.rectangle(cell_x, cell_y, cell_width, cell_height)
                    ctx.fill()
                    
                    # Redraw cell border
                    ctx.set_source_rgb(*grid_color)
                    ctx.set_line_width(1)
                    ctx.rectangle(cell_x, cell_y, cell_width, cell_height)
                    ctx.stroke()
            
            # Draw day number if this is a valid day
            if day != 0:
                day_text = str(day)
                
                # Position day number in top-left of cell with padding
                ctx.set_source_rgb(*text_color)
                optimized_draw_text(
                    ctx,
                    day_text,
                    cell_x + 10,
                    cell_y + 20,
                    size=day_font_size,
                    rgb_color=text_color
                )
                
                # Draw events for this day
                if day in events_by_day:
                    day_events = events_by_day[day]
                    event_y_offset = 35  # Start below day number
                    
                    # Sort events by multiplier (highest first) then by name
                    day_events.sort(key=lambda e: (-e["multiplier"], e["name"]))
                    
                    # Limit to max 3 events per cell to avoid overflow
                    max_events = 3
                    displayed_events = 0
                    
                    for event in day_events[:max_events]:
                        # Choose color based on multiplier
                        multiplier = event["multiplier"]
                        # Find the closest predefined multiplier color
                        closest_mult = min(event_colors.keys(), key=lambda x: abs(x - multiplier))
                        event_color = event_colors[closest_mult]
                        
                        # Draw event indicator
                        indicator_width = cell_width - 20
                        indicator_height = 20
                        
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
                            cell_y + event_y_offset + indicator_height/2,
                            size=event_font_size,
                            rgb_color=(1, 1, 1)  # White text
                        )
                        
                        # Increment y offset for next event
                        event_y_offset += indicator_height + 5
                        displayed_events += 1
                    
                    # If there are more events than we can display, add indicator
                    if len(day_events) > max_events:
                        more_text = f"+ {len(day_events) - max_events} more"
                        optimized_draw_text(
                            ctx,
                            more_text,
                            cell_x + cell_width - 40,
                            cell_y + cell_height - 10,
                            size=12,
                            rgb_color=(0.7, 0.7, 0.7)  # Light gray
                        )
    
    # Draw legend in the footer - only if we don't have a cached template
    legend_y = height - footer_height + 15
    legend_x = margin + 10
    legend_item_width = 150
    
    if not cached_template:
        # Title for legend
        optimized_draw_text(
            ctx,
            "XP Multipliers:",
            legend_x,
            legend_y,
            size=16,
            rgb_color=text_color
        )
        
        # Draw color boxes for each multiplier
        for i, (multiplier, color) in enumerate(sorted(event_colors.items())):
            item_x = legend_x + 150 + (i * legend_item_width)
            
            # Color box
            ctx.set_source_rgb(*color)
            ctx.rectangle(item_x, legend_y - 10, 15, 15)
            ctx.fill_preserve()
            ctx.set_source_rgb(color[0] * 0.7, color[1] * 0.7, color[2] * 0.7)
            ctx.set_line_width(1)
            ctx.stroke()
            
            # Multiplier text
            optimized_draw_text(
                ctx,
                f"{multiplier}x",
                item_x + 25,
                legend_y,
                size=14,
                rgb_color=text_color
            )
    
    # Add generation timestamp
    timestamp_text = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    timestamp_font = get_font(None, 12)
    timestamp_width, _ = measure_text_size(timestamp_text, timestamp_font)
    
    optimized_draw_text(
        ctx,
        timestamp_text,
        width - margin - timestamp_width,
        height - margin,
        size=12,
        rgb_color=(0.7, 0.7, 0.7)  # Light gray
    )
    
    # Convert to bytes
    image_bytes = io.BytesIO()
    surface.write_to_png(image_bytes)
    image_bytes.seek(0)
    
    # Clean up resources
    del surface
    del ctx
    
    # Cache the generated calendar template for future use
    # We don't cache the final image with events, but we could cache the base template
    # with the empty grid, headers, etc. for this month/year combination
    if cached_template is None:
        try:
            # Create a cloned surface without the events, just the base grid and styling
            # This is what we'll cache for reuse
            template_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            template_ctx = cairo.Context(template_surface)
            
            # Fill background
            template_ctx.set_source_rgb(*bg_color)
            template_ctx.rectangle(0, 0, width, height)
            template_ctx.fill()
            
            # Draw calendar title (Month Year)
            optimized_draw_text(
                template_ctx,
                cal,
                width/2 - title_width/2,
                margin + title_font_size/2,
                size=title_font_size,
                rgb_color=text_color
            )
            
            # Draw weekday headers
            for i, day_name in enumerate(weekday_names):
                day_x = margin + i * cell_width + cell_width / 2
                day_y = grid_top - 15
                short_name = day_name[:3]
                
                optimized_draw_text(
                    template_ctx,
                    short_name,
                    day_x,
                    day_y,
                    size=weekday_font_size,
                    rgb_color=text_color,
                    centered=True
                )
            
            # Draw basic grid with empty cells
            for week_idx, week in enumerate(cal):
                for day_idx, day in enumerate(week):
                    # Calculate cell position
                    cell_x = margin + day_idx * cell_width
                    cell_y = grid_top + week_idx * cell_height
                    
                    # Draw cell background (but not specific day styling)
                    if day != 0:  # Skip padding days (0)
                        # Check if it's a weekend
                        is_weekend = day_idx >= 5  # Saturday and Sunday
                        
                        # Set background color based on day type
                        if is_weekend:
                            template_ctx.set_source_rgb(*weekend_bg_color)
                        else:
                            template_ctx.set_source_rgb(*bg_color)
                        
                        # Draw cell background
                        template_ctx.rectangle(cell_x, cell_y, cell_width, cell_height)
                        template_ctx.fill()
                    
                    # Draw grid lines
                    template_ctx.set_source_rgb(*grid_color)
                    template_ctx.set_line_width(1)
                    template_ctx.rectangle(cell_x, cell_y, cell_width, cell_height)
                    template_ctx.stroke()
            
            # Draw legend in the footer (without timestamp)
            legend_y = height - footer_height + 15
            legend_x = margin + 10
            legend_item_width = 150
            
            # Title for legend
            optimized_draw_text(
                template_ctx,
                "XP Multipliers:",
                legend_x,
                legend_y,
                size=16,
                rgb_color=text_color
            )
            
            # Draw color boxes for each multiplier
            for i, (multiplier, color) in enumerate(sorted(event_colors.items())):
                item_x = legend_x + 150 + (i * legend_item_width)
                
                # Color box
                template_ctx.set_source_rgb(*color)
                template_ctx.rectangle(item_x, legend_y - 10, 15, 15)
                template_ctx.fill_preserve()
                template_ctx.set_source_rgb(color[0] * 0.7, color[1] * 0.7, color[2] * 0.7)
                template_ctx.set_line_width(1)
                template_ctx.stroke()
                
                # Multiplier text
                optimized_draw_text(
                    template_ctx,
                    f"{multiplier}x",
                    item_x + 25,
                    legend_y,
                    size=14,
                    rgb_color=text_color
                )
            
            # Cache the template
            # We need to convert the surface to bytes for storage in the cache
            template_bytes = io.BytesIO()
            template_surface.write_to_png(template_bytes)
            template_bytes.seek(0)
            TEMPLATE_CACHE.set(cache_key, template_bytes)
            logging.info(f"Cached calendar template for {month}/{year}")
            
            # Clean up the template resources we just created
            del template_surface
            del template_ctx
        except Exception as e:
            logging.warning(f"Failed to cache calendar template: {e}")
    
    return image_bytes

async def generate_event_calendar(guild_id, guild_name, year=None, month=None, bot=None):
    """
    Async wrapper to generate a calendar image for XP boost events
    
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