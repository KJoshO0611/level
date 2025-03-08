import discord
from discord.ext import commands
import os
import logging
from config import load_config
from modules.database import init_db
from modules.voice_activity import start_voice_tracking, handle_voice_state_update
from cogs.leveling import LevelingCommands
from cogs.admin import AdminCommands
from cogs.help import CustomHelpCommand

logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.WARN)

# Initialize the bot
def setup_bot():
    # Define bot intents
    intents = discord.Intents.all()
    intents.messages = True
    intents.guilds = True
    intents.voice_states = True
    intents.reactions = True  # Explicitly enable reaction intents
    intents.message_content = True  # Enable message content if needed

    # Create a custom bot class that handles speaking
    class LevelingBot(commands.Bot):
        async def setup_hook(self):
            for guild in self.guilds:
                for vc in guild.voice_channels:
                    vc.guild.voice_client

        async def on_voice_state_update(self, member, before, after):
            await handle_voice_state_update(self, member, before, after)            
    # Create the bot instance
    bot = commands.Bot(command_prefix="!!", intents=intents)
    bot.processed_reactions = set()

    # Event handlers
    @bot.event
    async def on_ready():
        logging.info(f"{bot.user} is now online!")
        await init_db(bot)
        await start_voice_tracking(bot)
    
    # Add cogs
    async def setup_cogs():
        await bot.add_cog(LevelingCommands(bot))
        await bot.add_cog(AdminCommands(bot))
        await bot.add_cog(CustomHelpCommand(bot))
        await bot.tree.sync()

    # Make this method accessible
    bot.setup_cogs = setup_cogs
    
    return bot

# Run the bot
def run_bot():
    # Load configuration
    config = load_config()
    
    # Setup bot
    bot = setup_bot()
    
    # Register the setup_cogs to be called when the bot is ready
    @bot.event
    async def on_ready():
        logging.info(f"{bot.user} is now online!")
        await init_db(bot)
        await start_voice_tracking(bot)
        await bot.setup_cogs()
        await bot.tree.sync()

    @bot.event
    async def on_message(message):
        # Process commands first
        await bot.process_commands(message)
        # Then handle XP for messages
        from modules.levels import handle_message_xp
        await handle_message_xp(bot, message)

    @bot.event
    async def on_voice_state_update(member, before, after):
        from modules.voice_activity import handle_voice_state_update
        logging.info(f"Voice state update: {member.name} moved from {before.channel} to {after.channel}")
        await handle_voice_state_update(bot, member, before, after)

    @bot.event
    async def on_reaction_add(reaction, user):
        logging.info(f"Reaction detected: {user.name} reacted with {reaction.emoji} to a message")

        # Create a unique identifier for this reaction
        reaction_id = f"{reaction.message.id}:{user.id}:{reaction.emoji}"

        # Check if this reaction has already been processed
        if reaction_id in bot.processed_reactions:
            return  # Skip processing if already handled
        
        # Add to processed reactions set
        bot.processed_reactions.add(reaction_id)

        from modules.levels import handle_reaction_xp
        await handle_reaction_xp(bot, reaction, user)
        logging.info(f"Reaction XP processed for {user.name}")
    
    @bot.event 
    async def on_raw_reaction_add(payload):
        logging.info(f"Raw reaction detected: User ID {payload.user_id} added reaction {payload.emoji}")
        
        # Get the necessary objects from the payload
        guild = bot.get_guild(payload.guild_id)
        if not guild:
            return
            
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(payload.message_id)
            user = guild.get_member(payload.user_id)
            
            if not user or user.bot:
                return
            
            reaction_id = f"{payload.message_id}:{payload.user_id}:{str(payload.emoji)}"

            if reaction_id in bot.processed_reactions:
                return  # Skip processing if already handled
        
            # Add to processed reactions set
            bot.processed_reactions.add(reaction_id)

            # Get the reaction from the message
            for reaction in message.reactions:
                if str(reaction.emoji) == str(payload.emoji):
                    from modules.levels import handle_reaction_xp
                    await handle_reaction_xp(bot, reaction, user)
                    logging.info(f"Raw reaction XP processed for {user.name}")
                    break
        except Exception as e:
            logging.info(f"Error processing raw reaction: {e}")
    
    # Run bot with token
    bot.run(config["TOKEN"])

if __name__ == "__main__":
    run_bot()