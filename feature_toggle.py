import asyncio
import discord
from discord.ext import commands
import asyncpg
from typing import Dict, Any, Optional, List, Union

class FeatureManager:
    def __init__(self, pool: asyncpg.Pool):
        """
        Initialize feature manager with asyncpg connection pool.
        
        :param pool: Asyncpg connection pool
        """
        self.pool = pool

    async def initialize_database(self):
        """Create the guild_feature_configs table if it doesn't exist."""
        async with self.pool.acquire() as connection:
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS guild_feature_configs (
                    guild_id BIGINT PRIMARY KEY,
                    moderation BOOLEAN DEFAULT TRUE,
                    utility BOOLEAN DEFAULT TRUE,
                    fun BOOLEAN DEFAULT TRUE,
                    music BOOLEAN DEFAULT TRUE,
                    leveling BOOLEAN DEFAULT TRUE
                )
            ''')

            # Create a separate table for specific command/group toggles
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS guild_command_configs (
                    guild_id BIGINT,
                    command_name TEXT,
                    is_enabled BOOLEAN DEFAULT TRUE,
                    PRIMARY KEY (guild_id, command_name)
                )
            ''')

    async def get_guild_features(self, guild_id: int) -> Dict[str, bool]:
        """
        Retrieve or create feature configuration for a specific guild.
        
        :param guild_id: Discord guild ID
        :return: Dictionary of feature configurations
        """
        async with self.pool.acquire() as connection:
            # Try to find existing configuration
            config = await connection.fetchrow(
                'SELECT * FROM guild_feature_configs WHERE guild_id = $1', 
                guild_id
            )
            
            # If no config exists, create a default one
            if not config:
                await connection.execute('''
                    INSERT INTO guild_feature_configs (guild_id) 
                    VALUES ($1) 
                    ON CONFLICT (guild_id) DO NOTHING
                ''', guild_id)
                
                # Return default configuration
                return {
                    'moderation': True,
                    'utility': True,
                    'fun': True,
                    'music': True,
                    'leveling': True
                }
            
            # Convert row to dictionary, excluding guild_id
            return {
                key: config[key] 
                for key in ['moderation', 'utility', 'fun', 'music', 'leveling']
            }

    async def is_command_enabled(self, guild_id: int, command_name: str) -> bool:
        """
        Check if a specific command or command group is enabled.
        
        :param guild_id: Discord guild ID
        :param command_name: Name of the command or command group
        :return: Whether the command is enabled
        """
        async with self.pool.acquire() as connection:
            # First, check group-level feature
            # Extract the group name (e.g., 'music' from 'music play')
            group_name = command_name.split()[0] if ' ' in command_name else command_name

            # Check group-level feature
            group_feature = await connection.fetchval(
                'SELECT $1 FROM guild_feature_configs WHERE guild_id = $2', 
                group_name, 
                guild_id
            )

            # If group feature is False, command is disabled
            if group_feature is False:
                return False

            # Check specific command toggle
            specific_toggle = await connection.fetchval('''
                SELECT is_enabled 
                FROM guild_command_configs 
                WHERE guild_id = $1 AND command_name = $2
            ''', guild_id, command_name)

            # If specific toggle exists, return its value
            # Otherwise, default to True
            return specific_toggle if specific_toggle is not None else True

    async def toggle_feature(self, 
                              guild_id: int, 
                              feature_name: str, 
                              is_specific_command: bool = False) -> Optional[bool]:
        """
        Toggle a feature or specific command.
        
        :param guild_id: Discord guild ID
        :param feature_name: Name of the feature or command to toggle
        :param is_specific_command: Whether this is a specific command toggle
        :return: New state of the feature (True/False)
        """
        async with self.pool.acquire() as connection:
            if not is_specific_command:
                # List of valid group features
                valid_features = ['moderation', 'utility', 'fun', 'music', 'leveling']
                
                if feature_name.lower() not in valid_features:
                    return None

                # Toggle group feature
                result = await connection.fetchrow(f'''
                    UPDATE guild_feature_configs 
                    SET {feature_name} = NOT {feature_name} 
                    WHERE guild_id = $1 
                    RETURNING {feature_name}
                ''', guild_id)
                
                return result[feature_name] if result else None
            else:
                # Toggle specific command
                result = await connection.fetchrow('''
                    INSERT INTO guild_command_configs (guild_id, command_name, is_enabled)
                    VALUES ($1, $2, FALSE)
                    ON CONFLICT (guild_id, command_name) 
                    DO UPDATE SET is_enabled = NOT guild_command_configs.is_enabled
                    RETURNING is_enabled
                ''', guild_id, feature_name)
                
                return result['is_enabled'] if result else None

class ConfigurableBot(commands.Bot):
    def __init__(self, feature_manager: FeatureManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.feature_manager = feature_manager

    def command_check(self, command_name: str):
        """Create a check function for a specific command."""
        async def predicate(ctx):
            # Check if the command is enabled
            return await self.feature_manager.is_command_enabled(ctx.guild.id, command_name)
        return commands.check(predicate)

    async def setup_hook(self):
        # Initialize database tables
        await self.feature_manager.initialize_database()

        # Register feature management slash commands
        @self.tree.command(name="toggle_feature", description="Toggle bot features on/off")
        @discord.app_commands.checks.has_permissions(administrator=True)
        async def toggle_feature(interaction: discord.Interaction, feature: str):
            result = await self.feature_manager.toggle_feature(
                interaction.guild_id, 
                feature.lower()
            )
            
            if result is not None:
                status = "enabled" if result else "disabled"
                await interaction.response.send_message(
                    f"{feature.capitalize()} feature has been {status} for this server!"
                )
            else:
                await interaction.response.send_message(
                    f"Feature {feature} not found or cannot be toggled!"
                )

        @self.tree.command(name="toggle_command", description="Toggle specific commands on/off")
        @discord.app_commands.checks.has_permissions(administrator=True)
        async def toggle_command(interaction: discord.Interaction, command: str):
            result = await self.feature_manager.toggle_feature(
                interaction.guild_id, 
                command.lower(),
                is_specific_command=True
            )
            
            if result is not None:
                status = "enabled" if result else "disabled"
                await interaction.response.send_message(
                    f"Command {command} has been {status} for this server!"
                )
            else:
                await interaction.response.send_message(
                    f"Command {command} not found or cannot be toggled!"
                )

# Example bot setup with command groups
class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(invoke_without_command=True)
    @commands.check_any(bot.command_check('music'))
    async def music(self, ctx):
        await ctx.send("Music command group")

    @music.command()
    @commands.check_any(bot.command_check('music play'))
    async def play(self, ctx):
        await ctx.send("Playing music!")

    @music.command()
    @commands.check_any(bot.command_check('music stop'))
    async def stop(self, ctx):
        await ctx.send("Stopping music!")

# Rest of the bot setup remains the same as in previous example
async def main():
    # PostgreSQL connection string
    DATABASE_URL = "postgresql://username:password@localhost/botdatabase"

    # Create connection pool
    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=5,
        max_size=10
    )

    # Initialize feature manager
    feature_manager = FeatureManager(pool)

    # Discord bot intents
    intents = discord.Intents.default()
    intents.message_content = True

    # Create bot instance
    bot = ConfigurableBot(
        feature_manager=feature_manager,
        command_prefix='!', 
        intents=intents
    )

    # Add cogs
    await bot.add_cog(MusicCog(bot))

    # Run the bot
    await bot.start('YOUR_TOKEN')

# Run the bot using asyncio
if __name__ == '__main__':
    asyncio.run(main())