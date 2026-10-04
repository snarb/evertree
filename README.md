# EverTree

Локальный агент с семантическим графом, исполняемыми Programs, памятью и проверяемыми обновлениями. Первая поддерживаемая среда — **Windows**. Интерфейсы: CLI и асинхронный Python API.

Нужны Python **3.13.16**, Git, [uv](https://docs.astral.sh/uv/) с поддержкой этой версии Python и действующая локальная авторизация Codex. Все LLM-вызовы идут через официальный Python SDK `openai-codex`, модель **gpt-6-luna**, effort **high**. Смена модели при ошибке доступности не выполняется. Node.js не требуется.

```sh
uv python install 3.13.16
uv sync --frozen
uv run evertree --home C:\agents\my-tree init
uv run evertree --home C:\agents\my-tree doctor
uv run evertree --home C:\agents\my-tree chat
```

`doctor` проверяет текущую авторизацию, Luna/high и фактический запуск AppContainer. Если sandbox недоступен, исполнение Programs завершается ошибкой; обычный Python-процесс не используется как замена.

```powershell
uv run evertree --home C:\agents\my-tree run "Создай и протестируй функцию для обработки CSV"
uv run evertree --home C:\agents\my-tree tasks list
uv run evertree --home C:\agents\my-tree tasks show TASK_ID
uv run evertree --home C:\agents\my-tree tasks resume TASK_ID "Ответ на уточнение"
uv run evertree --home C:\agents\my-tree tasks cancel TASK_ID
uv run evertree --home C:\agents\my-tree programs
uv run evertree --home C:\agents\my-tree graph Self
uv run evertree --home C:\agents\my-tree memory "обработка CSV"
uv run evertree --home C:\agents\my-tree traces
uv run evertree --home C:\agents\my-tree backup
uv run evertree --home C:\agents\my-tree backup --list
uv run evertree --home C:\agents\my-tree restore BACKUP_NAME
```

CLI и Python API используют одно ядро. Одновременно исполняется одна Task; входы в очередь сохраняются немедленно. Уточнение продолжает ту же Task. Сообщение, принятое во время работы контроллера или проверки, поступает в следующий вызов контроллера до выдачи ответа. Ответ сначала формируется и проверяется, затем доставляется; только подтверждённая доставка допускает успешное завершение.

```python
import asyncio
from evertree import EverTree

async def main():
    async with EverTree(r"C:\agents\my-tree") as tree:
        result = await tree.run("Создай и протестируй небольшой Python-модуль")
        print(result["answer"])

asyncio.run(main())
```

Для собственного транспорта используйте `submit()`, `events()` и `acknowledge_delivery()`. `run()` — удобный транспорт, автоматически подтверждающий получение ответа вызывающей стороной. `resume()` продолжает сохранённую задачу, `cancel()` останавливает её исполнение. Внешние действия требуют `approval_handler`; CLI запрашивает буквальное `yes`, а без терминала отказывает.

Python API принимает внешнюю числовую оценку через `supervisor_feedback(SupervisorFeedback(value=-2, comment="Причина"), source_id="feedback-1", task_id=...)`; `SupervisorFeedback` экспортируется из `evertree`. Диапазон — от −5 до +5; комментарий сохраняется с исходным наблюдением. Оценка сама по себе не запускает обучение. `save_prediction()` связывает исходный `TraceOutputRef` с семантическим target и контекстом, а Program `PredictionEvaluator` сопоставляет его с сохранёнными наблюдениями. Для составных наблюдений `observe(..., projections=..., context=...)` задаёт пути к отдельным значениям без копирования исходного payload.

Сознание само выбирает конечный бюджет задачи и долю дополнительного улучшения, сохраняя весь накопленный расход при пересмотре. Развитие навыка, необходимое для текущего запроса, использует основной бюджет; дополнительная работа ради будущей пользы требует выделенной доли. Ожидание подтверждения пользователя исключается из `active_time_minutes`. Технические таймауты вызовов действуют отдельно. `run --max-minutes N` задаёт пользовательский предел. Первоначальный разбор ограничен одним вызовом модели и техническим таймаутом пять минут.

Programs работают из неизменяемого commit в AppContainer без сетевых capabilities; Job Object владеет деревом процессов. Доступ к графу, памяти, модели и действиям проходит через проверяемый JSON IPC. Новый код разрабатывается в отдельном candidate checkout. Принятие требует независимого dataset, обязательных проверок, улучшения относительно baseline и явного `EvaluationChoice`. Недостаток evidence оставляет candidate неактивным. Разработчик связывает независимые проверки через `datasets.create()` и `bind_evaluation()`; агент не может подменить скрытые исходы собственными ожидаемыми ответами.

Для написания кода SDK использует официальный Codex `exec-server`, запущенный в собственном AppContainer EverTree. Его команды и файловые инструменты получают доступ к выбранной рабочей области; авторизация модели остаётся в доверенном процессе SDK. Python-мост на `websockets` связывает SDK и stdio сервера через loopback WebSocket с отдельным секретным токеном на каждый запуск. Изоляция исполнения не требует установки elevated Windows sandbox Codex или изменения его глобальных ACL. Расширение прав native-инструментов отклоняется; внешние действия проходят отдельный approval ядра.

Backup сохраняет граф, память, задачи, параметры, ledger, версии зависимостей, Git-код, файлы рабочих областей задач и SQLite DBOS вместе. Проверка необходимости backup выполняется каждые пять минут; копирование происходит только на согласованной границе. Сохраняются два последних завершённых комплекта. Ошибка автоматического backup публикуется как `maintenance_error` и не останавливает очередь задач. После остановки открытые задачи продолжаются явно через `tasks resume`. Восстановление гарантируется до последнего завершённого backup; скрытые внутренние операции Codex не объявляются воспроизводимыми. Неизвестный исход внешнего действия требует сверки, а не автоматического повтора.

В комплект также входят исходники установленного Python-пакета EverTree, их SHA256-манифест, точная версия Python и зафиксированные версии всех runtime-зависимостей, включая Codex SDK/CLI и `websockets`. Бинарные пакеты зависимостей не архивируются. Для restore требуется заранее установить идентичный runtime; несовпадение кода, Python или пакетов останавливает восстановление до замены состояния. Backup не перезаписывает доверенное ядро автоматически.

```powershell
uv run pytest -q
uv run ruff check src tests
uv run python -m evertree.demo --home C:\agents\demo
```

Основной набор тестов работает без LLM и включает native Windows isolation. Демонстрация с fake provider проходит создание, проверку и активацию Program, исправление по новому dataset и использование после перезапуска. Для отдельной живой проверки SDK см. [карту реализации](docs/implementation-v1.md).

[Архитектура](docs/architecture/Overview.md) · [Репозиторий](docs/repository-layout.md) · [Реализация и проверки](docs/implementation-v1.md)
