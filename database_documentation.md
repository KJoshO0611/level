# Discord Bot Database Documentation

## Overview

This document provides comprehensive details about the database architecture used in the Discord leveling bot. The database stores user information, experience points, achievements, quest progress, server configurations, and other essential data for the bot's functionality.

## Database Schema

### Tables

#### 1. **levels**
Stores user XP and leveling information.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| guild_id | TEXT | Discord server ID |
| user_id | TEXT | Discord user ID |
| xp | INTEGER | Total experience points |
| level | INTEGER | Current level |
| messages | INTEGER | Total messages sent (for XP calculations) |
| voice_time_seconds | INTEGER | Time spent in voice channels (in seconds) |
| total_messages | INTEGER | Total messages ever sent |
| total_reactions | INTEGER | Total reactions added |
| commands_used | INTEGER | Total commands used |
| last_message_time | TIMESTAMP | Timestamp of last message (for rate limiting) |

#### 2. **quests**
Stores quest definitions.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| guild_id | TEXT | Discord server ID |
| name | TEXT | Quest name |
| description | TEXT | Quest description |
| quest_type | TEXT | Type of quest (daily, weekly, special, event, challenge) |
| requirement_type | TEXT | Type of activity required (total_messages, total_reactions, voice_time_seconds, commands_used) |
| requirement_value | INTEGER | Amount required to complete |
| reward_xp | INTEGER | XP awarded upon completion |
| reward_multiplier | FLOAT | XP multiplier awarded (1.0 = no boost) |
| active | BOOLEAN | Whether the quest is active |
| refresh_cycle | TEXT | When the quest resets (daily, weekly, monthly, once) |
| difficulty | TEXT | Quest difficulty (easy, medium, hard) |
| created_at | TIMESTAMP | When the quest was created |

#### 3. **user_quests**
Tracks user progress on quests.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| guild_id | TEXT | Discord server ID |
| user_id | TEXT | Discord user ID |
| quest_id | INTEGER | Foreign key to quests table |
| progress | INTEGER | Overall progress counter (from achievement counter) |
| quest_specific_progress | INTEGER | Quest-specific progress value |
| completed | BOOLEAN | Whether the quest is completed |
| completed_at | TIMESTAMP | When the quest was completed |
| expires_at | TIMESTAMP | When the quest expires |

#### 4. **server_config**
Stores server-specific configurations.

| Column | Type | Description |
|--------|------|-------------|
| guild_id | TEXT | Primary key - Discord server ID |
| xp_rate | FLOAT | XP multiplier for the server |
| level_up_message | TEXT | Custom level up message |
| level_up_channel | TEXT | Channel ID for level up announcements |
| quest_channel | TEXT | Channel ID for quest notifications |
| achievement_channel | TEXT | Channel ID for achievement notifications |
| quest_reset_hour | INTEGER | Hour of day (UTC) for quest resets |
| quest_reset_day | INTEGER | Day of week for weekly quest resets (0 = Monday) |
| cooldowns | JSONB | Custom cooldown settings for quest activities |

#### 5. **achievements**
Stores achievement definitions.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| guild_id | TEXT | Discord server ID |
| name | TEXT | Achievement name |
| description | TEXT | Achievement description |
| requirement_type | TEXT | Type of requirement (level, messages, voice, etc.) |
| requirement_value | INTEGER | Value required to earn the achievement |
| reward_xp | INTEGER | XP reward for earning the achievement |
| badge_url | TEXT | Custom badge image URL |
| created_at | TIMESTAMP | When the achievement was created |

#### 6. **user_achievements**
Tracks which users have earned which achievements.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| guild_id | TEXT | Discord server ID |
| user_id | TEXT | Discord user ID |
| achievement_id | INTEGER | Foreign key to achievements table |
| earned_at | TIMESTAMP | When the achievement was earned |

#### 7. **cards**
Stores custom rank card settings.

| Column | Type | Description |
|--------|------|-------------|
| guild_id | TEXT | Discord server ID |
| user_id | TEXT | Discord user ID |
| background_url | TEXT | Custom background image URL |
| primary_color | TEXT | Hex code for primary color |
| secondary_color | TEXT | Hex code for secondary color |
| border_color | TEXT | Hex color for card border |
| text_color | TEXT | Hex color for text |
| card_style | TEXT | Style template name |

#### 8. **roles**
Stores level roles configuration.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| guild_id | TEXT | Discord server ID |
| role_id | TEXT | Discord role ID |
| level | INTEGER | Level required to earn the role |
| is_stacked | BOOLEAN | Whether role is kept when advancing to higher roles |

## Database Functions

### Core Functions

#### Connection Management
```python
async def get_connection():
    """Get a connection from the pool"""
    if 'pool' not in globals():
        await create_pool()
    return await globals()['pool'].acquire()
```

#### Safe Operations
```python
async def safe_db_operation(operation_name, *args, **kwargs):
    """Execute a database operation with retries and error handling"""
    # Implementation not shown in provided code
```

### User and Leveling Functions

```python
async def get_user_level(guild_id, user_id):
    """Get a user's level and XP"""
```

```python
async def award_xp(guild_id, user_id, xp_amount, member):
    """Award XP to a user and handle level ups"""
```

```python
async def update_activity_counter_db(guild_id, user_id, counter_type, increment):
    """Update activity counters (messages, voice time, etc.)"""
```

