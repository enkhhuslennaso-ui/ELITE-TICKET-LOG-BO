import os
import datetime
import asyncio
import threading
from flask import Flask
import discord
from discord.ext import commands
from discord.ui import Select, View, Button

# ==========================================
# 1. FLASK KEEP-ALIVE WEBSERVER (24/7)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Ticket Bot 24/7 амжилттай ажиллаж байна!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    thread = threading.Thread(target=run_flask)
    thread.daemon = True
    thread.start()

# ==========================================
# 2. DISCORD BOT CONFIGURATION
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ⚙️ ӨӨРИЙН СЕРВЕРИЙН ЖИНХЭНЭ ID-НУУДЫГ ЭНД ОРУУЛНА УУ
ADMIN_ROLE_ID = 1561373407033958524      # Админ ролийн ID
TICKET_CATEGORY_ID = 1561358461206528091 # Тикетүүд нээгдэх Support Category ID
LOG_CHANNEL_ID = 1566932061497983078     # Хаагдсан тикетийн лог очих сувгийн ID

# Давхар дарж олон суваг үүсэхээс хамгаалах санах ойн түгжээ
active_creators = set()

# ==========================================
# 3. TEXT TRANSCRIPT (EMBED LOG) GENERATOR
# ==========================================
async def generate_text_transcript(channel):
    messages = []
    async for msg in channel.history(limit=50, oldest_first=True):
        time_str = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.clean_content
        
        attachments = [att.url for att in msg.attachments]
        att_str = f"\n📎 **Файл/Зураг:** " + " | ".join(attachments) if attachments else ""
        
        messages.append(f"[`{time_str}`] **{msg.author.name}**: {content}{att_str}")
    
    transcript_text = "\n\n".join(messages)
    
    if len(transcript_text) > 4000:
        transcript_text = transcript_text[:3997] + "..."
    return transcript_text

# ==========================================
# 4. TICKET CONTROL VIEW (CLAIM & CLOSE)
# ==========================================
class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.green, custom_id="claim_ticket_btn", emoji="🛡️")
    async def claim_button(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Энэ товчлуурыг зөвхөн админууд ашиглах боломжтой!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🛡️ ТИКЕТ ХҮЛЭЭЖ АВСАН",
            description=f"Эрхэм хэрэглэгч таны үүсгэсэн билетийг **{interaction.user.mention}** амжилттай хүлээж авлаа.\n\n• Таны өгсөн мэдээллийг шалгаж байна, түр хүлээнэ үү.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Хариуцаж буй админ: {interaction.user.display_name}")
        await interaction.response.send_message(content=f"{interaction.user.mention}", embed=embed)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.red, custom_id="close_ticket_btn", emoji="🔒")
    async def close_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🔒 Энэ суваг хаагдаж, log бэлтгэгдэж байна...", ephemeral=True)
        
        transcript_content = await generate_text_transcript(interaction.channel)
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        
        if log_channel:
            embed = discord.Embed(
                title=f"🎫 Билет Хаагдлаа: {interaction.channel.name}",
                description=(
                    f"**Хаасан хэрэглэгч:** {interaction.user.mention}\n"
                    f"**Сувгийн нэр:** `{interaction.channel.name}`\n\n"
                    f"**Мессежийн түүх:**\n"
                    f"{transcript_content if transcript_content else 'Ямар нэгэн мессеж бичигдээгүй байна.'}"
                ),
                color=discord.Color.red(),
                timestamp=datetime.datetime.utcnow()
            )
            await log_channel.send(embed=embed)

        await asyncio.sleep(3)
        await interaction.channel.delete()

