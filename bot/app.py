import sqlite3

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from .db import init_db
from .events import ensure_chat_event_schedule
from .handlers import (
    beat,
    buy_boost,
    event_time,
    global_leaderboard,
    handle_aliases,
    handle_event_click,
    leaderboard,
    rep_balance,
    shop,
    start,
)
from .settings import DB_PATH, TOKEN


def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    init_db()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler(["beat", "hit"], beat))
    application.add_handler(CommandHandler(["rep"], rep_balance))
    application.add_handler(CommandHandler(["shop"], shop))
    application.add_handler(CommandHandler(["buy"], buy_boost))
    application.add_handler(CommandHandler(["event"], event_time))
    application.add_handler(CommandHandler(["top", "leaderboard"], leaderboard))
    application.add_handler(CommandHandler(["global", "all", "globaltop"], global_leaderboard))
    application.add_handler(CallbackQueryHandler(handle_event_click))
    application.add_handler(MessageHandler(filters.TEXT, handle_aliases))

    with sqlite3.connect(DB_PATH) as conn:
        chat_rows = conn.execute("SELECT chat_id FROM chat_events").fetchall()
    for (chat_id,) in chat_rows:
        ensure_chat_event_schedule(int(chat_id), application.job_queue)

    application.run_polling()
