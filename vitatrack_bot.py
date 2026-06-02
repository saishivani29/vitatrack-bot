#!/usr/bin/env python3
"""
VitaTrack — Telegram Life Tracker Bot
Tabs: Tasks · Fitness · Diet · Sleep · Mood · Journal
      Habits · Learning · Gratitude · 120 Day Challenge

Each tab has checkable subtasks. Weekly scorecard included.
100% free. No API keys needed.
"""

import sqlite3
import json
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
    raise ValueError("BOT_TOKEN not set. Please set it before running.")

# ─── Helpers ──────────────────────────────────────────────────────────────────
def today()      -> str: return datetime.now().strftime("%Y-%m-%d")
def now_iso()    -> str: return datetime.now().isoformat()
def week_start() -> str:
    d = datetime.now()
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
def week_end() -> str:
    ws = datetime.strptime(week_start(), "%Y-%m-%d")
    return (ws + timedelta(days=7)).strftime("%Y-%m-%d")

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
        "tasks":     "• Tick off your top 3 tasks every single day.",
        "mood":      "• Check in with yourself every morning — even one word counts.",
        "sleep":     "• A consistent bedtime makes everything easier.",
        "fitness":   "• Even 10 min of movement counts — show up daily.",
        "diet":      "• Focus on one healthy swap this week.",
        "habits":    "• Pick 1 habit and nail it before adding more.",
        "gratitude": "• Write 1 thing you're grateful for before you sleep.",
        "journal":   "• Even 2 sentences at end of day is enough.",
        "learning":  "• Protect a 20 min learning slot like a meeting.",
        "challenge": "• Show up every single day — that's the whole game.",
    }
    lines = ["📌 *Focus areas for next week:*"]
    for k, _ in weak:
        lines.append(TIPS.get(k, f"• Keep working on {k} this week."))
    return "\n".join(lines)

# ─── Subtasks ─────────────────────────────────────────────────────────────────
SUBTASKS = {
    "tasks": [
        "Plan top 3 tasks for today",
    ],
    "fitness": [
        "10k Steps",
        "5-10k Steps",
        "0-5k Steps",
        "Exercise",
        "Yoga",
    ],
    "diet": [
        "Eat healthy",
        "Cheat day",
        "No Sugar",
        "8 glasses water",
        "Dinner before 7",
        "Dinner after 8",
    ],
    "sleep": [
        "No phone 30 min before bed",
        "7-8 hours target",
    ],
    "mood": [
        "Good",
        "Bad",
        "Happy",
    ],
    "journal": [
        "Recorded",
    ],
    "habits": [
        "Skin Care",
    ],
    "learning": [
        "Read 20 pages",
        "Watch 1 lesson",
        "Practice / apply what I learned",
    ],
    "gratitude": [
        "Write 3 things I'm grateful for",
        "Appreciate one person today",
    ],
    "challenge": [
        "Workout",
        "Eat Healthy",
        "Study",
    ],
}

# ─── Database ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            item TEXT,
            date TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS task_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            note TEXT,
            date TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS moods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            score INTEGER,
            notes TEXT,
            logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sleep_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            hours REAL,
            quality INTEGER,
            notes TEXT,
            logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            mood TEXT,
            logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS gratitude (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            logged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS challenge_120 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            start_date TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS challenge_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            challenge_id INTEGER,
            day_number INTEGER,
            note TEXT,
            checked_in_at TEXT
        );
        CREATE TABLE IF NOT EXISTS weekly_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            week_start TEXT,
            reflection TEXT,
            created_at TEXT
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

def week_rows(user_id: int, table: str, date_col="logged_at") -> list[dict]:
    conn = db()
    c = conn.cursor()
    c.execute(
        f"SELECT * FROM {table} WHERE user_id=? AND {date_col} >= ? AND {date_col} < ?",
        [user_id, week_start(), week_end()],
    )
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

def today_rows(user_id: int, table: str, date_col="logged_at") -> list[dict]:
    return [r for r in week_rows(user_id, table, date_col) if r[date_col][:10] == today()]

