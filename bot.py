import os
import sqlite3
import threading
from datetime import date
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask, send_from_directory

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

# ================= WEB SERVER =================
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

# ================= DISCORD BOT =================
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
    boosts = int(has_role(member, BOOSTER_ROLE_ID)) + int(has_role(member, BOOSTER_ROLE_2_ID))
    return 6 if boosts >= 2 else 4 if boosts == 1 else 2

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

def staff_only(interaction: discord.Interaction):
    return has_role(interaction.user, STAFF_ROLE_ID)

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

# ================= USER COMMANDS =================
@bot.tree.command(name="steamaccount")
async def steamaccount(interaction: discord.Interaction, game: str):
    user = interaction.user

    if not has_role(user, MEMBER_ROLE_ID):
        await interaction.response.send_message("❌ Members only.", ephemeral=True)
        return

    if used_today(user.id) >= daily_limit(user):
        await interaction.response.send_message("⛔ Daily limit reached.", ephemeral=True)
        return

    con = db()
    cur = con.cursor()
    cur.execute("SELECT id, username, password FROM accounts WHERE used=0 AND games LIKE ? LIMIT 1", (f"%{game}%",))
    row = cur.fetchone()

    if not row:
        await interaction.response.send_message("❌ No accounts available.", ephemeral=True)
        con.close()
        return

    acc_id, u, p = row
    cur.execute("UPDATE accounts SET used=1 WHERE id=?", (acc_id,))
    cur.execute("INSERT INTO gens VALUES (?, ?)", (user.id, date.today().isoformat()))
    con.commit()
    con.close()

    await user.send(f"🎮 **{game} Account**\n```{u}:{p}```")
    await interaction.response.send_message("📩 Sent to your DMs.", ephemeral=True)

@bot.tree.command(name="listgames")
async def listgames(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT games FROM accounts WHERE used=0")
    games = sorted(set(g.strip() for row in cur.fetchall() for g in row[0].split(",")))
    con.close()
    await interaction.response.send_message(", ".join(games) or "No games available.", ephemeral=True)

@bot.tree.command(name="stock")
async def stock(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM accounts WHERE used=0")
    count = cur.fetchone()[0]
    con.close()
    await interaction.response.send_message(f"📦 Stock: {count}", ephemeral=True)

@bot.tree.command(name="boostinfo")
async def boostinfo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "💎 **Boost Perks**\nNo Boost → 2/day\n1 Boost → 4/day\n2 Boosts → 6/day",
        ephemeral=True
    )

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**🎮 User Commands**\n"
        "/steamaccount\n/listgames\n/stock\n/boostinfo\n\n"
        "**👨‍💼 Staff Commands**\n"
        "/addaccount\n/bulkadd\n/removeaccount\n/globalstats",
        ephemeral=True
    )

# ================= STAFF COMMANDS =================
@bot.tree.command(name="addaccount")
@app_commands.check(staff_only)
async def addaccount(interaction: discord.Interaction, username: str, password: str, games: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO accounts (username, password, games) VALUES (?, ?, ?)", (username, password, games))
    con.commit()
    con.close()
    await interaction.response.send_message("✅ Account added.", ephemeral=True)

@bot.tree.command(name="bulkadd")
@app_commands.check(staff_only)
async def bulkadd(interaction: discord.Interaction, games: str, accounts: str):
    con = db()
    cur = con.cursor()
    lines = [l for l in accounts.split("\n") if ":" in l]
    for l in lines:
        u, p = l.split(":", 1)
        cur.execute("INSERT INTO accounts (username, password, games) VALUES (?, ?, ?)", (u, p, games))
    con.commit()
    con.close()
    await interaction.response.send_message(f"✅ Added {len(lines)} accounts.", ephemeral=True)

@bot.tree.command(name="removeaccount")
@app_commands.check(staff_only)
async def removeaccount(interaction: discord.Interaction, account: str):
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM accounts WHERE username || ':' || password = ?", (account,))
    con.commit()
    con.close()
    await interaction.response.send_message("🗑️ Account removed.", ephemeral=True)

@bot.tree.command(name="globalstats")
@app_commands.check(staff_only)
async def globalstats(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM gens")
    gens = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts")
    accounts = cur.fetchone()[0]
    con.close()
    await interaction.response.send_message(f"📊 Gens: {gens}\n📦 Accounts: {accounts}", ephemeral=True)

# ================= START BOT (MUST BE LAST) =================
bot.run(TOKEN)
