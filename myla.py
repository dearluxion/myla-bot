import discord
from discord.ext import commands
from discord import app_commands, ui
import google.generativeai as genai
import asyncio
import yt_dlp
import re
import os
from flask import Flask        # <--- เพิ่มตัวสร้างเว็บ
from threading import Thread   # <--- เพิ่มตัวทำงานเบื้องหลัง

# ==========================================
# 0. หัวใจเทียม (ทำให้บอทไม่หลับ)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Myla is Online! 24/7"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# ==========================================
# 1. โซนตั้งค่า (Config Zone)
# ==========================================
# ดึงคีย์จากตู้เซฟออนไลน์ (เดี๋ยวพาไปใส่)
API_KEY = os.getenv("GEMINI_API_KEY") 
if API_KEY:
    genai.configure(api_key=API_KEY)

# เลือกโมเดล AI
try:
    model = genai.GenerativeModel('gemini-2.5-flash')
except:
    model = genai.GenerativeModel('gemini-1.5-flash')

# ==========================================
# 2. ระบบคิวเพลง & เก็บห้อง
# ==========================================
song_queues = {}
guild_channels = {}

def get_queue(guild_id):
    if guild_id not in song_queues:
        song_queues[guild_id] = []
    return song_queues[guild_id]

# ==========================================
# 3. ตั้งค่าระบบเสียง
# ==========================================
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extract_flat': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -af "bass=g=5,equalizer=f=1000:width_type=h:width=200:g=2"'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def create_source(cls, data, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        to_run = lambda: ytdl.extract_info(data['url'], download=False)
        processed_data = await loop.run_in_executor(None, to_run)
        
        if 'entries' in processed_data:
            processed_data = processed_data['entries'][0]
            
        filename = processed_data['url']
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=processed_data, volume=0.5)

# ==========================================
# 4. ระบบ UI จัดการคิว
# ==========================================

class JumpDropdown(ui.Select):
    def __init__(self, guild_id):
        queue = get_queue(guild_id)
        options = []
        for i, song in enumerate(queue[:20]):
            label = f"{i+1}. {song['title'][:90]}"
            options.append(discord.SelectOption(label=label, value=str(i)))

        if not options:
            options.append(discord.SelectOption(label="ไม่มีเพลงในคิว", value="-1"))

        super().__init__(placeholder="⏩ เลือกเพลงเพื่อลัดคิว...", min_values=1, max_values=1, options=options, disabled=len(queue) == 0)

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        if index == -1: return
        
        guild_id = interaction.guild.id
        queue = get_queue(guild_id)
        
        if 0 <= index < len(queue):
            del queue[:index]
            interaction.guild.voice_client.stop()
            await interaction.response.send_message(f"ลัดคิวเรียบร้อย!", ephemeral=True)
        else:
            await interaction.response.send_message("เกิดข้อผิดพลาด", ephemeral=True)

class RemoveDropdown(ui.Select):
    def __init__(self, guild_id):
        queue = get_queue(guild_id)
        options = []
        for i, song in enumerate(queue[:20]):
            label = f"{i+1}. {song['title'][:90]}"
            options.append(discord.SelectOption(label=label, value=str(i)))

        if not options:
            options.append(discord.SelectOption(label="ว่างเปล่า", value="-1"))

        super().__init__(placeholder="🗑️ เลือกเพลงเพื่อลบ...", min_values=1, max_values=1, options=options, disabled=len(queue) == 0)

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        if index == -1: return

        guild_id = interaction.guild.id
        queue = get_queue(guild_id)

        if 0 <= index < len(queue):
            removed = queue.pop(index)
            await interaction.response.send_message(f"ลบเพลง **{removed['title']}** แล้ว!", ephemeral=True)
        else:
            await interaction.response.send_message("หาเพลงไม่เจอ", ephemeral=True)

class QueueManagerView(ui.View):
    def __init__(self, guild_id):
        super().__init__()
        self.add_item(JumpDropdown(guild_id))
        self.add_item(RemoveDropdown(guild_id))

    @ui.button(label="ล้างคิวทั้งหมด", style=discord.ButtonStyle.danger, emoji="🔥")
    async def clear_queue(self, interaction: discord.Interaction, button: ui.Button):
        queue = get_queue(interaction.guild.id)
        queue.clear()
        await interaction.response.send_message("ล้างคิวหมดแล้ว! 🔥", ephemeral=True)