# ─── Daily Checks ─────────────────────────────────────────────────────────────
def get_checks(user_id: int, category: str) -> list[str]:
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT item FROM daily_checks WHERE user_id=? AND category=? AND date=?",
        [user_id, category, today()]
    )
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def toggle_check(user_id: int, category: str, item: str) -> bool:
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id FROM daily_checks WHERE user_id=? AND category=? AND item=? AND date=?",
        [user_id, category, item, today()]
    )
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM daily_checks WHERE id=?", [row[0]])
        checked = False
    else:
        c.execute(
            "INSERT INTO daily_checks (user_id, category, item, date, created_at) VALUES (?,?,?,?,?)",
            [user_id, category, item, today(), now_iso()]
        )
        checked = True
    conn.commit(); conn.close()
    return checked

def week_checks_count(user_id: int, category: str) -> int:
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM daily_checks WHERE user_id=? AND category=? AND date >= ? AND date < ?",
        [user_id, category, week_start(), week_end()]
    )
    count = c.fetchone()[0]
    conn.close()
    return count

# ─── Challenge ────────────────────────────────────────────────────────────────
def get_active_challenge(user_id: int) -> dict | None:
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM challenge_120 WHERE user_id=? AND active=1 ORDER BY id DESC LIMIT 1",
        [user_id]
    )
    row = c.fetchone()
    cols = [d[0] for d in c.description] if row else []
    conn.close()
    return dict(zip(cols, row)) if row else None

def get_challenge_checkins(user_id: int, challenge_id: int) -> list[dict]:
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM challenge_checkins WHERE user_id=? AND challenge_id=?",
        [user_id, challenge_id]
    )
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

def start_challenge(user_id: int, start_date: str) -> int:
    conn = db()
    conn.execute("UPDATE challenge_120 SET active=0 WHERE user_id=?", [user_id])
    conn.execute(
        "INSERT INTO challenge_120 (user_id, start_date, active, created_at) VALUES (?,?,1,?)",
        [user_id, start_date, now_iso()]
    )
    conn.commit()
    c = conn.cursor()
    c.execute("SELECT last_insert_rowid()")
    new_id = c.fetchone()[0]
    conn.close()
    return new_id

def challenge_day_number(start_date: str) -> int:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    diff  = (datetime.now() - start).days + 1
    return max(1, diff)

def progress_bar_long(done: int, total: int, length: int = 20) -> str:
    filled = int((done / max(1, total)) * length)
    return "█" * filled + "░" * (length - filled)

# ─── Weekly Scoring ───────────────────────────────────────────────────────────
def compute_scores(user_id: int) -> dict:
    s = {}

    s["tasks"]     = min(100, week_checks_count(user_id, "tasks") * 14)
    s["fitness"]   = min(100, week_checks_count(user_id, "fitness") * 5)
    s["diet"]      = min(100, week_checks_count(user_id, "diet") * 4)
    s["habits"]    = min(100, week_checks_count(user_id, "habits") * 14)
    s["gratitude"] = min(100, week_checks_count(user_id, "gratitude") * 7)
    s["journal"]   = min(100, week_checks_count(user_id, "journal") * 14)
    s["learning"]  = min(100, week_checks_count(user_id, "learning") * 5)

    moods = week_rows(user_id, "moods")
    s["mood"] = min(100, int(sum(m["score"] for m in moods) / len(moods) * 10)) if moods else 0

    sleeps = week_rows(user_id, "sleep_log")
    if sleeps:
        avg_h = sum(sl["hours"] for sl in sleeps) / len(sleeps)
        avg_q = sum(sl["quality"] for sl in sleeps) / len(sleeps)
        s["sleep"] = min(100, int(avg_h / 8 * 65 + avg_q * 3.5))
    else:
        s["sleep"] = 0

    challenge = get_active_challenge(user_id)
    if challenge:
        checkins = get_challenge_checkins(user_id, challenge["id"])
        ws  = datetime.strptime(week_start(), "%Y-%m-%d")
        wds = [(ws + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        week_checkins = sum(1 for c in checkins if c["checked_in_at"][:10] in wds)
        s["challenge"] = min(100, week_checkins * 14)
    else:
        s["challenge"] = 0

    s["overall"] = int(sum(s.values()) / len(s))
    return s

# ─── Keyboards ────────────────────────────────────────────────────────────────
def btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)

def back_row() -> list:
    return [[btn("◀️ Main menu", "m:back")]]

def back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(back_row())

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
        icon = "✅" if item in checked else "☐"
        rows.append([btn(f"{icon}  {item}", f"chk:{category}:{i}")])
    if extra:
        rows.extend(extra)
    rows.extend(back_row())
    return InlineKeyboardMarkup(rows)

def status_text(user_id: int, category: str, title: str, emoji: str) -> str:
    items   = SUBTASKS.get(category, [])
    checked = get_checks(user_id, category)
    done    = len([i for i in items if i in checked])
    return (
        f"{emoji} *{title}*\n\n"
        f"Today: {done}/{len(items)} done\n\n"
        f"Tap to check off 👇"
    )

# ─── Section displays ─────────────────────────────────────────────────────────
async def show_tasks(q, uid):
    items   = SUBTASKS.get("tasks", [])
    checked = get_checks(uid, "tasks")
    done    = len([i for i in items if i in checked])

    conn = db()
    c = conn.cursor()
    c.execute("SELECT note FROM task_notes WHERE user_id=? AND date=? ORDER BY id DESC", [uid, today()])
    notes = [r[0] for r in c.fetchall()]
    conn.close()

    text = f"✅ *Tasks*\n\nToday: {done}/{len(items)} done\n\nTap to check off 👇"
    if notes:
        text += "\n\n📝 *Notes:*\n"
        for n in notes:
            text += f"• _{n}_\n"

    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "tasks", extra=[
            [btn("📝 Add a note", "do:task_note")]
        ]))

