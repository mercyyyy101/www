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
            account TEXT,
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

def base_limit(member):
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

def staff_only(interaction: discord.Interaction):
    return has_role(interaction.user, STAFF_ROLE_ID)

# ================= FILE PARSER =================
def is_credential_line(line: str) -> bool:
    """Check if a line looks like user:pass credentials."""
    line = line.strip()
    if ":" not in line:
        return False
    user, pwd = line.split(":", 1)
    user = user.strip()
    pwd = pwd.strip()
    # Must have a non-empty username, password can be empty but username can't
    # Also username shouldn't contain spaces (game titles do)
    if not user or " " in user:
        return False
    return True

def parse_file(text: str):
    """
    Parses two formats:
      Format 1 (inline):  user:pass – Game Name
      Format 2 (block):   Game1\nGame2\nuser:pass\npassword_on_next_line
    Returns list of (username, password, games)
    """
    results = []
    lines = [l.rstrip() for l in text.splitlines()]
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Check for inline format: user:pass – Game or user:pass | Game
        normalised = line.replace(" \u2013 ", "|").replace(" \u2014 ", "|").replace(" - ", "|").replace(" | ", "|")
        normalised = normalised.replace("GAMES:", "").replace("Games:", "").replace("games:", "").strip()

        if "|" in normalised and ":" in normalised.split("|")[0]:
            parts = normalised.split("|", 1)
            creds = parts[0].strip()
            games = parts[1].strip()
            if ":" in creds and games:
                user, pwd = creds.split(":", 1)
                if user.strip() and pwd.strip():
                    results.append((user.strip(), pwd.strip(), games.strip()))
                    i += 1
                    continue

        # Check for block format: game lines followed by credential line(s)
        # Collect consecutive non-empty lines, find where credentials start
        block_start = i
        block_lines = []
        while i < len(lines) and lines[i].strip():
            block_lines.append(lines[i].strip())
            i += 1

        if not block_lines:
            i += 1
            continue

        # Find the credential line in the block (first line with ":" and no spaces in username)
        cred_index = None
        for j, bl in enumerate(block_lines):
            if is_credential_line(bl):
                cred_index = j
                break

        if cred_index is None:
            # No credentials found in this block, skip
            continue

        # Games are everything before the credential line
        game_lines = [bl for bl in block_lines[:cred_index] if bl]
        cred_line = block_lines[cred_index]

        # Password might be on the next line if cred line ends with ":"
        user, pwd = cred_line.split(":", 1)
        user = user.strip()
        pwd = pwd.strip()

        # If password is empty, check if next block line has it
        if not pwd and cred_index + 1 < len(block_lines):
            pwd = block_lines[cred_index + 1].strip()

        if not user or not pwd:
            continue

        games = ", ".join(game_lines) if game_lines else "Unknown"
        if games == "Unknown":
            continue

        results.append((user, pwd, games))

    return results

# ================= EVENTS =================
@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()

    await bot.change_presence(
        activity=discord.Game(name="🎮 Generating Steam accounts"),
        status=discord.Status.online
    )

    print(f"✅ Logged in as {bot.user}")
    print(f"🎮 Status set: Playing 🎮 Generating Steam accounts")

