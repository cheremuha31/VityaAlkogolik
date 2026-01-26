# VityaAlkogolik

Telegram-бот для избиения Вити с ежедневным кулдауном, общим и групповым лидербордами.

## Запуск

1. Установите зависимости:

```bash
pip install -r requirements.txt
```

2. Задайте токен:

```bash
export TELEGRAM_BOT_TOKEN="ваш_токен"
```

Для Windows:

PowerShell:
```powershell
$env:TELEGRAM_BOT_TOKEN="ваш_токен"
```

cmd.exe:
```bat
set TELEGRAM_BOT_TOKEN=ваш_токен
```

3. Запустите бота:

```bash
python bot.py
```

По умолчанию база данных хранится в `vityaalkogolik.sqlite`. Можно переопределить через
`VITYA_DB_PATH`.

## Команды

* `/beat` `/hit` `/удар` `/бей` `/ударь` — ударить (раз в 24 часа).
* `/top` `/leaderboard` `/топ` `/лидерборд` — лидерборд внутри группы.
* `/global` `/all` `/общий` `/globaltop` — общий лидерборд.

Примечание: Telegram принимает только латинские команды для стандартных хэндлеров,
поэтому русские команды обрабатываются отдельным текстовым парсером.