async def show_fitness(q, uid):
    await q.edit_message_text(
        status_text(uid, "fitness", "Fitness", "💪"),
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "fitness"))

async def show_diet(q, uid):
    await q.edit_message_text(
        status_text(uid, "diet", "Diet", "🥗"),
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "diet"))

async def show_sleep(q, uid):
    sleeps = today_rows(uid, "sleep_log")
    items  = SUBTASKS.get("sleep", [])
    checked = get_checks(uid, "sleep")
    done    = len([i for i in items if i in checked])

    text = f"😴 *Sleep*\n\nToday: {done}/{len(items)} done\n\n"
    if sleeps:
        text += f"Last logged: {sleeps[-1]['hours']}h · Quality {sleeps[-1]['quality']}/10\n\n"
    text += "Tap to check off 👇"

    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "sleep", extra=[
            [btn("🛏 Log sleep hours", "do:log_sleep")]
        ]))

async def show_mood(q, uid):
    await q.edit_message_text(
        status_text(uid, "mood", "Mood", "😊"),
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "mood"))

async def show_journal(q, uid):
    entries = today_rows(uid, "journal")
    items   = SUBTASKS.get("journal", [])
    checked = get_checks(uid, "journal")
    done    = len([i for i in items if i in checked])

    text = f"📓 *Journal*\n\nToday: {done}/{len(items)} done\n\n"
    if entries:
        snippet = entries[-1]["text"][:200]
        text += f"*Today's entry:*\n_{snippet}_\n\n"
    text += "Tap to check off 👇"

    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "journal", extra=[
            [btn("📝 Write journal entry", "do:log_journal")]
        ]))

async def show_habits(q, uid):
    await q.edit_message_text(
        status_text(uid, "habits", "Habits", "🔄"),
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "habits"))

async def show_learn(q, uid):
    await q.edit_message_text(
        status_text(uid, "learning", "Learning", "📚"),
        parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "learning"))

async def show_gratitude(q, uid):
    entries = today_rows(uid, "gratitude")
    items   = SUBTASKS.get("gratitude", [])
    checked = get_checks(uid, "gratitude")
    done    = len([i for i in items if i in checked])

    text = f"🙏 *Gratitude*\n\nToday: {done}/{len(items)} done\n\n"
    if entries:
        text += "*Today's notes:*\n"
        for e in entries[-3:]:
            text += f"• _{e['text']}_\n"
        text += "\n"
    text += "Tap to check off 👇"

    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=subtask_keyboard(uid, "gratitude", extra=[
            [btn("➕ Add gratitude note", "do:log_grat")]
        ]))

