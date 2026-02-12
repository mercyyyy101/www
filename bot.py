import os
import asyncio
import aiosqlite
from datetime import datetime, date

import discord
from discord.ext import commands

# ────────────────── CONFIG ──────────────────

TOKEN = os.environ.get("TOKEN") or os.environ.get("DISCORD_TOKEN")

BOOSTER_ROLE_ID = int(os.environ.get("BOOSTER_ROLE_ID", 0))
MEMBER_ROLE_ID  = int(os.environ.get("MEMBER_ROLE_ID", 0))
STAFF_ROLE_ID   = int(os.environ.get("STAFF_ROLE_ID", 0))

DB_PATH = os.environ.get("DATABASE_PATH", "bot.db")

if not TOKEN:
    print("❌ TOKEN NOT FOUND")
    raise SystemExit(1)

# ────────────────── BOT ──────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ────────────────── DATABASE ──────────────────

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            password TEXT,
            games TEXT,
            used INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS gens (
            user_id TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS reports (
            account TEXT,
            reporter TEXT,
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS referrals (
            owner_id TEXT,
            code TEXT UNIQUE,
            uses INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS referral_uses (
            referrer_id TEXT,
            referred_id TEXT
        );
        """)
        await db.commit()

# ────────────────── HELPERS ──────────────────

def is_staff(member: discord.Member):
    return (
        member.guild_permissions.manage_guild
        or any(r.id == STAFF_ROLE_ID for r in member.roles)
    )

def boost_count(member: discord.Member):
    return 1 if any(r.id == BOOSTER_ROLE_ID for r in member.roles) else 0

async def daily_gens(user_id: int):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=? AND DATE(created_at)=?",
            (str(user_id), today),
        )
        return (await cur.fetchone())[0]

# ────────────────── EVENTS ──────────────────

@bot.event
async def on_ready():
    await init_db()
    print(f"✅ Logged in as {bot.user}")

# ────────────────── USER COMMANDS ──────────────────

@bot.command()
async def steamaccount(ctx, *, game: str):
    limit = 2
    if boost_count(ctx.author) == 1:
        limit = 4

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM referral_uses WHERE referred_id=?",
            (str(ctx.author.id),),
        )
        if (await cur.fetchone())[0] > 0:
            limit += 1

    if await daily_gens(ctx.author.id) >= limit:
        return await ctx.reply(f"❌ Daily limit reached ({limit})")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, username, password, games FROM accounts WHERE used=0 AND games LIKE ? LIMIT 1",
            (f"%{game}%",),
        )
        row = await cur.fetchone()

        if not row:
            return await ctx.reply("❌ No accounts available")

        acc_id, u, p, g = row

        await db.execute("UPDATE accounts SET used=1 WHERE id=?", (acc_id,))
        await db.execute(
            "INSERT INTO gens VALUES (?,?)",
            (str(ctx.author.id), datetime.utcnow().isoformat()),
        )
        await db.commit()

    try:
        await ctx.author.send(f"🎮 **{game}**\n```{u}:{p}```\nGames: {g}")
        await ctx.reply("✅ Check your DMs!")
    except discord.Forbidden:
        await ctx.reply(f"⚠️ DMs closed: `{u}:{p}`")

@bot.command()
async def listgames(ctx):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT DISTINCT games FROM accounts WHERE used=0")
        rows = await cur.fetchall()

    games = set()
    for (g,) in rows:
        if g:
            games.update(x.strip() for x in g.split(","))

    await ctx.reply(", ".join(sorted(games)) if games else "❌ No stock")

@bot.command()
async def search(ctx, *, game: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM accounts WHERE used=0 AND games LIKE ?",
            (f"%{game}%",),
        )
        count = (await cur.fetchone())[0]
    await ctx.reply(f"🔎 {count} account(s) found")

@bot.command()
async def stock(ctx):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM accounts WHERE used=0")
        count = (await cur.fetchone())[0]
    await ctx.reply(f"📦 Stock: {count}")

@bot.command()
async def mystats(ctx):
    async with aiosqlite.connect(DB_PATH) as db:
        gens = (await (await db.execute(
            "SELECT COUNT(*) FROM gens WHERE user_id=?",
            (str(ctx.author.id),),
        )).fetchone())[0]

        refs = (await (await db.execute(
            "SELECT COUNT(*) FROM referrals WHERE owner_id=?",
            (str(ctx.author.id),),
        )).fetchone())[0]

    await ctx.reply(f"📊 Gens: {gens} | Referrals: {refs}")

@bot.command()
async def topusers(ctx):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, COUNT(*) FROM gens WHERE DATE(created_at)=? GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10",
            (today,),
        )
        rows = await cur.fetchall()

    if not rows:
        return await ctx.reply("❌ No activity today")

    msg = "\n".join(f"<@{u}> — {c}" for u, c in rows)
    await ctx.reply(msg)

@bot.command()
async def refer(ctx, code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT owner_id FROM referrals WHERE code=?", (code,))
        row = await cur.fetchone()
        if not row or row[0] == str(ctx.author.id):
            return await ctx.reply("❌ Invalid code")

        await db.execute(
            "INSERT INTO referral_uses VALUES (?,?)",
            (row[0], str(ctx.author.id)),
        )
        await db.commit()

    await ctx.reply("🎁 Referral applied (+1 daily gen)")

@bot.command()
async def boostinfo(ctx):
    await ctx.reply(
        "💎 Boost Perks\n"
        "No Boost → 2/day\n"
        "1 Boost → 4/day\n"
        "2 Boosts → 6/day\n"
        "Referrals → +1"
    )

@bot.command()
async def report(ctx, account: str, *, reason=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports VALUES (?,?,?)",
            (account, str(ctx.author.id), reason),
        )
        await db.commit()
    await ctx.reply("🚨 Report submitted")

# ────────────────── STAFF COMMANDS ──────────────────

@bot.command()
async def addaccount(ctx, user: str, pwd: str, *, games: str):
    if not is_staff(ctx.author):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
            (user, pwd, games),
        )
        await db.commit()
    await ctx.reply("✅ Account added")

@bot.command()
async def bulkadd(ctx):
    if not is_staff(ctx.author):
        return await ctx.reply("❌ Staff only")

    await ctx.reply("📥 Send accounts (user:pass | games), type `done` to finish")

    def check(m): return m.author == ctx.author

    while True:
        msg = await bot.wait_for("message", check=check)
        if msg.content.lower() == "done":
            break
        try:
            creds, games = msg.content.split("|")
            u, p = creds.strip().split(":")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO accounts (username,password,games) VALUES (?,?,?)",
                    (u, p, games.strip()),
                )
                await db.commit()
        except:
            await ctx.send("❌ Format error")

    await ctx.reply("✅ Bulk add complete")

@bot.command()
async def reportedaccounts(ctx):
    if not is_staff(ctx.author):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT account, COUNT(*) FROM reports GROUP BY account")
        rows = await cur.fetchall()

    await ctx.reply("\n".join(f"{a} — {c}" for a, c in rows) or "None")

@bot.command()
async def resetreport(ctx, account: str):
    if not is_staff(ctx.author):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM reports WHERE account=?", (account,))
        await db.commit()
    await ctx.reply("🧹 Reports cleared")

@bot.command()
async def resetallreports(ctx):
    if not is_staff(ctx.author):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM reports")
        await db.commit()
    await ctx.reply("🧹 All reports wiped")

@bot.command()
async def globalstats(ctx):
    if not is_staff(ctx.author):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        a = (await (await db.execute("SELECT COUNT(*) FROM accounts")).fetchone())[0]
        g = (await (await db.execute("SELECT COUNT(*) FROM gens")).fetchone())[0]
        r = (await (await db.execute("SELECT COUNT(*) FROM reports")).fetchone())[0]

    await ctx.reply(f"🌍 Accounts: {a}\nGens: {g}\nReports: {r}")

# ────────────────── START ──────────────────

bot.run(TOKEN)