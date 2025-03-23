import time
import logging
import functools
import discord
import asyncio
from discord.ext import commands, tasks
from modules.voice_activity import voice_sessions

# For memory profiling
try:
    import psutil
    import os
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available. Install with: pip install psutil")

# Constants for monitoring
MEMORY_LOG_INTERVAL = 15 * 60  # Log memory usage every 15 minutes
TIMING_LOG_THRESHOLD = 100  # Log timing for operations taking over 100ms
SESSION_METRICS_INTERVAL = 60 * 60  # Log session metrics hourly

# Global tracking
performance_data = {
    "function_times": {},  # Average execution times by function
    "memory_samples": [],  # Memory usage over time
    "peak_memory": 0,      # Peak memory usage
    "slow_operations": [],  # Record of slowest operations
}

# ======= 1. Memory Profiling =======

@tasks.loop(seconds=MEMORY_LOG_INTERVAL)
async def memory_usage_monitor():
    """Periodically log memory usage statistics"""
    if not PSUTIL_AVAILABLE:
        return
        
    try:
        # Get process memory info
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        
        # Update tracking
        performance_data["memory_samples"].append((time.time(), memory_mb))
        
        # Keep only last 24 hours of samples
        cutoff_time = time.time() - (24 * 60 * 60)
        performance_data["memory_samples"] = [
            sample for sample in performance_data["memory_samples"]
            if sample[0] >= cutoff_time
        ]
        
        # Track peak memory
        if memory_mb > performance_data["peak_memory"]:
            performance_data["peak_memory"] = memory_mb
            logging.warning(f"New peak memory usage: {memory_mb:.2f} MB")
        
        # Log memory usage
        logging.info(f"Memory usage: {memory_mb:.2f} MB, Peak: {performance_data['peak_memory']:.2f} MB")
        
        # Check memory growth
        if len(performance_data["memory_samples"]) > 2:
            first_sample = performance_data["memory_samples"][0]
            last_sample = performance_data["memory_samples"][-1]
            time_diff_hours = (last_sample[0] - first_sample[0]) / 3600
            memory_diff = last_sample[1] - first_sample[1]
            
            if time_diff_hours > 1 and memory_diff > 50:  # 50MB growth over 1+ hour
                growth_rate = memory_diff / time_diff_hours
                logging.warning(f"Memory growing at {growth_rate:.2f} MB/hour. Possible leak?")
        
    except Exception as e:
        logging.error(f"Error in memory monitoring: {e}")

# ======= 2. Performance Timing =======

