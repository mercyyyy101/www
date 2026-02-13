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
        cur = con.cursor()
        cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (user_id,))
        return cur.fetchone() is not None

def daily_limit(member):
    if has_role(member, STAFF_ROLE_ID):
        return 999
    limit = base_limit(member)
    if has_referral(member.id):
        limit += 1
    return limit

def used_today(user_id):
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=? AND day=?",
            (user_id, date.today().isoformat())
        )
        return cur.fetchone()[0]

# ================= READY =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

# ================= BULK ADD (FILE) =================
@bot.tree.command(name="bulkadd", description="Bulk add accounts via file upload")
@app_commands.check(staff_only)
async def bulkadd(interaction: discord.Interaction, file: discord.Attachment):
    if not file.filename.endswith(".txt"):
        await interaction.response.send_message("❌ Upload a .txt file", ephemeral=True)
        return

    text = (await file.read()).decode("utf-8")
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

    await interaction.response.send_message(
        f"📂 Added: {added} | Failed: {failed}", ephemeral=True
    )

# ================= ADD SINGLE =================
@bot.tree.command(name="addaccount", description="Add one account")
@app_commands.check(staff_only)
async def addaccount(interaction: discord.Interaction, user: str, password: str, games: str):
    with db() as con:
        con.execute(
            "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
            (user, password, games)
        )
    await interaction.response.send_message("✅ Account added", ephemeral=True)

# ================= REMOVE ACCOUNT =================
@bot.tree.command(name="removeaccount", description="Remove account")
@app_commands.check(staff_only)
async def removeaccount(interaction: discord.Interaction, account: str):
    user, pwd = account.split(":", 1)
    with db() as con:
        con.execute(
            "DELETE FROM accounts WHERE username=? AND password=?",
            (user, pwd)
        )
    await interaction.response.send_message("🗑️ Account removed", ephemeral=True)

# ================= ACCOUNT INFO =================
@bot.tree.command(name="accountinfo", description="View account info")
@app_commands.check(staff_only)
async def accountinfo(interaction: discord.Interaction, account: str):
    user, pwd = account.split(":", 1)
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id,games,used FROM accounts WHERE username=? AND password=?",
            (user, pwd)
        )
        row = cur.fetchone()

    if not row:
        await interaction.response.send_message("❌ Not found", ephemeral=True)
        return

    await interaction.response.send_message(
        f"ID: {row[0]}\nGames: {row[1]}\nUsed: {bool(row[2])}",
        ephemeral=True
    )

# ================= LIST GAMES =================
@bot.tree.command(name="listgames", description="List available games")
async def listgames(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute("SELECT games FROM accounts WHERE used=0").fetchall()
    games = sorted({g.strip() for (r,) in rows for g in r.split(",")})
    await interaction.response.send_message(
        "🎮 Games:\n" + ("\n".join(games) if games else "No stock")
    )

# ================= SEARCH =================
@bot.tree.command(name="search", description="Search stock")
async def search(interaction: discord.Interaction, game: str):
    with db() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM accounts WHERE used=0 AND LOWER(games) LIKE ?",
            (f"%{game.lower()}%",)
        ).fetchone()[0]
    await interaction.response.send_message(f"{game}: {count} accounts")

# ================= STOCK =================
@bot.tree.command(name="stock", description="Stock by game")
async def stock(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute("SELECT games FROM accounts WHERE used=0").fetchall()
    stock = {}
    for (g,) in rows:
        for game in g.split(","):
            stock[game.strip()] = stock.get(game.strip(), 0) + 1
    await interaction.response.send_message(
        "\n".join(f"{k}: {v}" for k, v in sorted(stock.items())) or "No stock"
    )

# ================= GENERATE =================
@bot.tree.command(name="steamaccount", description="Generate a Steam account")
async def steamaccount(interaction: discord.Interaction, game: str):
    if used_today(interaction.user.id) >= daily_limit(interaction.user):
        await interaction.response.send_message("❌ Daily limit reached", ephemeral=True)
        return

    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id,username,password FROM accounts "
            "WHERE used=0 AND LOWER(games) LIKE ? LIMIT 1",
            (f"%{game.lower()}%",)
        )
        row = cur.fetchone()

        if not row:
            await interaction.response.send_message("❌ Out of stock", ephemeral=True)
            return

        cur.execute("UPDATE accounts SET used=1 WHERE id=?", (row[0],))
        cur.execute(
            "INSERT INTO gens VALUES (?,?)",
            (interaction.user.id, date.today().isoformat())
        )

    await interaction.response.send_message(
        f"🎮 `{row[1]}:{row[2]}`", ephemeral=True
    )

