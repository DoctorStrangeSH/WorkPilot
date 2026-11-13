# Проверка заказов — подтверждённые правила

**Статус:** правила формализованы в детерминированном dry-run модуле. Подключения к Google Sheets, DataLens и Asgard ещё не реализованы. Никаких изменений в источниках этот модуль не выполняет.

## Последовательность

1. Получить из ИНВенты строку заказа с `cargo-place` и датой инвентаризации.
2. В DataLens искать `cargo-place` по полю `main_partner_code_original`.
3. Учитывать только СЦ МК Дзержинский КГТ, `SC ID = 101366`.
4. Среди записей этого cargo-place и этого СЦ учитывать только успешные сканы `result = OK`; выбрать самый поздний успешный скан.
5. Если дата последнего успешного скана строго позже даты инвентаризации, предложить результат:
   - статус: **Найден**;
   - цвет: зелёный.
6. Если успешного скана после даты инвентаризации нет, перейти в Asgard:
   - раздел **Обратный поток**;
   - поле **Штрихкод коробки**;
   - найти коробку по штрихкоду.

## Подтверждённые правила Asgard

| Текущий статус Asgard | Дополнительная проверка | Предлагаемый статус | Комментарий | Цвет |
|---|---|---|---|---|
| Принят на ФФ | Не требуется | В работе | Принят на ФФ | Оранжевый |
| Выдан | Не требуется | Выдан | — | Зелёный |
| В пути | Открыть ID коробки и проверить расширенную историю | В работе (результат расследования: «2 ШК Выдан»), только если в истории есть «Выдан» | 2 ШК Выдан | Оранжевый |
| Любой другой / неоднозначный | — | Не предлагать | Не назначать | Ручная проверка |

Для статуса **В пути** отсутствие ID коробки, отсутствие расширенной истории или отсутствие события **Выдан** не трактуется как успешное совпадение. Заказ направляется на ручную проверку.

| Два статуса Asgard одновременно «В работе» | Оба значения должны быть явно получены | В работе | — | Оранжевый |

## Fail-closed правила

- Не использовать сканы из других СЦ.
- Не использовать неуспешные сканы.
- Не сравнивать похожие cargo-place: идентификатор сопоставляется точно.
- Не считать скан в ту же календарную дату автоматически более поздним: дата инвентаризации не содержит времени. При отсутствии доказательства «позже» проверка переходит к Asgard.
- Неизвестные статусы и неполные данные направлять человеку.
- Не додумывать статусы, комментарии, исключения или результаты.
- Не менять строки, статусы или комментарии в ИНВенте, DataLens или Asgard.

## Реализация

`agent/malenia/order_check.py` — чистая функция `evaluate_order(...)`, которая принимает уже полученные и нормализованные снимки данных и возвращает предложение с источником/доказательствами. У неё нет сетевых клиентов и функций записи.

DataLens adapter должен передавать исходное поле `main_partner_code_original`, `sc_id`, `result`, `scanned_at`. Asgard adapter должен передавать основной `status`, `box_id` и список статусов из расширенной истории. Адаптеры пока не существуют.

## Следующий этап интеграции

1. Настроить отдельный Google OAuth Desktop client для Malenia. Desktop client является public client: использовать PKCE; client secret необязателен. Если конкретный проект требует его при обмене токена, пользователь может ввести его локально; он сохраняется только в Windows Credential Manager и не считается защищённым секретом.
2. Запрашивать только `https://www.googleapis.com/auth/spreadsheets.readonly`. Этот scope read-only, но Google классифицирует его как sensitive; до публичного распространения может потребоваться проверка OAuth consent screen. Этот scope технически позволяет просматривать все таблицы, доступные аккаунту пользователя; приложение на уровне своего API ограничено только явно введённым Spreadsheet ID и A1 range и выполняет только GET.
3. Открывать системный браузер и использовать loopback redirect на случайном локальном порту; проверять одноразовый `state` и PKCE verifier.
4. Хранить refresh token только в системном хранилище секретов Windows; не помещать токены в SQLite, конфигурацию, логи или frontend. Для этого уже подготовлен `WindowsCredentialStore` в `agent/malenia/secret_store.py`; OAuth пока не подключён.
5. Начать с явного выбора одного Spreadsheet ID и диапазона, только GET запросы Sheets API. Не добавлять Google Drive write scope, Sheets write scope, изменения/создания таблиц.
6. Сверить полученные строки с пользователем, затем построить read-only dry-run отчёт. Запись результатов в ИНВенту — отдельная функция, запрещённая до нового явного согласования.

OAuth credentials (Client ID) пользователь должен создать в своём Google Cloud проекте и передать приложению через локальный экран настройки. Не добавлять credentials в Git и не просить пользователя присылать refresh token.


## Подготовленные OAuth building blocks

`agent/malenia/google_oauth.py` содержит строгие функции протокола Desktop OAuth: Client ID validation, PKCE S256, random state, loopback redirect, callback и exact-scope/token validation. `agent/malenia/google_sheets.py` добавляет callback listener на `127.0.0.1`, обмен/обновление токена, Credential Manager storage и GET-only чтение одного Spreadsheet ID + A1 range. API endpoints и Tauri commands/UI уже добавлены. Реальная авторизация Google account и target-PC smoke test ещё не выполнены; пока нет Client ID пользователя и его consent.

## Официальные ссылки Google для OAuth этапа

