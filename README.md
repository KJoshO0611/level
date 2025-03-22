Level - Discord XP & Leveling System
A feature-rich Discord bot for managing an XP-based leveling system on your server. Track user engagement, reward active members with automatic role assignments, and customize the leveling experience with personalized level cards.
Features
Core Leveling System

XP Tracking: Users earn XP through messages, reactions, and voice activity
Configurable XP Rates: Customize XP gain rates for different activities
Voice Activity XP: Earn XP while in voice channels with different rates based on activity status (active, muted, idle, streaming, watching)
Multi-language Support: Level cards support multiple languages and scripts including Arabic, Hebrew, CJK (Chinese, Japanese, Korean), Cyrillic, Devanagari, Thai, and more

Visual Level Cards

Customizable Cards: Users can set their own background images
Dynamic Level Cards: Display current level, XP progress, and rank
Leaderboard Visualization: See the top members on your server
International Username Support: Properly displays usernames in various scripts and languages

Role Rewards

Automatic Role Assignment: Assign roles at specific level milestones
Role Progression: Replace previous roles with new ones as users level up
First-join Roles: Automatically assign level 1 roles to new members

XP Boosting

Channel Boosts: Set multipliers for specific text or voice channels
XP Boost Events: Create temporary server-wide XP multipliers
Scheduled Events: Plan boost events for special occasions
Event Announcements: Automatic notifications when XP events start

Admin Features

Interactive Dashboard: Manage server configuration through a user-friendly interface
XP Settings: Customize minimum/maximum XP, cooldown periods
Database Status: Monitor the health of the bot's database
Cache Management: Efficient caching system for high-performance operation

Advanced Voice Activity Detection

Stream Viewer Bonuses: Extra XP for users who watch streams in voice channels
Speaking Detection: Different XP rates based on active participation vs. idling
Status Tracking: Track when users are streaming, using video, or just listening

Commands
User Commands

!!level or !!lvl - View your level card
!!rank or !!r - Check your position on the server
!!leaderboard or !!lb - View the server leaderboard
!!setbackground or !!setbg - Set a custom background for your level card
!!removebackground or !!removebg - Remove your custom background
!!showbackground or !!showbg - Show your current background

Admin Commands

/config - Open the server configuration dashboard
/setxpchannel - Set where level-up messages are sent
/seteventchannel - Set where XP event announcements are sent
/xpboost - Set an XP multiplier for a specific channel
/createevent - Create a temporary XP boost event
/scheduleevent - Schedule a future XP boost event
/activeevents - View currently active XP boost events
/upcomingevents - View scheduled future XP boost events
/cancelevent - Cancel an active or scheduled XP boost event
/levelrole - Set a role reward for reaching a level
/deletelevelrole - Remove a level role mapping
/xpsettings - View current XP settings
/setminxp - Set minimum XP per message
/setmaxxp - Set maximum XP per message
/setcooldown - Set cooldown between XP awards
/resetxpsettings - Reset to default XP settings
!!dbstatus - Check database health
!!reload_channel_boosts - Reload channel boosts from the database
!!list_channel_boosts - List all channels with XP boosts

Technical Features
High Reliability

Database Health Monitoring: Automatic recovery from database connection issues
Batch Processing: Efficient handling of XP updates to prevent database overload
Caching System: Reduces database load and improves response times

Performance Optimizations

Asynchronous Image Generation: Non-blocking image processing using Cairo
Batch Database Operations: Optimized database operations for high-traffic servers
Connection Pooling: Efficient database connection management

International Support

Multi-script Rendering: Proper rendering of usernames in various writing systems
RTL Language Support: Right-to-left text handling for Arabic, Hebrew, etc.
Font Selection: Automatic font selection based on detected text script

Cairo-based Image Generation

High-quality Level Cards: Modern, clean design with proper text rendering
Custom Avatar Display: User avatars with status indicators
Customizable Backgrounds: Support for user-uploaded backgrounds
Status Indicators: Shows user's online status on level cards