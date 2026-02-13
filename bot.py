import os
import sqlite3
from datetime import date
import discord
from discord import app_commands
from discord.ext import commands

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD TOKEN MISSING")

DB_PATH = "steam_bot.db"

MEMBER_ROLE_ID = 1471512804535046237
BOOSTER_ROLE_ID = 1469733875709378674
BOOSTER_ROLE_2_ID = 1471590464279810210
STAFF_ROLE_ID = 1471515890225774663
# =========================================

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DATABASE =================
def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT,
        games TEXT,
        used INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gens (
        user_id INTEGER,
        day TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        account_id INTEGER,
        reason TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        owner_id INTEGER,
        code TEXT UNIQUE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS referral_uses (
        user_id INTEGER UNIQUE
    )
    """)

    con.commit()
    con.close()

# ================= HELPERS =================
def has_role(member, role_id):
    return any(r.id == role_id for r in member.roles)

def base_limit(member):
    boosts = 0
    if has_role(member, BOOSTER_ROLE_ID):
        boosts += 1
    if has_role(member, BOOSTER_ROLE_2_ID):
        boosts += 1

    if boosts == 1:
        return 4
    if boosts >= 2:
        return 6
    return 2

def has_referral(user_id):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (user_id,))
    used = cur.fetchone() is not None
    con.close()
    return used

def daily_limit(member):
    if has_role(member, STAFF_ROLE_ID):
        return 999
    limit = base_limit(member)
    if has_referral(member.id):
        limit += 1
    return limit

def used_today(user_id):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM gens WHERE user_id=? AND day=?",
        (user_id, date.today().isoformat())
    )
    count = cur.fetchone()[0]
    con.close()
    return count

def staff_only(interaction):
    return has_role(interaction.user, STAFF_ROLE_ID)

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

# ================= REFERRAL =================
@bot.tree.command(name="refer", description="Use a referral code")
async def refer(interaction: discord.Interaction, code: str):
    con = db()
    cur = con.cursor()

    cur.execute("SELECT owner_id FROM referrals WHERE code=?", (code,))
    row = cur.fetchone()

    if not row:
        await interaction.response.send_message("❌ Invalid referral code.", ephemeral=True)
        con.close()
        return

    if row[0] == interaction.user.id:
        await interaction.response.send_message("❌ You cannot use your own code.", ephemeral=True)
        con.close()
        return

    cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (interaction.user.id,))
    if cur.fetchone():
        await interaction.response.send_message("❌ You already used a referral.", ephemeral=True)
        con.close()
        return

    cur.execute("INSERT INTO referral_uses VALUES (?)", (interaction.user.id,))
    con.commit()
    con.close()

    await interaction.response.send_message("✅ Referral applied! +1 daily account.", ephemeral=True)

# ================= PAGINATED LIST =================
class GameView(discord.ui.View):
    def __init__(self, user_id, pages):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.pages = pages
        self.index = 0

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ These buttons aren’t for you.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        await interaction.response.edit_message(content=self.pages[self.index], view=self)
        self.update_buttons()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        await interaction.response.edit_message(content=self.pages[self.index], view=self)
        self.update_buttons()

    def update_buttons(self):
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index == len(self.pages) - 1

# ================= USER COMMANDS =================
@bot.tree.command(name="listgames", description="View available games")
async def listgames(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT games FROM accounts WHERE used=0")
    rows = cur.fetchall()
    con.close()

    games = sorted({g.strip() for (row,) in rows for g in row.split(",")})
    if not games:
        await interaction.response.send_message("❌ No games in stock.")
        return

    pages = []
    chunk = 15
    for i in range(0, len(games), chunk):
        page = games[i:i+chunk]
        pages.append("🎮 **Available Games**\n" + "\n".join(page))

    view = GameView(interaction.user.id, pages)
    view.update_buttons()
    await interaction.response.send_message(pages[0], view=view)

# ================= START =================
bot.run(TOKEN)
