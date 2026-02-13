import os
import sqlite3
from datetime import datetime, date
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

    con.commit()
    con.close()

# ================= HELPERS =================
def has_role(member, role_id):
    return any(r.id == role_id for r in member.roles)

def daily_limit(member):
    if has_role(member, STAFF_ROLE_ID):
        return 999

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

# ================= USER COMMANDS =================
@bot.tree.command(name="steamaccount", description="Generate a Steam account")
@app_commands.describe(game="Game name")
async def steamaccount(interaction: discord.Interaction, game: str):
    user = interaction.user

    if not has_role(user, MEMBER_ROLE_ID):
        await interaction.response.send_message("❌ Members only.", ephemeral=True)
        return

    limit = daily_limit(user)
    used = used_today(user.id)

    if used >= limit:
        await interaction.response.send_message(
            f"⛔ Daily limit reached ({limit}/day).",
            ephemeral=True
        )
        return

    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, username, password FROM accounts WHERE used=0 AND games LIKE ? LIMIT 1",
        (f"%{game}%",)
    )
    row = cur.fetchone()

    if not row:
        await interaction.response.send_message("❌ No accounts available.", ephemeral=True)
        con.close()
        return

    acc_id, usern, pwd = row
    cur.execute("UPDATE accounts SET used=1 WHERE id=?", (acc_id,))
    cur.execute("INSERT INTO gens VALUES (?, ?)", (user.id, date.today().isoformat()))
    con.commit()
    con.close()

    await user.send(f"🎮 **{game} Account**\n```{usern}:{pwd}```")
    await interaction.response.send_message("📩 Sent to your DMs.", ephemeral=True)

@bot.tree.command(name="listgames", description="List available games")
async def listgames(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT games FROM accounts WHERE used=0")
    games = set()
    for (g,) in cur.fetchall():
        for part in g.split(","):
            games.add(part.strip())
    con.close()

    if not games:
        await interaction.response.send_message("❌ No games in stock.", ephemeral=True)
    else:
        await interaction.response.send_message(
            "🎮 Available games:\n" + ", ".join(sorted(games)),
            ephemeral=True
        )

@bot.tree.command(name="search", description="Search for a game")
async def search(interaction: discord.Interaction, game: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM accounts WHERE used=0 AND games LIKE ?",
        (f"%{game}%",)
    )
    count = cur.fetchone()[0]
    con.close()
    await interaction.response.send_message(
        f"🔎 `{game}` accounts: {count}",
        ephemeral=True
    )

@bot.tree.command(name="stock", description="Check total stock")
async def stock(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM accounts WHERE used=0")
    count = cur.fetchone()[0]
    con.close()
    await interaction.response.send_message(f"📦 Stock remaining: {count}", ephemeral=True)

@bot.tree.command(name="mystats", description="View your stats")
async def mystats(interaction: discord.Interaction):
    used = used_today(interaction.user.id)
    limit = daily_limit(interaction.user)
    await interaction.response.send_message(
        f"📊 Used today: {used}/{limit}",
        ephemeral=True
    )

@bot.tree.command(name="topusers", description="Today's leaderboard")
async def topusers(interaction: discord.Interaction):
    con = db()
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
    con.close()

    if not rows:
        await interaction.response.send_message("No activity today.", ephemeral=True)
        return

    msg = "\n".join(f"<@{u}> — {c}" for u, c in rows)
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="boostinfo", description="Boost perks")
async def boostinfo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "💎 **Boost Perks**\n"
        "No Boost → 2/day\n"
        "1 Boost → 4/day\n"
        "2 Boosts → 6/day",
        ephemeral=True
    )

@bot.tree.command(name="report", description="Report a bad account")
async def report(interaction: discord.Interaction, account: str, reason: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT id FROM accounts WHERE username || ':' || password = ?",
        (account,)
    )
    row = cur.fetchone()

    if not row:
        await interaction.response.send_message("❌ Account not found.", ephemeral=True)
        con.close()
        return

    cur.execute("INSERT INTO reports VALUES (?, ?)", (row[0], reason))
    con.commit()
    con.close()
    await interaction.response.send_message("✅ Report submitted.", ephemeral=True)

