async def get_user_tier(bot, user_id, guild_id):
    """
    Get the tier level of a user (admin, moderator, regular)
    
    Returns:
    - tier: String representing the user's tier ("admin", "mod", "regular")
    - multiplier: Float multiplier to apply to rate limits (5.0, 2.0, 1.0)
    """
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return "regular", 1.0
        
    member = guild.get_member(int(user_id))
    if not member:
        return "regular", 1.0
    
    # Admin check
    if member.guild_permissions.administrator:
        return "admin", 5.0
    
    # Moderator check - adjust to check for your moderator role
    for role in member.roles:
        if role.name.lower() in ["mod", "moderator"]:
            return "moderator", 2.0
    
    # Get user level to provide slight benefits to active users
    from database import get_user_levels
    xp, level = await get_user_levels(guild_id, user_id)
    
    # High level users get slightly higher limits
    if level >= 50:
        return "active", 1.5
    elif level >= 20:
        return "active", 1.2
    
    return "regular", 1.0