# ==========================================
# 5. ระบบปุ่มควบคุมหลัก
# ==========================================
class MusicControl(ui.View):
    def __init__(self, guild):
        super().__init__(timeout=None)
        self.guild = guild

    @ui.button(label="หยุด/เล่น", style=discord.ButtonStyle.secondary, emoji="⏯️")
    async def pause_resume(self, interaction: discord.Interaction, button: ui.Button):
        vc = self.guild.voice_client
        if vc:
            if vc.is_playing():
                vc.pause()
                await interaction.response.send_message("หยุดพักชั่วคราว ⏸️", ephemeral=True)
            elif vc.is_paused():
                vc.resume()
                await interaction.response.send_message("เล่นต่อ ⏩", ephemeral=True)

    @ui.button(label="ข้าม", style=discord.ButtonStyle.primary, emoji="⏭️")
    async def skip(self, interaction: discord.Interaction, button: ui.Button):
        vc = self.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("ข้ามเพลง! ⏭️", ephemeral=True)
        else:
             await interaction.response.send_message("ไม่มีเพลงเล่นอยู่", ephemeral=True)

    @ui.button(label="-Vol", style=discord.ButtonStyle.success, emoji="🔉")
    async def vol_down(self, interaction: discord.Interaction, button: ui.Button):
        vc = self.guild.voice_client
        if vc and vc.source:
            new_vol = max(0.1, vc.source.volume - 0.1)
            vc.source.volume = new_vol
            await interaction.response.send_message(f"เสียง: {int(new_vol*100)}% 🔉", ephemeral=True)

    @ui.button(label="+Vol", style=discord.ButtonStyle.success, emoji="🔊")
    async def vol_up(self, interaction: discord.Interaction, button: ui.Button):
        vc = self.guild.voice_client
        if vc and vc.source:
            new_vol = min(2.0, vc.source.volume + 0.1)
            vc.source.volume = new_vol
            await interaction.response.send_message(f"เสียง: {int(new_vol*100)}% 🔊", ephemeral=True)

    @ui.button(label="คิวเพลง", style=discord.ButtonStyle.secondary, emoji="📜")
    async def view_queue(self, interaction: discord.Interaction, button: ui.Button):
        queue = get_queue(self.guild.id)
        
        if not queue:
            desc = "ว่างเปล่า..."
        else:
            desc = ""
            for i, song in enumerate(queue[:10]):
                desc += f"`{i+1}.` {song['title']}\n"
            if len(queue) > 10:
                desc += f"...และอีก {len(queue)-10} เพลง"

        embed = discord.Embed(title=f"📜 คิวเพลง ({len(queue)} เพลง)", description=desc, color=0xffd700)
        await interaction.response.send_message(embed=embed, view=QueueManagerView(self.guild.id), ephemeral=True)

    @ui.button(label="ออก", style=discord.ButtonStyle.danger, emoji="👋")
    async def leave(self, interaction: discord.Interaction, button: ui.Button):
        vc = self.guild.voice_client
        if vc:
            if self.guild.id in song_queues:
                song_queues[self.guild.id].clear()
            await vc.disconnect()
            await interaction.response.send_message("บ๊ายบาย 👋", ephemeral=True)

# ==========================================
# 6. ฟังก์ชันเล่นเพลงต่อเนื่อง
# ==========================================
async def play_next_song(guild):
    queue = get_queue(guild.id)
    if len(queue) > 0:
        song_data = queue.pop(0)
        try:
            player = await YTDLSource.create_source(song_data, loop=bot.loop)
            
            def after_playing(error):
                if error: print(f"Player error: {error}")
                coro = play_next_song(guild)
                fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
                try: fut.result()
                except: pass

            guild.voice_client.play(player, after=after_playing)
            
            if guild.id in guild_channels:
                channel = guild_channels[guild.id]
                embed = discord.Embed(
                    title=f"🎵 Now Playing: {player.title}",
                    description=f"📜 **คิวที่เหลือ:** {len(queue)} เพลง",
                    color=0xff0000
                )
                if player.thumbnail: embed.set_thumbnail(url=player.thumbnail)
                elif 'thumbnail' in song_data: embed.set_thumbnail(url=song_data['thumbnail'])
                
                view = MusicControl(guild)
                await channel.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Error: {e}")
            await play_next_song(guild)

# ==========================================
# 7. ตรรกะหลัก (Main Logic)
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

