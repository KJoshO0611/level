# utils/memory_cache.py
import threading
import time
import logging
import sys
import weakref
import gc

class MemoryAwareCache:
    """
    A thread-safe cache with memory size tracking, TTL, and multiple eviction policies.
    Supports weak references for large objects to facilitate GC.
    """
    def __init__(self, name="cache", maxsize=100, max_memory_mb=100, ttl=3600, weak_refs=False):
        """
        Initialize a memory-aware cache
        
        Parameters:
        - name: Name for this cache (for logging)
        - maxsize: Maximum number of items
        - max_memory_mb: Maximum memory usage in MB
        - ttl: Time-to-live in seconds
        - weak_refs: Whether to store values as weak references
        """
        self.name = name
        self.cache = {}  # {key: (value, timestamp, size_bytes)}
        self.maxsize = maxsize
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.ttl = ttl
        self.weak_refs = weak_refs
        self.current_memory = 0
        self.lock = threading.RLock()
        self._cleanup_counter = 0
        self.hits = 0
        self.misses = 0
        self._last_cleanup_time = time.time()
        
        # Create a separate dictionary for tracking hits to inform eviction policy
        # {key: hit_count}
        self.hit_counts = {}
        
        logging.info(f"Initialized {name} cache: maxsize={maxsize}, "
                    f"max_memory={max_memory_mb}MB, ttl={ttl}s, "
                    f"weak_refs={weak_refs}")
    
    def _estimate_size(self, value):
        """
        Estimate the memory size of an object in bytes.
        
        For special types like Cairo surfaces, uses custom size estimation.
        For other types, uses sys.getsizeof with a minimum size.
        """
        if value is None:
            return 0
            
        # For Cairo surfaces, estimate based on dimensions and format
        if hasattr(value, 'get_width') and hasattr(value, 'get_height') and hasattr(value, 'get_format'):
            try:
                width = value.get_width()
                height = value.get_height()
                
                # Bytes per pixel depends on format:
                # ARGB32/RGB24: 4 bytes, A8: 1 byte, etc.
                format_name = str(value.get_format())
                
                bytes_per_pixel = 4  # Default for ARGB32
                if 'A8' in format_name:
                    bytes_per_pixel = 1
                elif 'RGB24' in format_name:
                    bytes_per_pixel = 3
                
                # Calculate size plus some overhead
                return (width * height * bytes_per_pixel) + 1024
            except Exception as e:
                logging.debug(f"Error estimating Cairo surface size: {e}")
                # Fallback estimate for Cairo surfaces: 1MB
                return 1024 * 1024
        
        # For PIL Images
        if hasattr(value, 'width') and hasattr(value, 'height') and hasattr(value, 'mode'):
            try:
                width = value.width
                height = value.height
                mode = value.mode
                
                # Bytes per pixel depends on mode:
                # 'RGBA': 4 bytes, 'RGB': 3 bytes, 'L': 1 byte, etc.
                bytes_per_pixel = len(mode)
                if bytes_per_pixel == 0:  # Safety check
                    bytes_per_pixel = 4  # Default
                
                # Calculate size plus some overhead
                return (width * height * bytes_per_pixel) + 1024
            except Exception as e:
                logging.debug(f"Error estimating PIL Image size: {e}")
                # Fallback estimate: 500KB
                return 500 * 1024
        
        # For bytes or bytearrays, use their length
        if isinstance(value, (bytes, bytearray)):
            return len(value)
            
        # For other types, use sys.getsizeof with a minimum size
        try:
            size = sys.getsizeof(value)
            return max(size, 1024)  # Minimum 1KB to account for dictionary overhead
        except Exception:
            # Fallback for types that don't support getsizeof
            return 10 * 1024  # 10KB default
    
    def _should_cleanup(self):
        """Check if cleanup should be triggered based on various factors"""
        # Cleanup based on counter (every 100 operations)
        if self._cleanup_counter >= 100:
            return True
            
        # Cleanup if it's been more than 5 minutes since last cleanup
        if time.time() - self._last_cleanup_time > 300:
            return True
            
        # Cleanup if memory usage is above 90% of limit
        if self.current_memory > (self.max_memory_bytes * 0.9):
            return True
            
        # Cleanup if item count is above 90% of limit
        if len(self.cache) > (self.maxsize * 0.9):
            return True
            
        return False
    
    def _maybe_cleanup(self):
        """Run cleanup if needed based on heuristics"""
        self._cleanup_counter += 1
        
        if self._should_cleanup():
            self._cleanup()
            self._cleanup_counter = 0
            self._last_cleanup_time = time.time()
    
    def _cleanup(self):
        """
        Remove expired entries and enforce memory/size limits
        Uses a weighted algorithm that considers:
        - Age of entry
        - Frequency of access
        - Size of entry
        """
        with self.lock:
            # Track how many items and how much memory was freed
            removed_count = 0
            freed_memory = 0
            current_time = time.time()
            
            # 1. First pass: remove expired entries
            expired_keys = []
            for key, (value_ref, timestamp, size) in list(self.cache.items()):
                # Remove if TTL has expired
                if current_time - timestamp > self.ttl:
                    expired_keys.append(key)
                    removed_count += 1
                    freed_memory += size
                
                # If using weak references, check if the reference is dead
                if self.weak_refs:
                    value = value_ref() if callable(value_ref) else value_ref
                    if value is None:  # Reference is dead
                        expired_keys.append(key)
                        removed_count += 1
                        freed_memory += size
            
            # Remove all expired keys
            for key in expired_keys:
                self.cache.pop(key, None)
                self.hit_counts.pop(key, None)
            
            # Update current memory usage
            self.current_memory -= freed_memory
            
            # 2. If still over limits, use eviction policy
            if len(self.cache) > self.maxsize or self.current_memory > self.max_memory_bytes:
                # Calculate scores for each entry (higher score = more likely to be removed)
                scores = {}
                for key, (_, timestamp, size) in self.cache.items():
                    # Factors:
                    age_factor = (current_time - timestamp) / self.ttl  # 0-1 range
                    hits = self.hit_counts.get(key, 1)
                    hit_factor = 1.0 / (hits + 1)  # Lower is better
                    size_factor = size / max(self.current_memory, 1)  # Size relative to total
                    
                    # Weighted score (adjust weights based on preference)
                    scores[key] = (0.4 * age_factor) + (0.4 * hit_factor) + (0.2 * size_factor)
                
                # Sort keys by score (descending)
                sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
                
                # Remove items until within limits
                for key in sorted_keys:
                    if len(self.cache) <= self.maxsize and self.current_memory <= self.max_memory_bytes:
                        break
                        
                    _, _, size = self.cache.pop(key, (None, None, 0))
                    self.hit_counts.pop(key, None)
                    self.current_memory -= size
                    removed_count += 1
                    freed_memory += size
            
            # Log cleanup results if significant
            if removed_count > 0:
                logging.debug(f"{self.name} cache cleanup: removed {removed_count} items, "
                             f"freed {freed_memory/1024/1024:.2f}MB, "
                             f"current: {len(self.cache)} items, {self.current_memory/1024/1024:.2f}MB")
                
            # Suggest garbage collection if a lot of memory was freed
            if freed_memory > 10 * 1024 * 1024:  # 10MB
                gc.collect()
    
    def get(self, key):
        """Get an item from cache if it exists and is not expired"""
        with self.lock:
            if key in self.cache:
                value_ref, timestamp, _ = self.cache[key]
                current_time = time.time()
                
                # Check if expired
                if current_time - timestamp > self.ttl:
                    self.cache.pop(key, None)
                    self.hit_counts.pop(key, None)
                    self.misses += 1
                    return None
                
                # Resolve weak reference if needed
                value = value_ref() if self.weak_refs and callable(value_ref) else value_ref
                
                # If weak reference has been collected, treat as miss
                if self.weak_refs and value is None:
                    self.cache.pop(key, None)
                    self.hit_counts.pop(key, None)
                    self.misses += 1
                    return None
                
                # Update hit count for this key
                self.hit_counts[key] = self.hit_counts.get(key, 0) + 1
                self.hits += 1
                
                # Optionally update timestamp to extend TTL (comment out if not desired)
                # self.cache[key] = (value_ref, current_time, self.cache[key][2])
                
                return value
            
            self.misses += 1
            return None
    
    def set(self, key, value):
        """Store an item in cache with size tracking"""
        with self.lock:
            # If value is None, don't cache it
            if value is None:
                return False
                
            # Check if already in cache to update size tracking
            old_size = 0
            if key in self.cache:
                _, _, old_size = self.cache[key]
                self.current_memory -= old_size
            
            # Estimate size of new value
            size = self._estimate_size(value)
            
            # Store value as weak reference if configured
            value_ref = weakref.ref(value) if self.weak_refs else value
            
            # Update cache
            self.cache[key] = (value_ref, time.time(), size)
            self.current_memory += size
            
            # Reset hit count for this key
            self.hit_counts[key] = 1
            
            # Cleanup if needed
            self._maybe_cleanup()
            
            return True
    
    def invalidate(self, key):
        """Remove specific key from cache"""
        with self.lock:
            if key in self.cache:
                _, _, size = self.cache.pop(key, (None, None, 0))
                self.hit_counts.pop(key, None)
                self.current_memory -= size
                return True
            return False
    
    def clear(self):
        """Clear all entries from cache"""
        with self.lock:
            self.cache.clear()
            self.hit_counts.clear()
            self.current_memory = 0
            self._cleanup_counter = 0
            self.hits = 0
            self.misses = 0
    
    def __len__(self):
        """Return current cache size"""
        return len(self.cache)
    
    def stats(self):
        """Return cache statistics"""
        with self.lock:
            hit_ratio = self.hits / max(self.hits + self.misses, 1)
            return {
                "name": self.name,
                "items": len(self.cache),
                "max_items": self.maxsize,
                "memory_mb": self.current_memory / 1024 / 1024,
                "max_memory_mb": self.max_memory_bytes / 1024 / 1024,
                "ttl": self.ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio": hit_ratio,
                "weak_refs": self.weak_refs
            }