async def show_challenge(q, uid):
    challenge = get_active_challenge(uid)

    if not challenge:
        await q.edit_message_text(
            "🗓 *120 Day Challenge*\n\n"
            "Build discipline over 120 days.\n"
            "Tick off Workout, Eat Healthy, Study each day.\n\n"
            "Your Day 1 begins tomorrow 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [btn("🚀 Start my 120 days", "challenge:start")],
                *back_row(),
            ])
        ); return

    start_date = challenge["start_date"]
    ch_id      = challenge["id"]
    day_num    = challenge_day_number(start_date)
    days_left  = max(0, 120 - day_num + 1)
    checkins   = get_challenge_checkins(uid, ch_id)
    total_done = len(checkins)
    checked_today = any(c["checked_in_at"][:10] == today() for c in checkins)

    if day_num > 120:
        end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=119)).strftime("%d %b %Y")
        await q.edit_message_text(
            "🎉 *Challenge Complete!*\n\n"
            f"You did all 120 days!\n\n"
            f"📅 Started: {start_date}\n"
            f"🏁 Ended:   {end_date}\n"
            f"✅ Check-ins: {total_done}/120\n\n"
            "Amazing! Start a new 120 days? 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [btn("🔄 Start new 120 days", "challenge:start")],
                *back_row(),
            ])
        ); return

    start_fmt = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d %b %Y")
    end_fmt   = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=119)).strftime("%d %b %Y")
    pct       = int((day_num / 120) * 100)
    bar       = progress_bar_long(day_num, 120)

    if   day_num <= 10: motivation = "Great start — keep the momentum! 🔥"
    elif day_num <= 30: motivation = "One month in — you're building something real! 💪"
    elif day_num <= 60: motivation = "Halfway there — don't stop now! 🚀"
    elif day_num <= 90: motivation = "75% done — the finish line is in sight! 🏁"
    else:               motivation = "Final stretch — give it everything! 🌟"

    ch_items   = SUBTASKS.get("challenge", [])
    ch_checked = get_checks(uid, "challenge")
    ch_done    = len([i for i in ch_items if i in ch_checked])

    recent = sorted(checkins, key=lambda x: x["checked_in_at"], reverse=True)[:3]
    recent_txt = ""
    if recent:
        recent_txt = "\n\n📝 *Recent check-ins:*\n"
        for c in recent:
            recent_txt += f"Day {c['day_number']} · _{c['note']}_\n"

    text = (
        f"🗓 *120 Day Challenge*\n\n"
        f"*Day {day_num} of 120*\n"
        f"{days_left} days remaining\n\n"
        f"📅 Started: {start_fmt}\n"
        f"🏁 Ends:    {end_fmt}\n\n"
        f"`{bar}` {pct}%\n\n"
        f"✅ Check-ins: {total_done}/120\n"
        f"Today: {ch_done}/{len(ch_items)} done\n"
        f"_{motivation}_"
        f"{recent_txt}\n\n"
        f"Tick off today's tasks 👇"
    )

    rows = []
    for i, item in enumerate(ch_items):
        icon = "✅" if item in ch_checked else "☐"
        rows.append([btn(f"{icon}  {item}", f"chk:challenge:{i}")])

    if not checked_today:
        rows.append([btn("💾 Save today's check-in", "challenge:checkin")])
    else:
        rows.append([btn("✅ Checked in today!", "challenge:done")])

    rows.append([btn("📋 View all check-ins", "challenge:history")])
    rows.extend(back_row())

    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows))

async def show_challenge_history(q, uid):
    challenge = get_active_challenge(uid)
    if not challenge:
        await show_challenge(q, uid); return

    checkins = sorted(
        get_challenge_checkins(uid, challenge["id"]),
        key=lambda x: x["day_number"], reverse=True
    )

    text = "📋 *120 Day Challenge — Check-ins*\n\n"
    if not checkins:
        text += "_No check-ins yet._"
    else:
        for c in checkins[:15]:
            text += f"*Day {c['day_number']}* · {c['checked_in_at'][:10]}\n_{c['note']}_\n\n"
        if len(checkins) > 15:
            text += f"_...and {len(checkins) - 15} more_"

    await q.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [btn("◀️ Back to challenge", "m:challenge")],
            *back_row(),
        ]))

