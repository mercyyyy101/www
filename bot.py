import os
import sqlite3
import random
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
    with db() as con:
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
            account_id INTEGER,
            reason TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            owner_id INTEGER,
            code TEXT UNIQUE
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS referral_uses (
            user_id INTEGER UNIQUE
        )""")

# ================= HELPERS =================
def has_role(member, role_id):
    return any(r.id == role_id for r in member.roles)

def staff_only(interaction: discord.Interaction):
    return has_role(interaction.user, STAFF_ROLE_ID)

def base_limit(member):
    boosts = int(has_role(member, BOOSTER_ROLE_ID)) + int(has_role(member, BOOSTER_ROLE_2_ID))
    return 6 if boosts >= 2 else 4 if boosts == 1 else 2

def daily_limit(member):
    if has_role(member, STAFF_ROLE_ID):
        return 999
    with db() as con:
        bonus = con.execute(
            "SELECT 1 FROM referral_uses WHERE user_id=?",
            (member.id,)
        ).fetchone()
    return base_limit(member) + (1 if bonus else 0)

def used_today(user_id):
    with db() as con:
        return con.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=? AND day=?",
            (user_id, date.today().isoformat())
        ).fetchone()[0]

# ================= READY =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

# ================= ADD ACCOUNT (FILE – FIXED) =================
@bot.tree.command(name="addaccount", description="Add ONE account via file")
@app_commands.check(staff_only)
async def addaccount(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    try:
        content = (await file.read()).decode("utf-8").strip()
        creds, games = content.split("|", 1)
        user, pwd = creds.split(":", 1)

        with db() as con:
            con.execute(
                "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
                (user.strip(), pwd.strip(), games.strip())
            )

        await interaction.followup.send("✅ Account added successfully")
    except Exception as e:
        await interaction.followup.send("❌ Invalid file format")

# ================= BULK ADD (FILE – FIXED) =================
@bot.tree.command(name="bulkadd", description="Bulk add accounts via file")
@app_commands.check(staff_only)
async def bulkadd(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    try:
        text = (await file.read()).decode("utf-8")
    except Exception:
        await interaction.followup.send("❌ Could not read file")
        return

    added = failed = 0

    with db() as con:
        cur = con.cursor()
        for line in text.splitlines():
            try:
                creds, games = line.strip().split("|", 1)
                user, pwd = creds.split(":", 1)
                cur.execute(
                    "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
                    (user.strip(), pwd.strip(), games.strip())
                )
                added += 1
            except:
                failed += 1

    await interaction.followup.send(
        f"📂 Bulk upload complete\n"
        f"✅ Added: {added}\n"
        f"❌ Failed: {failed}"
    )

# ================= BASIC COMMANDS =================
@bot.tree.command(name="listgames")
async def listgames(interaction: discord.Interaction):
    rows = db().execute("SELECT games FROM accounts WHERE used=0").fetchall()
    games = sorted({g.strip() for (r,) in rows for g in r.split(",")})
    await interaction.response.send_message("\n".join(games) or "No stock")

@bot.tree.command(name="search")
async def search(interaction: discord.Interaction, game: str):
    count = db().execute(
        "SELECT COUNT(*) FROM accounts WHERE used=0 AND LOWER(games) LIKE ?",
        (f"%{game.lower()}%",)
    ).fetchone()[0]
    await interaction.response.send_message(f"{game}: {count}")

@bot.tree.command(name="stock")
async def stock(interaction: discord.Interaction):
    rows = db().execute("SELECT games FROM accounts WHERE used=0").fetchall()
    stock = {}
    for (g,) in rows:
        for game in g.split(","):
            stock[game.strip()] = stock.get(game.strip(), 0) + 1
    await interaction.response.send_message(
        "\n".join(f"{k}: {v}" for k, v in stock.items()) or "No stock"
    )

# ================= GENERATOR =================
@bot.tree.command(name="steamaccount")
async def steamaccount(interaction: discord.Interaction, game: str):
    await interaction.response.defer(ephemeral=True)

    if used_today(interaction.user.id) >= daily_limit(interaction.user):
        await interaction.followup.send("❌ Daily limit reached")
        return

    with db() as con:
        cur = con.cursor()
        row = cur.execute(
            "SELECT id,username,password FROM accounts "
            "WHERE used=0 AND LOWER(games) LIKE ? LIMIT 1",
            (f"%{game.lower()}%",)
        ).fetchone()

        if not row:
            await interaction.followup.send("❌ Out of stock")
            return

        cur.execute("UPDATE accounts SET used=1 WHERE id=?", (row[0],))
        cur.execute("INSERT INTO gens VALUES (?,?)",
                    (interaction.user.id, date.today().isoformat()))

    await interaction.followup.send(f"`{row[1]}:{row[2]}`")

# ================= START =================
bot.run(TOKEN)
