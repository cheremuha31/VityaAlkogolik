import os

COOLDOWN_SECONDS = 24 * 60 * 60
EVENT_INTERVAL_SECONDS = 12 * 60 * 60
EVENT_DURATION_SECONDS = 5 * 60
DB_PATH = os.getenv("VITYA_DB_PATH", "../vityaalkogolik.sqlite")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

BOOST_COSTS = {
    "vodka": 5,
    "time": 5,
}

BEAT_ALIASES = {"beat", "hit", "удар", "бей", "ударь", "ударить"}
TOP_ALIASES = {"top", "leaderboard", "топ", "лидерборд"}
GLOBAL_ALIASES = {"global", "all", "общий", "общийтоп", "globaltop"}
