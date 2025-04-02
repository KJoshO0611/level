# Level - Discord XP & Leveling System

A feature-rich Discord bot for managing an XP-based leveling system on your server. Track user engagement, reward active members with automatic role assignments, and customize the leveling experience with personalized level cards.

## Features

### Core Leveling System
- **XP Tracking**: Users earn XP through messages, reactions, and voice activity
- **Configurable XP Rates**: Customize XP gain rates for different activities
- **Voice Activity XP**: Earn XP while in voice channels with different rates based on activity status (active, muted, idle, streaming, watching)
- **Multi-language Support**: Level cards support multiple languages and scripts including Arabic, Hebrew, CJK (Chinese, Japanese, Korean), Cyrillic, Devanagari, Thai, and more

### Achievement System
- **Custom Achievements**: Create server-specific achievements with custom requirements
- **Achievement Badges**: Upload custom badge images for each achievement (supports transparent PNG)
- **Achievement Showcasing**: Display unlocked achievements on level cards
- **Titles**: Unlock special titles by completing achievements
- **Achievement Combos**: Set up achievement combinations that unlock special rewards
- **Event-based Achievements**: Track event attendance and other activities

### Visual Level Cards
- **Customizable Cards**: Users can set their own background images
- **Dynamic Level Cards**: Display current level, XP progress, and rank
- **Leaderboard Visualization**: See the top members on your server
- **International Username Support**: Properly displays usernames in various scripts and languages
- **Transparent Badges**: Support for transparent PNG badges that blend perfectly with card backgrounds

### Event Integration
- **Discord Event Tracking**: Integration with Discord's scheduled events
- **Event Attendance**: Track user attendance at events
- **Automatic Rewards**: Award XP or achievements for event participation
- **XP Boost Events**: Automatically boost XP during scheduled events

### Role Rewards
- **Automatic Role Assignment**: Assign roles at specific level milestones
- **Role Progression**: Replace previous roles with new ones as users level up
- **First-join Roles**: Automatically assign level 1 roles to new members

### XP Boosting
- **Channel Boosts**: Set multipliers for specific text or voice channels
- **XP Boost Events**: Create temporary server-wide XP multipliers
- **Scheduled Events**: Plan boost events for special occasions
- **Event Announcements**: Automatic notifications when XP events start

### Admin Features
- **Interactive Dashboard**: Manage server configuration through a user-friendly interface
- **XP Settings**: Customize minimum/maximum XP, cooldown periods
- **Database Status**: Monitor the health of the bot's database
- **Cache Management**: Efficient caching system for high-performance operation

### Advanced Voice Activity Detection
- **Stream Viewer Bonuses**: Extra XP for users who watch streams in voice channels
- **Speaking Detection**: Different XP rates based on active participation vs. idling
- **Status Tracking**: Track when users are streaming, using video, or just listening

## Installation and Setup

### Prerequisites
- Python 3.8 or higher
- PostgreSQL database
- Discord bot token

### Setup Steps
1. Clone the repository:
```bash
git clone https://github.com/yourusername/level.git
cd level
```

2. Create a virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Create a `.env` file in the project root with the following variables:
```
DISCORD_TOKEN=your_discord_bot_token
HOST=your_postgres_host
DB_PORT=5432
DB_NAME=your_database_name
DB_USER=your_database_user
PASSWORD=your_database_password
```

4. Set up the database:
```bash
python -m utils.database_migration all
```

5. Start the bot:
```bash
python main.py
```

### Database Migrations
The bot includes an automated migration system that handles database schema changes:

- **Automatic Migrations**: Running `python -m utils.database_migration all` applies all migrations
- **File-Based Migrations**: Add new migrations in the `database/migrations` directory
- **Migration Template**: Use the provided template at `database/migrations/010_migration_template.py`
- **Naming Convention**: Name migrations with format `NNN_description.py` where NNN is a sequential number

