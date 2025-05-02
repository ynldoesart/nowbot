import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import os
from dotenv import load_dotenv
import random
import sqlite3

# התחברות לבסיס הנתונים
conn = sqlite3.connect("invites.db")
c = conn.cursor()

# יצירת טבלה לשמירת ההזמנות
c.execute("""
CREATE TABLE IF NOT EXISTS invites (
    user_id INTEGER PRIMARY KEY,
    invite_count INTEGER
)
""")
conn.commit()

# יצירת טבלה למערכת רמות
c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, xp INTEGER)")
conn.commit()

# משתנה גלובלי למעקב אחרי הזמנות
invites = {}

# משתנה גלובלי לניהול תור השירים
song_queue = {}

# הגדרות הבוט
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.reactions = True
intents.members = True  # ודא שה-intent הזה מופעל
bot = commands.Bot(command_prefix="!", intents=intents)

# עדכון מספר ההזמנות בבסיס הנתונים
def update_invite_count(user_id, new_invites):
    # בדיקת מספר ההזמנות הקיים בבסיס הנתונים
    c.execute("SELECT invite_count FROM invites WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result:
        # הוספת ההזמנות החדשות למספר ההזמנות הקיים
        total_invites = result[0] + new_invites
        c.execute("UPDATE invites SET invite_count = ? WHERE user_id = ?", (total_invites, user_id))
    else:
        # אם המשתמש לא קיים בבסיס הנתונים, הוספתו עם מספר ההזמנות החדשות
        c.execute("INSERT INTO invites (user_id, invite_count) VALUES (?, ?)", (user_id, new_invites))
    conn.commit()

# הגדרות yt_dlp
youtube_dl.utils.bug_reports_message = lambda: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'ffmpeg_location': 'C:\\ffmpeg\\bin\\ffmpeg.exe',
    'default_search': 'ytsearch',
    'quiet': True,
    'cookiefile': 'path/to/cookies.txt',  # הוסף את הנתיב לקובץ ה-Cookies
}
ffmpeg_options = {
    'executable': 'C:\\ffmpeg\\bin\\ffmpeg.exe',  # נתיב מלא ל-ffmpeg
    'options': '-vn',
}
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        try:
            if not url.startswith("http"):
                url = f"ytsearch:{url}"
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            if 'entries' in data:
                data = data['entries'][0]
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)
        except Exception as e:
            print(f"Error extracting info: {e}")
            raise

def play_next_song(ctx):
    if song_queue[ctx.guild.id]:
        next_song = song_queue[ctx.guild.id].pop(0)
        ctx.voice_client.play(next_song, after=lambda e: play_next_song(ctx))
    else:
        asyncio.run_coroutine_threadsafe(ctx.voice_client.disconnect(), bot.loop)

def after_playing(error):
    if error:
        print(f"Player error: {error}")
    else:
        print("Song finished successfully.")

# פקודת !play
@bot.command(name="play")
async def play(ctx, *, query):
    if not ctx.author.voice:
        embed = discord.Embed(
            title="❌ Error",
            description="You need to be in a voice channel to play music!",
            color=0xFF0000
        )
        await ctx.send(embed=embed)
        return

    channel = ctx.author.voice.channel
    if not ctx.voice_client:
        try:
            await channel.connect()
        except discord.ClientException as e:
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to connect to the voice channel. Please try again.",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            print(f"Error connecting to voice channel: {e}")
            return
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="❌ Error",
                description="Connection to the voice channel timed out. Please try again.",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            return

    if not ctx.voice_client:
        await ctx.send("❌ The bot is not connected to a voice channel.")
        return

    async with ctx.typing():
        try:
            player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
            if not player:
                await ctx.send("❌ Could not find the requested song. Please try again.")
                return

            if ctx.guild.id not in song_queue:
                song_queue[ctx.guild.id] = []

            song_queue[ctx.guild.id].append(player)

            if not ctx.voice_client.is_playing():
                play_next_song(ctx)

            embed = discord.Embed(
                title="🎶 Now Playing",
                description=f"[{player.title}]({player.url})",
                color=0x1DB954
            )
            embed.set_thumbnail(url="https://mir-s3-cdn-cf.behance.net/project_modules/max_1200/8cfdf879936425.5cd284d4e4dd3.gif")
            embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar.url)

            await ctx.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to play the song. Please check the query or try again.",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            print(f"Error playing song: {e}")

# פקודת !stop
@bot.command(name="stop")
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        embed = discord.Embed(
            title="Music Stopped",
            description="The bot has disconnected from the voice channel.",
            color=0xFF4500
        )
        embed.set_thumbnail(url="https://i.imgur.com/5T1kejM.gif")
        await ctx.send(embed=embed)

