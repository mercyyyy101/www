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

# ================= HELPERS =================
def has_role(member, role_id):
    return any(r.id == role_id for r in member.roles)

def staff_only(interaction: discord.Interaction):
    return has_role(interaction.user, STAFF_ROLE_ID)

def base_limit(member):
    boosts = 0
    if has_role(member, BOOSTER_ROLE_ID):
        boosts += 1
    if has_role(member, BOOSTER_ROLE_2_ID):
        boosts += 1
    return 6 if boosts >= 2 else 4 if boosts == 1 else 2

def has_referral(user_id):
    with db() as con:
        return con.execute(
            "SELECT 1 FROM referral_uses WHERE user_id=?",
            (user_id,)
        ).fetchone() is not None

def daily_limit(member):
    if has_role(member, STAFF_ROLE_ID):
        return 999
    return base_limit(member) + (1 if has_referral(member.id) else 0)

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

# ================= ADD ACCOUNT (FILE) =================
@bot.tree.command(name="addaccount", description="Add ONE account via file")
@app_commands.check(staff_only)
async def addaccount(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    if not file.filename.endswith(".txt"):
        await interaction.followup.send("❌ Upload a .txt file")
        return

    line = (await file.read()).decode().strip()

    if "|" not in line or ":" not in line:
        await interaction.followup.send("❌ Invalid format")
        return

    creds, games = line.split("|", 1)
    user, pwd = creds.split(":", 1)

    with db() as con:
        con.execute(
            "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
            (user.strip(), pwd.strip(), games.strip())
        )

    await interaction.followup.send("✅ Account added")

# ================= BULK ADD =================
@bot.tree.command(name="bulkadd", description="Bulk add accounts via file")
@app_commands.check(staff_only)
async def bulkadd(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    text = (await file.read()).decode()
    added = failed = 0

    with db() as con:
        cur = con.cursor()
        for line in text.splitlines():
            if "|" not in line or ":" not in line:
                failed += 1
                continue
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

    await interaction.followup.send(
        f"📂 Added: {added}\n❌ Failed: {failed}"
    )

# ================= GENERATE =================
@bot.tree.command(name="steamaccount", description="Generate a Steam account")
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
        cur.execute(
            "INSERT INTO gens VALUES (?,?)",
            (interaction.user.id, date.today().isoformat())
        )

    await interaction.followup.send(
        f"🎮 `{row[1]}:{row[2]}`"
    )

# ================= LIST / SEARCH / STOCK =================
@bot.tree.command(name="listgames")
async def listgames(interaction: discord.Interaction):
    rows = db().execute(
        "SELECT games FROM accounts WHERE used=0"
    ).fetchall()
    games = sorted({g.strip() for (r,) in rows for g in r.split(",")})
    await interaction.response.send_message(
        "🎮 Games:\n" + ("\n".join(games) if games else "No stock")
    )

@bot.tree.command(name="search")
async def search(interaction: discord.Interaction, game: str):
    count = db().execute(
        "SELECT COUNT(*) FROM accounts WHERE used=0 AND LOWER(games) LIKE ?",
        (f"%{game.lower()}%",)
    ).fetchone()[0]
    await interaction.response.send_message(f"{game}: {count}")

@bot.tree.command(name="stock")
async def stock(interaction: discord.Interaction):
    rows = db().execute(
        "SELECT games FROM accounts WHERE used=0"
    ).fetchall()
    stock = {}
    for (g,) in rows:
        for game in g.split(","):
            stock[game.strip()] = stock.get(game.strip(), 0) + 1
    await interaction.response.send_message(
        "\n".join(f"{k}: {v}" for k, v in stock.items()) or "No stock"
    )

# ================= REPORTS =================
@bot.tree.command(name="report")
async def report(interaction: discord.Interaction, account: str):
    user, pwd = account.split(":", 1)
    with db() as con:
        row = con.execute(
            "SELECT id FROM accounts WHERE username=? AND password=?",
            (user, pwd)
        ).fetchone()
        if row:
            con.execute("INSERT INTO reports VALUES (?,?)", (row[0], "Bad"))
    await interaction.response.send_message("🚨 Report submitted", ephemeral=True)

@bot.tree.command(name="reportedaccounts")
@app_commands.check(staff_only)
async def reportedaccounts(interaction: discord.Interaction):
    rows = db().execute(
        "SELECT account_id,COUNT(*) FROM reports GROUP BY account_id"
    ).fetchall()
    await interaction.response.send_message(
        "\n".join(f"{a}: {c}" for a, c in rows) or "No reports",
        ephemeral=True
    )

# ================= REFERRALS =================
@bot.tree.command(name="referral_create")
async def referral_create(interaction: discord.Interaction):
    code = str(random.randint(10000000, 99999999))
    db().execute(
        "INSERT OR REPLACE INTO referrals VALUES (?,?)",
        (interaction.user.id, code)
    )
    await interaction.response.send_message(
        f"🎁 Your code: {code}", ephemeral=True
    )

@bot.tree.command(name="refer")
async def refer(interaction: discord.Interaction, code: str):
    db().execute(
        "INSERT OR IGNORE INTO referral_uses VALUES (?)",
        (interaction.user.id,)
    )
    await interaction.response.send_message("✅ Referral applied", ephemeral=True)

# ================= STATS =================
@bot.tree.command(name="mystats")
async def mystats(interaction: discord.Interaction):
    gens = db().execute(
        "SELECT COUNT(*) FROM gens WHERE user_id=?",
        (interaction.user.id,)
    ).fetchone()[0]
    await interaction.response.send_message(
        f"Gens used: {gens}", ephemeral=True
    )

@bot.tree.command(name="topusers")
async def topusers(interaction: discord.Interaction):
    rows = db().execute(
        "SELECT user_id,COUNT(*) c FROM gens "
        "WHERE day=? GROUP BY user_id ORDER BY c DESC LIMIT 10",
        (date.today().isoformat(),)
    ).fetchall()
    await interaction.response.send_message(
        "\n".join(f"<@{u}>: {c}" for u, c in rows) or "No data"
    )

# ================= BOOST INFO =================
@bot.tree.command(name="boostinfo")
async def boostinfo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "No boost: 2/day\n1 boost: 4/day\n2 boosts: 6/day"
    )

# ================= START =================
bot.run(TOKEN)
