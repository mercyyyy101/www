import os
import sqlite3
import logging
import random
import string
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT,
            reason TEXT,
            reporter INTEGER,
            day TEXT
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

def staff_only(interaction: discord.Interaction):
    return has_role(interaction.user, STAFF_ROLE_ID)

def used_today(user_id):
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=? AND day=?",
            (user_id, date.today().isoformat())
        )
        return cur.fetchone()[0]

def daily_limit(member):
    boosts = has_role(member, BOOSTER_ROLE_ID) + has_role(member, BOOSTER_ROLE_2_ID)
    base = 6 if boosts >= 2 else 4 if boosts == 1 else 2

    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (member.id,))
        if cur.fetchone():
            base += 1
    return base

def gen_referral_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ================= UI =================
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

    async def on_timeout(self):
        for i in self.children:
            i.disabled = True

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    logging.info(f"Logged in as {bot.user}")

# ================= USER COMMANDS =================

@bot.tree.command(name="search", description="Search stock for a game")
async def search(interaction: discord.Interaction, query: str):
    query_l = query.lower()

    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT games FROM accounts WHERE used=0")
        rows = cur.fetchall()

    matches = []
    for (games,) in rows:
        for g in games.split(","):
            if query_l in g.lower():
                matches.append(g.strip())

    if not matches:
        await interaction.response.send_message(f"❌ **{query}** is not in stock.")
        return

    await interaction.response.send_message(
        f"✅ **{query}** is in stock!\n"
        f"📦 Accounts available: **{len(matches)}**\n"
        f"🎮 Matches: {', '.join(sorted(set(matches))[:5])}"
    )

@bot.tree.command(name="stock", description="View stock by game")
async def stock(interaction: discord.Interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT games FROM accounts WHERE used=0")
        rows = cur.fetchall()

    counter = {}
    for (games,) in rows:
        for g in games.split(","):
            g = g.strip()
            counter[g] = counter.get(g, 0) + 1

    if not counter:
        await interaction.response.send_message("❌ No stock available.")
        return

    items = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    pages = []

    for i in range(0, len(items), 15):
        chunk = items[i:i+15]
        page = "📦 **Stock by Game**\n" + "\n".join(
            f"🎮 {g} — **{c}**" for g, c in chunk
        )
        pages.append(page)

    view = Pager(interaction.user.id, pages)
    await interaction.response.send_message(pages[0], view=view)

@bot.tree.command(name="steamaccount")
async def steamaccount(interaction: discord.Interaction, game: str):
    if used_today(interaction.user.id) >= daily_limit(interaction.user):
        await interaction.response.send_message("❌ Daily limit reached.", ephemeral=True)
        return

    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id, username, password FROM accounts WHERE used=0 AND LOWER(games) LIKE ? LIMIT 1",
            (f"%{game.lower()}%",)
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

@bot.tree.command(name="topusers")
async def topusers(interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT user_id, COUNT(*) 
            FROM gens 
            WHERE day=? 
            GROUP BY user_id 
            ORDER BY COUNT(*) DESC 
            LIMIT 10
        """, (date.today().isoformat(),))
        rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message("No activity today.")
        return

    msg = "\n".join(f"**{i+1}.** <@{u}> — {c}" for i, (u, c) in enumerate(rows))
    await interaction.response.send_message("🏆 **Top Users Today**\n" + msg)

# ================= REFERRALS =================

@bot.tree.command(name="refer")
async def refer(interaction, code: str):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT owner_id FROM referrals WHERE code=?", (code,))
        row = cur.fetchone()

        if not row or row[0] == interaction.user.id:
            await interaction.response.send_message("❌ Invalid referral code.", ephemeral=True)
            return

        cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (interaction.user.id,))
        if cur.fetchone():
            await interaction.response.send_message("❌ Already redeemed.", ephemeral=True)
            return

        cur.execute("INSERT INTO referral_uses VALUES (?)", (interaction.user.id,))

    await interaction.response.send_message("✅ Referral redeemed! +1 daily gen.", ephemeral=True)

@bot.tree.command(name="referral_create")
async def referral_create(interaction):
    code = gen_referral_code()
    with db() as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO referrals VALUES (?,?)", (interaction.user.id, code))
    await interaction.response.send_message(f"🎁 Your referral code: `{code}`", ephemeral=True)

# ================= STAFF COMMANDS =================

@bot.tree.command(name="bulkadd")
@app_commands.check(staff_only)
async def bulkadd(interaction, dump: str):
    added = failed = 0
    with db() as con:
        cur = con.cursor()
        for line in dump.splitlines():
            try:
                creds, games = line.split("|", 1)
                u, p = creds.split(":", 1)
                cur.execute(
                    "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
                    (u.strip(), p.strip(), games.strip())
                )
                added += 1
            except:
                failed += 1
    await interaction.response.send_message(
        f"✅ Added: {added}\n❌ Failed: {failed}",
        ephemeral=True
    )

@bot.tree.command(name="accountinfo")
@app_commands.check(staff_only)
async def accountinfo(interaction, account: str):
    user, pwd = account.split(":", 1)
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT games, used FROM accounts WHERE username=? AND password=?",
            (user, pwd)
        )
        acc = cur.fetchone()

        if not acc:
            await interaction.response.send_message("❌ Account not found.")
            return

        games, used = acc
        cur.execute("SELECT COUNT(*) FROM reports WHERE account=?", (account,))
        reports = cur.fetchone()[0]

    await interaction.response.send_message(
        f"🔍 **Account Info**\n"
        f"Games: {games}\n"
        f"Used: {'Yes' if used else 'No'}\n"
        f"Reports: {reports}"
    )

# ================= START =================
bot.run(TOKEN)