### Quest System Functions

```python
async def create_quest(guild_id, name, description, quest_type, requirement_type,
                     requirement_value, reward_xp, reward_multiplier=1.0,
                     difficulty="medium", refresh_cycle=None):
    """Create a new quest for a guild"""
```

```python
async def get_quest(quest_id):
    """Get a quest by ID with caching"""
```

```python
async def get_guild_active_quests(guild_id, quest_type=None):
    """Get all active quests for a guild"""
```

```python
async def get_user_active_quests(guild_id, user_id):
    """Get all active quests for a user with progress"""
```

```python
async def check_quest_progress(guild_id, user_id, counter_type, counter_value, session_value=None):
    """Check and update progress on all active quests for a user based on a counter"""
```

```python
async def award_quest_rewards(guild_id, user_id, quest_id, member):
    """Award rewards for completing a quest"""
```

```python
async def mark_quests_inactive(guild_id, quest_type=None):
    """Mark quests as inactive"""
```

```python
async def get_quest_reset_settings(guild_id):
    """Get guild-specific quest reset settings"""
```

### Achievement Functions

```python
async def create_achievement(guild_id, name, description, requirement_type, requirement_value, reward_xp=0):
    """Create a new achievement"""
```

```python
async def get_user_achievements(guild_id, user_id):
    """Get all achievements earned by a user"""
```

```python
async def check_achievement_progress(guild_id, user_id, counter_type, value):
    """Check if a user has earned new achievements based on a counter"""
```

### Server Configuration Functions

```python
async def get_server_config(guild_id):
    """Get server configuration settings"""
```

```python
async def update_server_config(guild_id, setting, value):
    """Update a server configuration setting"""
```

```python
async def get_level_up_channel(guild_id):
    """Get the channel ID for level up announcements"""
```

```python
async def get_quest_channel(guild_id):
    """Get the channel ID for quest notifications"""
```

## Data Sources

### User Data
- **Messages**: Collected from Discord message events
- **Voice Activity**: Tracked via voice state update events
- **Reactions**: Gathered from reaction add events
- **Commands**: Recorded from command execution events

### Quest Data
- **Quest Templates**: Predefined in the codebase for different types (daily, weekly, special)
- **Generated Quests**: Created by the QuestManager during resets or initialization
- **Custom Quests**: Created by server administrators using commands

### Server Configuration
- **Default Settings**: Defined in the codebase
- **Custom Settings**: Set by server administrators via commands

## Data Flow

### XP System Flow
1. User performs activity (sending messages, using voice channels, etc.)
2. Activity is captured by event handlers
3. XP is calculated based on activity type and server settings
4. XP is awarded to the user via `award_xp()`
5. If a level-up occurs, a notification is sent to the configured channel

### Quest System Flow
1. QuestManager initializes quests for each guild
2. User activities trigger event handlers
3. Activities update counters via `update_activity_counter_db()`
4. Quest progress is checked with `check_quest_progress()`
5. Completed quests award XP via `award_quest_rewards()`
6. Notifications are sent to the configured channel
7. Quests are reset on schedule by the QuestManager

### Achievement System Flow
1. User activities update counters
2. Achievement progress is checked via `check_achievement_progress()`
3. Newly earned achievements award XP
4. Achievement notifications are sent to the configured channel

## Caching System

The database uses a multi-tiered caching strategy to improve performance:

- **Quest Cache**: Caches individual quests by ID
- **Active Quests Cache**: Caches all active quests for a guild
- **User Quest Cache**: Caches quest progress for users
- **User Stats Cache**: Caches quest statistics for users
- **Server Config Cache**: Caches server configuration settings

Each cache has a TTL (Time-To-Live) to ensure data freshness while providing performance benefits.

## Database Migrations

Database migrations are handled through a migration system that tracks schema versions and applies updates as needed. Migration files are stored in the `migrations` directory and are executed sequentially to ensure database schema compatibility.

## Performance Considerations

- **Indexing**: Critical columns are indexed for faster queries (guild_id, user_id)
- **Caching**: Frequently accessed data is cached to reduce database load
- **Connection Pooling**: Database connections are pooled to improve performance
- **Transaction Management**: Critical operations use transactions to ensure data integrity

## Security Considerations

- **Input Validation**: All user inputs are validated before database operations
- **Parameterized Queries**: All SQL queries use parameterized statements to prevent SQL injection
- **Error Handling**: Errors are caught and logged without exposing sensitive information

## Troubleshooting

### Common Issues

1. **Missing Quests**
   - Verify the QuestManager is running (`bot.quest_manager.check_quest_resets.is_running()`)
   - Check if `initialize_guild_quests()` was called during startup

2. **Data Inconsistencies**
   - Run database verification commands to check for and fix inconsistencies
   - Review logs for database operation errors

3. **Performance Issues**
   - Check cache hit rates and adjust TTL values if needed
   - Review query execution times in logs
   - Consider additional indexing for frequently filtered columns

## Maintenance Tasks

1. **Regular Backups**: The database is backed up daily to prevent data loss
2. **Log Rotation**: Database logs are rotated to prevent excessive disk usage
3. **Cache Purging**: Caches are periodically purged to prevent memory issues
4. **Index Maintenance**: Database indexes are analyzed and rebuilt as needed 