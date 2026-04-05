import discord
from discord.ext import commands
import os
import asyncio
import time
import json
import urllib.request
import urllib.parse
import aiohttp
import random

# ==========================================
# ☢️ THE "NUCLEAR" PATCH (USER TOKEN LOGIN)
# ==========================================

async def patched_login(self, token):
    self.token = token.strip().strip('"')
    self._token_type = ""
    
    if not hasattr(self, '_HTTPClient__session') or getattr(self, '_HTTPClient__session').__class__.__name__ == '_MissingSentinel':
        self._HTTPClient__session = aiohttp.ClientSession()

    req = urllib.request.Request("https://discord.com/api/v9/users/@me")
    req.add_header("Authorization", self.token)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise discord.LoginFailure("Invalid User Token.")
        raise

async def direct_send(self, content=None, **kwargs):
    if hasattr(self, 'channel'):
        channel_id = self.channel.id 
    elif hasattr(self, 'id'):
        channel_id = self.id 
    else:
        return

    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    
    global bot
    session = bot.http._HTTPClient__session
    
    headers = {
        "Authorization": bot.http.token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    files_to_send = []
    if kwargs.get('files'):
        files_to_send.extend(kwargs['files'])
    if kwargs.get('file'):
        files_to_send.append(kwargs['file'])

    if files_to_send:
        data = aiohttp.FormData()
        payload = {'content': str(content) if content else ""}
        data.add_field('payload_json', json.dumps(payload))
        
        for i, file in enumerate(files_to_send):
            file.fp.seek(0)
            data.add_field(
                f'files[{i}]', 
                file.fp, 
                filename=file.filename,
                content_type='application/octet-stream' 
            )
        
        headers.pop("Content-Type", None) 
        
        try:
            async with session.post(url, data=data, headers=headers) as resp:
                if resp.status not in [200, 201]:
                    print(f"❌ Upload Failed: {resp.status}")
                return await resp.json()
        except Exception as e:
            print(f"❌ Upload Error: {e}")
            return None
    else:
        headers["Content-Type"] = "application/json"
        payload = {}
        if content:
            payload['content'] = str(content)
            
        async with session.post(url, json=payload, headers=headers) as resp:
            return await resp.json()

original_request = discord.http.HTTPClient.request
async def patched_request(self, route, **kwargs):
    headers = kwargs.get('headers', {})
    headers['Authorization'] = self.token
    headers['User-Agent'] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    kwargs['headers'] = headers
    
    try:
        return await original_request(self, route, **kwargs)
    except discord.HTTPException as e:
        if e.status == 401:
            return []
        raise e

# Apply Patches
discord.http.HTTPClient.static_login = patched_login
discord.http.HTTPClient.request = patched_request
discord.abc.Messageable.send = direct_send

# ==========================================
# --- CONFIGURATION ---
# ==========================================
TOKEN = os.getenv('DISCORD_TOKEN')
SECRET_KEY = os.getenv('KEY')
if SECRET_KEY:
    SECRET_KEY = SECRET_KEY.strip()

AUTHORIZED_USERS = set() 
ACTIVE_TASKS = [] 

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 
intents.guilds = True 

bot = commands.Bot(command_prefix='+', intents=intents, help_command=None)

# ==========================================
# --- CORE LOGIC & COMMANDS ---
# ==========================================

@bot.check
async def global_login_check(ctx):
    if ctx.command.name == 'login': return True
    if ctx.author.id in AUTHORIZED_USERS: return True
    await ctx.send("❌ **Access Denied.** Please use `+login <key>` first.")
    return False

def parse_interval(interval_str):
    interval_str = interval_str.lower().strip()
    try:
        if interval_str.endswith('s'):
            return float(interval_str[:-1])
        elif interval_str.endswith('m'):
            return float(interval_str[:-1]) * 60.0
        elif interval_str.endswith('h'):
            return float(interval_str[:-1]) * 3600.0
        elif interval_str.endswith('d'):
            return float(interval_str[:-1]) * 86400.0
        else:
            return float(interval_str) 
    except ValueError:
        return None

async def reminder_loop(guild_id, message_content, interval_seconds):
    try:
        await bot.wait_until_ready()
        
        while not bot.is_closed():
            loop_start_time = time.time()
            guild = bot.get_guild(guild_id)
            
            if guild:
                tasks = []
                # Fetch both text and voice channels for concurrent dispatch
                for channel in guild.channels:
                    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                        try:
                            if channel.permissions_for(guild.me).send_messages:
                                # Append the coro to the tasks list instead of awaiting it directly
                                tasks.append(channel.send(message_content))
                        except discord.Forbidden:
                            pass
                        except Exception as e:
                            print(f"Error preparing {channel.name}: {e}")
                
                # Execute all sends concurrently at the exact same time
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            
            # Smart Timer Compensation: Subtract the time it took to send from the interval
            elapsed_time = time.time() - loop_start_time
            sleep_time = interval_seconds - elapsed_time
            
            if sleep_time > 0:
                if sleep_time < 10:
                    target_time = time.time() + sleep_time
                    while time.time() < target_time:
                        await asyncio.sleep(0.05) # Finer precision for sub-second floats
                else:
                    await asyncio.sleep(sleep_time)
                
    except asyncio.CancelledError:
        print(f"Reminder loop for Guild {guild_id} was successfully stopped.")

@bot.event
async def on_ready():
    print(f'Logged in as "{bot.user.name}"')
    if SECRET_KEY:
        print("✅ Secret Key Loaded.")
    else:
        print("⚠️ Warning: No 'KEY' secret found.")
    print("✅ Nuclear Patch Active: User Token accepted.")
    print("✅ Testing Mode Active: Reminder system online with Concurrent Float Dispatch.")

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
        "`+join <invite_link>` - Join a server & bypass onboarding\n"
        "`+leave <server_id>` - Leave a server\n"
        "`+message` - Start the interactive reminder setup\n"
        "`+stop` - Stop all active reminders immediately\n"
    )
    await ctx.send(msg)