# ================= REPORT =================
@bot.tree.command(name="report", description="Report bad account")
async def report(interaction: discord.Interaction, account: str):
    user, pwd = account.split(":", 1)
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id FROM accounts WHERE username=? AND password=?",
            (user, pwd)
        )
        row = cur.fetchone()
        if not row:
            await interaction.response.send_message("❌ Not found", ephemeral=True)
            return
        cur.execute("INSERT INTO reports VALUES (?,?)", (row[0], "Bad"))
    await interaction.response.send_message("🚨 Report submitted", ephemeral=True)

# ================= REPORTED =================
@bot.tree.command(name="reportedaccounts", description="View reports")
@app_commands.check(staff_only)
async def reportedaccounts(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute(
            "SELECT account_id,COUNT(*) FROM reports GROUP BY account_id"
        ).fetchall()
    msg = "\n".join(f"Account {a}: {c} reports" for a, c in rows)
    await interaction.response.send_message(msg or "No reports", ephemeral=True)

# ================= RESET REPORTS =================
@bot.tree.command(name="resetreport", description="Clear reports for account")
@app_commands.check(staff_only)
async def resetreport(interaction: discord.Interaction, account: str):
    user, pwd = account.split(":", 1)
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id FROM accounts WHERE username=? AND password=?",
            (user, pwd)
        )
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM reports WHERE account_id=?", (row[0],))
    await interaction.response.send_message("🧹 Reports cleared", ephemeral=True)

@bot.tree.command(name="resetallreports", description="Clear all reports")
@app_commands.check(staff_only)
async def resetallreports(interaction: discord.Interaction):
    with db() as con:
        con.execute("DELETE FROM reports")
    await interaction.response.send_message("🧹 All reports wiped", ephemeral=True)

# ================= STATS =================
@bot.tree.command(name="mystats", description="Your stats")
async def mystats(interaction: discord.Interaction):
    with db() as con:
        gens = con.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=?",
            (interaction.user.id,)
        ).fetchone()[0]
    await interaction.response.send_message(f"Gens used: {gens}", ephemeral=True)

@bot.tree.command(name="topusers", description="Top users today")
async def topusers(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute(
            "SELECT user_id,COUNT(*) c FROM gens "
            "WHERE day=? GROUP BY user_id ORDER BY c DESC LIMIT 10",
            (date.today().isoformat(),)
        ).fetchall()
    msg = "\n".join(f"<@{u}>: {c}" for u, c in rows)
    await interaction.response.send_message(msg or "No data")

@bot.tree.command(name="globalstats", description="Global stats")
@app_commands.check(staff_only)
async def globalstats(interaction: discord.Interaction):
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM gens").fetchone()[0]
        stock = con.execute("SELECT COUNT(*) FROM accounts WHERE used=0").fetchone()[0]
    await interaction.response.send_message(
        f"Total gens: {total}\nStock left: {stock}",
        ephemeral=True
    )

# ================= BOOST INFO =================
@bot.tree.command(name="boostinfo", description="Boost perks")
async def boostinfo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "No boost: 2/day\n1 boost: 4/day\n2 boosts: 6/day"
    )

# ================= REFERRALS =================
@bot.tree.command(name="referral_create", description="Create referral code")
async def referral_create(interaction: discord.Interaction):
    code = str(random.randint(10000000, 99999999))
    with db() as con:
        con.execute(
            "INSERT OR REPLACE INTO referrals VALUES (?,?)",
            (interaction.user.id, code)
        )
    await interaction.response.send_message(f"Your code: {code}", ephemeral=True)

@bot.tree.command(name="refer", description="Redeem referral")
async def refer(interaction: discord.Interaction, code: str):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM referrals WHERE code=?", (code,))
        if not cur.fetchone():
            await interaction.response.send_message("❌ Invalid", ephemeral=True)
            return
        cur.execute(
            "INSERT OR IGNORE INTO referral_uses VALUES (?)",
            (interaction.user.id,)
        )
    await interaction.response.send_message("✅ Referral applied", ephemeral=True)

# ================= START =================
bot.run(TOKEN)
