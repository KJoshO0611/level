import time
import asyncio
import logging
import io
from collections import OrderedDict
import aiohttp

class AvatarCache:
    """LRU cache for Discord user avatars with time expiration"""
    
    def __init__(self, max_size=100, ttl=3600):
        """
        Initialize the avatar cache
        
        Parameters:
        - max_size: Maximum number of avatars to store in cache
        - ttl: Time-to-live in seconds (default: 1 hour)
        """
        self.cache = OrderedDict()  # {user_id: (avatar_bytes, timestamp, avatar_hash)}
        self.max_size = max_size
        self.ttl = ttl
        self._cleanup_task = None
    
    def start_cleanup_task(self, loop=None):
        """Start periodic cleanup of expired cache entries"""
        if self._cleanup_task is None:
            loop = loop or asyncio.get_event_loop()
            self._cleanup_task = loop.create_task(self._periodic_cleanup())
            logging.info(f"Avatar cache cleanup task started (TTL: {self.ttl}s, Max Size: {self.max_size})")
    
    async def _periodic_cleanup(self):
        """Periodically remove expired entries from cache"""
        while True:
            try:
                # Run cleanup every 10 minutes
                await asyncio.sleep(600)
                self.remove_expired()
            except Exception as e:
                logging.error(f"Error in avatar cache cleanup: {e}")
    
    def remove_expired(self):
        """Remove expired entries from the cache"""
        current_time = time.time()
        expired_keys = [
            user_id for user_id, (_, timestamp, _) in self.cache.items()
            if current_time - timestamp > self.ttl
        ]
        
        for user_id in expired_keys:
            self.cache.pop(user_id, None)
        
        if expired_keys:
            logging.debug(f"Removed {len(expired_keys)} expired avatars from cache")
    
    def get(self, user_id, avatar_hash=None):
        """
        Get avatar from cache if it exists and is not expired
        
        Parameters:
        - user_id: Discord user ID
        - avatar_hash: Current avatar hash to verify freshness
        
        Returns:
        - bytes or None: The avatar bytes, or None if not found or outdated
        """
        if user_id in self.cache:
            avatar_bytes, timestamp, cached_hash = self.cache[user_id]
            current_time = time.time()
            
            # Check if expired
            if current_time - timestamp > self.ttl:
                del self.cache[user_id]
                return None
            
            # Check if avatar changed (hash mismatch)
            if avatar_hash and cached_hash != avatar_hash:
                del self.cache[user_id]
                return None
            
            # Move to end (mark as recently used)
            self.cache.move_to_end(user_id)
            return avatar_bytes
        
        return None
    
    def set(self, user_id, avatar_bytes, avatar_hash=None):
        """
        Store avatar in cache
        
        Parameters:
        - user_id: Discord user ID
        - avatar_bytes: Avatar image data
        - avatar_hash: Avatar hash for freshness checks
        """
        # If at capacity, remove least recently used item
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        
        self.cache[user_id] = (avatar_bytes, time.time(), avatar_hash)
        # Move to end (mark as recently used)
        self.cache.move_to_end(user_id)
    
    def invalidate(self, user_id):
        """Remove specific user from cache"""
        if user_id in self.cache:
            del self.cache[user_id]
            return True
        return False
    
    def clear(self):
        """Clear all entries from cache"""
        self.cache.clear()
    
    def __len__(self):
        """Return current cache size"""
        return len(self.cache)
    
    def stats(self):
        """Return cache statistics"""
        current_time = time.time()
        avg_age = 0
        if self.cache:
            avg_age = sum(current_time - timestamp for _, timestamp, _ in self.cache.values()) / len(self.cache)
        
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl": self.ttl,
            "average_age": avg_age
        }

# Create global instance
avatar_cache = AvatarCache(max_size=200, ttl=3600)

async def get_cached_avatar(member, bot=None):
    """
    Get avatar for a Discord member, using cache when possible
    
    Parameters:
    - member: discord.Member object
    - bot: Optional bot instance (not used but included for compatibility)
    
    Returns:
    - bytes: Avatar image data
    """
    if not member:
        return None
        
    user_id = str(member.id)
    
    # Get avatar hash for freshness check
    avatar_hash = None
    if hasattr(member, 'guild_avatar') and member.guild_avatar:
        avatar_hash = member.guild_avatar.key
    elif member.avatar:
        avatar_hash = member.avatar.key
    
    # Try to get from cache first
    cached_avatar = avatar_cache.get(user_id, avatar_hash)
    if cached_avatar:
        return cached_avatar
    
    # Otherwise download the avatar
    try:
        avatar_url = None
        if hasattr(member, 'guild_avatar') and member.guild_avatar:
            avatar_url = member.guild_avatar.url
        elif member.avatar:
            avatar_url = member.avatar.url
        else:
            avatar_url = member.default_avatar.url
        
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()
                    
                    # Store in cache
                    avatar_cache.set(user_id, avatar_bytes, avatar_hash)
                    
                    return avatar_bytes
                else:
                    logging.warning(f"Failed to download avatar for {member.name} (status: {resp.status})")
                    return None
    except Exception as e:
        logging.error(f"Error downloading avatar for {member.name}: {e}")
        return None