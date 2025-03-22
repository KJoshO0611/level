import logging
import time
from utils.cairo_image_generator import initialize_template_cache, initialize_status_indicators

def initialize_image_templates(bot):
    """Initialize all image templates in background thread"""
    try:
        start_time = time.time()
        logging.info("Starting image template initialization...")
        
        # Initialize background templates
        initialize_template_cache()
        
        # Initialize status indicators
        initialize_status_indicators()
        
        # Initialize any other template types here
        # ...
        
        elapsed = time.time() - start_time
        logging.info(f"Image templates initialized in {elapsed:.2f} seconds")
        
        # Store initialization status on bot object
        bot.templates_initialized = True
    except Exception as e:
        logging.error(f"Error initializing image templates: {e}")
        bot.templates_initialized = False