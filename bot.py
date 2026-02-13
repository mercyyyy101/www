import os
import sqlite3
import logging
from datetime import date

import discord
from discord.ext import commands
from discord import app_commands

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD TOKEN MISSING")

DB_PATH = "steam_bot.db"

BOOSTER_ROLE_ID = 1469733875709378674
BOOSTER_ROLE_2_ID = 1471590464279810210
STAFF_ROLE_ID = 1471515890225774663
# =========================================

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DATABASE =================
def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    with db() as con:
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
            account TEXT,
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

# ================= HELPERS =================
def has_role(member, role_id):
    return any(r.id == role_id for r in member.roles)

def daily_limit(member):
    boosts = has_role(member, BOOSTER_ROLE_ID) + has_role(member, BOOSTER_ROLE_2_ID)
    base = 6 if boosts >= 2 else 4 if boosts == 1 else 2

    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (member.id,))
        if cur.fetchone():
            base += 1
    return base

def used_today(user_id):
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=? AND day=?",
            (user_id, date.today().isoformat())
        )
        return cur.fetchone()[0]

def staff_only(interaction: discord.Interaction):
    return has_role(interaction.user, STAFF_ROLE_ID)

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    logging.info(f"Logged in as {bot.user}")

# ================= UI (Pagination) =================
class Pager(discord.ui.View):
    def __init__(self, user_id, pages):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.pages = pages
        self.index = 0
        self.update()

    def update(self):
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index == len(self.pages) - 1

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Not your buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, button):
        self.index -= 1
        self.update()
        await interaction.response.edit_message(content=self.pages[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        self.index += 1
        self.update()
        await interaction.response.edit_message(content=self.pages[self.index], view=self)

# ================= USER COMMANDS =================

@bot.tree.command(name="listgames", description="View available games")
async def listgames(interaction: discord.Interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT games FROM accounts WHERE used=0")
        rows = cur.fetchall()

    games = sorted({g.strip() for (row,) in rows for g in row.split(",")})
    if not games:
        await interaction.response.send_message("❌ No games in stock.")
        return

    pages = [
        "🎮 **Available Games**\n" + "\n".join(games[i:i+15])
        for i in range(0, len(games), 15)
    ]

    view = Pager(interaction.user.id, pages)
    await interaction.response.send_message(pages[0], view=view)

@bot.tree.command(name="search", description="Search for a game")
async def search(interaction: discord.Interaction, game: str):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM accounts WHERE used=0 AND games LIKE ?", (f"%{game}%",))
        count = cur.fetchone()[0]

    await interaction.response.send_message(
        f"✅ **{game}** is in stock ({count})" if count else f"❌ **{game}** not found."
    )

@bot.tree.command(name="stock", description="Check remaining stock")
async def stock(interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM accounts WHERE used=0")
        total = cur.fetchone()[0]
    await interaction.response.send_message(f"📦 Accounts left: **{total}**")

@bot.tree.command(name="steamaccount", description="Generate a Steam account")
async def steamaccount(interaction, game: str):
    if used_today(interaction.user.id) >= daily_limit(interaction.user):
        await interaction.response.send_message("❌ Daily limit reached.", ephemeral=True)
        return

    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id, username, password FROM accounts WHERE used=0 AND games LIKE ? LIMIT 1",
            (f"%{game}%",)
        )
        row = cur.fetchone()
        if not row:
            await interaction.response.send_message("❌ No account available.")
            return

        acc_id, user, pwd = row
        cur.execute("UPDATE accounts SET used=1 WHERE id=?", (acc_id,))
        cur.execute("INSERT INTO gens VALUES (?,?)", (interaction.user.id, date.today().isoformat()))

    await interaction.response.send_message(
        f"🎮 **Steam Account**\n`{user}:{pwd}`",
        ephemeral=True
    )

@bot.tree.command(name="mystats", description="View your stats")
async def mystats(interaction):
    used = used_today(interaction.user.id)
    limit = daily_limit(interaction.user)
    await interaction.response.send_message(
        f"📊 **Your Stats**\nUsed today: {used}/{limit}"
    )

@bot.tree.command(name="boostinfo", description="Boost perks")
async def boostinfo(interaction):
    await interaction.response.send_message(
        "💎 **Boost Perks**\n"
        "No Boost: 2/day\n"
        "1 Boost: 4/day\n"
        "2 Boosts: 6/day\n"
        "+ Referral: +1/day"
    )

@bot.tree.command(name="report", description="Report a bad account")
async def report(interaction, account: str, reason: str):
    with db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO reports VALUES (?,?)", (account, reason))
    await interaction.response.send_message("✅ Report submitted.", ephemeral=True)

# ================= REFERRALS =================
@bot.tree.command(name="refer", description="Use a referral code")
async def refer(interaction, code: str):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT owner_id FROM referrals WHERE code=?", (code,))
        row = cur.fetchone()
        if not row or row[0] == interaction.user.id:
            await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
            return
        cur.execute("INSERT OR IGNORE INTO referral_uses VALUES (?)", (interaction.user.id,))
    await interaction.response.send_message("✅ Referral applied! +1 daily gen.", ephemeral=True)

@bot.tree.command(name="referral_create", description="Create your referral code")
async def referral_create(interaction):
    code = f"{interaction.user.id}".replace("0", "A")
    with db() as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO referrals VALUES (?,?)", (interaction.user.id, code))
    await interaction.response.send_message(f"🎁 Your referral code: `{code}`", ephemeral=True)

# ================= STAFF COMMANDS =================
@bot.tree.command(name="addaccount")
@app_commands.check(staff_only)
async def addaccount(interaction, username: str, password: str, games: str):
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
            (username, password, games)
        )
    await interaction.response.send_message("✅ Account added.")

@bot.tree.command(name="reportedaccounts")
@app_commands.check(staff_only)
async def reportedaccounts(interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT account, reason FROM reports")
        rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message("No reports.")
        return

    pages = [
        "\n".join(f"{a} — {r}" for a, r in rows[i:i+10])
        for i in range(0, len(rows), 10)
    ]

    view = Pager(interaction.user.id, pages)
    await interaction.response.send_message(pages[0], view=view)

# ================= START =================
bot.run(TOKEN)