# ================= PAGINATION VIEWS =================
class GameView(discord.ui.View):
    def __init__(self, user_id, pages):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.pages = pages
        self.index = 0

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ These buttons are not for you.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        self.update()
        await interaction.response.edit_message(
            content=self.pages[self.index],
            view=self
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self.update()
        await interaction.response.edit_message(
            content=self.pages[self.index],
            view=self
        )

    def update(self):
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index == len(self.pages) - 1




# ================= USER COMMANDS =================

@bot.tree.command(name="steamaccount", description="Generate a Steam account for a game")
async def steamaccount(interaction: discord.Interaction, game: str):
    await interaction.response.defer(ephemeral=True)

    used = used_today(interaction.user.id)
    limit = daily_limit(interaction.user)

    if used >= limit:
        await interaction.followup.send(
            f"❌ Daily limit reached ({limit}/day).",
            ephemeral=True
        )
        return

    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id, username, password, games FROM accounts "
            "WHERE used=0 AND games LIKE ? ORDER BY RANDOM() LIMIT 1",
            (f"%{game}%",)
        )
        row = cur.fetchone()

        if not row:
            await interaction.followup.send(
                "❌ No accounts available for that game.",
                ephemeral=True
            )
            return

        acc_id, user, pwd, games = row
        cur.execute("UPDATE accounts SET used=1 WHERE id=?", (acc_id,))
        cur.execute(
            "INSERT INTO gens VALUES (?,?)",
            (interaction.user.id, date.today().isoformat())
        )

    embed = discord.Embed(
        title="🎮 Generated Steam Account",
        description="Crimson gen has agreed to only distribute accounts they own. Crimson Gen takes no responsibility for what you do with these accounts.",
        color=discord.Color.blue()
    )

    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1470798856085307423/1471984801266532362/IMG_7053.gif")

    embed.add_field(
        name="🔐 Account Details",
        value=f"`{user}:{pwd}`",
        inline=False
    )

    embed.add_field(
        name="🎮 Games",
        value=games if len(games) < 1024 else games[:1021] + "...",
        inline=False
    )

    embed.set_footer(text=f"Enjoy! ❤️")

    try:
        await interaction.user.send(embed=embed)
        await interaction.followup.send(
            "✅ Account sent to your DMs!",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send(
            f"❌ Couldn't send DM. Please enable DMs from server members.\n\n"
            f"**Account:** `{user}:{pwd}`",
            ephemeral=True
        )


@bot.tree.command(name="listgames", description="View available games")
async def listgames(interaction: discord.Interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT games FROM accounts WHERE used=0")
        rows = cur.fetchall()

    games = sorted({
        g.strip()
        for (row,) in rows
        for g in row.split(",")
        if g.strip()
    })

    if not games:
        await interaction.response.send_message("❌ No games available.")
        return

    pages = []
    chunk = 15
    for i in range(0, len(games), chunk):
        pages.append(
            "🎮 **Available Games**\n" +
            "\n".join(games[i:i + chunk])
        )

    view = GameView(interaction.user.id, pages)
    view.update()
    await interaction.response.send_message(pages[0], view=view)


@bot.tree.command(name="search", description="Search stock for a game")
async def search(interaction: discord.Interaction, game: str):
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM accounts WHERE used=0 AND games LIKE ?",
            (f"%{game}%",)
        )
        count = cur.fetchone()[0]

    await interaction.response.send_message(
        f"🔍 **{game}** stock: **{count}**"
    )


@bot.tree.command(name="stock", description="View total available accounts")
async def stock(interaction: discord.Interaction):
    await interaction.response.defer()

    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM accounts")
        total = cur.fetchone()[0]

    embed = discord.Embed(
        title="📦 Stock",
        description=f"**{total}** account(s) available",
        color=discord.Color.blue()
    )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="mystats", description="View your stats")
async def mystats(interaction: discord.Interaction):
    used = used_today(interaction.user.id)
    limit = daily_limit(interaction.user)
    referral = has_referral(interaction.user.id)

    await interaction.response.send_message(
        f"📊 **Your Stats**\n"
        f"Gens today: **{used}/{limit}**\n"
        f"Referral bonus: **{'Yes' if referral else 'No'}**",
        ephemeral=True
    )


@bot.tree.command(name="topusers", description="Top users today")
async def topusers(interaction: discord.Interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT user_id, COUNT(*) FROM gens "
            "WHERE day=? GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10",
            (date.today().isoformat(),)
        )
        rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message("❌ No gens today.")
        return

    msg = "🏆 **Top Users Today**\n"
    for i, (uid, count) in enumerate(rows, 1):
        msg += f"{i}. <@{uid}> — {count}\n"

    await interaction.response.send_message(msg)

# ================= REFERRALS =================

@bot.tree.command(name="referral_create", description="Create your referral code")
async def referral_create(interaction: discord.Interaction):
    code = "".join(str(random.randint(0, 9)) for _ in range(8))

    with db() as con:
        cur = con.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO referrals VALUES (?,?)",
            (interaction.user.id, code)
        )

    await interaction.response.send_message(
        f"🎁 **Your Referral Code:** `{code}`",
        ephemeral=True
    )


@bot.tree.command(name="refer", description="Redeem a referral code")
async def refer(interaction: discord.Interaction, code: str):
    if not code.isdigit() or len(code) != 8:
        await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
        return

    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT owner_id FROM referrals WHERE code=?", (code,))
        row = cur.fetchone()

        if not row:
            await interaction.response.send_message("❌ Code not found.", ephemeral=True)
            return

        cur.execute(
            "INSERT OR IGNORE INTO referral_uses VALUES (?)",
            (interaction.user.id,)
        )

    await interaction.response.send_message(
        "✅ Referral redeemed! +1 daily gen.",
        ephemeral=True
    )


