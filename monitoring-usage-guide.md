# How to Use the Voice XP System Monitoring Tools

This guide explains how to integrate and use the monitoring tools to track your Discord bot's performance, especially for the time-aware XP system.

## Installation Requirements

First, install the required dependency:

```bash
pip install psutil
```

This package is used for memory profiling. If not installed, memory monitoring will be disabled, but the other monitoring tools will still work.

## 1. Adding the Monitoring Code

Place the monitoring code from `monitoring-tools-implementation.py` in a new file called `utils/performance_monitoring.py`.

## 2. Integration with Your Bot

### In your main.py file:

Add these imports to the top:

```python
from utils.performance_monitoring import start_monitoring, stop_monitoring, time_function
```

Initialize monitoring during bot startup:

```python
@bot.event
async def on_ready():
    # Your existing code...
    
    # Start performance monitoring
    await start_monitoring(bot)
    logging.info("Performance monitoring started")
```

Add shutdown handling to properly stop monitoring:

```python
# In your signal_handler or cleanup function
def signal_handler(sig, frame):
    async def cleanup():
        # Your existing cleanup code...
        
        # Stop performance monitoring
        stop_monitoring()
        
        # Rest of your cleanup...
```

### 3. Add Timing to Key Functions

Decorate functions you want to track with `@time_function`:

#### In voice_activity.py:

```python
from utils.performance_monitoring import time_function

@time_function
async def handle_voice_state_update(bot, member, before, after):
    # Existing function code...

@time_function
async def handle_voice_channel_exit(guild_id, user_id, member):
    # Existing function code...

@time_function
async def calculate_event_adjusted_xp(base_xp, start_time, end_time, events):
    # Existing function code...
```

#### In levels.py:

```python
from utils.performance_monitoring import time_function

@time_function
async def award_xp_without_event_multiplier(guild_id, user_id, xp_amount, member, update_last_xp_time=False):
    # Existing function code...
```

#### Additional options for timing:

You can add custom names or always log execution times:

```python
@time_function(name="Voice_StateUpdate", log_always=True)
async def handle_voice_state_update(bot, member, before, after):
    # Function will be logged as "Voice_StateUpdate" and every call will be logged
```

## 4. Using the Performance Command

The monitoring tools add a `!!performance` command that admins can use to see current metrics:

```
!!performance
```

This command shows:
- Current and peak memory usage
- CPU usage
- Voice session statistics
- Slowest functions by average execution time
- Recent slow operations

## 5. Understanding the Logs

The monitoring tools add these log entries:

### Memory Logging (every 15 minutes)

```
INFO: Memory usage: 85.32 MB, Peak: 112.47 MB
```

If memory grows significantly:

```
WARNING: Memory growing at 5.23 MB/hour. Possible leak?
```

### Performance Timing (when functions exceed threshold)

```
INFO: Performance: handle_voice_state_update executed in 152.35ms
```

### Session Metrics (hourly)

```
INFO: Voice session metrics: 15 active sessions | 12 with history | 348 total history entries | 29.0 avg entries per session | Oldest: 3.5 hours | Avg age: 45.2 minutes | States: {'active': 8, 'muted': 4, 'watching': 3}
```

## 6. Customizing Monitoring Parameters

You can adjust these constants at the top of the monitoring file:

```python
# Constants for monitoring
MEMORY_LOG_INTERVAL = 15 * 60  # Log memory usage every 15 minutes
TIMING_LOG_THRESHOLD = 100  # Log timing for operations taking over 100ms
SESSION_METRICS_INTERVAL = 60 * 60  # Log session metrics hourly
```

For busy servers, you might want to:
- Increase `MEMORY_LOG_INTERVAL` to reduce log noise
- Increase `TIMING_LOG_THRESHOLD` to only log very slow operations
- Adjust `SESSION_METRICS_INTERVAL` based on your activity patterns

## 7. Advanced Usage

### Timing specific code blocks

You can time specific parts of a function:

```python
from utils.performance_monitoring import time_function

async def complex_function():
    # Some code...
    
    @time_function(name="critical_calculation")
    async def _timed_calculation():
        # Intensive calculation...
        return result
    
    result = await _timed_calculation()
    
    # Rest of function...
```

### Memory snapshots during events

You can log memory usage at critical points:

```python
import psutil
import os
from utils.performance_monitoring import PSUTIL_AVAILABLE

def log_memory_snapshot(label):
    if not PSUTIL_AVAILABLE:
        return
    
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / 1024 / 1024
    logging.info(f"Memory snapshot [{label}]: {memory_mb:.2f} MB")

# Usage:
log_memory_snapshot("Before voice processing")
# ... do processing ...
log_memory_snapshot("After voice processing")
```

## 8. Troubleshooting

### If memory usage keeps growing

Check for:
- Voice sessions that never get cleaned up
- Growing voice session histories
- XP events that don't expire properly

### If functions are consistently slow

Focus optimization on:
- `calculate_event_adjusted_xp` - This handles time-slicing
- `handle_voice_channel_exit` - This processes accumulated XP
- Database operations - These can be bottlenecks

### If logs show warnings

Address performance warnings promptly:
- "Large average history size" - You may need to reduce `MAX_STATE_HISTORY_ENTRIES`
- "Very long voice session" - Check for session cleanup issues
- "Memory growing" - Look for memory leaks in your code

By monitoring these metrics regularly, you can ensure your timestamp-aware XP system remains efficient and reliable.