# ================= STAFF COMMANDS =================
@bot.tree.command(name="addaccount", description="Add one account")
@app_commands.check(staff_only)
async def addaccount(interaction: discord.Interaction, username: str, password: str, games: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO accounts (username, password, games) VALUES (?, ?, ?)",
        (username, password, games)
    )
    con.commit()
    con.close()
    await interaction.response.send_message("✅ Account added.", ephemeral=True)

@bot.tree.command(name="bulkadd", description="Bulk add accounts")
@app_commands.check(staff_only)
async def bulkadd(interaction: discord.Interaction, games: str, accounts: str):
    lines = [l for l in accounts.split("\n") if ":" in l]
    con = db()
    cur = con.cursor()

    for line in lines:
        u, p = line.strip().split(":", 1)
        cur.execute(
            "INSERT INTO accounts (username, password, games) VALUES (?, ?, ?)",
            (u, p, games)
        )

    con.commit()
    con.close()
    await interaction.response.send_message(f"✅ Added {len(lines)} accounts.", ephemeral=True)

@bot.tree.command(name="removeaccount", description="Remove an account")
@app_commands.check(staff_only)
async def removeaccount(interaction: discord.Interaction, account: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM accounts WHERE username || ':' || password = ?",
        (account,)
    )
    con.commit()
    con.close()
    await interaction.response.send_message("🗑️ Account removed.", ephemeral=True)

@bot.tree.command(name="accountinfo", description="Check account info")
@app_commands.check(staff_only)
async def accountinfo(interaction: discord.Interaction, account: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, used FROM accounts WHERE username || ':' || password = ?",
        (account,)
    )
    row = cur.fetchone()
    con.close()

    if not row:
        await interaction.response.send_message("❌ Not found.", ephemeral=True)
    else:
        await interaction.response.send_message(
            f"ID: {row[0]} | Used: {'Yes' if row[1] else 'No'}",
            ephemeral=True
        )

@bot.tree.command(name="reportedaccounts", description="View reported accounts")
@app_commands.check(staff_only)
async def reportedaccounts(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT a.username, a.password, COUNT(r.account_id)
        FROM accounts a
        JOIN reports r ON a.id = r.account_id
        GROUP BY a.id
    """)
    rows = cur.fetchall()
    con.close()

    if not rows:
        await interaction.response.send_message("No reports.", ephemeral=True)
        return

    msg = "\n".join(f"{u}:{p} — {c} reports" for u, p, c in rows)
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="resetreport", description="Clear reports for one account")
@app_commands.check(staff_only)
async def resetreport(interaction: discord.Interaction, account: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM reports WHERE account_id IN "
        "(SELECT id FROM accounts WHERE username || ':' || password = ?)",
        (account,)
    )
    con.commit()
    con.close()
    await interaction.response.send_message("✅ Reports cleared.", ephemeral=True)

@bot.tree.command(name="resetallreports", description="Clear all reports")
@app_commands.check(staff_only)
async def resetallreports(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM reports")
    con.commit()
    con.close()
    await interaction.response.send_message("✅ All reports wiped.", ephemeral=True)

@bot.tree.command(name="globalstats", description="Global stats")
@app_commands.check(staff_only)
async def globalstats(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM gens")
    gens = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM reports")
    reports = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts")
    accounts = cur.fetchone()[0]
    con.close()

    await interaction.response.send_message(
        f"📊 Total gens: {gens}\n🚨 Reports: {reports}\n📦 Accounts: {accounts}",
        ephemeral=True
    )

# ================= HELP =================
@bot.tree.command(name="help", description="Show all commands")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**🎮 User Commands**\n"
        "/steamaccount\n"
        "/listgames\n"
        "/search\n"
        "/stock\n"
        "/mystats\n"
        "/topusers\n"
        "/boostinfo\n"
        "/report\n\n"
        "**👨‍💼 Staff Commands**\n"
        "/addaccount\n"
        "/bulkadd\n"
        "/removeaccount\n"
        "/accountinfo\n"
        "/reportedaccounts\n"
        "/resetreport\n"
        "/resetallreports\n"
        "/globalstats",
        ephemeral=True
    )

# ================= START =================
bot.run(TOKEN)

# ---- START WEB SERVER FOR RAILWAY ----
import threading
from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder=".")

@app.route("/")
def home():
    return send_from_directory(".", "index.html")

@app.route("/health")
def health():
    return "OK"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# -------------------------------------
