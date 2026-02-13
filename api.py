from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3, random, string
from datetime import datetime

app = FastAPI()
DB = "steam_bot.db"

def db():
    return sqlite3.connect(DB)

def gen_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html") as f:
        return f.read()

@app.post("/generate-code")
def generate_code(user_id: int):
    con = db()
    cur = con.cursor()

    # one code per user
    cur.execute("SELECT code FROM referrals WHERE owner_id=?", (user_id,))
    row = cur.fetchone()
    if row:
        con.close()
        return {"code": row[0]}

    code = gen_code()
    cur.execute(
        "INSERT INTO referrals VALUES (?, ?, ?)",
        (code, user_id, datetime.utcnow().isoformat())
    )
    con.commit()
    con.close()

    return {"code": code}