@bot.command()
async def join(ctx, invite_link: str):
    # Extract the raw invite code from the link
    code = invite_link.split("/")[-1]
    if "?" in code:
        code = code.split("?")[0]
        
    headers = {
        "Authorization": bot.http.token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "*/*"
    }
    session = bot.http._HTTPClient__session
    
    await ctx.send(f"🔄 **Attempting to join via code:** `{code}`...")
    
    try:
        # Step 1: Hit the join endpoint
        join_url = f"https://discord.com/api/v9/invites/{code}"
        
        # Add a fake session_id to bypass basic anti-spam
        payload = {"session_id": os.urandom(16).hex()}
        
        async with session.post(join_url, headers=headers, json=payload) as resp:
            if resp.status not in [200, 201]:
                # Grab the exact error message from Discord
                error_msg = await resp.text()
                if "captcha" in error_msg.lower():
                    return await ctx.send(f"❌ **Failed: CAPTCHA Required.** Discord blocked this automated join. Try joining manually.\nStatus: {resp.status}")
                return await ctx.send(f"❌ Failed to join. Status code: {resp.status}.\n**Error Details:** `{error_msg[:500]}`")
                
            data = await resp.json()
            guild_id = data.get("guild", {}).get("id")
            guild_name = data.get("guild", {}).get("name")
            
        await ctx.send(f"✅ Successfully joined **{guild_name}** (`{guild_id}`).\n🔄 Checking for Server Onboarding...")
        
        # Step 2: Fetch and bypass onboarding
        onboarding_url = f"https://discord.com/api/v9/guilds/{guild_id}/onboarding"
        async with session.get(onboarding_url, headers=headers) as resp:
            if resp.status == 200:
                onboarding_data = await resp.json()
                prompts = onboarding_data.get("prompts", [])
                
                if prompts:
                    responses = []
                    # Pick a random answer for every question
                    for prompt in prompts:
                        options = prompt.get("options", [])
                        if options:
                            chosen = random.choice(options)
                            responses.append(chosen["id"])
                    
                    # Submit the random answers
                    submit_url = f"https://discord.com/api/v9/guilds/{guild_id}/onboarding-responses"
                    submit_payload = {"onboarding_responses": responses}
                    
                    async with session.post(submit_url, headers=headers, json=submit_payload) as submit_resp:
                        if submit_resp.status in [200, 204]:
                            await ctx.send("✅ Onboarding completed automatically (Random options selected).")
                        else:
                            await ctx.send(f"⚠️ Server joined, but onboarding submission returned status {submit_resp.status}.")
                else:
                    await ctx.send("ℹ️ No onboarding prompts found for this server.")
            elif resp.status == 404:
                await ctx.send("ℹ️ This server does not have onboarding enabled.")
            else:
                await ctx.send(f"⚠️ Could not check onboarding. Status: {resp.status}")
                
    except Exception as e:
        await ctx.send(f"❌ Error during join process: {e}")