# פקודת !pause
@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        embed = discord.Embed(
            title="⏸️ Music Paused",
            description="The music has been paused.",
            color=0xFFA500  # צבע כתום
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ No music is currently playing.")

# פקודת !resume
@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        embed = discord.Embed(
            title="▶️ Music Resumed",
            description="The music has been resumed.",
            color=0x1DB954  # צבע ירוק
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ No music is currently paused.")

# פקודת !skip
@bot.command(name="skip")
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()  # עוצר את השיר הנוכחי ומפעיל את הבא בתור
        embed = discord.Embed(
            title="⏭️ Song Skipped",
            description="The current song has been skipped.",
            color=0x1DB954  # צבע ירוק
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ No music is currently playing.")

# פקודת !queue
@bot.command(name="queue")
async def queue(ctx):
    if ctx.guild.id in song_queue and song_queue[ctx.guild.id]:
        embed = discord.Embed(
            title="🎶 Song Queue",
            description="Here are the songs currently in the queue:",
            color=0x1DB954  # צבע ירוק
        )
        for i, song in enumerate(song_queue[ctx.guild.id], start=1):
            embed.add_field(name=f"{i}. {song.title}", value=f"[Link]({song.url})", inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ The queue is currently empty.")

# פקודת !np (Now Playing)
@bot.command(name="np")
async def now_playing(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        current_song = ctx.voice_client.source
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"[{current_song.title}]({current_song.url})",
            color=0x1DB954  # צבע ירוק
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ No music is currently playing.")

@bot.command(name="music")
async def music(ctx):
    """
    פקודה להצגת כל פקודות המוזיקה עם הסבר.
    """
    embed = discord.Embed(
        title="🎵 Music Commands",
        description="Here are all the available music commands and what they do:",
        color=0x1DB954  # צבע ירוק
    )

    # הוספת פקודות מוזיקה
    embed.add_field(
        name="`!play [song]`",
        value="Plays a song from YouTube by name or URL. If a song is already playing, it will be added to the queue.",
        inline=False
    )
    embed.add_field(
        name="`!stop`",
        value="Stops the music and disconnects the bot from the voice channel.",
        inline=False
    )
    embed.add_field(
        name="`!pause`",
        value="Pauses the currently playing song.",
        inline=False
    )
    embed.add_field(
        name="`!resume`",
        value="Resumes the paused song.",
        inline=False
    )
    embed.add_field(
        name="`!skip`",
        value="Skips the currently playing song and plays the next song in the queue.",
        inline=False
    )
    embed.add_field(
        name="`!queue`",
        value="Displays the current song queue.",
        inline=False
    )
    embed.add_field(
        name="`!np`",
        value="Shows the currently playing song.",
        inline=False
    )

    embed.set_footer(text="Use these commands with the prefix '!' to control the music bot.")
    await ctx.send(embed=embed)

@bot.event
async def on_member_join(member):
    print(f"{member.name} has joined the server.")  # הודעת דיבוג
    channel = bot.get_channel(1353066066125000764)  # ה-ID של הערוץ שסיפקת
    if channel:
        embed = discord.Embed(
            title="👋 Welcome to the Server!",
            description=f"Welcome, {member.mention}! 🎉\nWe're glad to have you here. Feel free to introduce yourself and have fun!",
            color=0x1DB954
        )
        await channel.send(embed=embed)
    else:
        print("Welcome channel not found or bot lacks permissions.")

# מערכת Panel Ticket
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            category = await guild.create_category("Tickets")  # יצירת קטגוריה אם היא לא קיימת

        # בדיקה אם למשתמש כבר יש טיקט פתוח
        existing_channel = discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.id}")
        if (existing_channel):
            await interaction.response.send_message("❌ You already have an open ticket!", ephemeral=True)
            return

        # יצירת ערוץ טיקט
        ticket_channel = await category.create_text_channel(f"ticket-{interaction.user.id}")
        await ticket_channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
        await ticket_channel.set_permissions(guild.default_role, read_messages=False)

        # הודעה בערוץ הטיקט
        embed = discord.Embed(
            title="🎫 Ticket Opened",
            description=f"Hello {interaction.user.mention}, please describe your issue. A staff member will assist you shortly.",
            color=0x1DB954
        )
        await ticket_channel.send(embed=embed)

        staff_role = discord.utils.get(guild.roles, name="Support Team")
        if staff_role:
            await ticket_channel.send(f"{staff_role.mention}, a new ticket has been opened!")

        # תגובה למשתמש שפתח את הטיקט
        await interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)

@bot.command(name="panel")
async def panel(ctx):
    embed = discord.Embed(
        title="🎫 מערכת פתיחת טיקטים",
        description=(
            "ברוכים הבאים למערכת הטיקטים של השרת!\n"
            "אנא קראו את ההנחיות הבאות לפני פתיחת טיקט:\n\n"
            "1️⃣ **אין לפתוח טיקט ללא סיבה מוצדקת.**\n"
            "פתיחת טיקט ללא סיבה תגרור אזהרה או עונש.\n\n"
            "2️⃣ **היו ברורים ומפורטים.**\n"
            "כאשר אתם פותחים טיקט, אנא תארו את הבעיה או הבקשה שלכם בצורה ברורה.\n\n"
            "3️⃣ **אין לפתוח טיקט עבור נושאים שאינם קשורים לשרת.**\n"
            "לדוגמה: בקשות אישיות, פרסום, או כל דבר שאינו קשור לשרת.\n\n"
            "4️⃣ **המתינו בסבלנות.**\n"
            "צוות התמיכה יענה לכם בהקדם האפשרי. אין צורך לשלוח הודעות חוזרות.\n\n"
            "לחצו על הכפתור למטה כדי לפתוח טיקט."
        ),
        color=0x1DB954
    )
    embed.set_thumbnail(url="https://cdn.discordapp.com/icons/1352209606624935988/https://cdn.discordapp.com/attachments/1352766026122661969/1352785818384728246/69201e8c9db5352c3a2c64fbaf7a9bf4.jpg?ex=67df4778&is=67ddf5f8&hm=281d43d3b9f494231e128aff53a94c5266dca9b104a88dc1185e5c46151c3375&")  # החלף ב-URL של תמונת השרת
    embed.set_footer(text="תודה על שיתוף הפעולה!", icon_url="https://i.imgur.com/5T1kejM.gif")
    
    view = TicketView()
    await ctx.send(embed=embed, view=view)

@bot.command(name="close")
async def close(ctx):
    if ctx.channel.name.startswith("ticket-"):
        # שמירת לוגים
        with open(f"{ctx.channel.name}.txt", "w", encoding="utf-8") as log_file:
            async for message in ctx.channel.history(limit=None, oldest_first=True):
                log_file.write(f"{message.author}: {message.content}\n")

        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description=f"The ticket has been closed by {ctx.author.mention}.",
            color=0xFF4500
        )
        await ctx.send(embed=embed)
        await ctx.channel.delete()
    else:
        embed = discord.Embed(
            title="❌ Error",
            description="This command can only be used in a ticket channel.",
            color=0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command(name="add")
async def add(ctx, member: discord.Member):
    if ctx.channel.name.startswith("ticket-"):
        await ctx.channel.set_permissions(member, read_messages=True, send_messages=True)
        await ctx.send(f"✅ {member.mention} has been added to the ticket.")
    else:
        await ctx.send("❌ This command can only be used in a ticket channel.")

@bot.command(name="remove")
async def remove(ctx, member: discord.Member):
    if ctx.channel.name.startswith("ticket-"):
        await ctx.channel.set_permissions(member, overwrite=None)
        await ctx.send(f"✅ {member.mention} has been removed from the ticket.")
    else:
        await ctx.send("❌ This command can only be used in a ticket channel.")

# מערכת Verification עם כפתור
class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # הכפתור לא יפוג

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="<:custom_emoji_name:1352411558113710253>", custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        role = guild.get_role(1352405422216319077)  # שימוש ב-ID של התפקיד
        
        # בדיקה אם התפקיד Verified קיים
        if not role:
            await interaction.response.send_message("❌ The 'Verified' role does not exist. Please contact an admin.", ephemeral=True)
            return

        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("❌ Could not verify you. Please make sure you are a member of the server.", ephemeral=True)
            return

        try:
            # ניסיון להוסיף את התפקיד למשתמש
            await member.add_roles(role)
            await interaction.response.send_message("✅ You have been verified and now have access to the server!", ephemeral=True)
        except discord.Forbidden:
            # אם לבוט אין הרשאות מתאימות
            await interaction.response.send_message("❌ I don't have permission to assign roles. Please contact an admin.", ephemeral=True)

# פקודת !verify
@bot.command(name="verify")
async def verify(ctx):
    embed = discord.Embed(
        title="__Verification__",
        description="Click the button below to verify yourself and gain access to the server.",
        color=0x1DB954
    )
    view = VerificationView()
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_ready():
    global invites  # הכרזת המשתנה כגלובלי
    for guild in bot.guilds:
        try:
            invites[guild.id] = await guild.invites()  # שמירת ההזמנות הקיימות
        except Exception as e:
            print(f"Error fetching invites for guild {guild.name}: {e}")
    
    # הגדרת סטטוס מותאם אישית
    await bot.change_presence(
        activity=discord.Streaming(name="Live Coding", url="https://twitch.tv/your_channel"),
        status=discord.Status.dnd
    )
    print(f"Bot is ready and tracking invites! Logged in as {bot.user}")

from discord.ext.commands import has_permissions, MissingPermissions
# פקודת !clear
@bot.command(name="clear")
@has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    embed = discord.Embed(
        title="🧹 Chat Cleared",
        description=f"{amount} messages have been deleted.",
        color=0x1DB954
    )
    await ctx.send(embed=embed, delete_after=5)

@clear.error
async def clear_error(ctx, error):
    if isinstance(error, MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")

# פקודת !ban
@bot.command(name="ban")
@has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    embed = discord.Embed(
        title="🔨 User Banned",
        description=f"{member.mention} has been banned.\nReason: {reason or 'No reason provided.'}",
        color=0xFF0000
    )
    await ctx.send(embed=embed)

@ban.error
async def ban_error(ctx, error):
    if isinstance(error, MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")

@bot.command(name="unban")
@has_permissions(ban_members=True)
async def unban(ctx, *, member):
    banned_users = await ctx.guild.bans()
    member_name, member_discriminator = member.split('#')

    for ban_entry in banned_users:
        user = ban_entry.user

        if (user.name, user.discriminator) == (member_name, member_discriminator):
            await ctx.guild.unban(user)
            embed = discord.Embed(
                title="🔓 User Unbanned",
                description=f"{user.mention} has been unbanned.",
                color=0x1DB954
            )
            await ctx.send(embed=embed)
            return

    await ctx.send("❌ User not found in the ban list.")

@unban.error
async def unban_error(ctx, error):
    if isinstance(error, MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Please specify a user to unban. Example: `!unban User#1234`")

# פקודת !kick
@bot.command(name="kick")
@has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    embed = discord.Embed(
        title="👢 User Kicked",
        description=f"{member.mention} has been kicked.\nReason: {reason or 'No reason provided.'}",
        color=0xFF4500
    )
    await ctx.send(embed=embed)

@kick.error
async def kick_error(ctx, error):
    if isinstance(error, MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")

# פקודת !mute
@bot.command(name="mute")
@has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, time: int):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not role:
        role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(role, send_messages=False, speak=False)

    await member.add_roles(role)
    embed = discord.Embed(
        title="🔇 User Muted",
        description=f"{member.mention} has been muted for {time} seconds.",
        color=0xFFA500
    )
    await ctx.send(embed=embed)

    await asyncio.sleep(time)
    await member.remove_roles(role)

@mute.error
async def mute_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Please specify a member and duration. Example: `!mute @user 60`")
    elif isinstance(error, MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")

# פקודת !unmute
@bot.command(name="unmute")
@has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if role in member.roles:
        await member.remove_roles(role)
        embed = discord.Embed(
            title="🔊 User Unmuted",
            description=f"{member.mention} has been unmuted.",
            color=0x1DB954
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ This user is not muted.")

@unmute.error
async def unmute_error(ctx, error):
    if isinstance(error, MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")

# פקודת !slowmode
@bot.command(name="slowmode")
@has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    embed = discord.Embed(
        title="🐢 Slowmode Enabled",
        description=f"Slowmode has been set to {seconds} seconds.",
        color=0x1DB954
    )
    await ctx.send(embed=embed)

@slowmode.error
async def slowmode_error(ctx, error):
    if isinstance(error, MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")

@bot.command(name="drawprompt")
async def drawprompt(ctx):
    prompts = [
        "Draw a dragon in pixel art style.",
        "Create a futuristic cityscape.",
        "Sketch a magical creature.",
        "Design a superhero costume.",
        "Illustrate a scene from your favorite movie."
    ]
    prompt = random.choice(prompts)
    embed = discord.Embed(
        title="🎨 Drawing Prompt",
        description=prompt,
        color=0x1DB954
    )
    await ctx.send(embed=embed)

@bot.command(name="animationtip")
async def animationtip(ctx):
    tips = [
        "Keep your keyframes clear to avoid choppy motion.",
        "Use easing to make movements feel natural.",
        "Study real-life motion for reference.",
        "Experiment with timing to create dynamic animations.",
        "Don't forget to add secondary motion for realism."
    ]
    tip = random.choice(tips)
    embed = discord.Embed(
        title="🎞️ Animation Tip",
        description=tip,
        color=0x1DB954
    )
    await ctx.send(embed=embed)

@bot.command(name="palette")
async def palette(ctx):
    palettes = [
        ["#FF5733", "#33FF57", "#3357FF", "#F3FF33"],
        ["#FFB6C1", "#FFD700", "#8A2BE2", "#00CED1"],
        ["#FF4500", "#32CD32", "#1E90FF", "#FFDAB9"]
    ]
    palette = random.choice(palettes)
    embed = discord.Embed(
        title="🎨 Color Palette",
        description="Here is a random color palette for inspiration:",
        color=0x1DB954
    )
    embed.add_field(name="Colors", value=", ".join(palette))
    await ctx.send(embed=embed)

@bot.command(name="feedback")
async def feedback(ctx):
    feedback_role = discord.utils.get(ctx.guild.roles, name="Feedback Team")
    if feedback_role:
        await ctx.send(f"📢 {feedback_role.mention}, someone is requesting feedback!")
    else:
        await ctx.send("❌ Feedback role not found.")

@bot.command(name="speedpaint")
async def speedpaint(ctx, minutes: int = 10):
    embed = discord.Embed(
        title="⏱️ Speedpaint Challenge",
        description=f"You have {minutes} minutes to complete your speedpaint. Go!",
        color=0x1DB954
    )
    await ctx.send(embed=embed)
    await asyncio.sleep(minutes * 60)
    await ctx.send("⏰ Time's up! Share your creations!")

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        if before.channel and bot.user in before.channel.members and len(before.channel.members) == 1:
            await asyncio.sleep(300)
            if len(before.channel.members) == 1:
                await bot.voice_clients[0].disconnect()
    except Exception as e:
        print(f"Error in on_voice_state_update: {e}")

@bot.command(name="drawgame")
async def drawgame(ctx):
    lines = [
        "Draw something using only 3 lines.",
        "Create a character using only circles.",
        "Sketch a scene with only one color."
    ]
    challenge = random.choice(lines)
    embed = discord.Embed(
        title="🎮 Art Game",
        description=challenge,
        color=0x1DB954
    )
    await ctx.send(embed=embed)

@bot.command(name="remind")
async def remind(ctx, time: int, *, message: str):
    await ctx.send(f"⏰ Reminder set for {time} minutes.")
    await asyncio.sleep(time * 60)
    await ctx.send(f"🔔 Reminder: {message}")

import sqlite3

conn = sqlite3.connect("xp.db")
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, xp INTEGER)")
# יצירת טבלה למערכת הכלכלה
c.execute("CREATE TABLE IF NOT EXISTS economy (id INTEGER PRIMARY KEY, balance INTEGER)")
conn.commit()

# משתנה גלובלי למעקב אחרי הודעות
user_messages = {}

# משתנה גלובלי למעקב אחרי עבודות פעילות
active_jobs = {}

# מערכת רמות
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    c.execute("SELECT xp FROM users WHERE id = ?", (user_id,))
    result = c.fetchone()

    if result:
        xp = result[0] + 10  # הוספת XP
        c.execute("UPDATE users SET xp = ? WHERE id = ?", (xp, user_id))
    else:
        xp = 10
        c.execute("INSERT INTO users (id, xp) VALUES (?, ?)", (user_id, xp))
    conn.commit()

    # בדיקת רמה
    level = xp // 100
    if xp % 100 == 0:
        await message.channel.send(f"🎉 {message.author.mention} עלה לרמה {level}!")

    await bot.process_commands(message)

@bot.command(name="rank")
async def rank(ctx):
    user_id = ctx.author.id
    c.execute("SELECT xp FROM users WHERE id = ?", (user_id,))
    result = c.fetchone()

    if result:
        xp = result[0]
        level = xp // 100
        await ctx.send(f"🏆 {ctx.author.mention}, אתה ברמה {level} עם {xp} XP.")
    else:
        await ctx.send("❌ אין לך XP עדיין.")

@bot.command(name="work")
async def work(ctx):
    jobs = {
        "chat": {
            "description": "Send 50 messages in the server.",
            "reward": 100
        },
        "voice": {
            "description": "Spend 3 hours in a voice channel.",
            "reward": 200
        }
    }

    embed = discord.Embed(
        title="💼 Available Jobs",
        description="Choose a job to start working:",
        color=0x1DB954
    )
    for job, details in jobs.items():
        embed.add_field(name=job.capitalize(), value=f"{details['description']} (Reward: {details['reward']} coins)", inline=False)

    await ctx.send(embed=embed)

    # שמירת העבודה שנבחרה
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in jobs

    try:
        msg = await bot.wait_for("message", check=check, timeout=30.0)
        job_name = msg.content.lower()
        active_jobs[ctx.author.id] = {"job": job_name, "progress": 0, "reward": jobs[job_name]["reward"]}

        await ctx.send(f"✅ You have started the job: **{job_name.capitalize()}**. {jobs[job_name]['description']}")
    except asyncio.TimeoutError:
        await ctx.send("❌ You didn't choose a job in time. Please try again.")

@bot.command(name="shutdown")
@commands.is_owner()  # רק הבעלים של הבוט יכול להשתמש בפקודה זו
async def shutdown(ctx):
    await ctx.send("🛑 Shutting down...")
    await bot.close()

import os

# משתנה גלובלי לשמירת ה-ID של החדר
welcome_channel_id = None

# פקודת setup להגדרת חדר הברכה
@bot.command(name="setup")
@commands.has_permissions(administrator=True)  # רק אדמינים יכולים להשתמש בפקודה
async def setup(ctx, channel: discord.TextChannel):
    global welcome_channel_id
    welcome_channel_id = channel.id

    # שמירת ה-ID של החדר בקובץ
    with open("welcome_channel.txt", "w") as file:
        file.write(str(channel.id))

    embed = discord.Embed(
        title="✅ Setup Complete",
        description=f"Welcome messages will now be sent to {channel.mention}.",
        color=0x1DB954
    )
    await ctx.send(embed=embed)


# אירוע on_member_join לשליחת הודעת ברכה
@bot.event
async def on_member_join(member):
    print(f"{member.name} has joined the server.")  # הודעת דיבוג
    if welcome_channel_id is None:
        print("No welcome channel set.")
        return

    channel = bot.get_channel(welcome_channel_id)
    if channel:
        embed = discord.Embed(
            title="👋 Welcome to the Server!",
            description=f"Welcome, {member.mention}! 🎉\nWe're glad to have you here. Feel free to introduce yourself and have fun!",
            color=0x1DB954
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        embed.set_image(url="https://i.pinimg.com/originals/51/0a/a4/510aa4cebb7bccc7c283cca10f3b6601.gif")  # ה-GIF שיוצג מתחת לטקסטים
        embed.set_footer(text="Enjoy your stay!", icon_url="https://cdn.discordapp.com/attachments/1352406443491590197/1352641119472713789/69201e8c9db5352c3a2c64fbaf7a9bf4.jpg?ex=67dec0b5&is=67dd6f35&hm=ec627687c955a1b878bb2790390c440b1ef2404f6a8ba604f7d87f5514c9abf9&")

        await channel.send(embed=embed)
    else:
        print("Welcome channel not found.")

@bot.command(name="poll")
async def poll(ctx, question: str, *options):
    if len(options) < 2:
        await ctx.send("❌ You need at least two options to create a poll.")
        return
    if len(options) > 10:
        await ctx.send("❌ You can only provide up to 10 options.")
        return

    embed = discord.Embed(
        title="📊 Poll",
        description=question,
        color=0x1DB954
    )
    reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, option in enumerate(options):
        embed.add_field(name=f"{reactions[i]} {option}", value="\u200b", inline=False)

    message = await ctx.send(embed=embed)
    for i in range(len(options)):
        await message.add_reaction(reactions[i])

import aiohttp

@bot.command(name="balance")
async def balance(ctx):
    user_id = ctx.author.id
    c.execute("SELECT balance FROM economy WHERE id = ?", (user_id,))
    result = c.fetchone()
    if result:
        balance = result[0]
    else:
        balance = 0
        c.execute("INSERT INTO economy (id, balance) VALUES (?, ?)", (user_id, balance))
        conn.commit()

    embed = discord.Embed(
        title="💰 Balance",
        description=f"{ctx.author.mention}, your current balance is **{balance} coins**.",
        color=0x1DB954
    )
    await ctx.send(embed=embed)

@bot.command(name="progress")
async def progress(ctx):
    user_id = ctx.author.id
    if user_id not in active_jobs:
        await ctx.send("❌ You are not currently working on any job.")
        return

    job = active_jobs[user_id]["job"]
    progress = active_jobs[user_id]["progress"]
    if job == "chat":
        await ctx.send(f"📊 Progress: You have sent {progress}/50 messages.")
    elif job == "voice":
        await ctx.send(f"📊 Progress: You have spent {progress:.2f}/3 hours in voice chat.")


@bot.command(name="rule")
async def rule(ctx):
    embed = discord.Embed(
        title="חוקי השרת",
        description=(
            "**1**\n"
            "יש להימנע מכל סוג של דיבור שאינו מכבד, כולל מילים גזעניות, הטרדות, שיח פוליטי, ריבים או אפליה כגון גזענות, הומופוביה וכדומה. "
            "אם אינכם יכולים להשתמש במילה מסוימת, אל תנסו לעקוף זאת. במידה וקיבלתם עונש, אין לעקוף אותו באמצעות משתמש אחר.\n\n"
            "**2**\n"
            "חל איסור מוחלט על פרסום תוכן מיני או תוכן קשה לצפייה בכל רחבי השרת. זה כולל: תמונות, קישורים, גיפים, תמונות פרופיל ובאנרים, שמות וסטטוסים.\n\n"
            "**3**\n"
            "אסור להפיץ או לחפש מידע אישי על משתמשים אחרים. כל שימוש בקישורי פישינג (IP Loggers) יגרור באן מיידי.\n\n"
            "**4**\n"
            "אין לפרסם הזמנות לשרתי דיסקורד אחרים, ערוצי יוטיוב, למכור פריטים בשרת (כגון משחקים, חשבונות או כל דבר אחר) או כל סוג של פרסום עצמי. "
            "**(כולל פרסום שרתי דיסקורד בפרטי)**\n\n"
            "**5**\n"
            "יש להימנע מהפרעה למהלך התקין של הצ'אט. זה כולל: הספמת תווים בודדים, משפטים קצרים או ארוכים, שימוש בכינויים או תמונות בלתי נראים, הצפת תיוגים או בקשות לדברים בחינם "
            "(כגון כסף, משחקים, נייטרו וכו').\n\n"
            "**6**\n"
            "השיחה בשרת הדיסקורד חייבת להתנהל בעברית או באנגלית בלבד. הודעות בשפות אחרות יימחקו, ובמידת הצורך יטופלו בהתאם.\n\n"
            "**7**\n"
            "אין להפריע למשתמשים אחרים בחדרי דיבור ('וויסים') בשרת. זה כולל: יצירת רעשים חזקים או כואבים למיקרופון, כניסה ויציאה מהירה משיחות, שימוש ביותר משני בוטים בשיחה אחת, "
            "או כל פעולה אחרת שעלולה לפגוע בחוויית הדיבור של אחרים.\n\n"
            "**8**\n"
            "יש להקפיד על הוראות החדרים. לכל חדר יש מטרה משלו. (במחשב - באמצע המסך, ליד שם החדר. בטלפון - מתחת לשם החדר, על ידי גרירת המסך שמאלה)"
        ),
        color=0xA020F0
    )
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1352766026122661969/1352785818384728246/69201e8c9db5352c3a2c64fbaf7a9bf4.jpg?ex=67df4778&is=67ddf5f8&hm=281d43d3b9f494231e128aff53a94c5266dca9b104a88dc1185e5c46151c3375&")  # החלף ב-URL של תמונת השרת
    embed.set_image(url="https://cdn.discordapp.com/attachments/1113255099712671857/1113261532554469416/hWwGxv1.jpg?ex=67deabd8&is=67dd5a58&hm=e6355c70746b8e8ef5b138794c1701dbf4f8f64d727738867379e076a9f91b61&")
    await ctx.send(embed=embed)

import datetime

# משתנה גלובלי לשמירת פרטי ההגרלה הפעילה
active_giveaway = {}

@bot.command(name="giveaway")
@commands.has_permissions(manage_messages=True)  # רק משתמשים עם הרשאות ניהול הודעות יכולים להפעיל את הפקודה
async def giveaway(ctx, duration: str, winners: int, *, prize: str):
    global active_giveaway

    # בדיקה אם יש כבר הגרלה פעילה
    if active_giveaway:
        await ctx.send("❌ יש כבר הגרלה פעילה. אנא בטל אותה לפני שתתחיל חדשה.")
        return

    # המרת משך הזמן לשניות
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        time = int(duration[:-1]) * time_units[duration[-1]]
    except (ValueError, KeyError):
        await ctx.send("❌ פורמט הזמן לא תקין. השתמש בפורמט כמו `1h`, `30m`, או `10s`.")
        return

    # יצירת Embed להגרלה
    embed = discord.Embed(
        title="🎉 הגרלה!",
        description=f"**פרס:** {prize}\n"
                    f"**משך זמן:** {duration}\n"
                    f"**מספר זוכים:** {winners}\n\n"
                    f"React with 🎉 to enter!",
        color=0x1DB954
    )
    embed.set_footer(text="ההגרלה תסתיים בעוד זמן קצר...")
    message = await ctx.send(embed=embed)

    # הוספת ריאקציה להגרלה
    await message.add_reaction("🎉")

    # שמירת פרטי ההגרלה
    active_giveaway = {
        "message_id": message.id,
        "channel_id": ctx.channel.id,
        "winners": winners,
        "prize": prize,
        "time": time
    }

    # עדכון ההודעה עם טיימר
    while time > 0:
        try:
            minutes, seconds = divmod(time, 60)
            hours, minutes = divmod(minutes, 60)
            time_left = f"{hours}h {minutes}m {seconds}s" if hours > 0 else f"{minutes}m {seconds}s"
            embed.description = f"**פרס:** {prize}\n" \
                                f"**משך זמן:** {time_left}\n" \
                                f"**מספר זוכים:** {winners}\n\n" \
                                f"React with 🎉 to enter!"
            await message.edit(embed=embed)
            await asyncio.sleep(1)
            time -= 1
        except Exception as e:
            print(f"Error in timer: {e}")
            break

    # בדיקת המשתתפים
    try:
        message = await ctx.channel.fetch_message(message.id)
        reaction = discord.utils.get(message.reactions, emoji="🎉")
        if not reaction or reaction.count <= 1:
            await ctx.send("❌ לא היו מספיק משתתפים בהגרלה.")
            active_giveaway = {}
            return

        users = await reaction.users().flatten()
        users.remove(bot.user)
        if len(users) < winners:
            winners = len(users)

        winners_list = random.sample(users, winners)
        winners_mentions = ", ".join([winner.mention for winner in winners_list])

        # הכרזת הזוכים
        embed = discord.Embed(
            title="🎉 תוצאות ההגרלה!",
            description=f"**פרס:** {prize}\n"
                        f"**זוכים:** {winners_mentions}",
            color=0xFFD700
        )
        await ctx.send(embed=embed)
    except Exception as e:
        print(f"Error in selecting winners: {e}")
        await ctx.send("❌ אירעה שגיאה במהלך בחירת הזוכים.")
        active_giveaway = {}

@bot.command(name="cancel_giveaway")
@commands.has_permissions(manage_messages=True)  # רק משתמשים עם הרשאות ניהול הודעות יכולים לבטל הגרלה
async def cancel_giveaway(ctx):
    global active_giveaway

    # בדיקה אם יש הגרלה פעילה
    if not active_giveaway:
        await ctx.send("❌ אין כרגע הגרלה פעילה.")
        return

    # מחיקת ההגרלה הפעילה
    channel = bot.get_channel(active_giveaway["channel_id"])
    if channel:
        try:
            message = await channel.fetch_message(active_giveaway["message_id"])
            await message.delete()
        except discord.NotFound:
            pass

    await ctx.send("❌ ההגרלה בוטלה בהצלחה.")
    active_giveaway = {}

@bot.command(name="commands")
async def help_command(ctx):
    embed = discord.Embed(
        title="__תפריט עזרה__",
        description="כאן תוכל למצוא את כל הפקודות הזמינות למשתמשים רגילים:",
        color=0x1DB954
    )
    
    # פקודות מוזיקה
    embed.add_field(
        name="🎵 פקודות מוזיקה",
        value=(
            "`!play [song]` - מנגן שיר לפי שם או קישור.\n"
            "`!stop` - עוצר את המוזיקה ומנתק את הבוט מערוץ הקול."
        ),
        inline=False
    )
    
    # פקודות יצירתיות
    embed.add_field(
        name="🎨 פקודות יצירתיות",
        value=(
            "`!drawprompt` - מקבל רעיון לציור.\n"
            "`!palette` - מקבל פלטת צבעים אקראית.\n"
            "`!animationtip` - מקבל טיפ לאנימציה.\n"
            "`!speedpaint [minutes]` - מתחיל אתגר ציור מהיר למשך זמן מסוים (ברירת מחדל: 10 דקות)."
        ),
        inline=False
    )
    
    # פקודות כלכלה
    embed.add_field(
        name="💼 פקודות כלכלה",
        value=(
            "`!balance` - בודק את יתרת המטבעות שלך.\n"
            "`!work` - מתחיל עבודה (כגון שליחת הודעות או שהייה בערוץ קול).\n"
            "`!progress` - בודק את ההתקדמות שלך בעבודה הנוכחית."
        ),
        inline=False
    )
    
    embed.set_footer(text="השתמש בפקודות עם הקידומת '!'")
    await ctx.send(embed=embed)

# משתנה גלובלי למעקב אחרי הזמנות
invites = {}  # ודא שהמשתנה מוגדר מחוץ לכל הפונקציות

@bot.event
async def on_ready():
    global invites  # הכרזת המשתנה כגלובלי
    for guild in bot.guilds:
        try:
            invites[guild.id] = await guild.invites()  # שמירת ההזמנות הקיימות
        except Exception as e:
            print(f"Error fetching invites for guild {guild.name}: {e}")
    print("Bot is ready and tracking invites!")

@bot.event
async def on_member_join(member):
    global invites  # הכרזת המשתנה כגלובלי
    guild = member.guild

    # שליחת הודעת ברוך הבא לערוץ הברכה
    welcome_channel = bot.get_channel(1352631527774621849)  # ה-ID של ערוץ הברכה
    if welcome_channel:
        embed = discord.Embed(
            title="__Welcome to the Server!__",
            description=(
                f"🎉 **Welcome, {member.mention}!** 🎉\n\n"
                "We're so excited to have you here! Feel free to introduce yourself, "
                "explore the channels, and join the fun. If you have any questions, "
                "don't hesitate to ask the staff team. Enjoy your stay! 😊"
            ),
            color=0xDAF7A6
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        embed.set_image(url="https://i.pinimg.com/originals/51/0a/a4/510aa4cebb7bccc7c283cca10f3b6601.gif")  # ה-GIF שיוצג בתחתית

        await welcome_channel.send(embed=embed)
    else:
        print("Welcome channel not found or bot lacks permissions.")

    # בדיקת ההזמנה ושליחת הודעה לערוץ ההזמנות
    try:
        new_invites = await guild.invites()  # קבלת רשימת ההזמנות המעודכנת
        old_invites = invites[guild.id]

        # בדיקה מי השתמש בהזמנה
        inviter = None
        for invite in old_invites:
            for new_invite in new_invites:
                if invite.code == new_invite.code and invite.uses < new_invite.uses:
                    inviter = invite.inviter
                    new_uses = new_invite.uses - invite.uses  # חישוב מספר ההזמנות החדשות
                    update_invite_count(inviter.id, new_uses)  # עדכון בבסיס הנתונים
                    invite.uses = new_invite.uses  # עדכון מספר השימושים בהזמנה
                    break

        invites[guild.id] = new_invites  # עדכון ההזמנות

        # שליחת הודעה לערוץ ההזמנות
        invites_channel = bot.get_channel(1353066066125000764)  # ה-ID של ערוץ ההזמנות
        if invites_channel:
            if inviter:
                await invites_channel.send(f"👋 {member.mention} הצטרף לשרת! הוזמן על ידי {inviter.mention}. יש לו כעת {new_invite.uses} הזמנות.")
            else:
                await invites_channel.send(f"👋 {member.mention} הצטרף לשרת! לא הצלחנו לזהות מי הזמין אותו.")
        else:
            print("Invites channel not found or bot lacks permissions.")
    except Exception as e:
        print(f"Error in on_member_join: {e}")

import sqlite3

# התחברות לבסיס הנתונים
conn = sqlite3.connect("invites.db")
c = conn.cursor()

# יצירת טבלה לשמירת ההזמנות
c.execute("""
CREATE TABLE IF NOT EXISTS invites (
    user_id INTEGER PRIMARY KEY,
    invite_count INTEGER
)
""")
conn.commit()

# עדכון מספר ההזמנות בבסיס הנתונים
def update_invite_count(user_id, count):
    c.execute("SELECT invite_count FROM invites WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result:
        c.execute("UPDATE invites SET invite_count = ? WHERE user_id = ?", (count, user_id))
    else:
        c.execute("INSERT INTO invites (user_id, invite_count) VALUES (?, ?)", (user_id, count))
    conn.commit()

@bot.command(name="say")
async def say(ctx, *, message: str):
    """
    פקודה שגורמת לבוט לשלוח הודעה עם הטקסט שסופק, כולל תיוגים.
    לאחר שליחת ההודעה, ההודעה המקורית של המשתמש תימחק.
    """
    await ctx.message.delete()  # מחיקת ההודעה של המשתמש
    await ctx.send(message)  # שליחת ההודעה של הבוט

@bot.command(name="invite")
async def invite(ctx):
    """
    פקודה להצגת מספר ההזמנות של המשתמש.
    """
    user_id = ctx.author.id  # מזהה המשתמש
    c.execute("SELECT invite_count FROM invites WHERE user_id = ?", (user_id,))
    result = c.fetchone()

    if result:
        invite_count = result[0]
    else:
        invite_count = 0  # אם אין רשומה למשתמש, מספר ההזמנות הוא 0

    # יצירת Embed להצגת מספר ההזמנות
    embed = discord.Embed(
        title="📨 Your Invites",
        description=f"{ctx.author.mention}, you have invited **{invite_count}** members to the server!",
        color=0x1DB954  # צבע ירוק
    )
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
    embed.set_footer(text="Keep inviting more members to grow the server! 🚀")

    await ctx.send(embed=embed)

@bot.event
async def on_member_update(before, after):
    # בדיקה אם המשתמש קיבל את תפקיד הבוסטר
    booster_role = discord.utils.get(after.guild.roles, name="Booster")  # שם התפקיד של הבוסטרים
    if booster_role and booster_role not in before.roles and booster_role in after.roles:
        # קבלת הערוץ שבו תישלח ההודעה
        boost_channel = after.guild.get_channel(1357816421115105463)  # ה-ID של ערוץ הבוסטים
        if boost_channel:
            embed = discord.Embed(
                title="🚀 Thank You for Boosting!",
                description=f"{after.mention} just boosted the server! 🎉\nThank you for your support! ❤️",
                color=0xFF73FA  # צבע ורוד
            )
            embed.set_thumbnail(url=after.avatar.url if after.avatar else after.default_avatar.url)
            embed.set_footer(text="Your boost helps the server grow!")
            await boost_channel.send(embed=embed)

@bot.command(name="dm")
@commands.has_permissions(administrator=True)  # רק אדמינים יכולים להשתמש בפקודה
async def dm(ctx, member: discord.Member, *, message: str):
    """
    פקודה לשליחת הודעה פרטית למשתמש.
    """
    try:
        # שליחת הודעה פרטית למשתמש
        await member.send(message)
        embed = discord.Embed(
            title="📩 Message Sent",
            description=f"The message has been sent to {member.mention} successfully!",
            color=0x1DB954  # צבע ירוק
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        # אם הבוט לא יכול לשלוח הודעה פרטית למשתמש
        embed = discord.Embed(
            title="❌ Error",
            description=f"Could not send a message to {member.mention}. They might have DMs disabled.",
            color=0xFF0000  # צבע אדום
        )
        await ctx.send(embed=embed)

@bot.command(name="google")
async def google(ctx, *, query: str):
    await ctx.send(f"🔍 חיפוש בגוגל: https://www.google.com/search?q={query.replace(' ', '+')}")

# התחברות עם הטוקן
load_dotenv()
bot.run(os.getenv("DISCORD_TOKEN"))