async def play_music_logic(ctx_or_interaction, search_query):
    is_slash = isinstance(ctx_or_interaction, discord.Interaction)
    if is_slash:
        user = ctx_or_interaction.user
        guild = ctx_or_interaction.guild
        channel = ctx_or_interaction.channel
        await ctx_or_interaction.response.defer()
    else:
        user = ctx_or_interaction.author
        guild = ctx_or_interaction.guild
        channel = ctx_or_interaction.channel

    guild_channels[guild.id] = channel

    if not user.voice:
        msg = "ต้องเข้าห้องเสียงก่อนนะคะ 🥺"
        if is_slash: await ctx_or_interaction.followup.send(msg)
        else: await ctx_or_interaction.reply(msg)
        return

    if not guild.voice_client:
        try:
            await user.voice.channel.connect(timeout=60.0, reconnect=True)
        except:
            msg = "เชื่อมต่อไม่ได้ค่ะ 🥺"
            if is_slash: await ctx_or_interaction.followup.send(msg)
            else: await ctx_or_interaction.reply(msg)
            return
    else:
        if guild.voice_client.channel != user.voice.channel:
            await guild.voice_client.move_to(user.voice.channel)

    msg_response = ""
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=False))
        
        queue = get_queue(guild.id)
        added_count = 0
        first_title = ""

        if 'entries' in data:
            if data.get('extractor_key') == 'YoutubeSearch':
                queue.append(data['entries'][0])
                first_title = data['entries'][0]['title']
                added_count = 1
            else:
                for entry in data['entries']:
                    queue.append(entry)
                first_title = data['title']
                added_count = len(data['entries'])
        else:
            queue.append(data)
            first_title = data['title']
            added_count = 1

        if added_count > 1:
            msg_response = f"เพิ่ม **{added_count}** เพลงลงคิว! 🎵"
        else:
            msg_response = f"เพิ่ม **{first_title}** ลงคิว! 🎵"

        if not guild.voice_client.is_playing():
            await play_next_song(guild)
        
        # AI Talk
        try:
            if model and API_KEY:
                prompt = (f"คุณคือไมล่า แฟนสาวจอมมาร คุยกับ {user.display_name} "
                          f"บอกว่าจัดเพลง {first_title} ให้แล้ว (สั้นๆ น่ารัก)")
                resp = await loop.run_in_executor(None, lambda: model.generate_content(prompt))
                ai_text = resp.text
            else:
                ai_text = msg_response
        except:
            ai_text = msg_response

        if is_slash: await ctx_or_interaction.followup.send(ai_text)
        else: await ctx_or_interaction.reply(ai_text)

    except Exception as e:
        print(f"Error: {e}")
        err = "หาเพลงไม่เจอค่ะ 🥺"
        if is_slash: await ctx_or_interaction.followup.send(err)
        else: await ctx_or_interaction.reply(err)

# ==========================================
# 8. SLASH COMMANDS
# ==========================================
@bot.tree.command(name="say", description="พูดแทน")
@app_commands.describe(message="ข้อความ", image="แนบรูป")
async def say(interaction: discord.Interaction, message: str, image: discord.Attachment = None):
    if image:
        embed = discord.Embed(description=message, color=0xffc0cb)
        embed.set_image(url=image.url)
        await interaction.channel.send(embed=embed)
    else:
        await interaction.channel.send(message)
    await interaction.response.send_message(f"ส่งแล้ว! 🤫", ephemeral=True)

@bot.tree.command(name="play", description="เปิดเพลง")
async def play(interaction: discord.Interaction, query: str):
    await play_music_logic(interaction, query)

@bot.tree.command(name="stop", description="หยุดเพลง")
async def stop(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        if interaction.guild.id in song_queues:
            song_queues[interaction.guild.id].clear()
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("หยุดแล้ว 🫶")
    else:
        await interaction.response.send_message("เงียบอยู่แล้ว")

@bot.tree.command(name="skip", description="ข้ามเพลง")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("ข้าม! ⏭️")
    else:
        await interaction.response.send_message("ไม่มีเพลงให้ข้าม")

# ==========================================
# 9. EVENT HANDLERS
# ==========================================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'✅ Myla Online!')

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    content = message.content
    
    if "ไมล่า" in content and any(w in content for w in ["เปิดเพลง", "เล่นเพลง", "เปิด", "เล่น"]):
        query = re.sub(r'ไมล่า|เปิดเพลง|เล่นเพลง|เปิด|เล่น|หน่อย|ให้ที|ครับ|ค่ะ|นะ|จ๊ะ', '', content).strip()
        if query:
            await play_music_logic(message, query)
            return

    if "ไมล่า" in content or bot.user.mentioned_in(message):
        async with message.channel.typing():
            try:
                if model and API_KEY:
                    prompt = (f"คุณคือไมล่า แฟนสาวจอมมาร "
                              f"คุยกับ '{message.author.display_name}': {content} (สั้นๆ น่ารัก)")
                    resp = await asyncio.get_event_loop().run_in_executor(None, lambda: model.generate_content(prompt))
                    await message.reply(resp.text)
            except:
                pass

    await bot.process_commands(message)

# ==========================================
# 10. RUN BOT (จุดสำคัญ)
# ==========================================
keep_alive() # เริ่มหัวใจเทียมก่อน

token = os.getenv("TOKEN") # ไปเอารหัสจากตู้เซฟ
if token:
    bot.run(token)
else:
    print("❌ ไม่เจอ Token! อย่าลืมใส่ใน Render นะครับ")