To create a new migration:
1. Copy the template file: `cp database/migrations/010_migration_template.py database/migrations/011_your_migration.py`
2. Edit the SQL in the APPLY_SQL and REVERT_SQL sections
3. Run migrations: `python -m utils.database_migration all`

## Commands

### User Commands
- `!!level` or `!!lvl` - View your level card
- `!!rank` or `!!r` - Check your position on the server
- `!!leaderboard` or `!!lb` - View the server leaderboard
- `!!setbackground` or `!!setbg` - Set a custom background for your level card
- `!!removebackground` or `!!removebg` - Remove your custom background
- `!!showbackground` or `!!showbg` - Show your current background
- `!!achievements` - View your unlocked achievements
- `!!achievement info <id>` - Get information about an achievement
- `!!title set <title>` - Set your display title on your level card
- `!!title remove` - Remove your current title

### Admin Commands
- `/config` - Open the server configuration dashboard
- `/setxpchannel` - Set where level-up messages are sent
- `/seteventchannel` - Set where XP event announcements are sent
- `/xpboost` - Set an XP multiplier for a specific channel
- `/createevent` - Create a temporary XP boost event
- `/scheduleevent` - Schedule a future XP boost event
- `/activeevents` - View currently active XP boost events
- `/upcomingevents` - View scheduled future XP boost events
- `/cancelevent` - Cancel an active or scheduled XP boost event
- `/levelrole` - Set a role reward for reaching a level
- `/deletelevelrole` - Remove a level role mapping
- `/xpsettings` - View current XP settings
- `/setminxp` - Set minimum XP per message
- `/setmaxxp` - Set maximum XP per message
- `/setcooldown` - Set cooldown between XP awards
- `/resetxpsettings` - Reset to default XP settings
- `!!dbstatus` - Check database health
- `!!reload_channel_boosts` - Reload channel boosts from the database
- `!!list_channel_boosts` - List all channels with XP boosts
- `!!achievement create` - Create a new achievement
- `!!achievement badge <id>` - Upload a badge for an achievement (supports transparent PNG)
- `!!achievement edit <id>` - Edit an achievement's properties
- `!!achievement delete <id>` - Delete an achievement

## Technical Features

### High Reliability
- **Database Health Monitoring**: Automatic recovery from database connection issues
- **Batch Processing**: Efficient handling of XP updates to prevent database overload
- **Caching System**: Reduces database load and improves response times

### Performance Optimizations
- **Asynchronous Image Generation**: Non-blocking image processing using Cairo
- **Batch Database Operations**: Optimized database operations for high-traffic servers
- **Connection Pooling**: Efficient database connection management

### International Support
- **Multi-script Rendering**: Proper rendering of usernames in various writing systems
- **RTL Language Support**: Right-to-left text handling for Arabic, Hebrew, etc.
- **Font Selection**: Automatic font selection based on detected text script

### Cairo-based Image Generation
- **High-quality Level Cards**: Modern, clean design with proper text rendering
- **Custom Avatar Display**: User avatars with status indicators
- **Customizable Backgrounds**: Support for user-uploaded backgrounds
- **Status Indicators**: Shows user's online status on level cards
- **Transparent Badges**: Full support for transparency in badge images

### Database Migrations
- **Automated Schema Updates**: Seamless database schema evolution
- **Version Control**: Track all database changes with versioned migrations
- **Safe Migrations**: Checks for existing objects before making changes
- **Revertible Changes**: Each migration includes both apply and revert SQL

## Directory Structure

```
level/
├── cogs/               # Discord command modules
├── database/           # Database interaction modules
│   └── migrations/     # Database migration files
├── modules/            # Core functionality modules
├── utils/              # Utility functions
│   └── cairo_image_generator.py  # Image generation
├── main.py             # Bot entry point
├── config.py           # Configuration
└── README.md           # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit your changes: `git commit -am 'Add some feature'`
4. Push to the branch: `git push origin feature-name`
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
