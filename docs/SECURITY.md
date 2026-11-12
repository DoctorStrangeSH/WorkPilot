# Malenia — базовая модель безопасности

Этот документ задаёт обязательные требования для реализации. Он не означает, что механизмы уже реализованы.

## Доступ к аккаунтам и рабочим ресурсам

- Malenia использует только пользовательские сессии и интеграции, которые пользователь подключил сам.
- Доступ не должен расширяться за пределы прав текущего аккаунта.
- Нельзя обходить MFA, CAPTCHA, ограничения доступа, лицензирование или защиту сайтов.
- Секреты не извлекаются из профиля браузера и не попадают в логи.

## Хранение секретов

- Windows Credential Manager или эквивалентное системное хранилище.
- Исключить секреты из Git, crash dumps, логов и диагностических отчётов.
- Конфигурационные примеры содержат только фиктивные значения.
- При экспорте диагностики секреты маскируются.

## Разрешения инструментов

Каждый инструмент описывает:
- требуемые разрешения;
- типы данных, к которым он обращается;
- возможные побочные эффекты;
- уровень риска;
- поддерживаемую отмену;
- тайм-аут и предел повторов.

## Подтверждение действий

Подтверждение требуется как минимум для:
- отправки писем и сообщений;
- публикации или отправки данных внешним адресатам;
- покупок, платежей и финансовых операций;
- удаления или массового изменения данных;
- изменения настроек безопасности и прав доступа;
- любых действий, которые нельзя надёжно отменить.

## Работа с изображениями

- Проверять тип, размер и декодируемость файла.
- Ограничивать разрешение и размер временных буферов.
- Не исполнять и не открывать вложенное содержимое как код.
- Удалять временные файлы по завершении задачи согласно настройкам.
- Не отправлять изображения внешнему провайдеру без понятного уведомления и разрешения.

## Защита от prompt injection

Текст страницы, OCR, документы, письма и результаты поиска являются недоверенными данными, а не инструкциями для агента. Они не могут самостоятельно менять разрешения, раскрывать секреты или инициировать высокорисковые действия.

## Аудит и остановка

- Записывать инструмент, время, результат, источник и ID задачи.
- Не записывать пароли, токены и ненужные персональные данные.
- Предусмотреть глобальную остановку агента.
- Предусмотреть отмену конкретной задачи и блокировку новых действий.


## Реализованный Browser Bridge preview (0.1)

- Расширение Manifest V3 запрашивает только `activeTab` и `nativeMessaging`; нет разрешений `tabs`, `history`, `cookies`, `scripting` и широких host permissions.
- Пользователь вручную нажимает кнопку передачи активной вкладки. Автоматического сканирования вкладок нет.
- Native host сверяет origin расширения с локально зарегистрированным ID и принимает только `hello` и `share_active_tab`.
- Разрешены только URL HTTP(S); URL с userinfo отклоняются; query и fragment удаляются до сохранения.
- Сохраняются только title и очищенный URL, максимум 100 последних переданных вкладок.
- Не читаются DOM, содержимое страницы, формы, cookies, пароли, история, localStorage или файлы профиля.
- Native Messaging host использует бинарный length-prefixed JSON, ограничение 1 MiB и пишет диагностику только в stderr.
- Поддержка и поиск Native Messaging host должны быть проверены на точной версии/канале Яндекс Браузера пользователя; наличие корпоративных политик само по себе не доказывает совместимость каждой потребительской сборки.


## Explicit runtime installation and public search (0.6.0)

- Runtime setup downloads only the pinned official Windows x64 archive over HTTPS,
  validates exact size and SHA256 before extraction, rejects unsafe paths/symlinks
  and oversized archives, and stages in a unique app-owned directory. It preserves
  bundled upstream licenses. No system installer, administrator privileges, startup
  entry, driver changes or changes to an existing server. Failed staging is removed;
  a retry downloads again. Closing during download may leave an unused staging folder.
- Public search is off by default and explicit per chat setting. Only the current
  question is sent to Bing; search queries are processed under that provider's terms.
  Stored memories, notes, tasks and previous turns are never added to the query.
- The network endpoint is fixed, proxy use disabled, redirects rejected, and the XML
  response is bounded with DTD/entities rejected. Result pages are never fetched.
  Only HTTP(S) source links are displayed; opening one is a separate user click in
  their ordinary browser. Browser profiles/cookies/passwords/history are not accessed
  by Malenia. The browser's normal behavior applies when the user opens a source.
- Web snippets are untrusted data, not action authorization. Web mode excludes local
  knowledge/history and requires structured, validated known source IDs. A citation
  establishes which supplied snippet was referenced, not truth or relevance.


## Реализованный локальный vault интеграций

- `agent/malenia/secret_store.py` предоставляет Windows Credential Manager backend для именованных секретов.
- Используются Generic Credentials текущего пользователя с локальной персистентностью; токены не записываются в SQLite, JSON-конфигурацию, frontend или логи.
- На не-Windows платформах backend завершается ошибкой; plaintext fallback отсутствует.
- Имена credentials ограничены безопасным ASCII-форматом, размер секрета — 2048 байт.
- OAuth flow и выдача/обновление Google токенов пока не реализованы; наличие vault само по себе не означает, что Google Sheets подключён.
- Тесты используют изолированный fake backend; Windows CI дополнительно проверяет реальную запись/чтение/удаление временного credential.


## Google Sheets read-only connector

- Desktop OAuth client only. Installed apps are public clients; PKCE S256 and random one-use state are mandatory. Client secret is optional; if a project requires it, the user may enter it locally and it is stored in Windows Credential Manager. Never treat a bundled client secret as confidential.
- Loopback callback binds to `127.0.0.1` on a random port; no LAN binding. The callback validates Host, state, path and authorization code.
- The app requests exactly `https://www.googleapis.com/auth/spreadsheets.readonly`. Token responses that omit this scope or contain any additional scope are rejected before storage.
- Refresh token, public client ID, and optional client secret are stored as Windows Credential Manager Generic Credentials. Access token is memory-only. No plaintext fallback exists.
- Sheets access is GET-only for a user-entered spreadsheet ID and A1 range. The connector has no write method or Google Drive API client. Response size and cell count are bounded.
- Disconnect deletes local credentials but does not claim to revoke Google's grant; the UI tells the user how to revoke it in Google Account settings.
- The OAuth callback flow, token exchange and real-account authorization must pass CI and target-PC smoke tests before the connection is treated as production-ready.