@bot.tree.command(name="boostinfo", description="Boost perks info")
async def boostinfo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "💎 **Boost Perks**\n"
        "No boost: 2/day\n"
        "1 boost: 4/day\n"
        "2 boosts: 6/day\n"
        "+ Referral bonus",
        ephemeral=True
    )


@bot.tree.command(name="report", description="Report a bad account")
async def report(interaction: discord.Interaction, account: str, reason: str = "Invalid"):
    with db() as con:
        con.execute(
            "INSERT INTO reports VALUES (?,?)",
            (account, reason)
        )

    await interaction.response.send_message(
        "🚨 Report submitted.",
        ephemeral=True
    )

# ================= STAFF COMMANDS =================

@bot.tree.command(name="restock", description="Upload a file to restock accounts")
@app_commands.check(staff_only)
async def restock(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    try:
        text = (await file.read()).decode("utf-8", errors="ignore")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to read file: {e}", ephemeral=True)
        return

    parsed_accounts = parse_file(text)
    added = 0
    game_counts = {}

    with db() as con:
        cur = con.cursor()
        for user, pwd, games in parsed_accounts:
            try:
                cur.execute(
                    "INSERT INTO accounts (username, password, games, used) VALUES (?, ?, ?, 0)",
                    (user, pwd, games)
                )
                added += 1
                game_counts[games] = game_counts.get(games, 0) + 1
            except Exception:
                pass
        con.commit()

    if added == 0:
        await interaction.followup.send("❌ No valid accounts found in file.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🔄 Restock Complete",
        color=discord.Color.green()
    )

    stock_lines = "\n".join(
        f"**{game}:** `{count}` added"
        for game, count in sorted(game_counts.items(), key=lambda x: x[0].lower())
    )
    embed.add_field(name="📦 Games Added", value=stock_lines or "None", inline=False)
    embed.set_footer(text=f"✅ {added} account(s) added")

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="removeaccount", description="Remove an account")
@app_commands.check(staff_only)
async def removeaccount(interaction: discord.Interaction, account: str):
    with db() as con:
        cur = con.cursor()
        cur.execute("DELETE FROM accounts WHERE username||':'||password=?", (account,))
        removed = cur.rowcount

    await interaction.response.send_message(
        f"🗑️ Removed **{removed}** account(s).",
        ephemeral=True
    )


@bot.tree.command(name="accountinfo", description="View account info")
@app_commands.check(staff_only)
async def accountinfo(interaction: discord.Interaction, account: str):
    with db() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT games, used FROM accounts WHERE username||':'||password=?",
            (account,)
        )
        row = cur.fetchone()

    if not row:
        await interaction.response.send_message("❌ Account not found.", ephemeral=True)
        return

    games, used = row
    await interaction.response.send_message(
        f"ℹ️ **Account Info**\n"
        f"Games: `{games}`\n"
        f"Used: `{bool(used)}`",
        ephemeral=True
    )


@bot.tree.command(name="reportedaccounts", description="View reported accounts")
@app_commands.check(staff_only)
async def reportedaccounts(interaction: discord.Interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT account, reason FROM reports")
        rows = cur.fetchall()

    if not rows:
        await interaction.response.send_message("✅ No reports.")
        return

    msg = "🚨 **Reported Accounts**\n"
    for acc, reason in rows:
        msg += f"`{acc}` — {reason}\n"

    await interaction.response.send_message(msg)


@bot.tree.command(name="resetreport", description="Clear report for account")
@app_commands.check(staff_only)
async def resetreport(interaction: discord.Interaction, account: str):
    with db() as con:
        cur = con.cursor()
        cur.execute("DELETE FROM reports WHERE account=?", (account,))

    await interaction.response.send_message(
        "✅ Report cleared.",
        ephemeral=True
    )


@bot.tree.command(name="resetallreports", description="Clear all reports")
@app_commands.check(staff_only)
async def resetallreports(interaction: discord.Interaction):
    with db() as con:
        con.execute("DELETE FROM reports")

    await interaction.response.send_message(
        "✅ All reports cleared.",
        ephemeral=True
    )


@bot.tree.command(name="globalstats", description="View bot stats")
@app_commands.check(staff_only)
async def globalstats(interaction: discord.Interaction):
    with db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM accounts")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM accounts WHERE used=0")
        available = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM gens")
        gens = cur.fetchone()[0]

    await interaction.response.send_message(
        f"🌍 **Global Stats**\n"
        f"Total accounts: **{total}**\n"
        f"Available: **{available}**\n"
        f"Total gens: **{gens}**",
        ephemeral=True
    )

# ================= START BOT =================
bot.run(TOKEN)
