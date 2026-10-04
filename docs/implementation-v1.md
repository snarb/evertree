# EverTree v1: реализация и проверка

## Границы

Доверенный core установлен как Python-пакет; изменяемый репозиторий содержит Programs и их общие помощники. Типы SDK остаются в адаптере. Состояние графа, памяти, задач и обучения не зависит от провайдера; внутренняя сессия возобновляется только адаптером с совпадающим именем. При смене провайдера подготавливается новый контекст из памяти.

Основная роль Program — ровно `model` либо `exec`. `meta` модифицирует `exec`. Режим исполнения (`live`, `evaluation`, `simulation`) задаётся конкретному запуску. Model-вызовы не получают shell, динамические инструменты действий или внешние наблюдения.

SDK работает в доверенном процессе с локальной авторизацией. Для native coding он подключает внешнюю среду исполнения: официальный Codex `exec-server` запускается внутри AppContainer EverTree с правами на выбранную workspace и временный профиль. Shell, файловые инструменты и их дочерние процессы остаются в этом контейнере; сетевые capabilities ему не выдаются. Python-мост `core/codex_executor.py` передаёт JSON-RPC между stdio сервера и loopback WebSocket. Подключение требует случайного bearer capability текущего запуска; браузерные Origin и второй клиент отклоняются. Capability не включается в URL или трассу.

В проверенной Windows-среде `cmd /c dir` и Git внутри AppContainer не работают из-за ограничений Windows на нормализацию DOS-путей. Дополнительные права `ReadAttributes` и `Traverse` на родительские каталоги это не исправляют; такие права runtime не добавляет. Агент использует файловые инструменты Codex или Python `pathlib`/`os` для работы с workspace и Python для запуска тестов. Создание commit и операции принятия кандидата выполняет доверенное ядро с проверками метаданных Git; перенос native-команд в процесс без изоляции не выполняется.

Нативная регрессионная проверка подтверждает AppContainer-токен дочернего процесса, запрет чтения, записи и удаления внешних контрольных файлов и недоступность локального TCP-сервера из контейнера. Доступность того же TCP-сервера с хоста проверяется до и после попытки: Windows может как немедленно отклонить соединение, так и отбросить пакеты до тайм-аута.

Мост использует пакет `websockets`; Node.js и установка elevated Windows sandbox Codex не требуются. Изоляция обеспечивается AppContainer/Job Object EverTree, без настройки глобальных ACL Codex. Native-инструменты не получают расширение прав через SDK approval. Подтверждение внешнего действия запрашивает отдельный gateway ядра.

Для `cmd /c` адаптер исправляет передачу вложенных кавычек в закреплённом Codex SDK 0.160: закрытый Python-интерпретатор внутри того же контейнера передаёт Windows исходную командную строку. Мост не исполняет команды на хосте; рабочий каталог, окружение, stdio, токен AppContainer и владение деревом процессов сохраняются. Проверяются кавычки, пробелы, `&`, `&&` и код возврата команды.

## Карта требований

