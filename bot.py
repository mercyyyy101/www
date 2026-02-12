import os
import discord
import aiosqlite
from discord import app_commands
from discord.ext import commands
from datetime import datetime, date

# =========================
# TOKEN
# =========================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN NOT FOUND")

# =========================
# ROLE IDS
# =========================
MEMBER_ROLE_ID = 1471512804535046237
STAFF_ROLE_ID  = 1471515890225774663

BOOSTER_ROLE_1 = 1469733875709378674
BOOSTER_ROLE_2 = 1471590464279810210

DB_PATH = "bot.db"

# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DATABASE
# =========================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            password TEXT,
            games TEXT,
            used INTEGER DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS gens (
            user_id INTEGER,
            account_id INTEGER,
            created_at TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            account_id INTEGER,
            reporter_id INTEGER,
            reason TEXT,
            created_at TEXT
        )
        """)
        await db.commit()

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    await init_db()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

# =========================
# HELPERS
# =========================
def has_role(member, role_id):
    return any(r.id == role_id for r in member.roles)

def boost_count(member):
    return int(has_role(member, BOOSTER_ROLE_1)) + int(has_role(member, BOOSTER_ROLE_2))

def daily_limit(member):
    if has_role(member, STAFF_ROLE_ID):
        return 999
    boosts = boost_count(member)
    if boosts == 1:
        return 4
    if boosts >= 2:
        return 6
    return 2

async def daily_gens(user_id):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=? AND DATE(created_at)=?",
            (user_id, today)
        )
        return (await cur.fetchone())[0]

# =========================
# USER COMMANDS
# =========================
@bot.tree.command(name="steamaccount")
@app_commands.describe(game="Game name")
async def steamaccount(interaction: discord.Interaction, game: str):
    member = interaction.user

    if not has_role(member, MEMBER_ROLE_ID):
        await interaction.response.send_message("❌ Member role required.", ephemeral=True)
        return

    if await daily_gens(member.id) >= daily_limit(member):
        await interaction.response.send_message("❌ Daily limit reached.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, username, password FROM accounts WHERE used=0 AND games LIKE ? LIMIT 1",
            (f"%{game}%",)
        )
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("❌ No stock for that game.", ephemeral=True)
            return

        acc_id, u, p = row
        await db.execute("UPDATE accounts SET used=1 WHERE id=?", (acc_id,))
        await db.execute(
            "INSERT INTO gens VALUES (?, ?, ?)",
            (member.id, acc_id, datetime.utcnow().isoformat())
        )
        await db.commit()

    await member.send(f"🎮 **{game}**\n```{u}:{p}```")
    await interaction.response.send_message("📩 Sent to your DMs.", ephemeral=True)

@bot.tree.command(name="listgames")
async def listgames(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT DISTINCT games FROM accounts WHERE used=0"
        )).fetchall()

    games = set()
    for (g,) in rows:
        for part in g.split(","):
            games.add(part.strip())

    await interaction.response.send_message(
        "🎮 Games:\n" + ", ".join(sorted(games)),
        ephemeral=True
    )

@bot.tree.command(name="search")
@app_commands.describe(game="Game name")
async def search(interaction: discord.Interaction, game: str):
    async with aiosqlite.connect(DB_PATH) as db:
        count = (await (await db.execute(
            "SELECT COUNT(*) FROM accounts WHERE used=0 AND games LIKE ?",
            (f"%{game}%",)
        )).fetchone())[0]

    await interaction.response.send_message(f"Found {count} account(s).", ephemeral=True)

@bot.tree.command(name="stock")
async def stock(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_PATH) as db:
        count = (await (await db.execute(
            "SELECT COUNT(*) FROM accounts WHERE used=0"
        )).fetchone())[0]

    await interaction.response.send_message(f"📦 Stock: {count}", ephemeral=True)

@bot.tree.command(name="mystats")
async def mystats(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_PATH) as db:
        gens = (await (await db.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=?",
            (interaction.user.id,)
        )).fetchone())[0]

    await interaction.response.send_message(f"📊 You generated {gens} accounts.", ephemeral=True)

@bot.tree.command(name="boostinfo")
async def boostinfo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "💎 Boost Perks:\n"
        "No Boost → 2/day\n"
        "1 Boost → 4/day\n"
        "2 Boosts → 6/day",
        ephemeral=True
    )

@bot.tree.command(name="report")
@app_commands.describe(account="username:password", reason="Reason")
async def report(interaction: discord.Interaction, account: str, reason: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM accounts WHERE username||':'||password=?",
            (account,)
        )
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("Account not found.", ephemeral=True)
            return

        await db.execute(
            "INSERT INTO reports VALUES (?, ?, ?, ?)",
            (row[0], interaction.user.id, reason, datetime.utcnow().isoformat())
        )
        await db.commit()

    await interaction.response.send_message("✅ Report submitted.", ephemeral=True)

# =========================
# STAFF COMMANDS
# =========================
@bot.tree.command(name="addaccount")
async def addaccount(interaction: discord.Interaction, username: str, password: str, games: str):
    if not has_role(interaction.user, STAFF_ROLE_ID):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO accounts (username, password, games) VALUES (?, ?, ?)",
            (username, password, games)
        )
        await db.commit()

    await interaction.response.send_message("✅ Account added.", ephemeral=True)

@bot.tree.command(name="bulkadd")
async def bulkadd(interaction: discord.Interaction, data: str):
    if not has_role(interaction.user, STAFF_ROLE_ID):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    entries = [e.strip() for e in data.split("|") if ":" in e]
    async with aiosqlite.connect(DB_PATH) as db:
        for e in entries:
            u, p = e.split(":", 1)
            await db.execute(
                "INSERT INTO accounts (username, password, games) VALUES (?, ?, '')",
                (u, p)
            )
        await db.commit()

    await interaction.response.send_message(f"✅ Added {len(entries)} accounts.", ephemeral=True)

@bot.tree.command(name="removeaccount")
async def removeaccount(interaction: discord.Interaction, account: str):
    if not has_role(interaction.user, STAFF_ROLE_ID):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM accounts WHERE username||':'||password=?",
            (account,)
        )
        await db.commit()

    await interaction.response.send_message("🗑️ Account removed.", ephemeral=True)

@bot.tree.command(name="reportedaccounts")
async def reportedaccounts(interaction: discord.Interaction):
    if not has_role(interaction.user, STAFF_ROLE_ID):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute("""
        SELECT a.username, a.password, COUNT(r.account_id)
        FROM accounts a JOIN reports r ON a.id=r.account_id
        GROUP BY a.id
        """)).fetchall()

    if not rows:
        await interaction.response.send_message("No reports.", ephemeral=True)
        return

    msg = "\n".join(f"{u}:{p} — {c} reports" for u,p,c in rows)
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="resetreport")
async def resetreport(interaction: discord.Interaction, account: str):
    if not has_role(interaction.user, STAFF_ROLE_ID):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM reports WHERE account_id=(SELECT id FROM accounts WHERE username||':'||password=?)",
            (account,)
        )
        await db.commit()

    await interaction.response.send_message("✅ Reports cleared.", ephemeral=True)

@bot.tree.command(name="resetallreports")
async def resetallreports(interaction: discord.Interaction):
    if not has_role(interaction.user, STAFF_ROLE_ID):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM reports")
        await db.commit()

    await interaction.response.send_message("✅ All reports cleared.", ephemeral=True)

@bot.tree.command(name="globalstats")
async def globalstats(interaction: discord.Interaction):
    if not has_role(interaction.user, STAFF_ROLE_ID):
        await interaction.response.send_message("Staff only.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        gens = (await (await db.execute("SELECT COUNT(*) FROM gens")).fetchone())[0]
        reports = (await (await db.execute("SELECT COUNT(*) FROM reports")).fetchone())[0]
        accs = (await (await db.execute("SELECT COUNT(*) FROM accounts")).fetchone())[0]

    await interaction.response.send_message(
        f"📊 Total gens: {gens}\n🚨 Reports: {reports}\n📦 Accounts: {accs}",
        ephemeral=True
    )

# =========================
# RUN
# =========================
bot.run(TOKEN)
