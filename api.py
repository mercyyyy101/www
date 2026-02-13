from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import requests, sqlite3, os, random, string
from datetime import datetime

app = FastAPI()
DB = "steam_bot.db"

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

def db():
    return sqlite3.connect(DB)

def gen_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html") as f:
        return f.read()

@app.get("/login")
def login():
    return RedirectResponse(
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify"
    )

@app.get("/callback", response_class=HTMLResponse)
def callback(code: str):
    token_res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "scope": "identify",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).json()

    user = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {token_res['access_token']}"},
    ).json()

    user_id = int(user["id"])

    con = db()
    cur = con.cursor()
    cur.execute("SELECT code FROM referrals WHERE owner_id=?", (user_id,))
    row = cur.fetchone()

    if row:
        code = row[0]
    else:
        code = gen_code()
        cur.execute(
            "INSERT INTO referrals VALUES (?, ?, ?)",
            (code, user_id, datetime.utcnow().isoformat())
        )
        con.commit()

    con.close()

    return f"""
    <html>
    <body style="background:#0f172a;color:white;font-family:sans-serif;text-align:center;padding-top:80px">
        <h1>🎉 Your Referral Code</h1>
        <h2 style="color:#38bdf8">{code}</h2>
        <p>Share this code with friends.</p>
        <p>They use <b>/refer {code}</b> in Discord.</p>
    </body>
    </html>
    """
