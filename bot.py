import os
import sqlite3
from datetime import date
import asyncio

import discord
from discord.ext import commands
from discord import app_commands

from flask import Flask

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

# ================= DISCORD =================
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
    boosts = 0
    if has_role(member, BOOSTER_ROLE_ID):
        boosts += 1
    if has_role(member, BOOSTER_ROLE_2_ID):
        boosts += 1
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

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

# ================= COMMANDS =================
@bot.tree.command(name="steamaccount")
async def steamaccount(interaction: discord.Interaction, game: str):
    if not has_role(interaction.user, MEMBER_ROLE_ID):
        await interaction.response.send_message("Members only.", ephemeral=True)
        return

    if used_today(interaction.user.id) >= daily_limit(interaction.user):
        await interaction.response.send_message("Daily limit reached.", ephemeral=True)
        return

    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, username, password FROM accounts WHERE used=0 AND games LIKE ? LIMIT 1",
        (f"%{game}%",)
    )
    row = cur.fetchone()

    if not row:
        await interaction.response.send_message("Out of stock.", ephemeral=True)
        con.close()
        return

    acc_id, u, p = row
    cur.execute("UPDATE accounts SET used=1 WHERE id=?", (acc_id,))
    cur.execute(
        "INSERT INTO gens VALUES (?,?)",
        (interaction.user.id, date.today().isoformat())
    )
    con.commit()
    con.close()

    await interaction.user.send(f"```{u}:{p}```")
    await interaction.response.send_message("📩 Sent to DMs.", ephemeral=True)

# ================= FLASK (RAILWAY ENTRYPOINT) =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

@app.route("/health")
def health():
    return "OK"

# ================= START =================
async def start_bot():
    await bot.start(TOKEN)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
