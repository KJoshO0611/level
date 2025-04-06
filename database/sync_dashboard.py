import logging
from typing import Optional
import discord
import asyncpg
import json

# Assuming 'get_connection' is available from core.py or similar
# We now pass the bot object instead of importing the pool directly
from .core import get_connection

async def upsert_dashboard_user(bot: discord.Client, user: discord.User | discord.Member):
    """
    Inserts or updates user data in the dashboard 'users' table.
    Uses the user's current profile information.
    Accepts bot object to access the database pool (bot.db).
    """
    if not hasattr(bot, 'db') or bot.db is None:
        logging.error("Database pool not available in bot object for upsert_dashboard_user")
        return

    # Define the default role
    default_role_json = json.dumps(["user"])

    query = """
        INSERT INTO users (discord_id, username, discriminator, avatar, role)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        ON CONFLICT (discord_id) DO UPDATE SET
            username = EXCLUDED.username,
            discriminator = EXCLUDED.discriminator,
            avatar = EXCLUDED.avatar;
    """
    # Ensure discord_id is BIGINT but passed as a string
    discord_id_str = str(user.id)
    # Handle potential None avatar
    avatar_url = str(user.display_avatar.url) if user.display_avatar else None

    try:
        # Use bot.db to acquire connection
        async with bot.db.acquire() as conn:
            # Pass discord_id as string
            await conn.execute(query, discord_id_str, user.name, user.discriminator, avatar_url, default_role_json)
        # logging.debug(f"Upserted user {user.id} ({user.name}) into dashboard users table.")
    except Exception as e:
        logging.error(f"Error upserting dashboard user {user.id}: {e}")

async def upsert_dashboard_guild(bot: discord.Client, guild: discord.Guild):
    """
    Inserts or updates guild data in the dashboard 'guilds' table.
    Uses the guild's current information.
    Accepts bot object to access the database pool (bot.db).
    """
    if not hasattr(bot, 'db') or bot.db is None:
        logging.error("Database pool not available in bot object for upsert_dashboard_guild")
        return

    # Assuming a 'preferred_locale' text column might exist, causing the $7 error.
    # Also adding back created_at and channel_count
    query = """
        INSERT INTO guilds (guild_id, name, icon, owner_id, preferred_locale, created_at, channel_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (guild_id) DO UPDATE SET
            name = EXCLUDED.name,
            icon = EXCLUDED.icon,
            owner_id = EXCLUDED.owner_id,
            preferred_locale = EXCLUDED.preferred_locale,
            created_at = EXCLUDED.created_at,
            channel_count = EXCLUDED.channel_count;
    """
    # Ensure IDs are BIGINT but passed as strings
    guild_id_str = str(guild.id)
    owner_id_str = str(guild.owner_id)
    # Handle potential None icon
    icon_url = str(guild.icon.url) if guild.icon else None
    # Get locale as string
    locale_str = str(guild.preferred_locale)
    # Get created_at (datetime object is usually fine for asyncpg)
    created_at = guild.created_at
    # Get channel count
    channel_count = len(guild.channels)

    try:
        # Use bot.db to acquire connection
        async with bot.db.acquire() as conn:
            # Pass IDs and locale as strings, created_at as datetime, channel_count as int
            await conn.execute(query, guild_id_str, guild.name, icon_url, owner_id_str, locale_str, created_at, channel_count)
        # logging.debug(f"Upserted guild {guild.id} ({guild.name}) into dashboard guilds table.")
    except Exception as e:
        # The error message might still mention $7 if the root cause is different,
        # but we log the guild.id for context.
        logging.error(f"Error upserting dashboard guild {guild.id}: {e}")

async def sync_all_from_levels_table(bot: discord.Client):
    """
    Fetches all unique user/guild IDs from the bot's 'levels' table
    and attempts to upsert their current data into the dashboard tables.
    Should be called on bot startup (after cache is ready and bot.db is available).
    """
    if not hasattr(bot, 'db') or bot.db is None:
        logging.error("Database pool not available in bot object for sync_all_from_levels_table")
        return

    logging.info("Starting synchronization from levels table to dashboard tables...")
    processed_users = set()
    processed_guilds = set()

    query = "SELECT DISTINCT guild_id, user_id FROM levels;"
    try:
        # Use bot.db to acquire connection
        async with bot.db.acquire() as conn:
            records = await conn.fetch(query)

        for record in records:
            try:
                # Use integer IDs for discord.py functions
                guild_id = int(record['guild_id'])
                user_id = int(record['user_id'])

                # Upsert Guild Info (if not already processed)
                if guild_id not in processed_guilds:
                    guild = bot.get_guild(guild_id) # Pass integer ID
                    if guild:
                        # Pass bot object to upsert function
                        await upsert_dashboard_guild(bot, guild)
                        processed_guilds.add(guild_id)
                    else:
                        logging.warning(f"Could not find guild {guild_id} in bot cache during sync.")

                # Upsert User Info (if not already processed)
                if user_id not in processed_users:
                    user = bot.get_user(user_id) # Pass integer ID
                    # If user not in cache, try fetching (might be slow)
                    if not user:
                        try:
                            user = await bot.fetch_user(user_id) # Pass integer ID
                        except discord.NotFound:
                            logging.warning(f"Could not find user {user_id} via API during sync.")
                        except discord.HTTPException as http_err:
                             logging.warning(f"HTTP error fetching user {user_id} during sync: {http_err}")

                    if user:
                        # Pass bot object to upsert function
                        await upsert_dashboard_user(bot, user)
                        processed_users.add(user_id)

            except ValueError:
                logging.warning(f"Skipping record with non-integer ID: guild={record['guild_id']}, user={record['user_id']}")
            except Exception as inner_e:
                 logging.error(f"Error processing record (guild={record.get('guild_id')}, user={record.get('user_id')}) during sync: {inner_e}")


        logging.info(f"Synchronization complete. Processed {len(processed_guilds)} guilds and {len(processed_users)} users from levels table.")

    except Exception as e:
        logging.error(f"Error during bulk sync from levels table: {e}")

# --- Integration Points ---
# 1. Call sync_all_from_levels_table(bot) in your bot's on_ready event (after cache is loaded and bot.db is set).
# 2. In relevant cogs/event handlers pass the 'bot' or 'ctx.bot' object:
#    - on_guild_join(guild): await upsert_dashboard_guild(bot, guild)
#    - on_guild_update(before, after): await upsert_dashboard_guild(bot, after)
#    - on_member_join(member): await upsert_dashboard_user(bot, member); await upsert_dashboard_guild(bot, member.guild)
#    - on_member_update(before, after): await upsert_dashboard_user(bot, after)
#    - on_user_update(before, after): await upsert_dashboard_user(bot, after) 