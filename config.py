import os
#from dotenv import load_dotenv

#load_dotenv()

# XP settings
XP_SETTINGS = {
    "COOLDOWN": 60,  # seconds between XP awards per user
    "MIN": 10,       # minimum XP awarded
    "MAX": 20,       # maximum XP awarded
    "RATES": {
        "active": 5, # 5 XP per minute for active users
        "muted": 2,  # 2 XP per minute for muted users
        "idle": 1 ,  # 1 XP per minute for idle users
        "streaming": 8, # 1 XP per minute for streaming users
        "watching": 6 # 1 XP per minute for watching users
    },
    "IDLE_THRESHOLD": 300  # 5 minutes without speaking = idle
}

LEVEL_ROLES = {
    1: 1349303634906841128,  # Replace with actual role IDs
    10: 1349304838277562419,
    20: 1349305333394440253,
    30: 1349305944315662367,
    40: 1349306704088530994,
    50: 975670597147303996,
    # Add more level-role mappings as needed
}

# Paths
PATHS = {
    "FONT_PATH": "assets/fonts/VCR_OSD_MONO_1.001.ttf",
    "DATABASE_PATH": "root/database/levels.db"
}

DATABASE = {
        "HOST": os.getenv("HOST"),
        "PORT": 5432,
        "NAME": os.getenv("NAME"),
        "USER": os.getenv("USER"),
        "PASSWORD": os.getenv("PASSWORD")
}

def load_config():
    """Load environment variables and return a configuration dictionary"""
    # Load environment variables from .env file
    #load_dotenv()
    
    # Create configuration dictionary
    config = {
        "TOKEN": os.getenv("TOKEN"),
        "GUILD_ID": os.getenv("GUILDID"),
        "XP_SETTINGS": XP_SETTINGS,
        "PATHS": PATHS,
        "DATABASE": DATABASE,
        "LEVEL_ROLES": LEVEL_ROLES
    }
    
    return config