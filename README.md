# Malenia

**Malenia** — локальный рабочий ИИ-помощник для Windows: поиск по доступным пользователю системам, работа с изображениями, управление браузером и автоматизация компьютерных задач.

Проект развивается поэтапно. Возможности, описанные как будущие, не считаются реализованными, пока они не подтверждены кодом и проверками.

## Принятые требования

- Основная ОС: Windows.
- Основной браузер: Яндекс Браузер.
- Гибридная архитектура браузера: текущий профиль через разрешённый мост и отдельный изолированный профиль Malenia.
- Поиск по фото: локальные/подключённые источники и внешние трекеры через отдельные адаптеры.
- Максимальная автоматизация повторяемых задач с контролем риска.
- Целевое оборудование: 16 ГБ RAM, Intel Core 5 220H, встроенная Intel Graphics.
- Базовое приложение не требует платного API.

## Маления 0.6.0

Шерлок поддерживает автоматическую установку локального движка из приложения и
включаемый интернет-поиск по публичным выдержкам со ссылками. По умолчанию вопрос
остаётся локальным. Установка, ограничения и приватность: [локальный ИИ](docs/LOCAL_AI.md).

## Текущий статус

### Python Agent Runtime 0.2
- Локальный Python Agent Runtime.
- SQLite-хранилище задач и журнала событий.
- Resource Manager: память, CPU utilization и режимы Normal / Economy / Emergency.
- HTTP API только на loopback, с временным bearer-токеном.
- Создание, просмотр и отмена ожидающих задач.
- Unit-тесты и GitHub Actions.

### Desktop Shell 0.3 — в разработке
- Tauri 2 + React + Vite.
- Русскоязычный тёмный интерфейс.
- Запуск и остановка Python Agent из приложения.
- RAM/CPU, очередь задач, создание и отмена.
- Локальный токен остаётся в Rust-процессе и не передаётся frontend.
- Windows NSIS installer собирается через GitHub Actions; Python Agent и Native Messaging host упаковываются PyInstaller `onedir`.
- Browser Bridge: явная проверка активной вкладки через MV3 extension + Native Messaging; для Google Sheets автоматически сохраняются только ID документа и активный gid (без прочих query/fragment), после чего desktop читает лист через Google Sheets API в режиме readonly.

Установщик с новым Browser Bridge требует успешного завершения текущего Windows workflow и проверки артефакта. 2026-11-12: пользователь подтвердил работу ручной передачи вкладки через Browser Bridge на своём компьютере.

**Уже реализовано в экспериментальном режиме:** локальный Шерлок на Qwen/Ollama, память и справочные заметки, реестр навыков с проверкой черновиков, оценки полезности навыков, предложения новых навыков из чата и три режима глубины рассуждений. Browser Bridge умеет ограниченно читать заранее разрешённые страницы, выполнять экспериментальную сверку и показывать её суммарный результат и прогресс в Malenia.

**Пока не реализовано/не подтверждено:** произвольное выполнение задач из очереди, универсальный исполнитель инструментов, работа автономного ИИ с файлами и программами, подтверждённая совместимость браузерных адаптеров с реальными ИНВентой/DataLens/Asgard, автоматическая запись статусов, Desktop Automation и поиск по фото. Оценки навыков меняют только ранжирование инструкций, а не веса Qwen.

## Тестирование новой версии Windows

Завтра при проверке используйте [план тестирования от 13 ноября 2026](docs/TESTING_2026-11-13.md).

