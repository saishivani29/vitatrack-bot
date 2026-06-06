#!/usr/bin/env python3
"""
VitaTrack — Telegram Life Tracker Bot
Tabs: Tasks · Fitness · Diet · Sleep · Mood · Journal
      Habits · Learning · Gratitude · 120 Day Challenge
100% free. No API keys needed.
"""

import sqlite3
import os
import logging
from datetime import datetime, timedelta

# Load .env from the script's own directory
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

# ─── Config ───────────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH   = os.getenv("DB_PATH", "vitatrack.db")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set.")

# ─── Helpers ──────────────────────────────────────────────────────────────────
def today()      -> str: return datetime.now().strftime("%Y-%m-%d")
def now_iso()    -> str: return datetime.now().isoformat()
def week_start() -> str:
    d = datetime.now()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
def week_end() -> str:
    ws = datetime.strptime(week_start(), "%Y-%m-%d")
    return (ws + timedelta(days=7)).strftime("%Y-%m-%d")
def week_days_list() -> list:
    ws = datetime.strptime(week_start(), "%Y-%m-%d")
    return [(ws + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

def score_bar(s: int) -> str:
    filled = max(0, min(10, s // 10))
    return "█" * filled + "░" * (10 - filled)

def grade(s: int) -> str:
    if s >= 90: return "A+ 🌟 Outstanding!"
    if s >= 80: return "A  🎯 Excellent!"
    if s >= 70: return "B+ ✅ Great job!"
    if s >= 60: return "B  👍 Good week!"
    if s >= 50: return "C  ⚠️  Room to grow"
    return          "D  💪 Keep pushing!"

def tips(scores: dict) -> str:
    weak = sorted(
        [(k, v) for k, v in scores.items() if k != "overall"],
        key=lambda x: x[1]
    )[:3]
    TIPS = {
        "tasks":     "• Complete all 3 priorities every day.",
        "fitness":   "• Log your steps and exercise daily.",
        "diet":      "• Focus on eat healthy, no sugar, water, early dinner.",
        "sleep":     "• Put the phone down 30 min before bed.",
        "mood":      "• Check in with your mood every single day.",
        "journal":   "• Update your notes daily — even one line is enough.",
        "habits":    "• Do all 3 care steps — make them non-negotiable.",
        "learning":  "• Pick one learning area and go deep this week.",
        "gratitude": "• Write 3 things you're grateful for every single day.",
        "challenge": "• Show up every single day — that's the whole game.",
    }
    lines = ["📌 *Focus areas for next week:*"]
    for k, _ in weak:
        lines.append(TIPS.get(k, f"• Keep working on {k} this week."))
    return "\n".join(lines)

# ─── Subtasks ─────────────────────────────────────────────────────────────────
SUBTASKS = {
    "tasks": [
        "Priority One",
        "Priority Two",
        "Priority Three",
    ],
    "fitness": [
        "Steps",
        "Exercise",
        "No Exercise",
        "No Steps",
    ],
    "diet": [
        "Eat healthy",
        "Cheat day",
        "No Sugar",
        "8 glasses water",
        "Dinner before 7",
        "Not Met All",
    ],
    "sleep": [
        "No phone 30 min before bed",
        "7-8 hours target",
        "Logged sleep hours",
    ],
    "mood": [
        "Happy",
        "Good",
        "Neutral",
        "Low",
        "Stressed",
    ],
    "journal": [
        "Update in Notes",
        "No",
    ],
    "habits": [
        "AM Skin Care",
        "PM Skin Care",
        "Hair Care",
    ],
    "learning": [
        "Read 20 pages of any book",
        "AI",
        "Finance",
    ],
    "gratitude": [
        "Write 3 things I'm grateful for",
    ],
    "challenge": [
        "Workout",
        "Eat Healthy",
        "Study",
    ],
}

# Mood & Journal are single-select (only one option active at a time)
SINGLE_SELECT = {"mood", "journal"}

# Mood score values
MOOD_SCORES = {
    "Happy": 100, "Good": 80, "Neutral": 60,
    "Low": 30, "Stressed": 20,
}

# ─── Database ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, category TEXT, item TEXT,
            date TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS task_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, note TEXT, date TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sleep_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, hours REAL, quality INTEGER,
            notes TEXT, logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, text TEXT, mood TEXT, logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS gratitude (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, text TEXT, logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS challenge_120 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, start_date TEXT,
            active INTEGER DEFAULT 1, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS challenge_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, challenge_id INTEGER, day_number INTEGER,
            note TEXT, checked_in_at TEXT
        );
        CREATE TABLE IF NOT EXISTS weekly_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, week_start TEXT,
            reflection TEXT, created_at TEXT
        );
    """)
    conn.commit()
    conn.close()

def db(): return sqlite3.connect(DB_PATH)

def insert(table: str, user_id: int, **kwargs):
    conn = db()
    kwargs["user_id"] = user_id
    if "logged_at" not in kwargs and "created_at" not in kwargs and "date" not in kwargs:
        kwargs["logged_at"] = now_iso()
    cols = ", ".join(kwargs.keys())
    vals = ", ".join(["?"] * len(kwargs))
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({vals})", list(kwargs.values()))
    conn.commit(); conn.close()

def today_rows(user_id: int, table: str, date_col="logged_at") -> list[dict]:
    conn = db()
    c = conn.cursor()
    c.execute(f"SELECT * FROM {table} WHERE user_id=? AND {date_col} LIKE ?",
              [user_id, today() + "%"])
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

# ─── Daily Checks ─────────────────────────────────────────────────────────────
def get_checks(user_id: int, category: str, date: str = None) -> list[str]:
    if date is None:
        date = today()
    conn = db()
    c = conn.cursor()
    c.execute("SELECT item FROM daily_checks WHERE user_id=? AND category=? AND date=?",
              [user_id, category, date])
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def toggle_check(user_id: int, category: str, item: str) -> bool:
    conn = db()
    c = conn.cursor()
    if category in SINGLE_SELECT:
        # Check if already selected
        c.execute("SELECT id FROM daily_checks WHERE user_id=? AND category=? AND item=? AND date=?",
                  [user_id, category, item, today()])
        already = c.fetchone()
        # Clear all options for this category today
        c.execute("DELETE FROM daily_checks WHERE user_id=? AND category=? AND date=?",
                  [user_id, category, today()])
        if not already:
            c.execute("INSERT INTO daily_checks (user_id, category, item, date, created_at) VALUES (?,?,?,?,?)",
                      [user_id, category, item, today(), now_iso()])
            checked = True
        else:
            checked = False
    else:
        c.execute("SELECT id FROM daily_checks WHERE user_id=? AND category=? AND item=? AND date=?",
                  [user_id, category, item, today()])
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM daily_checks WHERE id=?", [row[0]])
            checked = False
        else:
            c.execute("INSERT INTO daily_checks (user_id, category, item, date, created_at) VALUES (?,?,?,?,?)",
                      [user_id, category, item, today(), now_iso()])
            checked = True
    conn.commit(); conn.close()
    return checked

def auto_check(user_id: int, category: str, item: str):
    """Silently check an item if not already checked."""
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id FROM daily_checks WHERE user_id=? AND category=? AND item=? AND date=?",
              [user_id, category, item, today()])
    if not c.fetchone():
        c.execute("INSERT INTO daily_checks (user_id, category, item, date, created_at) VALUES (?,?,?,?,?)",
                  [user_id, category, item, today(), now_iso()])
    conn.commit(); conn.close()

# ─── Scoring ──────────────────────────────────────────────────────────────────
def daily_score(user_id: int, category: str, date: str) -> int:
    checked = get_checks(user_id, category, date)

    if category == "tasks":
        items = SUBTASKS["tasks"]
        done  = len([i for i in items if i in checked])
        return int(done / len(items) * 100) if items else 0

    elif category == "fitness":
        steps_s    = 0 if "No Steps"    in checked else (50 if "Steps"    in checked else 0)
        exercise_s = 0 if "No Exercise" in checked else (50 if "Exercise" in checked else 0)
        return steps_s + exercise_s

    elif category == "diet":
        if "Cheat day" in checked or "Not Met All" in checked:
            return 0
        scoring = ["Eat healthy", "No Sugar", "8 glasses water", "Dinner before 7"]
        done    = len([i for i in scoring if i in checked])
        return int(done / len(scoring) * 100)

    elif category == "sleep":
        scoring = ["No phone 30 min before bed", "7-8 hours target", "Logged sleep hours"]
        done    = len([i for i in scoring if i in checked])
        return int(done / len(scoring) * 100)

    elif category == "mood":
        for mood, score in MOOD_SCORES.items():
            if mood in checked:
                return score
        return 0

    elif category == "journal":
        return 100 if "Update in Notes" in checked else 0

    elif category == "habits":
        items = SUBTASKS["habits"]
        done  = len([i for i in items if i in checked])
        return int(done / len(items) * 100) if items else 0

    elif category == "learning":
        items = SUBTASKS["learning"]
        done  = len([i for i in items if i in checked])
        return int(done / len(items) * 100) if items else 0

    elif category == "gratitude":
        return 100 if "Write 3 things I'm grateful for" in checked else 0

    return 0

def compute_scores(user_id: int) -> dict:
    s    = {}
    days = week_days_list()
    cats = ["tasks", "fitness", "diet", "sleep", "mood",
            "journal", "habits", "learning", "gratitude"]
    for cat in cats:
        s[cat] = int(sum(daily_score(user_id, cat, d) for d in days) / 7)
    # Challenge
    ch = get_active_challenge(user_id)
    if ch:
        checkins = get_challenge_checkins(user_id, ch["id"])
        week_ins = sum(1 for c in checkins if c["checked_in_at"][:10] in days)
        s["challenge"] = min(100, week_ins * 14)
    else:
        s["challenge"] = 0
    s["overall"] = int(sum(s.values()) / len(s))
    return s

# ─── Challenge ────────────────────────────────────────────────────────────────
def get_active_challenge(user_id: int) -> dict | None:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM challenge_120 WHERE user_id=? AND active=1 ORDER BY id DESC LIMIT 1", [user_id])
    row  = c.fetchone()
    cols = [d[0] for d in c.description] if row else []
    conn.close()
    return dict(zip(cols, row)) if row else None

def get_challenge_checkins(user_id: int, challenge_id: int) -> list[dict]:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM challenge_checkins WHERE user_id=? AND challenge_id=?",
              [user_id, challenge_id])
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

def start_challenge(user_id: int, start_date: str) -> int:
    conn = db()
    conn.execute("UPDATE challenge_120 SET active=0 WHERE user_id=?", [user_id])
    conn.execute("INSERT INTO challenge_120 (user_id, start_date, active, created_at) VALUES (?,?,1,?)",
                 [user_id, start_date, now_iso()])
    conn.commit()
    c = conn.cursor()
    c.execute("SELECT last_insert_rowid()")
    new_id = c.fetchone()[0]
    conn.close()
    return new_id

def challenge_day_number(start_date: str) -> int:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    return max(1, (datetime.now() - start).days + 1)

def progress_bar_long(done: int, total: int, length: int = 20) -> str:
    filled = int((done / max(1, total)) * length)
    return "█" * filled + "░" * (length - filled)

# ─── Keyboards ────────────────────────────────────────────────────────────────
def btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)
def back_row() -> list: return [[btn("◀️ Main menu", "m:back")]]
def back() -> InlineKeyboardMarkup: return InlineKeyboardMarkup(back_row())

def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("✅ Tasks",              "m:tasks"),     btn("💪 Fitness",           "m:fitness")],
        [btn("🥗 Diet",               "m:diet"),      btn("😴 Sleep",             "m:sleep")],
        [btn("😊 Mood",               "m:mood"),      btn("📓 Journal",           "m:journal")],
        [btn("🔄 Habits",             "m:habits"),    btn("📚 Learning",          "m:learn")],
        [btn("🙏 Gratitude",          "m:grat"),      btn("🗓 120 Day Challenge", "m:challenge")],
        [btn("📊 Weekly Report",                      "m:weekly")],
        [btn("📅 Today's Summary",                    "m:today")],
    ])

def subtask_keyboard(user_id: int, category: str, extra: list = None) -> InlineKeyboardMarkup:
    items   = SUBTASKS.get(category, [])
    checked = get_checks(user_id, category)
    rows    = []
    for i, item in enumerate(items):
        if item == "Logged sleep hours":
            continue  # Auto-managed, not shown as button
        icon = "✅" if item in checked else "☐"
        rows.append([btn(f"{icon}  {item}", f"chk:{category}:{i}")])
    if extra:
        rows.extend(extra)
    rows.extend(back_row())
    return InlineKeyboardMarkup(rows)

# ─── Section displays ─────────────────────────────────────────────────────────
async def show_tasks(q, uid):
    items   = SUBTASKS["tasks"]
    checked = get_checks(uid, "tasks")
    done    = len([i for i in items if i in checked])
    score   = daily_score(uid, "tasks", today())
    conn    = db()
    c       = conn.cursor()
    c.execute("SELECT note FROM task_notes WHERE user_id=? AND date=? ORDER BY id DESC", [uid, today()])
    notes   = [r[0] for r in c.fetchall()]
    conn.close()
    text    = f"✅ *Tasks*\n\nToday: {done}/{len(items)} done · Score: {score}/100\n\nTap to check off 👇"
    if notes:
        text += "\n\n📝 *Notes:*\n" + "".join(f"• _{n}_\n" for n in notes)
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "tasks", extra=[[btn("📝 Add a note", "do:task_note")]]))

async def show_fitness(q, uid):
    score = daily_score(uid, "fitness", today())
    await q.edit_message_text(
        f"💪 *Fitness*\n\nToday score: {score}/100\n\n"
        f"ℹ️ Steps = 50pts · Exercise = 50pts\n"
        f"No Steps / No Exercise = 0 for that item\n\n"
        f"Tap to check off 👇",
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "fitness"))

async def show_diet(q, uid):
    score = daily_score(uid, "diet", today())
    await q.edit_message_text(
        f"🥗 *Diet*\n\nToday score: {score}/100\n\n"
        f"ℹ️ Eat healthy · No Sugar · 8 glasses water · Dinner before 7 = 25pts each\n"
        f"Cheat day / Not Met All = 0\n\n"
        f"Tap to check off 👇",
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "diet"))

async def show_sleep(q, uid):
    sleeps  = today_rows(uid, "sleep_log")
    checked = get_checks(uid, "sleep")
    score   = daily_score(uid, "sleep", today())
    sleep_status = f"✅ {sleeps[-1]['hours']}h logged" if sleeps else "☐ Not logged yet"
    text = (
        f"😴 *Sleep*\n\nToday score: {score}/100\n\n"
        f"🛏 Sleep hours: {sleep_status}\n\n"
        f"Tap to check off 👇"
    )
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "sleep", extra=[[btn("🛏 Log sleep hours", "do:log_sleep")]]))

async def show_mood(q, uid):
    checked = get_checks(uid, "mood")
    score   = daily_score(uid, "mood", today())
    current = checked[0] if checked else "Not set"
    text    = (
        f"😊 *Mood*\n\nToday: {current} · Score: {score}/100\n\n"
        f"ℹ️ Happy=100 · Good=80 · Neutral=60 · Low=30 · Stressed=20\n\n"
        f"Select your mood 👇"
    )
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "mood"))

async def show_journal(q, uid):
    entries = today_rows(uid, "journal")
    score   = daily_score(uid, "journal", today())
    text    = f"📓 *Journal*\n\nToday score: {score}/100\n\n"
    if entries:
        snippet = entries[-1]["text"][:200]
        text   += f"*Today's entry:*\n_{snippet}_\n\n"
    text += "Tap to check off 👇"
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "journal", extra=[[btn("📝 Write journal entry", "do:log_journal")]]))

async def show_habits(q, uid):
    items   = SUBTASKS["habits"]
    checked = get_checks(uid, "habits")
    done    = len([i for i in items if i in checked])
    score   = daily_score(uid, "habits", today())
    await q.edit_message_text(
        f"🔄 *Habits*\n\nToday: {done}/{len(items)} done · Score: {score}/100\n\nTap to check off 👇",
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "habits"))

async def show_learn(q, uid):
    items   = SUBTASKS["learning"]
    checked = get_checks(uid, "learning")
    done    = len([i for i in items if i in checked])
    score   = daily_score(uid, "learning", today())
    await q.edit_message_text(
        f"📚 *Learning*\n\nToday: {done}/{len(items)} done · Score: {score}/100\n\nTap to check off 👇",
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "learning"))

async def show_gratitude(q, uid):
    entries = today_rows(uid, "gratitude")
    score   = daily_score(uid, "gratitude", today())
    text    = f"🙏 *Gratitude*\n\nToday score: {score}/100\n\n"
    if entries:
        text += "*Today's notes:*\n" + "".join(f"• _{e['text']}_\n" for e in entries[-3:]) + "\n"
    text += "Tap to check off 👇"
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "gratitude", extra=[[btn("➕ Add gratitude note", "do:log_grat")]]))

async def show_challenge(q, uid):
    ch = get_active_challenge(uid)
    if not ch:
        await q.edit_message_text(
            "🗓 *120 Day Challenge*\n\n"
            "Build discipline over 120 days.\n"
            "Tick off Workout, Eat Healthy, Study each day.\n\n"
            "Your Day 1 begins tomorrow 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [btn("🚀 Start my 120 days", "challenge:start")], *back_row()
            ])
        ); return

    day_num       = challenge_day_number(ch["start_date"])
    days_left     = max(0, 120 - day_num + 1)
    checkins      = get_challenge_checkins(uid, ch["id"])
    total_done    = len(checkins)
    checked_today = any(c["checked_in_at"][:10] == today() for c in checkins)

    if day_num > 120:
        end_date = (datetime.strptime(ch["start_date"], "%Y-%m-%d") + timedelta(days=119)).strftime("%d %b %Y")
        await q.edit_message_text(
            f"🎉 *Challenge Complete!*\n\nYou did all 120 days!\n\n"
            f"📅 Started: {ch['start_date']}\n🏁 Ended: {end_date}\n"
            f"✅ Check-ins: {total_done}/120\n\nAmazing! Start a new 120 days? 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [btn("🔄 Start new 120 days", "challenge:start")], *back_row()
            ])
        ); return

    start_fmt = datetime.strptime(ch["start_date"], "%Y-%m-%d").strftime("%d %b %Y")
    end_fmt   = (datetime.strptime(ch["start_date"], "%Y-%m-%d") + timedelta(days=119)).strftime("%d %b %Y")
    pct       = int((day_num / 120) * 100)
    bar       = progress_bar_long(day_num, 120)

    if   day_num <= 10: mot = "Great start — keep the momentum! 🔥"
    elif day_num <= 30: mot = "One month in — you're building something real! 💪"
    elif day_num <= 60: mot = "Halfway there — don't stop now! 🚀"
    elif day_num <= 90: mot = "75% done — the finish line is in sight! 🏁"
    else:               mot = "Final stretch — give it everything! 🌟"

    ch_items   = SUBTASKS["challenge"]
    ch_checked = get_checks(uid, "challenge")
    ch_done    = len([i for i in ch_items if i in ch_checked])

    recent = sorted(checkins, key=lambda x: x["checked_in_at"], reverse=True)[:3]
    rec_txt = ""
    if recent:
        rec_txt = "\n\n📝 *Recent check-ins:*\n" + "".join(
            f"Day {c['day_number']} · _{c['note']}_\n" for c in recent
        )

    text = (
        f"🗓 *120 Day Challenge*\n\n"
        f"*Day {day_num} of 120* · {days_left} days left\n\n"
        f"📅 Started: {start_fmt}\n🏁 Ends: {end_fmt}\n\n"
        f"`{bar}` {pct}%\n\n"
        f"✅ Check-ins: {total_done}/120 · Today: {ch_done}/{len(ch_items)}\n"
        f"_{mot}_{rec_txt}\n\nTick off today's tasks 👇"
    )

    rows = []
    for i, item in enumerate(ch_items):
        icon = "✅" if item in ch_checked else "☐"
        rows.append([btn(f"{icon}  {item}", f"chk:challenge:{i}")])
    rows.append([btn("💾 Save today's check-in", "challenge:checkin") if not checked_today
                 else btn("✅ Checked in today!", "challenge:done")])
    rows.append([btn("📋 View all check-ins", "challenge:history")])
    rows.extend(back_row())
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))

async def show_challenge_history(q, uid):
    ch = get_active_challenge(uid)
    if not ch: await show_challenge(q, uid); return
    checkins = sorted(get_challenge_checkins(uid, ch["id"]),
                      key=lambda x: x["day_number"], reverse=True)
    text = "📋 *120 Day Challenge — Check-ins*\n\n"
    if not checkins:
        text += "_No check-ins yet._"
    else:
        for c in checkins[:15]:
            text += f"*Day {c['day_number']}* · {c['checked_in_at'][:10]}\n_{c['note']}_\n\n"
        if len(checkins) > 15:
            text += f"_...and {len(checkins)-15} more_"
    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn("◀️ Back to challenge","m:challenge")], *back_row()]))

async def show_today_summary(q, uid):
    CATS = [
        ("✅ Tasks",     "tasks"),
        ("💪 Fitness",   "fitness"),
        ("🥗 Diet",      "diet"),
        ("😴 Sleep",     "sleep"),
        ("😊 Mood",      "mood"),
        ("📓 Journal",   "journal"),
        ("🔄 Habits",    "habits"),
        ("📚 Learning",  "learning"),
        ("🙏 Gratitude", "gratitude"),
    ]
    lines = [f"📅 *Today — {today()}*\n"]
    for label, cat in CATS:
        score = daily_score(uid, cat, today())
        lines.append(f"{label}: {score}/100")
    ch = get_active_challenge(uid)
    if ch:
        lines.append(f"\n🗓 Challenge: Day {challenge_day_number(ch['start_date'])}/120")
    await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=back())

async def show_weekly(q, uid):
    await q.edit_message_text("⏳ Calculating your weekly report…")
    scores = compute_scores(uid)
    conn   = db()
    c      = conn.cursor()
    c.execute("SELECT reflection FROM weekly_notes WHERE user_id=? AND week_start=? ORDER BY id DESC LIMIT 1",
              [uid, week_start()])
    note_row = c.fetchone(); conn.close()
    note_txt = f"\n\n📝 *Your weekly note:*\n_{note_row[0]}_" if note_row else ""
    report = (
        f"📊 *WEEKLY SCORECARD*\n_{week_start()} → {today()}_\n\n"
        f"*🏆 Overall: {scores['overall']}/100*\n*{grade(scores['overall'])}*\n\n"
        f"```\n"
        f"✅ Tasks         {score_bar(scores['tasks'])} {scores['tasks']:>3}\n"
        f"💪 Fitness       {score_bar(scores['fitness'])} {scores['fitness']:>3}\n"
        f"🥗 Diet          {score_bar(scores['diet'])} {scores['diet']:>3}\n"
        f"😴 Sleep         {score_bar(scores['sleep'])} {scores['sleep']:>3}\n"
        f"😊 Mood          {score_bar(scores['mood'])} {scores['mood']:>3}\n"
        f"📓 Journal       {score_bar(scores['journal'])} {scores['journal']:>3}\n"
        f"🔄 Habits        {score_bar(scores['habits'])} {scores['habits']:>3}\n"
        f"📚 Learning      {score_bar(scores['learning'])} {scores['learning']:>3}\n"
        f"🙏 Gratitude     {score_bar(scores['gratitude'])} {scores['gratitude']:>3}\n"
        f"🗓 Challenge     {score_bar(scores['challenge'])} {scores['challenge']:>3}\n"
        f"```\n\n{tips(scores)}{note_txt}"
    )
    await q.edit_message_text(report, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [btn("📝 Add weekly reflection", "do:weekly_note")],
            [btn("◀️ Main menu",             "m:back")],
        ]))

# ─── Prompts ──────────────────────────────────────────────────────────────────
PROMPTS = {
    "task_note":   ("📝 *Add a note*\n\nWrite your note for today's tasks:", "task_note"),
    "log_sleep":   ("😴 *Log sleep*\n\nHow many hours did you sleep?\nSend a number like `7.5`", "sleep_hours"),
    "log_journal": ("📓 *Daily Journal*\n\nWrite your reflection for today:", "journal"),
    "log_grat":    ("🙏 *Gratitude*\n\nWhat are you grateful for today?", "gratitude"),
    "weekly_note": ("📝 *Weekly Reflection*\n\nWrite your end-of-week note:", "weekly_note"),
}

# ─── Callback handler ─────────────────────────────────────────────────────────
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    d   = q.data
    await q.answer()

    section_map = {
        "m:tasks":     show_tasks,     "m:fitness":   show_fitness,
        "m:diet":      show_diet,      "m:sleep":     show_sleep,
        "m:mood":      show_mood,      "m:journal":   show_journal,
        "m:habits":    show_habits,    "m:learn":     show_learn,
        "m:grat":      show_gratitude, "m:challenge": show_challenge,
        "m:today":     show_today_summary,
    }

    if d in section_map:
        await section_map[d](q, uid); return

    if d == "m:back":
        await q.edit_message_text(
            "🌿 *VitaTrack* — What would you like to track?",
            parse_mode="Markdown", reply_markup=main_kb()
        ); return

    if d == "m:weekly":
        await show_weekly(q, uid); return

    # ── Subtask toggle ────────────────────────────────────────────────────────
    if d.startswith("chk:"):
        parts    = d.split(":")
        category = parts[1]
        idx      = int(parts[2])
        items    = SUBTASKS.get(category, [])
        if idx < len(items):
            toggle_check(uid, category, items[idx])
        refresh = {
            "tasks": show_tasks, "fitness": show_fitness, "diet": show_diet,
            "sleep": show_sleep, "mood": show_mood, "journal": show_journal,
            "habits": show_habits, "learning": show_learn,
            "gratitude": show_gratitude, "challenge": show_challenge,
        }
        if category in refresh:
            await refresh[category](q, uid)
        return

    # ── Input prompts ─────────────────────────────────────────────────────────
    if d.startswith("do:"):
        action = d[3:]
        if action in PROMPTS:
            context.user_data["awaiting"] = PROMPTS[action][1]
            await q.edit_message_text(PROMPTS[action][0], parse_mode="Markdown", reply_markup=back())
        return

    # ── Challenge ─────────────────────────────────────────────────────────────
    if d == "challenge:history":
        await show_challenge_history(q, uid); return

    if d == "challenge:done":
        await q.answer("Already checked in today! ✅", show_alert=True); return

    if d == "challenge:start":
        tomorrow     = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow_fmt = (datetime.now() + timedelta(days=1)).strftime("%d %b %Y")
        start_challenge(uid, tomorrow)
        await q.edit_message_text(
            f"🚀 *120 Day Challenge started!*\n\n"
            f"Your Day 1 begins tomorrow — *{tomorrow_fmt}*\n\n"
            f"Come back tomorrow, tap 🗓 120 Day Challenge,\n"
            f"tick off Workout / Eat Healthy / Study,\n"
            f"then tap 💾 Save today's check-in. 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn("◀️ Main menu", "m:back")]]),
        ); return

    if d == "challenge:checkin":
        ch = get_active_challenge(uid)
        if not ch:
            await q.answer("No active challenge.", show_alert=True); return
        day_num    = challenge_day_number(ch["start_date"])
        ch_items   = SUBTASKS["challenge"]
        ch_checked = get_checks(uid, "challenge")
        done_items = [i for i in ch_items if i in ch_checked]
        note       = ", ".join(done_items) if done_items else "Showed up today"
        conn = db()
        conn.execute(
            "INSERT INTO challenge_checkins (user_id, challenge_id, day_number, note, checked_in_at) VALUES (?,?,?,?,?)",
            [uid, ch["id"], day_num, note, now_iso()]
        )
        conn.commit(); conn.close()
        days_left = max(0, 120 - day_num)
        await q.edit_message_text(
            f"✅ *Day {day_num} checked in!*\n\nDone: _{note}_\n\n"
            f"🗓 {days_left} days remaining. Keep going! 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn("◀️ Main menu", "m:back")]]),
        ); return

    # ── Sleep quality ─────────────────────────────────────────────────────────
    if d.startswith("sleep_q:"):
        q_val = int(d.split(":")[1])
        hours = context.user_data.pop("sleep_hours", 7)
        insert("sleep_log", uid, hours=hours, quality=q_val, notes="")
        auto_check(uid, "sleep", "Logged sleep hours")
        emoji = "🌟" if hours >= 8 else "✅" if hours >= 7 else "⚠️" if hours >= 6 else "😔"
        await q.edit_message_text(
            f"😴 Sleep logged!\n{emoji} {hours}h · Quality {q_val}/10\n✅ Sleep hours auto-checked!",
            reply_markup=back()
        ); return

# ─── Message handler ──────────────────────────────────────────────────────────
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()
    aw   = context.user_data.pop("awaiting", None)

    if not aw:
        await update.message.reply_text("Use /start to open the menu 🌿", reply_markup=main_kb())
        return

    if aw == "task_note":
        conn = db()
        conn.execute("INSERT INTO task_notes (user_id, note, date, created_at) VALUES (?,?,?,?)",
                     [uid, text, today(), now_iso()])
        conn.commit(); conn.close()
        await update.message.reply_text(f"📝 Note saved!\n_{text}_", parse_mode="Markdown", reply_markup=main_kb())

    elif aw == "sleep_hours":
        try:
            hours = float(text.replace(",", "."))
            context.user_data["sleep_hours"] = hours
            await update.message.reply_text(
                f"😴 {hours}h — rate your sleep quality (1–10):",
                reply_markup=InlineKeyboardMarkup([
                    [btn(str(i), f"sleep_q:{i}") for i in range(1, 6)],
                    [btn(str(i), f"sleep_q:{i}") for i in range(6, 11)],
                ]))
        except:
            await update.message.reply_text("Please send a number like `7` or `7.5`", parse_mode="Markdown")

    elif aw == "journal":
        insert("journal", uid, text=text, mood="")
        await update.message.reply_text("📓 Journal entry saved! 🌟", reply_markup=main_kb())

    elif aw == "gratitude":
        insert("gratitude", uid, text=text)
        await update.message.reply_text(f"🙏 Saved!\n_{text}_", parse_mode="Markdown", reply_markup=main_kb())

    elif aw == "weekly_note":
        conn = db()
        conn.execute("INSERT INTO weekly_notes (user_id, week_start, reflection, created_at) VALUES (?,?,?,?)",
                     [uid, week_start(), text, now_iso()])
        conn.commit(); conn.close()
        await update.message.reply_text("📝 Weekly reflection saved! 🌿", reply_markup=main_kb())

    else:
        await update.message.reply_text("Use /start to open the menu.", reply_markup=main_kb())

# ─── Commands ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"🌿 *Welcome to VitaTrack, {name}!*\n\n"
        "Your free daily life tracker.\n\n"
        "✅ Tasks  ·  💪 Fitness  ·  🥗 Diet  ·  😴 Sleep\n"
        "😊 Mood  ·  📓 Journal  ·  🔄 Habits  ·  📚 Learning\n"
        "🙏 Gratitude  ·  🗓 120 Day Challenge\n\n"
        "📊 Weekly scorecard every week\nTap any button to start 👇",
        parse_mode="Markdown", reply_markup=main_kb())

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    CATS  = [("✅ Tasks","tasks"),("💪 Fitness","fitness"),("🥗 Diet","diet"),
             ("😴 Sleep","sleep"),("😊 Mood","mood"),("📓 Journal","journal"),
             ("🔄 Habits","habits"),("📚 Learning","learning"),("🙏 Gratitude","gratitude")]
    lines = [f"📅 *Today — {today()}*\n"]
    for label, cat in CATS:
        lines.append(f"{label}: {daily_score(uid, cat, today())}/100")
    ch = get_active_challenge(uid)
    if ch:
        lines.append(f"\n🗓 Challenge: Day {challenge_day_number(ch['start_date'])}/120")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_kb())

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    await update.message.reply_text("⏳ Calculating your weekly report…")
    scores = compute_scores(uid)
    conn   = db()
    c      = conn.cursor()
    c.execute("SELECT reflection FROM weekly_notes WHERE user_id=? AND week_start=? ORDER BY id DESC LIMIT 1",
              [uid, week_start()])
    note_row = c.fetchone(); conn.close()
    note_txt = f"\n\n📝 *Weekly note:*\n_{note_row[0]}_" if note_row else ""
    report = (
        f"📊 *WEEKLY SCORECARD — {week_start()}*\n\n"
        f"*🏆 Overall: {scores['overall']}/100*\n*{grade(scores['overall'])}*\n\n"
        f"```\n"
        f"✅ Tasks         {score_bar(scores['tasks'])} {scores['tasks']:>3}\n"
        f"💪 Fitness       {score_bar(scores['fitness'])} {scores['fitness']:>3}\n"
        f"🥗 Diet          {score_bar(scores['diet'])} {scores['diet']:>3}\n"
        f"😴 Sleep         {score_bar(scores['sleep'])} {scores['sleep']:>3}\n"
        f"😊 Mood          {score_bar(scores['mood'])} {scores['mood']:>3}\n"
        f"📓 Journal       {score_bar(scores['journal'])} {scores['journal']:>3}\n"
        f"🔄 Habits        {score_bar(scores['habits'])} {scores['habits']:>3}\n"
        f"📚 Learning      {score_bar(scores['learning'])} {scores['learning']:>3}\n"
        f"🙏 Gratitude     {score_bar(scores['gratitude'])} {scores['gratitude']:>3}\n"
        f"🗓 Challenge     {score_bar(scores['challenge'])} {scores['challenge']:>3}\n"
        f"```\n\n{tips(scores)}{note_txt}"
    )
    await update.message.reply_text(report, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [btn("📝 Add weekly reflection", "do:weekly_note")],
            [btn("🏠 Main menu",             "m:back")],
        ]))

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    init_db()
    log.info("VitaTrack bot starting…")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("today",  cmd_today))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("Bot running — Ctrl+C to stop")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
