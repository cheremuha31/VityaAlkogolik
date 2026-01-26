import os
import random
import sqlite3
import time
from dataclasses import dataclass

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


COOLDOWN_SECONDS = 24 * 60 * 60
DB_PATH = os.getenv("VITYA_DB_PATH", "vityaalkogolik.sqlite")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


@dataclass(frozen=True)
class Outcome:
    name: str
    weight: int
    power_min: int
    power_max: int
    messages: tuple[str, ...]

    def roll_power(self) -> int:
        return random.randint(self.power_min, self.power_max)

    def message(self) -> str:
        return random.choice(self.messages)


OUTCOMES = (
    Outcome(
        name="Контратака: хук (бокс)",
        weight=6,
        power_min=-25,
        power_max=-10,
        messages=(
            "VityaAlkogolik увернулся и пробил хук из бокса - это сильнее твоего замаха.",
            "Контратака: хук из бокса. По силе выше твоего промаха.",
            "Слишком слабый размах, VityaAlkogolik отвечает хуком.",
        ),
    ),
    Outcome(
        name="Промах: уличный размах (стрит-файт)",
        weight=14,
        power_min=-9,
        power_max=-1,
        messages=(
            "Промах: уличный размах слабее любого джеба.",
            "Ты задел воздух - даже уличная пощёчина была бы сильнее.",
            "Удар ушёл в пустоту. Хуже любой техники.",
        ),
    ),
    Outcome(
        name="D-уровень: джеб (бокс)",
        weight=26,
        power_min=1,
        power_max=6,
        messages=(
            "Джеб из бокса: слабее лоу-кика и локтя, но лучше промаха.",
            "Лёгкая пощёчина из стрит-файта - это ниже лоу-кика по силе.",
            "Легкий тычок: уступает карате-гэри, но всё же в цель.",
        ),
    ),
    Outcome(
        name="C-уровень: лоу-кик (кикбоксинг)",
        weight=30,
        power_min=7,
        power_max=15,
        messages=(
            "Лоу-кик из кикбоксинга: сильнее джеба, но слабее локтя.",
            "Маваши-гери из карате - уже ощутимо мощнее джеба.",
            "Неплохой удар: сильнее уличной пощёчины, но ниже критики.",
        ),
    ),
    Outcome(
        name="B-уровень: локоть (муай-тай)",
        weight=18,
        power_min=16,
        power_max=28,
        messages=(
            "Локоть из муай-тай: ощутимо сильнее лоу-кика.",
            "Сильный хук из бокса - выше среднего по силе.",
            "Удар коленом из муай-тай - мощнее большинства техник.",
        ),
    ),
    Outcome(
        name="A-уровень: гильотина (джиу-джитсу)",
        weight=6,
        power_min=29,
        power_max=45,
        messages=(
            "Гильотина из джиу-джитсу - самая сильная техника сегодня.",
            "Критика: удушение/рычаг из джиу-джитсу сильнее всех ударных техник.",
            "Комбо с локтями и добиванием - топ по силе!",
        ),
    ),
)

