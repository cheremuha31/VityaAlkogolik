import sqlite3
import time

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from .db import (
    get_user_state,
    spend_respect_points,
    update_user_after_beat,
    update_user_cooldown,
    update_user_pending_boost,
    update_user_power_only,
    upsert_group_member,
    upsert_user,
)
from .events import ensure_chat_event_schedule
from .settings import (
    BEAT_ALIASES,
    BOOST_COSTS,
    DB_PATH,
    GLOBAL_ALIASES,
    TOP_ALIASES,
    COOLDOWN_SECONDS,
)
from .utils import (
    extract_command,
    format_cooldown,
    get_event_spec,
    get_user_display,
    roll_outcome,
)


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
        _total_power,
        last_hit_ts,
        _respect_points,
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
