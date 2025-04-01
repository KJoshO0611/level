"""
Migration for adding Discord Scheduled Event integration tables.
"""

APPLY_SQL = """
-- Table to store guild-specific settings for event integration
CREATE TABLE IF NOT EXISTS guild_event_settings (
    guild_id VARCHAR(255) PRIMARY KEY,
    enable_auto_boosts BOOLEAN NOT NULL DEFAULT FALSE,
    default_boost_voice REAL NOT NULL DEFAULT 1.5,
    default_boost_stage REAL NOT NULL DEFAULT 1.2,
    default_boost_external REAL NOT NULL DEFAULT 1.1,
    enable_attendance_rewards BOOLEAN NOT NULL DEFAULT FALSE,
    attendance_bonus_xp INTEGER NOT NULL DEFAULT 50,
    attendance_achievement_id VARCHAR(255) -- Link to an achievement ID if desired
);

-- Table to log Discord's scheduled events
CREATE TABLE IF NOT EXISTS discord_scheduled_events (
    internal_id SERIAL PRIMARY KEY, -- Internal identifier
    event_id VARCHAR(255) UNIQUE NOT NULL, -- Discord's event ID
    guild_id VARCHAR(255) NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    event_type VARCHAR(50) NOT NULL, -- e.g., 'VOICE', 'STAGE_INSTANCE', 'EXTERNAL'
    status VARCHAR(50) NOT NULL, -- e.g., 'SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED'
    creator_id VARCHAR(255),
    associated_boost_id INTEGER, -- Link to the xp_boost_events table
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (associated_boost_id) REFERENCES xp_boost_events(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_discord_events_guild_status ON discord_scheduled_events (guild_id, status);
CREATE INDEX IF NOT EXISTS idx_discord_events_start_time ON discord_scheduled_events (start_time);

-- Table to track user attendance at events
CREATE TABLE IF NOT EXISTS event_attendance (
    attendance_id SERIAL PRIMARY KEY,
    event_id VARCHAR(255) NOT NULL REFERENCES discord_scheduled_events(event_id) ON DELETE CASCADE,
    guild_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    join_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (event_id, user_id) -- Prevent duplicate attendance records per event
);

CREATE INDEX IF NOT EXISTS idx_event_attendance_guild_user ON event_attendance (guild_id, user_id);

"""

REVERT_SQL = """
DROP TABLE IF EXISTS event_attendance;
DROP TABLE IF EXISTS discord_scheduled_events;
DROP TABLE IF EXISTS guild_event_settings;
"""

# Optional: Add any validation logic here if needed
def validate_migration(connection):
    """Placeholder for validation logic before/after applying."""
    pass 