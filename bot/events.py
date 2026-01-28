import sqlite3
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from .settings import DB_PATH, EVENT_DURATION_SECONDS, EVENT_INTERVAL_SECONDS
from .utils import select_random_event


def ensure_chat_event_schedule(chat_id: int, job_queue) -> None:
    if job_queue is None:
        return
    job_name = f"event_{chat_id}"
    if job_queue.get_jobs_by_name(job_name):
        return
    now_ts = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT next_event_ts FROM chat_events WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row is None:
            next_event_ts = now_ts + EVENT_INTERVAL_SECONDS
            conn.execute(
                "INSERT INTO chat_events (chat_id, next_event_ts) VALUES (?, ?)",
                (chat_id, next_event_ts),
            )
        else:
            next_event_ts = int(row[0])
    delay = max(next_event_ts - now_ts, 1)
    job_queue.run_once(
        trigger_event,
        delay,
        data={"chat_id": chat_id},
        name=job_name,
    )


async def trigger_event(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if job is None or job.data is None:
        return
    chat_id = int(job.data["chat_id"])
    spec = select_random_event()
    now_ts = int(time.time())
    end_ts = now_ts + EVENT_DURATION_SECONDS
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO events (chat_id, event_type, start_ts, end_ts)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, spec.event_type, now_ts, end_ts),
        )
        event_id = cursor.lastrowid
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(spec.button_text, callback_data=f"event:{event_id}")]]
    )
    text = f"{spec.title}\n{spec.description}\nИвент активен 5 минут!"
    message = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE events SET message_id = ? WHERE id = ?",
            (message.message_id, event_id),
        )
    cleanup_name = f"event_cleanup_{event_id}"
    context.job_queue.run_once(
        cleanup_event,
        EVENT_DURATION_SECONDS,
        data={"chat_id": chat_id, "event_id": event_id, "message_id": message.message_id},
        name=cleanup_name,
    )
    next_event_ts = now_ts + EVENT_INTERVAL_SECONDS
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE chat_events SET next_event_ts = ? WHERE chat_id = ?",
            (next_event_ts, chat_id),
        )
    ensure_chat_event_schedule(chat_id, context.job_queue)


async def cleanup_event(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if job is None or job.data is None:
        return
    chat_id = int(job.data["chat_id"])
    event_id = int(job.data["event_id"])
    message_id = int(job.data["message_id"])
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.execute("DELETE FROM event_clicks WHERE event_id = ?", (event_id,))
