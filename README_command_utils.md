# Auto-Delete Command Message Feature

This feature automatically deletes command messages to keep chat channels clean. This is particularly useful for bots that are used in active servers, as it prevents command spam from cluttering the chat history.

## Implementation Details

We've created a decorator in `utils/command_utils.py` that automatically handles message deletion for text-based commands.

### How It Works

1. The `auto_delete_command()` decorator is applied to command functions
2. When a command is invoked, the decorator tries to delete the message that triggered the command
3. The original command function is then executed normally
4. Error handling ensures that any issues with message deletion don't affect command execution

## Usage

### For Existing Commands

To add message deletion to existing commands, import the decorator and apply it to commands:

```python
from utils.command_utils import auto_delete_command

@commands.command(name="example")
@auto_delete_command()  # Add this line before the async def
async def example_command(self, ctx):
    # Command implementation
    pass
```

### Decorator Order

The order of decorators matters. The `auto_delete_command()` decorator should generally be placed:
- After the `@commands.command()` or `@some_group.command()` decorator
- After any `@rate_limit()` decorators
- Before the command function definition

Example of correct order:
```python
@commands.command(name="example")
@rate_limit(calls=5, period=60)
@auto_delete_command()
async def example_command(self, ctx):
    pass
```

### For Commands That Already Delete Messages

⚠️ **IMPORTANT**: You must choose one method of deletion, not both!

For commands that already include `await ctx.message.delete()`, you have two options:

1. **RECOMMENDED**: Remove the existing `await ctx.message.delete()` line and add the decorator
2. Keep the existing `await ctx.message.delete()` code and DO NOT add the decorator

Using both will cause errors as the second deletion attempt will fail with a "404 Not Found" error since the message has already been deleted.

Example of fixing a command:

```python
# Before (problematic - has both deletion methods)
@commands.command(name="example")
@auto_delete_command()  # This tries to delete the message
async def example_command(self, ctx):
    await ctx.message.delete()  # This tries to delete it AGAIN - will error!
    # Rest of command
    
# After (fixed - using only the decorator)
@commands.command(name="example")
@auto_delete_command()  # Only deletion method
async def example_command(self, ctx):
    # Rest of command
```

## Files to Update

The following cog files contain text commands that should be updated:

- [x] `cogs/quest_commands.py` (example implementation)
- [x] `cogs/achievement_commands.py`
- [x] `cogs/admin.py`
- [x] `cogs/calendar_commands.py`
- [x] `cogs/card_customization.py`
- [x] `cogs/help.py`
- [x] `cogs/leveling.py`

## Benefits

- Cleaner chat channels
- Better user experience
- Consistent behavior across all commands
- Error handling for failed deletions 