Установщик скачивается из [Windows installer — GitHub Actions](https://github.com/DoctorStrangeSH/WorkPilot/actions/workflows/windows-installer.yml): откройте **последний успешный запуск** в ветке `feat/desktop-shell` и скачайте `malenia-windows-installer`. Если требуется Browser Bridge, возьмите `malenia-browser-extension` из **того же запуска**. Не используйте старый установщик для проверки новых навыков.

В Windows CI добавлена отдельная проверка упакованного `malenia-agent.exe`: каталог навыков, создание и утверждение черновика, сохранение в отдельной SQLite-базе. Это проверка возможности запуска, а не доказательство работы Qwen на конкретном ПК.

## Запуск Python Agent отдельно

Требуется Python 3.11+.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
malenia-agent
```

После запуска standalone Agent показывает временный bearer-токен в консоли. Не публикуй его и не отправляй в чаты.

## Запуск Desktop в режиме разработки

Требуются Python 3.11+, Node.js 20+, Rust stable, Microsoft C++ Build Tools и WebView2 Runtime.

```powershell
cd desktop
npm install
npm run tauri dev
```

Подробнее: [desktop/README.md](desktop/README.md).

## Документация

- [Архитектура](docs/ARCHITECTURE.md)
- [Дорожная карта](docs/ROADMAP.md)
- [Архитектурные решения](docs/DECISIONS.md)
- [Безопасность](docs/SECURITY.md)
- [Локальный API](docs/API.md)
- [Передача контекста ИИ](docs/AI_HANDOFF.md)

## Безопасность

Malenia не извлекает cookies, пароли или токены из профиля браузера. Agent API слушает только localhost. Страницы, OCR и файлы считаются недоверенными данными. Высокорисковые и необратимые действия должны требовать подтверждения.

Изменения ведутся в feature-ветках и поставляются через Pull Request. Не добавляйте в Git реальные cookies, пароли, токены, личные данные, дампы профилей или рабочие выгрузки.

## Полное имя Malenia

Версия 0.3 использует отдельное пространство имён: Python-пакет `malenia`, команда `malenia-agent`, приложение `com.malenia.desktop`, Browser Bridge `com.malenia.browser`, папка `%LOCALAPPDATA%\Malenia` и база `malenia.sqlite3`. По запросу пользователя старые вкладки и задания не переносятся. Старые установленные файлы и данные автоматически не удаляются.

Повторный запуск окна активирует уже открытое окно Malenia. Агент не занимает чужой порт, не завершает посторонние процессы и при занятом порте выдаёт понятную ошибку до объявления готовности.

Расширение нужно обновить в прежней папке и заново зарегистрировать новый Native Messaging host. Подробности — в `browser-extension/README.md`. Адрес GitHub пока остаётся прежним; имя внешнего репозитория нельзя изменить заменой строк в коде.


## 2026-11-13 — OAuth invalid_request diagnostics
- User's Connections screenshot showed `google_oauth_invalid_request`. The callback page only confirms that the browser response (authorization code/state) reached the loopback handler; it does not confirm token exchange or credential persistence.
- The code maps this category specifically from HTTP 400/401 responses at Google's token endpoint, not from the authorization URL stage. The user-facing copy now says "token exchange" rather than generic authorization request.
- Token error handling now classifies only safe parameter categories when Google's bounded `error_description` mentions `code_verifier`, `redirect_uri`, `client_id`, `client_secret`, or authorization code. Raw provider descriptions and any authorization material are never returned or logged.
- Added regression tests for those mappings and for ensuring no provider description/client ID leaks. Python tests passed on 3.11, 3.12, and 3.13 for commit `ce0ec0b5`.
- Still not proven: exact root cause of the user's original provider error. The next built version should display a more specific safe category if Google returns one; if it remains generic, inspect Google Cloud client type/configuration and exact token request metadata without collecting secrets.


## 2026-11-13 — INVenta archive parser correction
- User confirmed Google OAuth works after adding the OAuth Desktop Client Secret. A real read-only Google Sheets read succeeded for `22.08 (Архив)` (185 rows).
- Screenshot evidence: first row/order ID `PVZ_FBS_RET_7720160`, partner/cargo code same value, Sheets serial date `46256` (2026-08-22), cost `29980`, product `Кеды RALF RINGER`, status `Исключение`, ticket `FA254276C66034580038`.
- Actual export has a blank header for the product-name column (E) and a blank header for status (H). The parser already inferred status; it now also infers the unlabeled product column without confusing mapped comment/ticket/group columns.
- Google Sheets serial dates are normalized to ISO calendar dates. Rows without an order ID are treated as report/summary/empty rows and skipped from order-level missing-field counts.
- The desktop first-order preview now shows the product name and labels the date as export date. Source remains read-only; DataLens and Asgard checks remain explicitly unverified.
- Regression tests cover the real screenshot shape and serial date. Python matrix passed 3.11/3.12/3.13 at commit `959471ce`; Desktop check at that commit was still running when last checked. A later UI commit adds the product line; re-check CI before packaging.
