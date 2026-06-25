# SOAP-тестер событий (data-receiver)

Интерактивная отправка тестовых запросов по событиям из swagger.
Выбираешь событие → тело подставляется автоматически → `eventId` и `eventType`
проставляются сами → запрос уходит через Python (`urllib`) → видишь и тело, и ответ.

Работает на **Windows / macOS / Linux** — только Python 3, никаких внешних зависимостей.

## Что внутри
```
soap-tester/
├── send.py                 # главный скрипт (запускать его)
├── config.env              # endpoint, логины, режим — ОТРЕДАКТИРУЙ под себя
├── events.index.json       # список всех событий (генерится из swagger)
├── templates/              # тело eventData по каждому событию
│   ├── ACTIVE.json
│   ├── ASSIGNMENT_KDU.json
│   └── ... (остальные — из swagger-схем)
├── responses/              # сюда складываются ответы сервера
└── lib/
    └── generate_templates.py   # пере-генерация шаблонов из api-docs.json
```

## Настройка конфига
Файл `config.env` не хранится в репозитории (содержит учётные данные).
Получи его отдельно и положи в корень проекта рядом с `send.py`:
```
soap-tester/
└── config.env   ← сюда
```

Заполни в нём:
```
ENDPOINT="https://....../SyncChannel"   # URL шины (из Postman)
SENDER_ID="..."
SENDER_PASSWORD="..."
LOGIN="..."
PASSWORD="..."
TEST_IIN="..."                          # ИИН тестового пациента
```

## Как пользоваться
```bash
# macOS / Linux
python3 send.py                  # меню: выбрать событие и отправить
python3 send.py ACTIVE           # сразу конкретное событие
python3 send.py --list           # показать все события с номерами
python3 send.py ACTIVE --dry     # собрать и показать запрос, НО не отправлять
python3 send.py ACTIVE --op UPDATE
python3 send.py ACTIVE --rest    # послать чистый JSON на REST-эндпоинт swagger
python3 send.py ACTIVE --debug   # показать эквивалентную curl-команду

# Windows
py send.py ACTIVE
```

## Логика
- **eventId** формируется как `EVENT_<ТИП>_<MMDDHHMM>`, например `EVENT_ACTIVE_06231140`,
  и проставляется одновременно в `<eventId>` конверта и в поле `eventId` тела.
- **eventType** берётся из имени события и тоже синхронизируется в обоих местах.
- **messageId** — новый UUID на каждый запрос; **sendDate/messageDate** — текущее время (+05:00).
- Тело берётся из `templates/<ТИП>.json`; `{{TEST_IIN}}` заменяется значением из `config.env`.

## Два режима (`MODE` в config.env или флаги `--soap`/`--rest`)
- `soap` — заворачивает тело в SOAP-конверт SyncChannel и шлёт на единый `ENDPOINT` (как в Postman). **По умолчанию.**
- `rest` — шлёт чистый JSON на REST-эндпоинт из swagger (`/active`, `/blood-transfusion`, …).
  Для `--op UPDATE/DELETE` путь дополняется `/{eventId}` (PUT / DELETE).

## Поправить данные в шаблоне
Просто отредактируй нужный `templates/<ТИП>.json`. Это обычный JSON — меняй значения,
чтобы запрос проходил валидацию. `eventId`/`eventType` трогать не нужно — они проставятся сами.

## Обновить шаблоны из нового swagger
```bash
python3 lib/generate_templates.py /путь/к/api-docs.json          # не трогает существующие файлы
python3 lib/generate_templates.py /путь/к/api-docs.json --force  # перегенерировать ВСЕ заново
```
Без `--force` твои выверенные шаблоны не перезапишутся — добавятся только новые события.

## Заметки
- Шаблоны сгенерированы из swagger-схем (значения — заглушки `"string"`, `0`, даты и т.п.).
  Их нужно по необходимости довести до «проходящих».
- `CURL_EXTRA="-k"` в конфиге игнорирует самоподписанный сертификат стенда; убери, если не нужно.
