import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from datetime import date
import random

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN missing")

DB_PATH = "steam_bot.db"

MEMBER_ROLE_ID = 1471512804535046237
BOOSTER_ROLE_ID = 1469733875709378674
BOOSTER_ROLE_2_ID = 1471590464279810210
STAFF_ROLE_ID = 1471515890225774663
# ========================================

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
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gens (
        user_id INTEGER,
        day TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        account TEXT,
        reason TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        user_id INTEGER,
        code TEXT UNIQUE
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS referral_uses (
        user_id INTEGER UNIQUE
    )""")

    con.commit()
    con.close()

# ================= HELPERS =================
def has_role(member, role_id):
    return any(r.id == role_id for r in member.roles)

def daily_limit(member):
    if has_role(member, STAFF_ROLE_ID):
        return 999
    limit = 2
    if has_role(member, BOOSTER_ROLE_ID):
        limit = 4
    if has_role(member, BOOSTER_ROLE_2_ID):
        limit = 6
    con = db()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (member.id,))
    if cur.fetchone():
        limit += 1
    con.close()
    return limit

def used_today(user_id):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM gens WHERE user_id=? AND day=?",
                (user_id, date.today().isoformat()))
    count = cur.fetchone()[0]
    con.close()
    return count

def staff_only(i: discord.Interaction):
    return has_role(i.user, STAFF_ROLE_ID)

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print("Bot ready")

# ================= USER COMMANDS =================

@bot.tree.command()
async def steamaccount(interaction: discord.Interaction, game: str):
    await interaction.response.defer(ephemeral=True)

    if used_today(interaction.user.id) >= daily_limit(interaction.user):
        await interaction.followup.send("❌ Daily limit reached")
        return

    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, username, password FROM accounts WHERE used=0 AND games LIKE ?",
        (f"%{game}%",)
    )
    row = cur.fetchone()
    if not row:
        await interaction.followup.send("❌ No stock for that game")
        con.close()
        return

    cur.execute("UPDATE accounts SET used=1 WHERE id=?", (row[0],))
    cur.execute("INSERT INTO gens VALUES (?,?)",
                (interaction.user.id, date.today().isoformat()))
    con.commit()
    con.close()

    await interaction.followup.send(
        f"🎮 **{game}**\n```{row[1]}:{row[2]}```"
    )

@bot.tree.command()
async def listgames(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT games FROM accounts WHERE used=0")
    games = sorted({g.strip() for (row,) in cur.fetchall() for g in row.split(",")})
    con.close()
    await interaction.response.send_message(
        "🎮 **Available Games**\n" + "\n".join(games) if games else "No stock"
    )

@bot.tree.command()
async def search(interaction: discord.Interaction, game: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM accounts WHERE used=0 AND games LIKE ?",
        (f"%{game}%",)
    )
    count = cur.fetchone()[0]
    con.close()
    await interaction.response.send_message(f"📦 **{game}**: {count}")

@bot.tree.command()
async def stock(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT games FROM accounts WHERE used=0")
    counts = {}
    for (row,) in cur.fetchall():
        for g in row.split(","):
            counts[g.strip()] = counts.get(g.strip(), 0) + 1
    con.close()

    msg = "\n".join(f"{g}: {c}" for g, c in counts.items())
    await interaction.response.send_message(msg or "No stock")

@bot.tree.command()
async def referral_create(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    code = str(random.randint(10000000, 99999999))
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO referrals VALUES (?,?)",
                (interaction.user.id, code))
    con.commit()
    con.close()
    await interaction.followup.send(f"🎁 Your referral code: `{code}`")

@bot.tree.command()
async def refer(interaction: discord.Interaction, code: str):
    await interaction.response.defer(ephemeral=True)
    con = db()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM referrals WHERE code=?", (code,))
    if not cur.fetchone():
        await interaction.followup.send("❌ Invalid code")
        con.close()
        return
    cur.execute("INSERT OR IGNORE INTO referral_uses VALUES (?)",
                (interaction.user.id,))
    con.commit()
    con.close()
    await interaction.followup.send("✅ Referral redeemed (+1 daily gen)")

@bot.tree.command()
async def report(interaction: discord.Interaction, account: str, reason: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO reports VALUES (?,?)", (account, reason))
    con.commit()
    con.close()
    await interaction.response.send_message("⚠️ Report submitted", ephemeral=True)

# ================= STAFF COMMANDS =================

@bot.tree.command()
@app_commands.check(staff_only)
async def bulkadd(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    data = (await file.read()).decode().splitlines()

    con = db()
    cur = con.cursor()
    added = 0

    for line in data:
        try:
            creds, games = line.split("|")
            user, pw = creds.split(":")
            cur.execute(
                "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
                (user, pw, games)
            )
            added += 1
        except:
            continue

    con.commit()
    con.close()
    await interaction.followup.send(f"✅ Added {added} accounts")

@bot.tree.command()
@app_commands.check(staff_only)
async def addaccount(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    data = (await file.read()).decode().strip()

    try:
        creds, games = data.split("|")
        user, pw = creds.split(":")
        con = db()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
            (user, pw, games)
        )
        con.commit()
        con.close()
        await interaction.followup.send("✅ Account added")
    except:
        await interaction.followup.send("❌ Invalid format")

# ================= START =================
bot.run(TOKEN)