BEAT_ALIASES = {"beat", "hit", "удар", "бей", "ударь", "ударить"}
TOP_ALIASES = {"top", "leaderboard", "топ", "лидерборд"}
GLOBAL_ALIASES = {"global", "all", "общий", "общийтоп", "globaltop"}


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                power INTEGER NOT NULL DEFAULT 0,
                last_hit_ts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_members (
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (group_id, user_id)
            )
            """
        )


def get_user_display(username: str | None, first_name: str | None, user_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return f"User {user_id}"


def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (user_id, username, first_name),
        )


def get_user_state(user_id: int) -> tuple[int, int]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT power, last_hit_ts FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return 0, 0
        return int(row[0]), int(row[1])


def update_user_power(user_id: int, delta: int, now_ts: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE users
            SET power = power + ?, last_hit_ts = ?
            WHERE user_id = ?
            """,
            (delta, now_ts, user_id),
        )
        row = conn.execute(
            "SELECT power FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row[0]) if row else delta


def upsert_group_member(group_id: int, user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO group_members (group_id, user_id)
            VALUES (?, ?)
            ON CONFLICT(group_id, user_id) DO NOTHING
            """,
            (group_id, user_id),
        )


def format_cooldown(seconds_left: int) -> str:
    hours = seconds_left // 3600
    minutes = (seconds_left % 3600) // 60
    return f"{hours}ч {minutes}м"


def roll_outcome() -> tuple[Outcome, int]:
    outcome = random.choices(OUTCOMES, weights=[o.weight for o in OUTCOMES], k=1)[0]
    power = outcome.roll_power()
    return outcome, power


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return
    upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    message = (
        "Команды:\n"
        "• /beat или /удар - ударить (раз в 24 часа)\n"
        "• /top или /топ - лидерборд в чате\n"
        "• /global или /общий - общий лидерборд\n"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=message)


async def beat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return

    user = update.effective_user
    chat = update.effective_chat
    upsert_user(user.id, user.username, user.first_name)
    total_power, last_hit_ts = get_user_state(user.id)
    now_ts = int(time.time())
    elapsed = now_ts - last_hit_ts

    if elapsed < COOLDOWN_SECONDS:
        remaining = COOLDOWN_SECONDS - elapsed
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f"Рано! Кулдаун ещё {format_cooldown(remaining)}.\n"
                "Попробуй позже."
            ),
        )
        return

    outcome, power_delta = roll_outcome()
    new_total = update_user_power(user.id, power_delta, now_ts)
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        upsert_group_member(chat.id, user.id)

    display = get_user_display(user.username, user.first_name, user.id)
    result_text = (
        f"{display} {outcome.message()}\n"
        f"Техника: {outcome.name}\n"
        f"Сила удара: {power_delta}\n"
        f"Твоя мощь теперь: {new_total}"
    )
    await context.bot.send_message(chat_id=chat.id, text=result_text)


def format_leaderboard(
    rows: list[tuple[int, int, str | None, str | None]],
    title: str,
) -> str:
    lines = [f"<b>{title}</b>"]
    if not rows:
        return "\n".join(lines + ["Пока никого нет."])
    for idx, (power, user_id, username, first_name) in enumerate(rows, start=1):
        name = get_user_display(username, first_name, user_id)
        lines.append(f"{idx}. {name} - {power}")
    return "\n".join(lines)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await context.bot.send_message(
            chat_id=chat.id,
            text="Команда работает только в группах. Используйте /global.",
        )
        return
    if update.effective_user is not None:
        upsert_group_member(chat.id, update.effective_user.id)

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT u.power, u.user_id, u.username, u.first_name
            FROM group_members gm
            JOIN users u ON u.user_id = gm.user_id
            WHERE gm.group_id = ?
            ORDER BY u.power DESC
            LIMIT 10
            """,
            (chat.id,),
        ).fetchall()

    message = format_leaderboard(rows, "Лидерборд чата (общая мощь)")
    await context.bot.send_message(chat_id=chat.id, text=message, parse_mode=ParseMode.HTML)


async def global_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT power, user_id, username, first_name
            FROM users
            ORDER BY power DESC
            LIMIT 10
            """
        ).fetchall()

    message = format_leaderboard(rows, "Глобальный лидерборд")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode=ParseMode.HTML,
    )


def extract_command(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command = stripped[1:].split(maxsplit=1)[0]
    if "@" in command:
        command = command.split("@", 1)[0]
    return command.lower()


async def handle_aliases(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return
    if update.effective_chat and update.effective_user:
        if update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            upsert_group_member(update.effective_chat.id, update.effective_user.id)
    command = extract_command(update.message.text)
    if command is None:
        return

    if command in BEAT_ALIASES:
        await beat(update, context)
    elif command in TOP_ALIASES:
        await leaderboard(update, context)
    elif command in GLOBAL_ALIASES:
        await global_leaderboard(update, context)


def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    init_db()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler(["beat", "hit"], beat))
    application.add_handler(CommandHandler(["top", "leaderboard"], leaderboard))
    application.add_handler(CommandHandler(["global", "all", "globaltop"], global_leaderboard))
    application.add_handler(MessageHandler(filters.TEXT, handle_aliases))

    application.run_polling()


if __name__ == "__main__":
    main()
