"""
Database operations for Discord Scheduled Event integration.
"""
import logging
from datetime import datetime
from .core import get_connection

# Default settings
DEFAULT_EVENT_SETTINGS = {
    "enable_auto_boosts": False,
    "default_boost_voice": 1.5,
    "default_boost_stage": 1.2,
    "default_boost_external": 1.1,
    "enable_attendance_rewards": False,
    "attendance_bonus_xp": 50,
    "attendance_achievement_id": None
}

async def get_guild_event_settings(guild_id: str) -> dict:
    """Get the event integration settings for a guild."""
    query = "SELECT * FROM guild_event_settings WHERE guild_id = $1"
    async with get_connection() as conn:
        settings = await conn.fetchrow(query, guild_id)
        if settings:
            return dict(settings)
        else:
            # Return defaults if no specific settings found
            return DEFAULT_EVENT_SETTINGS.copy()

async def update_guild_event_settings(guild_id: str, settings: dict):
    """Update event integration settings for a guild."""
    # Ensure only valid keys are updated
    valid_keys = DEFAULT_EVENT_SETTINGS.keys()
    update_data = {k: settings[k] for k in valid_keys if k in settings}

    if not update_data:
        logging.warning(f"No valid event settings provided for update in guild {guild_id}")
        return

    set_clauses = [f"{key} = ${i+2}" for i, key in enumerate(update_data.keys())]
    values = [guild_id] + list(update_data.values())

    query = f"""
    INSERT INTO guild_event_settings (guild_id, {', '.join(update_data.keys())})
    VALUES ($1, {', '.join([f'${i+2}' for i in range(len(update_data))])})
    ON CONFLICT (guild_id) DO UPDATE SET {', '.join(set_clauses)}
    """
    async with get_connection() as conn:
        await conn.execute(query, *values)
    logging.info(f"Updated event settings for guild {guild_id}: {update_data}")

async def log_scheduled_event(guild_id: str, event_id: str, name: str, description: str, start_time: datetime, end_time: datetime, event_type: str, status: str, creator_id: str):
    """Log or update a Discord scheduled event in the database."""
    # Convert datetime objects to Unix timestamps (float)
    start_timestamp = start_time.timestamp() if start_time else None
    end_timestamp = end_time.timestamp() if end_time else None
    
    query = """
    INSERT INTO discord_scheduled_events (event_id, guild_id, name, description, start_time, end_time, event_type, status, creator_id, updated_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
    ON CONFLICT (event_id) DO UPDATE SET
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        start_time = EXCLUDED.start_time,
        end_time = EXCLUDED.end_time,
        event_type = EXCLUDED.event_type,
        status = EXCLUDED.status,
        updated_at = NOW()
    RETURNING internal_id
    """
    async with get_connection() as conn:
        internal_id = await conn.fetchval(query, event_id, guild_id, name, description, start_timestamp, end_timestamp, event_type, status, creator_id)
    logging.info(f"Logged/Updated Discord event {event_id} ({name}) for guild {guild_id}. Status: {status}")
    return internal_id

async def update_scheduled_event_status(event_id: str, status: str):
    """Update the status of a Discord scheduled event."""
    query = "UPDATE discord_scheduled_events SET status = $1, updated_at = NOW() WHERE event_id = $2"
    async with get_connection() as conn:
        await conn.execute(query, status, event_id)
    logging.info(f"Updated status for Discord event {event_id} to {status}")

async def link_xp_boost_to_event(event_id: str, boost_event_id: int):
    """Link an internal XP boost event to a Discord scheduled event."""
    query = "UPDATE discord_scheduled_events SET associated_boost_id = $1 WHERE event_id = $2"
    async with get_connection() as conn:
        await conn.execute(query, boost_event_id, event_id)
    logging.info(f"Linked XP boost {boost_event_id} to Discord event {event_id}")

async def get_scheduled_event_by_id(event_id: str) -> dict | None:
    """Get details of a logged scheduled event."""
    query = "SELECT * FROM discord_scheduled_events WHERE event_id = $1"
    async with get_connection() as conn:
        event_data = await conn.fetchrow(query, event_id)
        return dict(event_data) if event_data else None

async def record_event_attendance(event_id: str, guild_id: str, user_id: str, status: str = "active"):
    """Record a user's attendance (joining) for an event."""
    query = """
    INSERT INTO event_attendance (event_id, guild_id, user_id, joined_at, status)
    VALUES ($1, $2, $3, NOW(), $4)
    ON CONFLICT (event_id, user_id) DO NOTHING
    """
    async with get_connection() as conn:
        await conn.execute(query, event_id, guild_id, user_id, status)
    logging.debug(f"Recorded attendance for user {user_id} at event {event_id} in guild {guild_id}, status: {status}")

async def get_event_attendees(event_id: str) -> list[dict]:
    """Get all users recorded as attending an event."""
    query = "SELECT user_id, joined_at FROM event_attendance WHERE event_id = $1"
    async with get_connection() as conn:
        attendees = await conn.fetch(query, event_id)
        return [dict(row) for row in attendees]

async def get_user_event_attendance_count(guild_id: str, user_id: str) -> int:
    """Get the total number of events a user has attended in a guild."""
    # Note: This counts unique events the user joined, based on insertion into event_attendance
    query = "SELECT COUNT(*) FROM event_attendance WHERE guild_id = $1 AND user_id = $2"
    async with get_connection() as conn:
        count = await conn.fetchval(query, guild_id, user_id)
        return count or 0

async def get_guild_event_stats(guild_id: str) -> dict:
    """Get basic event statistics for a guild."""
    stats = {
        "total_events_logged": 0,
        "total_attendance_records": 0,
        "events_by_type": {},
        "events_by_status": {}
    }
    async with get_connection() as conn:
        # Total events logged
        stats["total_events_logged"] = await conn.fetchval(
            "SELECT COUNT(*) FROM discord_scheduled_events WHERE guild_id = $1", guild_id
        ) or 0

        # Total attendance records (individual joins)
        stats["total_attendance_records"] = await conn.fetchval(
            "SELECT COUNT(*) FROM event_attendance WHERE guild_id = $1", guild_id
        ) or 0

        # Count by type
        type_counts = await conn.fetch(
            "SELECT event_type, COUNT(*) as count FROM discord_scheduled_events WHERE guild_id = $1 GROUP BY event_type", guild_id
        )
        stats["events_by_type"] = {row["event_type"]: row["count"] for row in type_counts}

        # Count by status
        status_counts = await conn.fetch(
            "SELECT status, COUNT(*) as count FROM discord_scheduled_events WHERE guild_id = $1 GROUP BY status", guild_id
        )
        stats["events_by_status"] = {row["status"]: row["count"] for row in status_counts}

    return stats 