- [OAuth 2.0 для Desktop Apps](https://developers.google.com/identity/protocols/oauth2/native-app) — desktop client является public client; Google рекомендует PKCE и поддерживает loopback redirect для desktop apps.
- [Scopes Google Sheets API](https://developers.google.com/workspace/sheets/api/scopes) — `spreadsheets.readonly` позволяет просматривать таблицы и классифицируется Google как sensitive scope.
- [Миграция loopback IP flow](https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration) — loopback flow остаётся поддерживаемым для desktop OAuth clients.


## Важное ограничение Google OAuth Testing

Для External OAuth consent screen в статусе Testing Google выдаёт refresh token, который истекает через 7 дней, если запрошен не только базовый профиль. Для постоянного использования не оставлять внешний проект в Testing. Для личного использования Google допускает исключение из полной проверки, но может показывать предупреждение о непроверенном приложении и ограничивать число пользователей; для Google Workspace можно рассмотреть Internal OAuth project, если это соответствует организации. Коннектор распознаёт `invalid_grant`, показывает повторную авторизацию и подставляет сохранённый public Client ID; optional Client Secret остаётся в Credential Manager. После истечения/отзыва refresh token пользователь должен пройти OAuth заново. Источник: https://developers.google.com/identity/protocols/oauth2.

## Настройка личного Gmail для постоянной работы (решение 2026-11-12)

Пользователь выбрал **личный Gmail**, а не корпоративный Google Workspace. Для одного или небольшого числа лично известных пользователей оптимальная схема — отдельный проект Google Cloud для Malenia, Google Auth Platform Audience **External**, затем **Publish app / In production**. Это не делает непроверенное приложение общедоступным продуктом автоматически и не отменяет ограничения на число пользователей/предупреждение о непроверенном приложении. Google допускает исключение из обязательной OAuth verification для personal use, но требует соблюдения Google API Services User Data Policy. Не публиковать приложение для произвольной широкой аудитории без проверки.

Шаги для владельца аккаунта:

1. Перейти на https://console.cloud.google.com/ , создать отдельный проект `Malenia Personal` (не использовать проект другого приложения).
2. В **APIs & Services → Library** включить **Google Sheets API**. Не включать Google Drive API без новой необходимости.
3. **Google Auth Platform → Branding**: App name `Malenia Personal`; User support email и Developer contact — собственный Gmail. **Audience → External**.
4. **Data Access**: добавить только `https://www.googleapis.com/auth/spreadsheets.readonly` (sensitive; читает потенциально все таблицы аккаунта, но коннектор Malenia делает GET только по указанному ID и диапазону). Никаких Gmail, Drive или write scopes.
5. **Clients → Create client → Desktop app**, назвать `Malenia Windows Personal`. Клиент типа Desktop использует PKCE, системный браузер и локальный loopback callback. Для этой схемы Client Secret — необязательный параметр, не защищённый секрет desktop-приложения.
6. **Audience → Publish app / In production**: для личного применения не оставлять **Testing**, иначе при Sheets scope refresh token истечёт через 7 дней. Не нажимать Submit for verification только ради личного использования: для personal use есть исключение, однако на consent screen может появляться предупреждение Unverified app и действует лимит до 100 пользователей.
7. Установить проверенную сборку Malenia, открыть **Источники → Google Sheets**, ввести **Client ID** (и Client Secret лишь если требуется данным проектом), нажать «Подключить Google», в системном браузере проверить аккаунт, название приложения и точный scope и дать согласие. Не отправлять Client Secret, authorization code или refresh token в чат или GitHub.
8. Ввести ID конкретной таблицы ИНВенты и A1-диапазон, выполнить тестовое GET-чтение; отметить соединение подтверждённым только после успешного чтения. Если таблица принадлежит другому аккаунту, предоставить доступ к ней своему Gmail на стороне Google до теста. После этого сверить реальные названия колонок, не угадывая mapping.

Что даёт Production: **устраняет именно обязательное 7-дневное истечение refresh token из-за статуса Testing**. Это не бессрочная гарантия: токен может быть отозван, истечь по другим причинам, либо стать недействительным по политике Google. Обрабатывать `invalid_grant` и повторный consent; не пытаться обойти проверки. Не использовать service account для доступа к личному Gmail без отдельной модели совместного доступа.

В проекте уже реализованы OAuth/PKCE, Credential Manager и GET-only чтение, но личные credentials ещё не подключены и реальный доступ к ИНВенте не проверен. **Публикация в Google Cloud требует входа и подтверждения владельца аккаунта и не может быть выполнена без него.**

Официальные источники:
- https://support.google.com/cloud/answer/13464323 — личное использование и исключение из обязательной verification
- https://developers.google.com/identity/protocols/oauth2 — 7-дневный refresh token в Testing
- https://developers.google.com/identity/protocols/oauth2/production-readiness/overview — статусы Audience/Publishing
- https://developers.google.com/workspace/guides/configure-oauth-consent — настройка Branding, Audience, Data Access
- https://developers.google.com/identity/protocols/oauth2/native-app — Desktop OAuth PKCE и loopback
- https://developers.google.com/workspace/sheets/api/scopes — sensitive scope Sheets readonly


## Уточнение правил от пользователя (2026-11-13)

- Основной статус Asgard **«Выдан»** классифицируется как **«Выдан»**, а не «В работе».
- Если оба независимых статуса Asgard равны **«В работе»**, результат — **«В работе»**.
- Для **«В пути»** при наличии «Выдан» в расширенной истории сохраняется комментарий/результат расследования **«2 ШК Выдан»**; без подтверждающей истории — ручная проверка.
- Эти результаты являются выводом расследования. Они не означают, что Malenia должна исправлять исходные ячейки ИНВенты или менять статусы в источниках.