async def show_today_summary(q, uid):
    def ct(cat):
        items   = SUBTASKS.get(cat, [])
        checked = get_checks(uid, cat)
        done    = len([i for i in items if i in checked])
        return f"{done}/{len(items)}"

    sleeps    = today_rows(uid, "sleep_log")
    challenge = get_active_challenge(uid)
    day_num   = challenge_day_number(challenge["start_date"]) if challenge else 0

    lines = [
        f"📅 *Today — {today()}*\n",
        f"✅ Tasks:      {ct('tasks')}",
        f"💪 Fitness:    {ct('fitness')}",
        f"🥗 Diet:       {ct('diet')}",
        f"😴 Sleep:      {sleeps[-1]['hours']}h" if sleeps else "😴 Sleep:      —",
        f"😊 Mood:       {ct('mood')}",
        f"📓 Journal:    {ct('journal')}",
        f"🔄 Habits:     {ct('habits')}",
        f"📚 Learning:   {ct('learning')}",
        f"🙏 Gratitude:  {ct('gratitude')}",
        f"🗓 Challenge:  {'Day ' + str(day_num) if day_num > 0 else '—'}",
    ]
    await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=back())

async def show_weekly(q, uid):
    await q.edit_message_text("⏳ Calculating your weekly report…")
    scores = compute_scores(uid)

    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT reflection FROM weekly_notes WHERE user_id=? AND week_start=? ORDER BY id DESC LIMIT 1",
        [uid, week_start()]
    )
    note_row = c.fetchone(); conn.close()
    note_txt = f"\n\n📝 *Your weekly note:*\n_{note_row[0]}_" if note_row else ""

    report = (
        f"📊 *WEEKLY SCORECARD*\n"
        f"_{week_start()} → {today()}_\n\n"
        f"*🏆 Overall: {scores['overall']}/100*\n"
        f"*{grade(scores['overall'])}*\n\n"
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
        f"```\n\n"
        f"{tips(scores)}"
        f"{note_txt}"
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
        "m:tasks":     show_tasks,
        "m:fitness":   show_fitness,
        "m:diet":      show_diet,
        "m:sleep":     show_sleep,
        "m:mood":      show_mood,
        "m:journal":   show_journal,
        "m:habits":    show_habits,
        "m:learn":     show_learn,
        "m:grat":      show_gratitude,
        "m:challenge": show_challenge,
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
            prompt_text, state = PROMPTS[action]
            context.user_data["awaiting"] = state
            await q.edit_message_text(prompt_text, parse_mode="Markdown", reply_markup=back())
        return

    # ── Challenge actions ─────────────────────────────────────────────────────
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
            f"then tap 💾 Save today's check-in.\n\n"
            f"You've got this! 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn("◀️ Main menu", "m:back")]]),
        ); return

    if d == "challenge:checkin":
        challenge = get_active_challenge(uid)
        if not challenge:
            await q.answer("No active challenge.", show_alert=True); return

        day_num    = challenge_day_number(challenge["start_date"])
        ch_items   = SUBTASKS.get("challenge", [])
        ch_checked = get_checks(uid, "challenge")
        done_items = [i for i in ch_items if i in ch_checked]
        note       = ", ".join(done_items) if done_items else "Showed up today"

        conn = db()
        conn.execute(
            "INSERT INTO challenge_checkins (user_id, challenge_id, day_number, note, checked_in_at) VALUES (?,?,?,?,?)",
            [uid, challenge["id"], day_num, note, now_iso()]
        )
        conn.commit(); conn.close()

        days_left = max(0, 120 - day_num)
        await q.edit_message_text(
            f"✅ *Day {day_num} checked in!*\n\n"
            f"Done today: _{note}_\n\n"
            f"🗓 {days_left} days remaining. Keep going! 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn("◀️ Main menu", "m:back")]]),
        ); return

    # ── Sleep quality rating ──────────────────────────────────────────────────
    if d.startswith("sleep_q:"):
        q_val = int(d.split(":")[1])
        hours = context.user_data.pop("sleep_hours", 7)
        insert("sleep_log", uid, hours=hours, quality=q_val, notes="")
        emoji = "🌟" if hours >= 8 else "✅" if hours >= 7 else "⚠️" if hours >= 6 else "😔"
        await q.edit_message_text(
            f"😴 Sleep logged!\n{emoji} {hours}h · Quality {q_val}/10",
            reply_markup=back()
        ); return