| Область | Реализация | Проверки |
| --- | --- | --- |
| Идентичность, типизированный гипермультиграф, атомарные дельты, taxonomy, слоты, AccessView, Facets, UNKNOWN | `core/graph.py` | `test_graph.py` |
| Атрибуция, интервалы, нормализация, структурные сигналы | `core/attribution.py`, `core/topology.py` | `test_attribution.py`, `test_graph.py` |
| Неизменяемые traces, provenance, output refs, retention closure, retrieval, отложенное удаление | `core/memory.py` | `test_memory.py` |
| Binary/categorical beliefs, зависимые источники, пересмотр и отзыв evidence, ограниченное неподтверждённое влияние | `core/beliefs.py` | `test_beliefs.py` |
| AppContainer, приватный Python, JSON IPC, Job Object, commit-код | `core/sandbox.py`, `core/runtime.py`, `core/worker.py` | `test_runtime.py` |
| CodeAnchor, точные Git-версии и семантические operator ID | `core/anchors.py`, `core/runtime.py` | `test_anchors.py`, `test_runtime.py` |
| DBOS workflow на ProgramRun, дочерние workflows, steps, replay и наблюдения | `core/runtime.py`, `core/worker.py` | `test_runtime.py`, `test_lifecycle_backup.py` |
| Backup core + SQLite + код + параметры + окружение; ошибки обслуживания и длинные пути | `core/backup.py`, `application.py` | `test_lifecycle_backup.py`, `test_application.py`, `test_application_guards.py` |
| Bundle исходников доверенного runtime, SHA256, Python и frozen requirements; проверка совместимости до restore | `core/environment.py`, `core/backup.py`, `application.py` | `test_environment.py`, `test_application_guards.py` |
| Provider abstraction, Luna/high, динамические инструменты, события, отмена, ограничение прав | `core/provider.py`, `core/codex_provider.py` | `test_provider.py`, отдельная SDK-интеграция |
| Изолированный native Codex exec-server, authenticated loopback bridge и остановка дерева | `core/codex_executor.py`, `core/sandbox.py` | `test_codex_executor.py`, `test_native_executor_security.py` |
| Готовые Action-команды, проверка сессии, unknown outcome, отсутствие автоматического повтора | `core/actions.py` | `test_actions.py` |
| TaskSpecification, внимание, единственная Task, бюджеты, исключение approval wait и ancestry расхода | `core/cognition.py`, `application.py` | `test_cognition_learning.py`, `test_application.py`, `test_application_guards.py` |
| Первоначальный разбор, подготовка контекста/аргументов, планирование, контроль ресурсов, verification, reflection | `processes/*/_programs/default/implementation.py` | `test_bootstrap.py`, `test_application.py` |
| Evaluated / NotApplicable / Unresolved → Signal → Credit → PreparedUpdate → ledger/receipt; отзыв и коррекция | `core/evaluation.py`, `core/learning.py` | `test_cognition_learning.py` |
| SupervisorFeedback −5…+5, PREDICTS → исходный trace, сопоставление наблюдений, missing prediction → дочерний CreditAssignment → Attention | `core/predictions.py`, `core/evaluation.py`, `application.py`, `processes/prediction_evaluator/` | `test_prediction_flow.py` |
| Bernoulli, категории, числовые моменты, линейная регрессия; prediction без изменения параметров | `core/learning.py` | `test_cognition_learning.py` |
| Неизменяемые datasets, версии, source/episode independence, exposure lineage | `core/datasets.py` | `test_cognition_learning.py` |
| Claim, candidate clone, фиксированные проверки, exact commit, EvaluationChoice, активация | `core/lifecycle.py`, `core/experiments.py`, `application.py` | `test_lifecycle_backup.py`, `test_experiments.py`, `test_demo.py` |
| CLI и асинхронный API, новые входы во время выполнения, отдельные формирование/доставка/завершение | `cli.py`, `application.py` | `test_cli.py`, `test_application.py`, `test_application_guards.py` |

## Воспроизводимость

`uv.lock` фиксирует зависимости; `.python-version` — Python 3.13.16. При запуске EverTree создаёт bundle исходников установленного пакета `src/evertree`, исключая cache, скрытые файлы и данные авторизации. Bundle содержит хеши файлов, точные версии Python/платформы и транзитивных runtime-зависимостей, включая `evertree`, SDK, CLI и `websockets`, а также `requirements.txt` и `.python-version`. Его каталог адресуется fingerprint; backup включает его как зависимость `core_runtime` и проверяет целостность общим манифестом.

Restore проверяет исходники и версии установленного runtime до замены сохранённого состояния. При несовпадении он явно отказывает; доверенные исходники не заменяются автоматически. Бинарные distributions и интерпретатор в backup не копируются: для восстановления требуется предварительная установка идентичного runtime по сохранённым исходникам и манифесту зависимостей.

Trace хранит переданный EverTree контекст, схему, инструменты, ID сессии, доступные уведомления и usage; непрозрачные внутренние запросы провайдера помечаются `not_exposed`.

DBOS повторно выдаёт результат завершённого step при продолжении с прежней identity. Смена commit требует нового запуска. Внешний action ledger сначала сохраняет потенциально неизвестный исход; повтор с той же identity возвращает этот исход и не вызывает adapter снова. Гарантия относится к последнему согласованному backup, а не к произвольному моменту аварии хоста.

Каждый evaluator получает отдельные graph/memory/learning snapshots, рабочую область и DBOS. Реестр вызываемых Programs фиксируется до исполнения обеих сторон. Исходы holdout остаются в core; в Program передаются только входы. Одинаковая версия dataset используется для baseline и candidate. Точное сравнение JSON различает boolean и число, включая вложенные значения. Для новой Program отсутствие baseline обозначается явно, и применяются абсолютные критерии. Повторное обучение или переработка по уже раскрытым исходам не создаёт независимого evidence.

`bind_evaluation(..., criteria=AcceptanceCriteria(...))` фиксирует критерии разработчика для конкретной Program. По умолчанию требуется accuracy 1.0; набор с правилом `prediction` поддерживает Brier score, log loss, squared/absolute error, residual и exact match. Cases агрегируются взвешенным средним по неизменяемому dataset. Отсутствующие или бесконечные обязательные оценки блокируют принятие. Изменение criteria или привязанной версии dataset после проверки требует новой независимой Evaluation; обязательные проверки contracts/tests/holdout сохраняются при любой политике.

Application guards проверяют, что отмена дожидается SDK callbacks и worker перед финальным статусом; Program не может переписать `verified_task_rate` или удалить Process prototype; смена провайдера не возобновляет чужую сессию. Прерванный Program после backup продолжает прежний DBOS run ID. Ожидание approval исключается из общего расхода и доли дополнительного улучшения ровно один раз, включая технический timeout.

