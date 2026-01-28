import sqlite3

from .settings import COOLDOWN_SECONDS, DB_PATH


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


def update_user_pending_boost(
    user_id: int,
    power_multiplier: float,
    cooldown_multiplier: float,
) -> None:
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