# ─── Text message handler ─────────────────────────────────────────────────────
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()
    aw   = context.user_data.pop("awaiting", None)

    if not aw:
        await update.message.reply_text(
            "Use /start to open the menu 🌿", reply_markup=main_kb()
        ); return

    if aw == "task_note":
        conn = db()
        conn.execute(
            "INSERT INTO task_notes (user_id, note, date, created_at) VALUES (?,?,?,?)",
            [uid, text, today(), now_iso()]
        )
        conn.commit(); conn.close()
        await update.message.reply_text(
            f"📝 Note saved!\n_{text}_", parse_mode="Markdown", reply_markup=main_kb()
        )

    elif aw == "sleep_hours":
        try:
            hours = float(text.replace(",", "."))
            context.user_data["sleep_hours"] = hours
            await update.message.reply_text(
                f"😴 {hours}h — rate your sleep quality (1–10):",
                reply_markup=InlineKeyboardMarkup([
                    [btn(str(i), f"sleep_q:{i}") for i in range(1, 6)],
                    [btn(str(i), f"sleep_q:{i}") for i in range(6, 11)],
                ]),
            )
        except:
            await update.message.reply_text(
                "Please send a number like `7` or `7.5`", parse_mode="Markdown"
            )

    elif aw == "journal":
        insert("journal", uid, text=text, mood="")
        await update.message.reply_text("📓 Journal entry saved! 🌟", reply_markup=main_kb())

    elif aw == "gratitude":
        insert("gratitude", uid, text=text)
        await update.message.reply_text(
            f"🙏 Saved!\n_{text}_", parse_mode="Markdown", reply_markup=main_kb()
        )

    elif aw == "weekly_note":
        conn = db()
        conn.execute(
            "INSERT INTO weekly_notes (user_id, week_start, reflection, created_at) VALUES (?,?,?,?)",
            [uid, week_start(), text, now_iso()]
        )
        conn.commit(); conn.close()
        await update.message.reply_text("📝 Weekly reflection saved! 🌿", reply_markup=main_kb())

    else:
        await update.message.reply_text(
            "Use /start to open the menu.", reply_markup=main_kb()
        )

# ─── Commands ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"🌿 *Welcome to VitaTrack, {name}!*\n\n"
        "Your free daily life tracker.\n\n"
        "✅ Tasks  ·  💪 Fitness  ·  🥗 Diet  ·  😴 Sleep\n"
        "😊 Mood  ·  📓 Journal  ·  🔄 Habits  ·  📚 Learning\n"
        "🙏 Gratitude  ·  🗓 120 Day Challenge\n\n"
        "📊 Weekly scorecard every week\n"
        "Tap any button to start 👇",
        parse_mode="Markdown",
        reply_markup=main_kb(),
    )

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    def ct(cat):
        items   = SUBTASKS.get(cat, [])
        checked = get_checks(uid, cat)
        done    = len([i for i in items if i in checked])
        return f"{done}/{len(items)}"

    sleeps    = today_rows(uid, "sleep_log")
    challenge = get_active_challenge(uid)
    day_num   = challenge_day_number(challenge["start_date"]) if challenge else 0

    lines = [
        f"📅 *Today — {today()}*\n",
        f"✅ Tasks:      {ct('tasks')}",
        f"💪 Fitness:    {ct('fitness')}",
        f"🥗 Diet:       {ct('diet')}",
        f"😴 Sleep:      {sleeps[-1]['hours']}h" if sleeps else "😴 Sleep:      —",
        f"😊 Mood:       {ct('mood')}",
        f"📓 Journal:    {ct('journal')}",
        f"🔄 Habits:     {ct('habits')}",
        f"📚 Learning:   {ct('learning')}",
        f"🙏 Gratitude:  {ct('gratitude')}",
        f"🗓 Challenge:  {'Day ' + str(day_num) if day_num > 0 else '—'}",
    ]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_kb()
    )

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text("⏳ Calculating your weekly report…")
    scores = compute_scores(uid)

    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT reflection FROM weekly_notes WHERE user_id=? AND week_start=? ORDER BY id DESC LIMIT 1",
        [uid, week_start()]
    )
    note_row = c.fetchone(); conn.close()
    note_txt = f"\n\n📝 *Weekly note:*\n_{note_row[0]}_" if note_row else ""

    report = (
        f"📊 *WEEKLY SCORECARD — {week_start()}*\n\n"
        f"*🏆 Overall: {scores['overall']}/100*\n"
        f"*{grade(scores['overall'])}*\n\n"
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
        f"```\n\n"
        f"{tips(scores)}"
        f"{note_txt}"
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
