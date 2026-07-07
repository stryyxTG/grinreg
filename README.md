# TGLol Bot

Telegram-бот на `aiogram` + `Telethon` для добавления Telegram-аккаунтов и хранения файлов `.session` / `.json`.

Используй бот только для аккаунтов, к которым у тебя есть законный доступ.

## Что осталось в проекте

- Регистрация аккаунта по номеру телефона и коду входа.
- Ручной ввод email и кода с email, если Telegram попросит привязать почту.
- Сохранение зарегистрированного аккаунта в хранилище.
- Генерация Android JSON-профиля для зарегистрированного аккаунта.
- Единое хранилище всех зарегистрированных аккаунтов.
- Проверка, живая ли текущая `.session`.
- Скачивание одного `.session`, одного JSON или всего хранилища ZIP-архивом.
- Удаление одного аккаунта или полной очисткой хранилища.
- Доступ только для владельцев из `OWNER_IDS`.

ZIP-импорт, массовое добавление, старые разделы `НЕРЕГ/РЕГ`, фильтры сервисов и триггер-чаты убраны из рабочего интерфейса.

## Требования

- Python 3.11+
- Telegram Bot Token от `@BotFather`
- `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` с https://my.telegram.org

## Установка

```bash
python -m venv venv
```

Windows:

```powershell
.\venv\Scripts\activate
pip install -r requirements.txt
```

Linux:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка `.env`

Создай файл `.env` в корне проекта:

```env
BOT_TOKEN=PUT_BOT_TOKEN_HERE
OWNER_IDS=123456789,987654321

TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=put_api_hash_here

BOT_PARSE_MODE=HTML
DATA_DIR=storage
```

Несколько владельцев указываются через запятую, пробел или точку с запятой:

```env
OWNER_IDS=111111111,222222222,333333333
```

`ADMIN_IDS` тоже поддерживается как fallback, но лучше использовать `OWNER_IDS`.

Для мини-приложения загрузи `webapp/webappindex.html` на HTTPS-домен и добавь:

```env
WEBAPP_URL=https://example.com/webappindex.html
```

## Запуск

```bash
python bot2.py
```

Запуск на сервере через `nohup`:

```bash
source venv/bin/activate
nohup python bot2.py > bot.log 2>&1 &
```

Проверить лог:

```bash
tail -f bot.log
```

Остановить процесс:

```bash
ps aux | grep bot2.py
kill PROCESS_ID
```

## Как пользоваться

1. Напиши боту `/start` с аккаунта владельца.
2. Нажми `Регистрация`.
3. Отправь номер телефона и введи код Telegram.
4. Если Telegram попросит email, отправь email, затем код из письма.
5. После успешной регистрации аккаунт попадает в `Хранилище`.
6. В карточке аккаунта можно проверить session, скопировать номер, скачать файлы или удалить аккаунт.

## Хранилище файлов

По умолчанию данные лежат в папке `storage`:

```text
storage/
  bot.sqlite3
  sessions/
  json/
  tmp/
```

- `bot.sqlite3` — база данных.
- `sessions/` — `.session` файлы аккаунтов.
- `json/` — оригинальные или сгенерированные JSON.
- `tmp/` — временные файлы загрузки.

При удалении аккаунта из бота строка удаляется из базы, а файлы аккаунта удаляются с сервера. Telegram-сессия в самом Telegram при этом не разлогинивается.

## Проверка проекта

```bash
python -m compileall -q bot2.py tglol
python -m unittest discover -s tests -p "test*.py"
```