# ==========================================
# 5. TICKET SELECT MENU & PANEL LOGIC
# ==========================================
class TicketSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Clan Join", description="Кланд орох хүсэлт илгээх", emoji="🛡️"),
            discord.SelectOption(label="Support Ticket", description="Ямар нэгэн тусламж авах", emoji="🎫"),
            discord.SelectOption(label="Report Ticket", description="Админ эсвэл тоглогчид гомдол гаргах", emoji="⚠️"),
            discord.SelectOption(label="Partnership Ticket", description="Хамтын ажиллагаа болон реклам", emoji="🤝"),
        ]
        super().__init__(
            placeholder="Доорх цэснээс сонголт хийж билет нээнэ үү.", 
            min_values=1, 
            max_values=1, 
            options=options,
            custom_id="ticket_select_menu"
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.response.is_done():
            return
        
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        member = interaction.user
        selected_value = self.values[0]

        # 🛑 Нэг хэрэглэгч дараалж дарж олон суваг үүсгэхээс сэргийлэх түгжээ
        if member.id in active_creators:
            await interaction.followup.send("❌ Таны тикет үүсэх явцдаа байна, түр хүлээнэ үү!", ephemeral=True)
            return

        active_creators.add(member.id)
        try:
            # 🛑 Нэг хэрэглэгч зөвхөн 1 идэвхтэй тикеттэй байх шалгалт
            for channel in guild.text_channels:
                if channel.name.endswith(f"-{member.name.lower()}") and channel.name.startswith("ticket-"):
                    await interaction.followup.send(f"❌ Та аль хэдийн идэвхтэй тикет нээсэн байна: {channel.mention}", ephemeral=True)
                    return

            admin_role = guild.get_role(ADMIN_ROLE_ID)
            
            # 📂 Зөвхөн Support категори дотор үүсгэх
            category = guild.get_channel(TICKET_CATEGORY_ID)
            if not category or not isinstance(category, discord.CategoryChannel):
                category = discord.utils.get(guild.categories, name="SUPPORT")
                if not category:
                    category = await guild.create_category("SUPPORT")

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True)
            }
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True)

            clean_name = selected_value.lower().replace(" ", "-")
            safe_username = member.name.lower().replace(" ", "-")
            channel_name = f"ticket-{clean_name}-{safe_username}"
            
            ticket_channel = await guild.create_text_channel(
                name=channel_name, 
                overwrites=overwrites, 
                category=category
            )

            admin_mention = admin_role.mention if admin_role else "@admin"

            if selected_value == "Clan Join":
                embed = discord.Embed(
                    title="🛡️ ELITE CLAN — ЭЛСЭЛТИЙН ШААРДЛАГА",
                    description=(
                        f"Сайн байна уу, {member.mention}!\n\n"
                        "**Доорх асуултуудад дарааллаар нь үнэн зөв хариулна уу:**\n"
                        "1. Нас: Хэдэн настай вэ?\n"
                        "2. Тоглосон цаг: CS2 дээр нийт хэдэн цаг тоглосон бэ?\n"
                        "3. Элсэх шалтгаан: Яагаад ELITE clan-д орохыг хүсэж байна вэ?\n"
                        "4. Өмнөх clan: Өмнө нь ямар ямар clan-д орж байсан бэ?\n"
                        "5. FACEIT: FACEIT-ийн түвшин хэд вэ?\n"
                        "6. Premier ELO: Premier горимын одоогийн ELO хэд вэ?\n"
                        "7. Novacs rank: Novacs дээрх rank чинь хэд вэ?\n"
                        "8. Хүйс?\n\n"
                        "━━━━━━━━━━━━━━━━━━━━ **АНХААРУУЛГА**\n"
                        "Таны хариултаас tax тань 5-20к-д бодогдоно шүү.\n"
                        "Асуултуудыг бүрэн бөглөсний дараа ELITE-ийн Lounge call-д орж, шалгуулна. "
                        "Шалгалтад тэнцсэн тохиолдолд clan-д элсэх боломжтой. Баярлалаа. ELITE-д амжилт хүсье!\n\n"
                        f"{admin_mention} - Админууд хариултыг тань шалгах болно."
                    ),
                    color=discord.Color.gold()
                )
            else:
                embed = discord.Embed(
                    title=f"🎫 {selected_value} - Билет нээгдлээ",
                    description=(
                        f"Сайн байна уу, {member.mention}!\n\n"
                        f"Та **{selected_value}** чиглэлээр билет нээсэн байна.\n"
                        "Бидэнд тулгарсан асуудал болон холбогдох дэлгэрэнгүй мэдээллээ үлдээгээрэй.\n\n"
                        f"{admin_mention} - Удахгүй админууд тантай холбогдох болно."
                    ),
                    color=discord.Color.blue()
                )

            embed.set_footer(text="Асуудлаа шийдвэрлэсний дараа доорх товчлуураар хаана уу.")

            await ticket_channel.send(content=f"{member.mention} {admin_mention}", embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ Таны билет амжилттай нээгдлээ: {ticket_channel.mention}", ephemeral=True)
        
        finally:
            active_creators.discard(member.id)

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# ==========================================
# 6. BOT EVENTS & COMMANDS
# ==========================================
@bot.event
async def on_ready():
    bot.add_view(TicketView())
    bot.add_view(TicketControlView())
    print(f"✅ {bot.user} тикет бот амжилттай аслаа!")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_ticket(ctx):
    embed = discord.Embed(
        title="ELITE Support Center",
        description="Доорх цэснээс сонголт хийж билет нээнэ үү.",
        color=discord.Color.dark_theme()
    )
    await ctx.send(embed=embed, view=TicketView())

@bot.command()
@commands.has_permissions(administrator=True)
async def claim(ctx):
    if not ctx.channel.name.startswith("ticket-"):
        await ctx.send("❌ Энэ команд зөвхөн тикет суваг дээр ажиллана!", delete_after=5)
        return

    admin = ctx.author
    embed = discord.Embed(
        title="🛡️ ТИКЕТ ХҮЛЭЭЖ АВСАН",
        description=f"Эрхэм хэрэглэгч таны үүсгэсэн билетийг **{admin.mention}** амжилттай хүлээж авлаа.\n\n• Таны өгсөн мэдээллийг шалгаж байна, түр хүлээнэ үү.",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Хариуцаж буй админ: {admin.display_name}")
    await ctx.message.delete()
    await ctx.send(content=f"{admin.mention}", embed=embed)

@bot.command()
async def close(ctx):
    if ctx.channel.name.startswith("ticket-"):
        await ctx.send("🔒 Энэ суваг хаагдаж, log бэлтгэгдэж байна...")
        
        transcript_content = await generate_text_transcript(ctx.channel)
        log_channel = ctx.guild.get_channel(LOG_CHANNEL_ID)
        
        if log_channel:
            embed = discord.Embed(
                title=f"🎫 Билет Хаагдлаа: {ctx.channel.name}",
                description=(
                    f"**Хаасан хэрэглэгч:** {ctx.author.mention}\n"
                    f"**Сувгийн нэр:** `{ctx.channel.name}`\n\n"
                    f"**Мессежийн түүх:**\n"
                    f"{transcript_content if transcript_content else 'Ямар нэгэн мессеж бичигдээгүй байна.'}"
                ),
                color=discord.Color.red(),
                timestamp=datetime.datetime.utcnow()
            )
            await log_channel.send(embed=embed)

        await asyncio.sleep(3)
        await ctx.channel.delete()
    else:
        await ctx.send("❌ Энэ команд зөвхөн тикет суваг дээр ажиллана!", delete_after=5)

# ==========================================
# 7. RUN BOT
# ==========================================
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)