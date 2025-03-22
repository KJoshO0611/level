import time
import asyncio
import logging
from typing import Dict, List, Tuple, Any, Optional
import functools
from utils.user_tiers import get_user_tier

class RateLimitExceeded(Exception):
    """Exception raised when a rate limit is exceeded"""
    def __init__(self, wait_time, message=None):
        self.wait_time = wait_time
        self.message = message or f"Rate limit exceeded. Try again in {wait_time} seconds."
        super().__init__(self.message)

class RateLimiter:
    """Rate limiter to prevent abuse of bot features"""
    
    def __init__(self, max_calls: int, period: int, name: str = "generic"):
        """
        Initialize a rate limiter
        
        Parameters:
        - max_calls: Maximum number of calls allowed in the period
        - period: Time period in seconds
        - name: Name for this limiter for logging purposes
        """
        self.max_calls = max_calls
        self.period = period
        self.name = name
        self.buckets: Dict[str, List[float]] = {}
        self._cleanup_task = None
    
    def start_cleanup_task(self, bot):
        """Start the periodic cleanup task"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = bot.loop.create_task(self._cleanup_loop())
            logging.info(f"Started cleanup task for rate limiter: {self.name}")
    
    def stop_cleanup_task(self):
        """Stop the cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logging.info(f"Stopped cleanup task for rate limiter: {self.name}")
    
    async def _cleanup_loop(self):
        """Periodically clean up expired entries"""
        try:
            while True:
                await asyncio.sleep(60)  # Run cleanup every minute
                
                # Get current time once for all comparisons
                current_time = time.time()
                cleanup_count = 0
                
                # Make a copy of keys to avoid modification during iteration
                for key in list(self.buckets.keys()):
                    # Filter timestamps, keeping only those within the period
                    self.buckets[key] = [
                        ts for ts in self.buckets[key]
                        if current_time - ts < self.period
                    ]
                    
                    # Remove empty buckets
                    if not self.buckets[key]:
                        del self.buckets[key]
                        cleanup_count += 1
                
                if cleanup_count > 0:
                    logging.debug(f"Rate limiter {self.name} cleaned up {cleanup_count} buckets")
        except asyncio.CancelledError:
            logging.debug(f"Rate limiter cleanup task cancelled: {self.name}")
        except Exception as e:
            logging.error(f"Error in rate limiter cleanup task: {e}")
    
    async def check_rate_limit(self, key: str) -> Tuple[bool, int]:
        """
        Check if a key is rate limited
        
        Parameters:
        - key: Unique identifier for rate limiting (e.g., user_id or guild_id)
        
        Returns:
        - Tuple of (is_limited, wait_time_seconds)
        """
        current_time = time.time()
        
        # Initialize bucket if needed
        if key not in self.buckets:
            self.buckets[key] = []
        
        # Clear old entries
        self.buckets[key] = [
            ts for ts in self.buckets[key]
            if current_time - ts < self.period
        ]
        
        # Check if rate limited
        if len(self.buckets[key]) >= self.max_calls:
            # Calculate wait time until oldest entry expires
            wait_time = int(self.period - (current_time - self.buckets[key][0]) + 1)
            return True, max(1, wait_time)
        
        # Not rate limited, record this call
        self.buckets[key].append(current_time)
        return False, 0

# Command decorator for rate limiting
def rate_limit(calls: int, period: int, key_func=None, use_tiers=True):
    """
    Rate limit decorator for commands
    
    Parameters:
    - calls: Maximum number of calls allowed in the period
    - period: Time period in seconds
    - key_func: Optional function to generate a key from ctx (default: uses user_id)
    """
    def decorator(func):
        # Store limiter with the function
        func.__rate_limiter = RateLimiter(calls, period, name=func.__name__)
        
        @functools.wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            adjusted_calls = calls

            # Apply tier multipliers if enabled
            if use_tiers:
                guild_id = str(ctx.guild.id) if ctx.guild else "0"
                user_id = str(ctx.author.id)
                
                tier, multiplier = await get_user_tier(ctx.bot, user_id, guild_id)
                adjusted_calls = int(calls * multiplier)

            # Generate the rate limit key
            if key_func:
                key = key_func(ctx)
            else:
                # Default: limit by user ID
                key = str(ctx.author.id)
            
            # Check rate limit
            is_limited, wait_time = await func.__rate_limiter.check_rate_limit(key)
            
            # Check if they've exceeded even the adjusted limit
            actual_limit_exceeded = len(func.__rate_limiter.buckets.get(key, [])) >= adjusted_calls

            if is_limited and actual_limit_exceeded:
                logging.info(f"Rate limit hit: {self.name} for key {key}, wait time: {wait_time}s")

                await ctx.send(
                    f"⏱️ Please wait {wait_time} seconds before using this command again.",
                    delete_after=min(wait_time, 10)
                )
                raise RateLimitExceeded(wait_time)
            
            # Execute the command
            return await func(self, ctx, *args, **kwargs)
        
        return wrapper
    return decorator

# Helper functions for different rate limit key types
def user_key(ctx):
    """Rate limit by user ID"""
    return str(ctx.author.id)

def guild_key(ctx):
    """Rate limit by guild ID"""
    return str(ctx.guild.id) if ctx.guild else str(ctx.author.id)

def channel_key(ctx):
    """Rate limit by channel ID"""
    return str(ctx.channel.id)

def command_key(ctx):
    """Rate limit by command and user (prevents command spam)"""
    return f"{ctx.command.name}:{ctx.author.id}"