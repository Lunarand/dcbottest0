import discord
from discord.ext import commands
import os
import asyncio
import time

# --- CONFIGURATION ---
TOKEN = os.getenv('DISCORD_TOKEN')
SECRET_KEY = os.getenv('KEY')
if SECRET_KEY:
    SECRET_KEY = SECRET_KEY.strip()

AUTHORIZED_USERS = set() 
ACTIVE_TASKS = [] # Stores our running background loops

# --- SETUP ---
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 
intents.guilds = True 

bot = commands.Bot(command_prefix='+', intents=intents, help_command=None)

# --- 🔒 THE GATEKEEPER ---
@bot.check
async def global_login_check(ctx):
    if ctx.command.name == 'login': return True
    if ctx.author.id in AUTHORIZED_USERS: return True
    await ctx.send("❌ **Access Denied.** Please use `+login <key>` first.")
    return False

# --- HELPER: INTERVAL PARSER ---
def parse_interval(interval_str):
    """Converts a string like '3h', '10m', or '30s' into seconds."""
    interval_str = interval_str.lower().strip()
    try:
        if interval_str.endswith('s'):
            return int(interval_str[:-1])
        elif interval_str.endswith('m'):
            return int(interval_str[:-1]) * 60
        elif interval_str.endswith('h'):
            return int(interval_str[:-1]) * 3600
        elif interval_str.endswith('d'):
            return int(interval_str[:-1]) * 86400
        elif interval_str.isdigit():
            return int(interval_str) 
    except ValueError:
        return None
    return None

# --- BACKGROUND TASK ---
async def reminder_loop(guild_id, message_content, interval_seconds):
    """Loop that sends the message to all text channels in the target guild."""
    try:
        await bot.wait_until_ready()
        
        while not bot.is_closed():
            guild = bot.get_guild(guild_id)
            if guild:
                for channel in guild.text_channels:
                    try:
                        if channel.permissions_for(guild.me).send_messages:
                            await channel.send(message_content)
                    except discord.Forbidden:
                        pass 
                    except Exception as e:
                        print(f"Error sending to {channel.name}: {e}")
            
            # --- "STAY AWAKE" PRECISE TIMING LOGIC ---
            if interval_seconds < 10:
                # For tight intervals, use a precise micro-sleep to prevent drift
                target_time = time.time() + interval_seconds
                while time.time() < target_time:
                    await asyncio.sleep(0.1) 
            else:
                # Standard async sleep for longer intervals
                await asyncio.sleep(interval_seconds)
                
    except asyncio.CancelledError:
        print(f"Reminder loop for Guild {guild_id} was successfully stopped.")

# --- COMMANDS ---

@bot.event
async def on_ready():
    print(f'Logged in as "{bot.user.name}"')
    if SECRET_KEY:
        print("✅ Secret Key Loaded.")
    else:
        print("⚠️ Warning: No 'KEY' secret found.")
    print("✅ Testing Mode Active: Reminder system online.")

@bot.command()
async def login(ctx, *, key: str):
    try: await ctx.message.delete()
    except: pass
    
    if ctx.author.id in AUTHORIZED_USERS:
        return await ctx.send("✅ You are already logged in.")

    if not SECRET_KEY:
        return await ctx.send("⚠️ **System Error:** KEY Secret is missing.")

    if key.strip() == SECRET_KEY:
        AUTHORIZED_USERS.add(ctx.author.id)
        await ctx.send(f"✅ **Access Granted.** Welcome, {ctx.author.display_name}.")
    else:
        await ctx.send("❌ **Wrong Key.** Access Denied.")

@bot.command()
async def help(ctx):
    msg = (
        "**⚙️ Testing Bot**\n"
        "`+login <key>` - Unlock the bot\n"
        "`+message` - Start the interactive reminder setup\n"
        "`+stop` - Stop all active reminders immediately\n"
    )
    await ctx.send(msg)

@bot.command()
async def stop(ctx):
    global ACTIVE_TASKS
    if not ACTIVE_TASKS:
        return await ctx.send("🛑 There are no active reminders running to stop.")
    
    # Cancel all running background loops
    for task in ACTIVE_TASKS:
        if not task.done():
            task.cancel()
            
    ACTIVE_TASKS.clear()
    await ctx.send("🛑 **All active reminders have been stopped!**")

@bot.command()
async def message(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    # Step 1: Server ID
    await ctx.send("📝 **Step 1:** Please provide the **Server ID** where you want to send the reminders.")
    try:
        msg_guild = await bot.wait_for('message', timeout=60.0, check=check)
        guild_id = int(msg_guild.content.strip())
        
        guild = bot.get_guild(guild_id)
        if not guild:
            return await ctx.send("❌ I cannot find a server with that ID. Make sure I am invited to it first.")
            
    except ValueError:
        return await ctx.send("❌ Invalid ID format. It must be numbers only.")
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Time is up. Try the command again.")

    # Step 2: Message Content
    await ctx.send(f"📝 **Step 2:** I found the server **{guild.name}**.\nWhat message would you like me to send?")
    try:
        msg_content_resp = await bot.wait_for('message', timeout=120.0, check=check)
        message_content = msg_content_resp.content.strip()
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Time is up. Try the command again.")

    # Step 3: Interval
    await ctx.send(
        "📝 **Step 3:** How often should I send this message?\n"
        "*(Limits: Min `1s`, Max `10h`. Recommended for testing: `10s`. Recommended for reminders: `1h`)*"
    )
    try:
        msg_interval = await bot.wait_for('message', timeout=60.0, check=check)
        interval_str = msg_interval.content.strip()
        
        interval_seconds = parse_interval(interval_str)
        if not interval_seconds:
            return await ctx.send("❌ Invalid interval format. Please use numbers followed by s, m, or h.")
        
        if interval_seconds < 1:
            return await ctx.send("❌ The interval must be at least 1 second (`1s`).")
        if interval_seconds > 36000:
            return await ctx.send("❌ The interval cannot exceed 10 hours (`10h`).")
            
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Time is up. Try the command again.")

    # Final Step: Launch Background Task
    task = bot.loop.create_task(reminder_loop(guild_id, message_content, interval_seconds))
    ACTIVE_TASKS.append(task) # Save it so we can cancel it later with +stop
    
    await ctx.send(f"✅ **Reminder successfully started!**\nI will send:\n> {message_content}\n...to all valid channels in **{guild.name}** every `{interval_str}`.")

if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found.")
    else:
        bot.run(TOKEN)