@bot.command()
async def leave(ctx, server_id: str):
    try:
        guild_id = int(server_id)
        guild = bot.get_guild(guild_id)
        guild_name = guild.name if guild else server_id
        
        headers = {
            "Authorization": bot.http.token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        session = bot.http._HTTPClient__session
        leave_url = f"https://discord.com/api/v9/users/@me/guilds/{guild_id}"
        
        async with session.delete(leave_url, headers=headers) as resp:
            if resp.status == 204:
                await ctx.send(f"👋 **Successfully left server:** `{guild_name}`")
            else:
                await ctx.send(f"❌ Failed to leave. Status code: {resp.status}. Make sure you are actually in that server.")
                
    except ValueError:
        await ctx.send("❌ Invalid Server ID format. It must be numbers only.")
    except Exception as e:
        await ctx.send(f"❌ Error leaving server: {e}")

@bot.command()
async def stop(ctx):
    global ACTIVE_TASKS
    if not ACTIVE_TASKS:
        return await ctx.send("🛑 There are no active reminders running to stop.")
    
    for task in ACTIVE_TASKS:
        if not task.done():
            task.cancel()
            
    ACTIVE_TASKS.clear()
    await ctx.send("🛑 **All active reminders have been stopped!**")

@bot.command()
async def message(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    await ctx.send("📝 **Step 1:** Please provide the **Server ID** where you want to send the reminders.")
    try:
        msg_guild = await bot.wait_for('message', timeout=60.0, check=check)
        guild_id = int(msg_guild.content.strip())
        
        guild = bot.get_guild(guild_id)
        if not guild:
            return await ctx.send("❌ I cannot find a server with that ID. Make sure I am invited to it first.")
            
        # Highlighted confirmation of the Server Name right after providing the ID
        await ctx.send(f"✅ **Server Found:** `{guild.name}`")
            
    except ValueError:
        return await ctx.send("❌ Invalid ID format. It must be numbers only.")
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Time is up. Try the command again.")

    await ctx.send(f"📝 **Step 2:** What message would you like me to send to **{guild.name}**?")
    try:
        msg_content_resp = await bot.wait_for('message', timeout=120.0, check=check)
        message_content = msg_content_resp.content.strip()
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Time is up. Try the command again.")

    await ctx.send(
        "📝 **Step 3:** How often should I send this message?\n"
        "*(Limits: Min `0.5s`, Max `10h`. Recommended: `2.5s` minimum if sending to multiple channels!)*"
    )
    try:
        msg_interval = await bot.wait_for('message', timeout=60.0, check=check)
        interval_str = msg_interval.content.strip()
        
        interval_seconds = parse_interval(interval_str)
        if interval_seconds is None:
            return await ctx.send("❌ Invalid interval format. Please use numbers followed by s, m, or h.")
        
        if interval_seconds < 0.5:
            return await ctx.send("❌ The absolute minimum interval allowed is `0.5s`.")
        if interval_seconds > 36000:
            return await ctx.send("❌ The interval cannot exceed 10 hours (`10h`).")
            
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Time is up. Try the command again.")

    task = bot.loop.create_task(reminder_loop(guild_id, message_content, interval_seconds))
    ACTIVE_TASKS.append(task) 
    
    await ctx.send(f"✅ **Reminder successfully started!**\nI will send:\n> {message_content}\n...concurrently to all valid Text/VC channels in **{guild.name}** every `{interval_str}`.")

if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found.")
    else:
        bot.run(TOKEN)