def time_function(function=None, *, name=None, log_always=False):
    """
    Decorator to time function execution
    
    Parameters:
    - name: Optional custom name for the function in logs
    - log_always: If True, log every call regardless of duration
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                return result
            finally:
                elapsed_ms = (time.time() - start_time) * 1000
                func_name = name or func.__name__
                
                # Update average execution time
                if func_name not in performance_data["function_times"]:
                    performance_data["function_times"][func_name] = {"count": 0, "total_ms": 0}
                
                performance_data["function_times"][func_name]["count"] += 1
                performance_data["function_times"][func_name]["total_ms"] += elapsed_ms
                
                # Track slow operations
                if elapsed_ms > TIMING_LOG_THRESHOLD:
                    performance_data["slow_operations"].append({
                        "function": func_name,
                        "time_ms": elapsed_ms,
                        "timestamp": time.time()
                    })
                    
                    # Keep only the 100 most recent slow operations
                    if len(performance_data["slow_operations"]) > 100:
                        performance_data["slow_operations"].pop(0)
                
                # Log execution time if slow or if log_always is True
                if log_always or elapsed_ms > TIMING_LOG_THRESHOLD:
                    logging.info(f"Performance: {func_name} executed in {elapsed_ms:.2f}ms")
        
        # For synchronous functions
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed_ms = (time.time() - start_time) * 1000
                func_name = name or func.__name__
                
                # Update average execution time
                if func_name not in performance_data["function_times"]:
                    performance_data["function_times"][func_name] = {"count": 0, "total_ms": 0}
                
                performance_data["function_times"][func_name]["count"] += 1
                performance_data["function_times"][func_name]["total_ms"] += elapsed_ms
                
                # Track slow operations
                if elapsed_ms > TIMING_LOG_THRESHOLD:
                    performance_data["slow_operations"].append({
                        "function": func_name,
                        "time_ms": elapsed_ms,
                        "timestamp": time.time()
                    })
                    
                    # Keep only the 100 most recent slow operations
                    if len(performance_data["slow_operations"]) > 100:
                        performance_data["slow_operations"].pop(0)
                
                # Log execution time if slow or if log_always is True
                if log_always or elapsed_ms > TIMING_LOG_THRESHOLD:
                    logging.info(f"Performance: {func_name} executed in {elapsed_ms:.2f}ms")
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return wrapper
        else:
            return sync_wrapper
    
    # Handle both @time_function and @time_function() syntax
    if function is None:
        return decorator
    else:
        return decorator(function)

# ======= 3. Session Metrics =======

@tasks.loop(seconds=SESSION_METRICS_INTERVAL)
async def session_metrics_monitor():
    """Periodically log voice session metrics"""
    try:
        # Import the voice sessions dict - adjust import path as needed
        
        
        if not voice_sessions:
            logging.info("Session metrics: No active voice sessions")
            return
            
        # Basic metrics
        total_sessions = len(voice_sessions)
        sessions_with_history = sum(1 for session in voice_sessions.values() if "state_history" in session)
        
        # History metrics
        total_history_entries = sum(
            len(session.get("state_history", [])) 
            for session in voice_sessions.values()
        )
        avg_history_size = total_history_entries / sessions_with_history if sessions_with_history > 0 else 0
        
        # State distribution
        states = {}
        for session in voice_sessions.values():
            state = session.get("current_state", "unknown")
            states[state] = states.get(state, 0) + 1
        
        # Session age metrics
        current_time = time.time()
        session_ages = []
        for session in voice_sessions.values():
            if "state_start_time" in session:
                age = current_time - session["state_start_time"]
                session_ages.append(age)
        
        oldest_session = max(session_ages) if session_ages else 0
        avg_session_age = sum(session_ages) / len(session_ages) if session_ages else 0
        
        # Log all metrics
        logging.info(
            f"Voice session metrics: {total_sessions} active sessions | "
            f"{sessions_with_history} with history | "
            f"{total_history_entries} total history entries | "
            f"{avg_history_size:.1f} avg entries per session | "
            f"Oldest: {oldest_session/3600:.1f} hours | "
            f"Avg age: {avg_session_age/60:.1f} minutes | "
            f"States: {states}"
        )
        
        # Alert on potential issues
        if oldest_session > 12 * 3600:  # 12 hours
            logging.warning(f"Very long voice session detected: {oldest_session/3600:.1f} hours")
            
        if avg_history_size > 50:  # Large history average
            logging.warning(f"Large average history size: {avg_history_size:.1f} entries")
            
    except Exception as e:
        logging.error(f"Error in session metrics monitoring: {e}")

# ======= Integration Functions =======

async def start_monitoring(bot):
    """Start all monitoring tasks"""
    # Start memory monitoring if available
    if PSUTIL_AVAILABLE:
        memory_usage_monitor.start()
        logging.info("Memory usage monitoring started")
    
    # Start session metrics monitoring
    session_metrics_monitor.start()
    logging.info("Voice session metrics monitoring started")
    
    # Create a monitoring status command
    @bot.command(name="performance", hidden=True)
    @commands.has_permissions(administrator=True)
    async def performance_status(ctx):
        """Show performance metrics for the bot"""
        if not PSUTIL_AVAILABLE:
            psutil_status = "⚠️ psutil not installed (memory metrics unavailable)"
        else:
            psutil_status = "✅ psutil available (memory metrics enabled)"
            
        # Create an embed with performance data
        embed = discord.Embed(
            title="🔍 Performance Monitoring",
            description="Current performance metrics for the bot",
            color=discord.Color.blue()
        )
        
        # Memory metrics
        if PSUTIL_AVAILABLE:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            embed.add_field(
                name="Memory Usage",
                value=f"Current: {memory_mb:.2f} MB\nPeak: {performance_data['peak_memory']:.2f} MB",
                inline=True
            )
            
            # CPU usage
            cpu_percent = process.cpu_percent(interval=0.5)
            embed.add_field(
                name="CPU Usage",
                value=f"Current: {cpu_percent:.1f}%",
                inline=True
            )
        
        # Voice session metrics
        try:
            
            
            total_sessions = len(voice_sessions)
            total_history = sum(
                len(session.get("state_history", [])) 
                for session in voice_sessions.values()
            )
            
            embed.add_field(
                name="Voice Sessions",
                value=f"Active: {total_sessions}\nHistory entries: {total_history}",
                inline=True
            )
        except:
            embed.add_field(
                name="Voice Sessions",
                value="Unable to retrieve voice session data",
                inline=True
            )
        
        # Function timing metrics
        if performance_data["function_times"]:
            # Sort by average time
            sorted_funcs = sorted(
                performance_data["function_times"].items(),
                key=lambda x: x[1]["total_ms"] / x[1]["count"],
                reverse=True
            )
            
            # Show top 5 slowest functions
            timing_text = "\n".join([
                f"`{name}`: {data['total_ms']/data['count']:.1f}ms avg ({data['count']} calls)"
                for name, data in sorted_funcs[:5]
            ])
            
            embed.add_field(
                name="Slowest Functions (Average)",
                value=timing_text,
                inline=False
            )
        
        # Recent slow operations
        if performance_data["slow_operations"]:
            recent_slow = sorted(
                performance_data["slow_operations"],
                key=lambda x: x["timestamp"],
                reverse=True
            )[:5]
            
            slow_text = "\n".join([
                f"`{op['function']}`: {op['time_ms']:.1f}ms"
                for op in recent_slow
            ])
            
            embed.add_field(
                name="Recent Slow Operations",
                value=slow_text,
                inline=False
            )
        
        # Add footer with dependencies
        embed.set_footer(text=f"Monitoring status: {psutil_status}")
        
        await ctx.send(embed=embed)
    
    return True

def stop_monitoring():
    """Stop all monitoring tasks"""
    if memory_usage_monitor.is_running():
        memory_usage_monitor.cancel()
    
    if session_metrics_monitor.is_running():
        session_metrics_monitor.cancel()
    
    logging.info("Performance monitoring stopped")

# ======= Example Usage =======

# Start monitoring in your bot setup:
# await start_monitoring(bot)

# Decorate functions you want to time:
# @time_function
# async def process_voice_state_update(guild_id, user_id, state):
#     ...

# Stop monitoring during shutdown:
# stop_monitoring()