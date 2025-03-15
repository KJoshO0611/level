# Level - Discord XP & Leveling System

A feature-rich Discord bot for managing an XP-based leveling system on your server. Track user engagement, reward active members with automatic role assignments, and customize the leveling experience with personalized level cards.

## Features

### Core Leveling System
- **XP Tracking**: Users earn XP through messages, reactions, and voice activity
- **Configurable XP Rates**: Customize XP gain rates for different activities
- **Voice Activity XP**: Earn XP while in voice channels with different rates based on activity status (active, muted, idle, streaming, watching)

### Visual Level Cards
- **Customizable Cards**: Users can set their own background images
- **Dynamic Level Cards**: Display current level, XP progress, and rank
- **Leaderboard Visualization**: See the top members on your server

### Role Rewards
- **Automatic Role Assignment**: Assign roles at specific level milestones
- **Role Progression**: Replace previous roles with new ones as users level up

### XP Boosting
- **Channel Boosts**: Set multipliers for specific text or voice channels
- **XP Boost Events**: Create temporary server-wide XP multipliers
- **Scheduled Events**: Plan boost events for special occasions

### Admin Features
- **Dashboard**: Interactive server configuration
- **XP Settings**: Customize minimum/maximum XP, cooldown periods
- **Database Status**: Monitor the health of the bot's database

## Commands

### User Commands
- `!!level` or `!!lvl` - View your level card
- `!!rank` or `!!r` - Check your position on the server
- `!!leaderboard` or `!!lb` - View the server leaderboard
- `!!setbackground` or `!!setbg` - Set a custom background for your level card
- `!!removebackground` or `!!removebg` - Remove your custom background
- `!!showbackground` or `!!showbg` - Show your current background

### Admin Commands
- `/config` - Open the server configuration dashboard
- `/setxpchannel` - Set where level-up messages are sent
- `/xpboost` - Set an XP multiplier for a specific channel
- `/createevent` - Create a temporary XP boost event
- `/scheduleevent` - Schedule a future XP boost event
- `/levelrole` - Set a role reward for reaching a level
- `/xpsettings` - View current XP settings
- `/setminxp` - Set minimum XP per message
- `/setmaxxp` - Set maximum XP per message
- `/setcooldown` - Set cooldown between XP awards
- `/resetxpsettings` - Reset to default XP settings
- `!!reload_channel_boosts` - Reload channel boosts from the database
- `!!list_channel_boosts` - List all channels with XP boosts
- `!!dbstatus` - Check database health

## Setup

### Prerequisites
- Python 3.8+
- PostgreSQL database
- Discord Bot Token

### Installation

1. Clone the repository
```bash
git clone https://github.com/yourusername/level.git
cd level
```

2. Install requirements
```bash
pip install -r req.txt
```

3. Set up environment variables in a `.env` file
```
TOKEN=your_discord_bot_token
HOST=your_postgres_host
NAME=your_postgres_database_name
USER=your_postgres_username
PASSWORD=your_postgres_password
```

4. Create database (PostgreSQL)
```sql
CREATE DATABASE yourdbname;
```

5. Run the bot
```bash
python main.py
```

### Docker Deployment
1. Build the Docker image
```bash
docker build -t level-bot .
```

2. Run with Docker
```bash
docker run -d \
  --name level-bot \
  -v /path/to/external_volume:/external_volume \
  -e TOKEN=your_discord_bot_token \
  -e HOST=your_postgres_host \
  -e NAME=your_postgres_database_name \
  -e USER=your_postgres_username \
  -e PASSWORD=your_postgres_password \
  level-bot
```

## Configuration

### External Volume
The bot uses an external volume for storing level card backgrounds. Make sure this directory is accessible by the bot and properly configured in your environment.

### XP Settings
Default XP settings can be adjusted in `config.py`:
- Message XP: 10-20 XP per message
- Voice XP rates per minute:
  - Active: 5 XP
  - Muted: 2 XP
  - Idle: 1 XP
  - Streaming: 8 XP
  - Watching: 6 XP

## Database Structure
The bot uses PostgreSQL with the following tables:
- `levels`: Stores user XP and levels
- `server_config`: Server-specific settings
- `channel_boosts`: Channel XP multipliers
- `level_roles`: Role rewards for levels
- `server_xp_settings`: Server-specific XP settings
- `custom_backgrounds`: User custom backgrounds
- `xp_boost_events`: Temporary XP boost events

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## License
[MIT License](LICENSE)
