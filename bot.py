import os
import random
import sqlite3
import time
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


COOLDOWN_SECONDS = 24 * 60 * 60
EVENT_INTERVAL_SECONDS = 12 * 60 * 60
EVENT_DURATION_SECONDS = 5 * 60
DB_PATH = os.getenv("VITYA_DB_PATH", "vityaalkogolik.sqlite")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

BOOST_COSTS = {
    "vodka": 5,
    "time": 5,
}


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


@dataclass(frozen=True)
class EventSpec:
    event_type: str
    title: str
    description: str
    button_text: str
    power_multiplier: float = 1.0
    cooldown_multiplier: float = 1.0


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

EVENT_SPECS = (
    EventSpec(
        event_type="women",
        title="Ивент: Витя буянит",
        description="Витя набухался и пристает к женщинам. Ебни его и получи x2 мощи!",
        button_text="Вмазать за x2",
        power_multiplier=2.0,
    ),
    EventSpec(
        event_type="sober",
        title="Ивент: Трезвый Витя",
        description="Витя сегодня трезвый. Мощь снижается до x0.5.",
        button_text="Ударить за x0.5",
        power_multiplier=0.5,
    ),
    EventSpec(
        event_type="fight",
        title="Ивент: Витя хочет драться",
        description="Встань напротив него и получи x3 мощи, но риски высоки!",
        button_text="Принять вызов x3",
        power_multiplier=3.0,
    ),
    EventSpec(
        event_type="time",
        title="Ивент: Потеря памяти",
        description="Витя после бухича ничего не помнит, поэтому время быстро летит.",
        button_text="Сократить кулдаун",
        cooldown_multiplier=0.5,
    ),
)


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER NOT NULL,
                message_id INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_clicks (
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (event_id, user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_events (
                chat_id INTEGER PRIMARY KEY,
                next_event_ts INTEGER NOT NULL
            )
            """
        )
        ensure_user_columns(conn)


def ensure_user_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "respect_points" not in existing:
        conn.execute("ALTER TABLE users ADD COLUMN respect_points INTEGER NOT NULL DEFAULT 0")
    if "pending_power_multiplier" not in existing:
        conn.execute(
            "ALTER TABLE users ADD COLUMN pending_power_multiplier REAL NOT NULL DEFAULT 1.0"
        )
    if "pending_cooldown_multiplier" not in existing:
        conn.execute(
            "ALTER TABLE users ADD COLUMN pending_cooldown_multiplier REAL NOT NULL DEFAULT 1.0"
        )
    if "cooldown_seconds" not in existing:
        conn.execute(
            "ALTER TABLE users ADD COLUMN cooldown_seconds INTEGER NOT NULL DEFAULT "
            f"{COOLDOWN_SECONDS}"
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


def get_user_state(user_id: int) -> tuple[int, int, int, float, float, int]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT power, last_hit_ts, respect_points,
                   pending_power_multiplier, pending_cooldown_multiplier, cooldown_seconds
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return 0, 0, 0, 1.0, 1.0, COOLDOWN_SECONDS
        return (
            int(row[0]),
            int(row[1]),
            int(row[2]),
            float(row[3]),
            float(row[4]),
            int(row[5]),
        )


def update_user_after_beat(
    user_id: int,
    delta: int,
    now_ts: int,
    cooldown_seconds: int,
    respect_delta: int,
) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE users
            SET power = power + ?, last_hit_ts = ?
                , cooldown_seconds = ?
                , respect_points = respect_points + ?
                , pending_power_multiplier = 1.0
                , pending_cooldown_multiplier = 1.0
            WHERE user_id = ?
            """,
            (delta, now_ts, cooldown_seconds, respect_delta, user_id),
        )
        row = conn.execute(
            "SELECT power FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row[0]) if row else delta


def update_user_power_only(user_id: int, delta: int, respect_delta: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE users
            SET power = power + ?, respect_points = respect_points + ?
            WHERE user_id = ?
            """,
            (delta, respect_delta, user_id),
        )
        row = conn.execute(
            "SELECT power FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row[0]) if row else delta


def update_user_cooldown(user_id: int, last_hit_ts: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET last_hit_ts = ? WHERE user_id = ?",
            (last_hit_ts, user_id),
        )


def update_user_pending_boost(user_id: int, power_multiplier: float, cooldown_multiplier: float) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE users
            SET pending_power_multiplier = ?, pending_cooldown_multiplier = ?
            WHERE user_id = ?
            """,
            (power_multiplier, cooldown_multiplier, user_id),
        )


def spend_respect_points(user_id: int, amount: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT respect_points FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        current = int(row[0])
        if current < amount:
            return False
        conn.execute(
            "UPDATE users SET respect_points = respect_points - ? WHERE user_id = ?",
            (amount, user_id),
        )
        return True


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


def get_event_spec(event_type: str) -> EventSpec:
    for spec in EVENT_SPECS:
        if spec.event_type == event_type:
            return spec
    return EVENT_SPECS[0]


def select_random_event() -> EventSpec:
    return random.choice(EVENT_SPECS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return
    upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    if update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        ensure_chat_event_schedule(update.effective_chat.id, context.application.job_queue)
    message = (
        "🥊 <b>Команды:</b>\n"
        "• /beat или /удар - ударить (раз в 24 часа)\n"
        "• /rep - твой баланс респекта и бусты\n"
        "• /shop - магазин бустов\n"
        "• /buy &lt;vodka|time&gt; - купить буст\n"
        "• /event - время до следующего ивента\n"
        "• /top или /топ - лидерборд в чате\n"
        "• /global или /общий - общий лидерборд\n"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode=ParseMode.HTML,
    )

async def beat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return

    user = update.effective_user
    chat = update.effective_chat
    upsert_user(user.id, user.username, user.first_name)
    (
        total_power,
        last_hit_ts,
        respect_points,
        pending_power_multiplier,
        pending_cooldown_multiplier,
        cooldown_seconds,
    ) = get_user_state(user.id)
    now_ts = int(time.time())
    elapsed = now_ts - last_hit_ts

    if elapsed < cooldown_seconds:
        remaining = cooldown_seconds - elapsed
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "⏳ <b>Рано!</b>\n"
                f"Кулдаун ещё: {format_cooldown(remaining)}.\n"
                "Попробуй позже."
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    outcome, power_delta = roll_outcome()
    boost_applied = []
    if pending_power_multiplier != 1.0:
        power_delta = int(round(power_delta * pending_power_multiplier))
        boost_applied.append(f"мощь x{pending_power_multiplier:g}")
    next_cooldown_seconds = int(COOLDOWN_SECONDS * pending_cooldown_multiplier)
    if pending_cooldown_multiplier != 1.0:
        boost_applied.append(f"кулдаун x{pending_cooldown_multiplier:g}")
    new_total = update_user_after_beat(user.id, power_delta, now_ts, next_cooldown_seconds, 1)
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        upsert_group_member(chat.id, user.id)
        ensure_chat_event_schedule(chat.id, context.application.job_queue)

    display = get_user_display(user.username, user.first_name, user.id)
    boost_line = ""
    if boost_applied:
        boost_line = "\nБусты: " + ", ".join(boost_applied)
    result_text = (
        f"💥 <b>{display}</b> {outcome.message()}\n"
        f"🥋 Техника: {outcome.name}\n"
        f"⚡ Сила удара: <b>{power_delta}</b>\n"
        f"🏆 Твоя мощь теперь: <b>{new_total}</b>"
        f"{boost_line}"
    )
    await context.bot.send_message(
        chat_id=chat.id,
        text=result_text,
        parse_mode=ParseMode.HTML,
    )

def format_leaderboard(
    rows: list[tuple[int, int, str | None, str | None]],
    title: str,
) -> str:
    lines = [f"<b>{title}</b>"]
    if not rows:
        return "\n".join(lines + ["Пока никого нет."])
    for idx, (power, user_id, username, first_name) in enumerate(rows, start=1):
        name = get_user_display(username, first_name, user_id)
        lines.append(f"{idx}. {name}: {power}")
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
        ensure_chat_event_schedule(chat.id, context.application.job_queue)

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


async def rep_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return
    upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    (
        _power,
        _last_hit_ts,
        respect_points,
        pending_power_multiplier,
        pending_cooldown_multiplier,
        _cooldown_seconds,
    ) = get_user_state(update.effective_user.id)
    boosts = []
    if pending_power_multiplier != 1.0:
        boosts.append(f"мощь x{pending_power_multiplier:g}")
    if pending_cooldown_multiplier != 1.0:
        boosts.append(f"кулдаун x{pending_cooldown_multiplier:g}")
    boosts_text = "нет" if not boosts else ", ".join(boosts)
    message = (
        "🪙 <b>Твой респект</b>\n"
        f"Баланс: <b>{respect_points}</b>\n"
        f"Активные бусты: {boosts_text}\n"
        "Зарабатывай респект, чтобы покупать бусты в /shop."
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode=ParseMode.HTML,
    )


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    message = (
        "🛒 <b>Магазин бустов</b>\n"
        f"• vodka — x2 к мощности следующего удара (стоимость {BOOST_COSTS['vodka']} респекта)\n"
        f"• time — в 2 раза меньше кулдаун после следующего удара (стоимость {BOOST_COSTS['time']} респекта)\n"
        "Купить: /buy &lt;vodka|time&gt;"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode=ParseMode.HTML,
    )


async def buy_boost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None:
        return
    upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Укажи буст: /buy <vodka|time>",
        )
        return
    boost_name = context.args[0].lower()
    if boost_name not in BOOST_COSTS:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Неизвестный буст. Доступно: vodka, time.",
        )
        return
    (
        _power,
        _last_hit_ts,
        _respect_points,
        pending_power_multiplier,
        pending_cooldown_multiplier,
        _cooldown_seconds,
    ) = get_user_state(update.effective_user.id)
    if boost_name == "vodka" and pending_power_multiplier != 1.0:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="У тебя уже есть активный буст на мощь.",
        )
        return
    if boost_name == "time" and pending_cooldown_multiplier != 1.0:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="У тебя уже есть активный буст на кулдаун.",
        )
        return
    cost = BOOST_COSTS[boost_name]
    if not spend_respect_points(update.effective_user.id, cost):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Не хватает респекта.",
        )
        return
    if boost_name == "vodka":
        update_user_pending_boost(update.effective_user.id, 2.0, pending_cooldown_multiplier)
        text = "✅ Буст x2 к мощности куплен. Сработает на следующем ударе."
    else:
        update_user_pending_boost(update.effective_user.id, pending_power_multiplier, 0.5)
        text = "✅ Буст на половинный кулдаун куплен. Сработает на следующем ударе."
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def event_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await context.bot.send_message(
            chat_id=chat.id,
            text="Ивенты работают только в групповых чатах.",
        )
        return
    ensure_chat_event_schedule(chat.id, context.application.job_queue)
    now_ts = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT next_event_ts FROM chat_events WHERE chat_id = ?",
            (chat.id,),
        ).fetchone()
    if row is None:
        await context.bot.send_message(chat_id=chat.id, text="Пока нет расписания ивентов.")
        return
    remaining = max(int(row[0]) - now_ts, 0)
    await context.bot.send_message(
        chat_id=chat.id,
        text=f"⏱️ До следующего ивента: {format_cooldown(remaining)}",
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


async def handle_event_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    query = update.callback_query
    data = query.data or ""
    if not data.startswith("event:"):
        return
    event_id = int(data.split(":", 1)[1])
    user = update.effective_user
    upsert_user(user.id, user.username, user.first_name)
    with sqlite3.connect(DB_PATH) as conn:
        event_row = conn.execute(
            "SELECT chat_id, event_type, end_ts FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if event_row is None:
            await query.answer("Ивент уже закончился.", show_alert=True)
            return
        chat_id, event_type, end_ts = int(event_row[0]), str(event_row[1]), int(event_row[2])
        if int(time.time()) > end_ts:
            await query.answer("Ивент уже закончился.", show_alert=True)
            return
        try:
            conn.execute(
                "INSERT INTO event_clicks (event_id, user_id) VALUES (?, ?)",
                (event_id, user.id),
            )
        except sqlite3.IntegrityError:
            await query.answer("Ты уже участвовал.", show_alert=True)
            return
    spec = get_event_spec(event_type)
    display = get_user_display(user.username, user.first_name, user.id)
    if spec.event_type == "time":
        (
            _power,
            last_hit_ts,
            _respect,
            _pending_power_multiplier,
            _pending_cooldown_multiplier,
            cooldown_seconds,
        ) = get_user_state(user.id)
        now_ts = int(time.time())
        elapsed = now_ts - last_hit_ts
        remaining = max(cooldown_seconds - elapsed, 0)
        new_remaining = int(remaining * spec.cooldown_multiplier)
        new_last_hit_ts = now_ts - (cooldown_seconds - new_remaining)
        if remaining > 0:
            update_user_cooldown(user.id, new_last_hit_ts)
        message = (
            f"⏩ {display} воспользовался ивентом.\n"
            f"Оставшийся кулдаун уменьшен: {format_cooldown(new_remaining)}."
        )
        await context.bot.send_message(chat_id=chat_id, text=message)
        await query.answer("Кулдаун ускорен!")
        return

    outcome, power_delta = roll_outcome()
    power_delta = int(round(power_delta * spec.power_multiplier))
    new_total = update_user_power_only(user.id, power_delta, 1)
    result_text = (
        f"🎉 <b>{display}</b> {outcome.message()}\n"
        f"🥋 Техника: {outcome.name}\n"
        f"🎯 Ивент: {spec.title}\n"
        f"⚡ Сила удара: <b>{power_delta}</b>\n"
        f"🏆 Твоя мощь теперь: <b>{new_total}</b>"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=result_text,
        parse_mode=ParseMode.HTML,
    )
    await query.answer("Готово!")


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


if __name__ == "__main__":
    main()