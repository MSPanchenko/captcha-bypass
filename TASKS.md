Реализовывать без оверинженеринга.
Если что-то неизвестно/не уверен - гуглить документацию, а не придумывать.
Если что-то в задаче не ясно - спрашивать пользователя.

# Tasks

## 1. Структура проекта и pip-пакет

- [ ] Создать структуру директорий для Python-пакета
- [ ] Настроить pyproject.toml для публикации в PyPI
- [ ] Указать зависимости: aiohttp, camoufox[geoip] (geoip нужен для корректной работы с прокси)
- [ ] Создать CLI entrypoint `captcha-bypass` с параметрами:
  - `--workers` (default: cpu_count)
  - `--port` (default: 8191)
  - `--result-ttl` (секунды хранения результата, default: 600)

## 2. Docker

- [ ] Создать Dockerfile с установкой зависимостей и Camoufox
- [ ] Настроить docker-compose.yml с переменными окружения:
  - `WORKERS`
  - `PORT`
  - `RESULT_TTL`
- [ ] Проверить что образ работает "из коробки" без дополнительных настроек

## 3. HTTP API (aiohttp)

### GET /health
- [ ] Возвращать статус сервиса, количество воркеров, текущая очередь

### POST /solve
- [ ] Принимать параметры:
  - `url` (required) — ссылка для прохождения капчи
  - `success_text` (required) — текст, появление которого означает успех
  - `proxy` (optional) — объект `{"server": "http://host:port", "username": "user", "password": "pass"}`
  - `timeout` (required) — таймаут в секундах
- [ ] Генерировать UUID задачи
- [ ] Добавлять в FIFO очередь
- [ ] Возвращать `{task_id: "uuid"}`

### DELETE /task/{task_id}
- [ ] Отменить задачу если в статусе `pending` (удалить из очереди)
- [ ] Если `running` — пометить на отмену, воркер должен проверять флаг и убивать браузер
- [ ] Если `completed` — удалить результат из хранилища
- [ ] Возвращать `{success: true/false, message: "..."}`

### GET /result/{task_id}
- [ ] Возвращать структуру:
  ```json
  {
    "status": "pending|running|completed|error|not_found",
    "error": {"code": "alias", "message": "..."} или null,
    "data": {
      "cookies": [...],
      "headers": {...},
      "status_code": 200,
      "html": "...",
      "url": "final url after redirects",
      "timeout_reached": true/false
    } или null
  }
  ```
- [ ] Возвращаемые статусы задач:
  - `pending` — в очереди ожидания
  - `running` — браузер выполняет
  - `completed` — результат готов (data содержит результат, timeout_reached указывает нашёлся ли success_text)
  - `error` — ошибка при выполнении (error содержит code и message)
  - `not_found` — задача не существует или была удалена/отменена/expired

## 4. Task Queue и хранилище

- [ ] In-memory FIFO очередь (asyncio.Queue)
- [ ] Хранилище результатов (dict с task_id → result)
- [ ] Статусы задач (dict с task_id → status)
- [ ] TTL cleanup: удалять результаты старше N секунд
- [ ] При переходе задачи между статусами — обновлять статус

## 5. Captcha Solver (воркеры)

- [ ] Semaphore для ограничения параллельных браузеров
- [ ] Воркер берёт задачу из очереди → меняет статус на `running`
- [ ] Запуск Camoufox с proxy (если указан)
- [ ] Переход на URL, ожидание появления `success_text` через `page.wait_for_selector` или polling
- [ ] Таймаут отсчитывается с момента запуска браузера
- [ ] При таймауте:
  - НЕ ошибка, а success с `timeout_reached: true`
  - Вернуть текущее состояние страницы (html, cookies, headers, status)
- [ ] При нахождении текста:
  - success с `timeout_reached: false`
  - Вернуть все данные страницы
- [ ] При ошибке браузера:
  - success: false, error: "browser_error" или конкретный alias
- [ ] Гарантировать убийство браузера во всех случаях (context manager)
- [ ] После завершения — статус `completed`, результат в хранилище

## 6. Документация

- [ ] README.md: установка через pip и docker, примеры запросов
- [ ] Примеры curl/httpie для всех endpoint'ов

---

## Решения

- **Proxy формат**: объект `{"server": "http://host:port", "username": "user", "password": "pass"}`
- **Отмена задачи**: `DELETE /task/{task_id}`
- **Логирование**: stdout (docker json-file driver с ротацией 10m x 3)