`SupervisorFeedback` валидирует конечное число в диапазоне −5…+5 и необязательный комментарий; его принимает API доверенного транспорта, а не инструменты модели. Для численной проверки используется только `value`, а комментарий остаётся в исходном наблюдении. `PredictionEvaluator` сопоставляет графовый `PREDICTS` с исходным output по `TraceOutputRef`, контексту `{process_id, subject, episode, conditions}` и необязательному временному горизонту. Назначение прогноза должно предшествовать наблюдению. Для составного исхода `parts` задаёт именованные части, а `observe(..., projections={target: {part: output_path}}, context=...)` сохраняет их связь с исходным наблюдением. Evaluator собирает новые и ранее сохранённые части; недостаток или неоднозначность данных дают `UnresolvedEvaluationResult` без выдуманного score. Отсутствие прогноза для выбранного target вызывает дочерний `CreditAssignment` и передаёт случай в контекст задачи для сознательного разбора. Сохранённое решение не прогнозировать применяется только в совпадающей области контекста и не отменяет обязательный target. Повторная обработка не создаёт новые unresolved credits. Выполнение оценки не запускает parameter learning.

## Проверки

```powershell
uv sync --frozen
uv run pytest -q
uv run ruff check src tests
uv run evertree --home C:\agents\check doctor
uv run python -m evertree.demo --home C:\agents\demo
```

Offline-тесты используют `ScriptedProvider`; unit-тесты DBOS могут явно подставлять обычный subprocess только внутри теста. Native-тесты запускают настоящий Windows AppContainer, проверяют запрещённые чтение/запись и завершение дочерних процессов. Рабочий runtime такой подстановки из CLI не предоставляет.

Живой SDK-тест запускается отдельно с текущей авторизацией Codex. Он расходует лимиты учётной записи; наличие SDK и `doctor` сами по себе не доказывают успешное выполнение моделью кода.

```powershell
# Транспорт и native exec-server без вызовов модели:
uv run pytest tests/test_codex_executor.py tests/test_native_executor_security.py -q

# Реальные Luna/high: структурированный ответ, dynamic tool, сессия и coding:
$env:EVERTREE_CODEX_INTEGRATION = "1"
uv run pytest tests/test_codex_integration.py -q
Remove-Item Env:\EVERTREE_CODEX_INTEGRATION

# Полная демонстрация с моделью; нужен новый каталог состояния:
uv run python -m evertree.demo --home C:\agents\live-demo --live
```

Эти команды задают способ проверки; успешность конкретного live-запуска устанавливается его результатами. Offline-демонстрация с явно указанным fake provider проверяет lifecycle и повторное использование после перезапуска, но не подтверждает доступность модели.

### Проверенный прогон 4 октября 2026

- Полный offline-набор: **228 passed, 2 skipped** за 285.57 секунды. Две пропущенные SDK-интеграции запущены отдельно с настоящей моделью и прошли.
- `doctor`: `ready: true`, текущая авторизация доступна, `gpt-6-luna` / `high`, SDK `0.160.0`, native executor в AppContainer подключён. Проверки чтения, записи и разрешённого scratch прошли.
- Живая демонстрация в `.state/live-demo-verified`: создана и принята Program 119; затем воспроизведена потеря дубликата `[3,1,3] → [1,3]`. Модель изменила код, независимая accuracy выросла с 0 до 1, принятое улучшение после закрытия и восстановления вернуло `[1,3,3]`.
- Проверенные commits демонстрации: `1b0a9fb4011c371c74f7692f247545ab92bae77e` и `49afc30ea90b9cc74f55e6c168ef6f03cedfe8a8`. При восстановлении сохранены 2913 trace events; три проверенных исхода задач прошли через learning pipeline.
- Ruff и проверка форматирования прошли; `uv sync --frozen` подтверждает согласованность окружения с lockfile.

Численные результаты относятся к этому небольшому демонстрационному dataset, а не к общей способности агента решать произвольные задачи.

## Не входит в v1

Associative Plane с пометкой `future`, composite attribution axes, сотрудничество и естественный отбор v2, fine-tuning Luna, горячая замена Python frames, полноценный debugger, веб-интерфейс и облачное развёртывание. Самообучение меняет знания, явно связанные параметры и проверенные версии Programs.

## Использованные интерфейсы

- [Официальный Python Codex SDK](https://learn.chatgpt.com/docs/codex-sdk) и [app-server](https://learn.chatgpt.com/docs/app-server).
- [Codex permission profiles](https://learn.chatgpt.com/docs/permissions).
- [Windows AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation).
- [DBOS: локальная база](https://docs.dbos.dev/python/tutorials/database-connection).
