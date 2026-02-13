from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3

app = FastAPI()
DB = "steam_bot.db"

def db():
    return sqlite3.connect(DB)

@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r") as f:
        return f.read()

@app.post("/use-referral")
def use_referral(user_id: int, code: str):
    con = db()
    cur = con.cursor()

    cur.execute("SELECT owner_id FROM referrals WHERE code=?", (code,))
    row = cur.fetchone()
    if not row:
        return {"error": "Invalid code"}

    cur.execute("SELECT 1 FROM referral_uses WHERE user_id=?", (user_id,))
    if cur.fetchone():
        return {"error": "Already used"}

    cur.execute("INSERT INTO referral_uses VALUES (?)", (user_id,))
    con.commit()
    con.close()

    return {"success": True}
