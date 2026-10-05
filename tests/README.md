# Tests

[Каталог сценариев желаемого поведения](../docs/behavioral-test-cases.md) — простые acceptance-кейсы по архитектуре с критериями приёмки и задействованными подсистемами.

Тесты используют pytest. Полный набор:

```sh
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Тесты самого EverTree работают без LLM; на Windows полный набор включает изоляцию AppContainer. Живые SDK-проверки включаются отдельно через `EVERTREE_CODEX_INTEGRATION=1`.

Для тестов создаваемых агентом Programs действует отдельный контракт: committed `tests/test_*.py` с `unittest.TestCase`. Core запускает их в sandbox перед принятием кандидата; этот каталог проверяет ядро EverTree.

Все сохранённые поведенческие проверки каталога, включая варианты граничных условий, можно запустить в PowerShell:

```powershell
$behavioralTests = @(Get-ChildItem -LiteralPath tests -Filter 'test_behavioral_*.py' | ForEach-Object FullName)
uv run pytest $behavioralTests -q
```

Они используют реальные хранилища, EverTree, lifecycle и DBOS. Там, где важны решения внешней модели, `ScriptedProvider` задаёт ответы и кандидатов; он не доказывает способность LLM самостоятельно обнаруживать закономерности. Для проверки оркестрации используется явно внедрённый `TestProcess`; это не проверка Windows AppContainer и не изменение изоляции рабочего runtime. Новые тесты не скрывают отсутствующие возможности через `skip` или `xfail`.

## Покрытие каталога

«Контракт» означает, что проверяется существующая часть сценария; недостающие шаги указаны явно. Несколько вариантов одного ID могут соответствовать нескольким pytest cases. Число запущенных тестов не равно числу полностью реализованных строк каталога.

| Сценарии | Сохранённые проверки | Границы |
| --- | --- | --- |
| MEM-01…04, MEM-09, MEM-10, MEM-12 | [test_behavioral_memory.py](test_behavioral_memory.py) | Реальные retention, compaction, provenance, восстановление защиты, структурная валидация и retrieval. |
| MEM-05 | [test_behavioral_memory.py](test_behavioral_memory.py) | Контракт: предложение сохраняет заданные частоты. Сам агрегатор частот ещё отсутствует. |
| MEM-06 | [test_behavioral_memory.py](test_behavioral_memory.py) | Контракт: retrieval и выбор replay не создают копий источников. Подсчёт событий и распознавание пересказов не реализованы. |
| MEM-07, MEM-13 | Пока нет | Отсутствуют API объединения частот с неизвестным пересечением и кэш active_state. |
| MEM-08 | [test_behavioral_beliefs.py](test_behavioral_beliefs.py) | Реальные consolidation и retract сравниваются с несжатым контрольным состоянием. |
| MEM-11 | [test_behavioral_memory.py](test_behavioral_memory.py) | Контракт: независимые причины retention. Нет связанного lifecycle удаления Dataset и его требований хранения. |
| MEM-14 | [test_behavioral_memory.py](test_behavioral_memory.py) | Контракт: отдельный replay trace, provenance и запрет live-действия; нет полной оркестрации ReplayTask/Episode. |
| BEL-01…08, BEL-11…14, BEL-18 | [test_behavioral_beliefs.py](test_behavioral_beliefs.py) | Реальная арифметика, зависимости, scope, prior и консолидация; likelihood-модели заданы условиями теста. |
| BEL-08: граница Program → core | [test_behavioral_control.py](test_behavioral_control.py) | Сохранённое наблюдение и флаг от Program не подтверждают её модель likelihoods; действует общий предел неподтверждённого влияния. |
| BEL-09, BEL-10 | [test_behavioral_beliefs.py](test_behavioral_beliefs.py) | Контракт: пересчёт, immutable assignments и current mapping. Автоматического TraceEvent для revise/retract пока нет. |
| BEL-15 | [test_behavioral_beliefs.py](test_behavioral_beliefs.py) | Контракт: сохранение гипотетических условий PropertyReading. Произвольная цепочка условного вывода не проверяется. |
| BEL-16, BEL-17 | Пока нет | Нет unresolved assessment без готовых likelihoods, привязки evidence к версии observation model и invalidation/reassessment чтения. |
| BEL-19 | [test_behavioral_beliefs.py](test_behavioral_beliefs.py) | Контракт supplied-likelihood updater; самостоятельная оценка и интеграция SourceReliability отсутствуют. |
| BEL-20 | [test_behavioral_beliefs.py](test_behavioral_beliefs.py) | Контракт: прежняя identity scope не принимает другие альтернативы; новый scope не получает evidence автоматически. Автоматической structural revision нет. |
| LRN-01, LRN-02 | [test_behavioral_generalization.py](test_behavioral_generalization.py) | Проверка и выбор готового общего кандидата, сохранение исключения. Для LRN-01 используется заданная метрика числа реализаций тарифа; автоматический синтез общего механизма и объединение двух графовых моделей не проверяются. |
| LRN-04, LRN-08 | [test_behavioral_generalization.py](test_behavioral_generalization.py) | Контракт Reflection: предложение с источниками не подтверждает гипотезу и не переписывает принцип. Автоматическая материализация Note/Claim и пересмотр его scope отсутствуют. |
| LRN-05, LRN-07 | [test_behavioral_generalization.py](test_behavioral_generalization.py) | Независимая проверка готового парсера, lifecycle-активация и реальный запуск принятой версии с новым входом. Автоматический поиск исправления и семантический выбор обработчика новой Task не проверяются. |
| LRN-06 | [test_behavioral_generalization.py](test_behavioral_generalization.py) | По заданному аудируемому trace после сжатия восстанавливаются сбои, гипотеза, проверки и активированная revision. |
| LRN-03, LRN-10…17 | [test_behavioral_learning.py](test_behavioral_learning.py) | Реальные shared bindings, credit, блокировки, идемпотентность, коррекция и откат транзакций. |
| LRN-09 | [test_behavioral_evaluation.py](test_behavioral_evaluation.py) | Независимость источников/нарезок, сокрытие исхода до прогноза и проверка доступности holdout через начальную память. |
| LRN-18 | Future, автотеста нет | Ассоциативная подсистема явно отнесена документацией к future. |
| SEM-01 | Пока нет | Нет автоматической семантической канонизации синонимов; точный поиск по имени её не заменяет. |
| SEM-02…05 | [test_behavioral_semantics.py](test_behavioral_semantics.py), [test_behavioral_control.py](test_behavioral_control.py) | Реальные views, кратность, UNKNOWN, исторические snapshots и временные границы belief; восстановление reader после backup. |
| COG-01, COG-02 | [test_behavioral_tasks.py](test_behavioral_tasks.py), [test_behavioral_runtime.py](test_behavioral_runtime.py) | Оркестрация с заданными внешними решениями: требования, provenance, исправление ответа, уточнение той же Task и Unicode через worker/replay. |
| COG-03, COG-04 | [test_behavioral_control.py](test_behavioral_control.py) | Gate последовательного исполнения, сохранение прогресса/расходов и учёт самоулучшения внутри общего бюджета. |
| COG-05 | [test_behavioral_tasks.py](test_behavioral_tasks.py) | Контракт mandatory-check gate и обработка отрицательного verifier. Нет автоматического реестра произвольных обязательных проверок задачи; ложное `verified=True` модели этим не исключается. |
| ACT-01…03 | Пока нет | Нет ActionDistribution, исполнителя policy или planner оценки продолжений. Bootstrap Planning возвращает предложение плана и не заменяет эти контракты. |
| ACT-04, ACT-05 | [test_behavioral_control.py](test_behavioral_control.py) | Реальный ActionGateway: неизменные команды текущего списка и accepted отдельно от Observation/успеха. |
| ACT-06 | [test_behavioral_control.py](test_behavioral_control.py) | Контракт: unknown не вызывает повторной отправки; pending/reconcile сохраняются через snapshot. Автоматическое получение подтверждения у источника не проверяется. |
| EVA-01…04 | [test_behavioral_evaluation.py](test_behavioral_evaluation.py) | Статусы, proper score, frozen evaluation, скрытые исходы и отказ активации без независимых оснований. |
| INT-01 | [test_behavioral_memory.py](test_behavioral_memory.py) | Контракт: урок и основания доступны после сжатия. Последующий выбор плана не проверяется. |
| INT-02 | [test_behavioral_generalization.py](test_behavioral_generalization.py) | Контракт: реальный estimator обучается, проверяется на независимых примерах и после сжатия/восстановления даёт `7 → 8`. Полная оркестрация обучения, активации Program и её выбора следующей Task не проверяется. |
| INT-03, INT-04 | [test_behavioral_beliefs.py](test_behavioral_beliefs.py) | Контракт: актуальное чтение после retract и разделение вероятности поведения/убеждения в trace. Исполняемая policy и пересмотр плана отсутствуют. |
| INT-05 | [test_behavioral_learning.py](test_behavioral_learning.py) | Контракт: комментарий хранится отдельно от численной оценки, заданный target получает credit либо UnresolvedCredit. Самостоятельный выбор причины по тексту не проверяется. |

## Ограничение текущего прогона

Завершающий прогон 4 октября 2026 года: **254 passed, 7 deselected** — все 105 новых поведенческих вариантов вместе с регрессиями изменённых модулей. Команда этого прогона:

```powershell
$behavioralTests = @(Get-ChildItem -LiteralPath tests -Filter 'test_behavioral_*.py' | ForEach-Object FullName)
$regressionTests = @('tests/test_graph.py', 'tests/test_attribution.py', 'tests/test_beliefs.py', 'tests/test_memory.py', 'tests/test_actions.py', 'tests/test_cognition_learning.py', 'tests/test_bootstrap.py', 'tests/test_experiments.py', 'tests/test_runtime.py', 'tests/test_application_guards.py', 'tests/test_prediction_flow.py', 'tests/test_lifecycle_backup.py')
uv run pytest @behavioralTests @regressionTests -q -k 'not native and not appcontainer'
```

`ruff check`, `ruff format --check` и `git diff --check` также прошли. В карте выше все 77 сценариев: у 68 есть полная либо частичная автоматическая проверка, у 9 — пока нет.

Полный нативный набор требует места для частных копий Python и зависимостей. При работе над каталогом его исходный запуск остановлен после `WinError 112` (недостаточно места). Для проверки остальных контрактов использован отдельный набор без нативных копий и живых SDK-вызовов:

```powershell
uv run pytest -q --ignore=tests/test_application.py --ignore=tests/test_demo.py --ignore=tests/test_native_executor_security.py --ignore=tests/test_codex_integration.py -k 'not native and not appcontainer'
```

Успех этого набора не подтверждает прохождение исключённых нативных и живых SDK-проверок. Обычная команда полного прогона и существующие нативные тесты сохранены.
