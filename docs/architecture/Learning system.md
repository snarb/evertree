---
status: draft
target_version: next
---
## Intro

#concept #topic_intro

(def_id:: et.LearningSystem)

> [!definition]  
> **Learning System** — система, которая оркестрирует обработку оценённого опыта, владеет назначением learning credit и маршрутизацией parameter updates и вызывает Belief System, когда требуется assessment epistemic evidence.
> ^def-LearningSystem


---

## Core

#topic_core

Программы EverTree могут предсказывать состояния, переходы и сигналы по отдельным каналам. Новые [[Memory#^def-Observation|наблюдения]] поступают через [[Process Plane/Program Layer#^process-observation-input|программу выбранного процесса]]. [[Process Plane/Action Selection and Planning#Управление процессом и развитие навыка|`TaskManagingProgram`]], включая её специализаци, например `SkillDevelopmentProgram`, организует нужные Evaluation, выбирает опыт, цель и момент обучения в рамках текущей `Task`; эту работу можно делегировать подпрограмме. Обучение может запускаться по наблюдению, batch, эпизоду или оценённому результату Task либо процесса, отдельно от вызова политики для выбора действия.

[[#^def-PredictionEvaluator|`PredictionEvaluator`]] находит прогнозы для выбранных [[Process Plane/Program Layer#^def-PredictionTarget|PredictionTarget]] и оценивает их по наблюдениям. Для известного target без назначенного прогноза фиксируется [[#LearningCredit and UnresolvedCredit|UnresolvedCredit]]. `LearningCoordinator` организует обработку выбранного для обучения опыта: оценку epistemic evidence, назначение credit выбранным [[#^def-LearningTarget|LearningTarget]] и подготовку обновлений. Наблюдение может быть основанием для beliefs без проверяемого прогноза; выполнение Evaluation само по себе не означает training.

Наблюдения можно накапливать и проверять за окно или эпизод. Вычислять [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] для каждого отдельного исхода не требуется.

Основной поток обучения по опыту:

```text
В контексте Task:
ProgramRun → prediction / epistemic Profile / OutcomeProfile / expected signals
Observations + контекст процесса + метрики → PredictionEvaluator
├─ найденные соответствия → evaluate_prediction → EvaluationResult для каждого прогноза
└─ наблюдения без прогноза → handle_unmatched_observations
   →  PredictionTarget's → CreditAssignmentProgram
     → UnresolvedCredit(target, missing_prediction) → сохранить → Attention
   → другие несопоставленные случаи → учесть прежние решения / разобрать

Выбранные observations / Evaluation прогнозов, результатов Task или процесса → LearningCoordinator
├─ Belief System
│  → EvidenceAssessmentProgram
│  → EvidenceAssignment[]
│  → Evidence lifecycle / belief recomputation
│
└─ LearningSignal, только для EvaluatedResult
   → CreditAssignmentProgram: назначить credit LearningTarget в контексте опыта
   → CreditAssignmentResult[]
      ├─ LearningCredit(target, signal)
      │  → UpdatePlanner: выбрать конкретный estimator или параметры Program
      │  → PreparedUpdate
      │  → UpdateTransactionManager.apply
      │  → UpdateDispatcher
      │  → estimator / optimizer по контракту состояния
      │  → atomic commit: updated parametric state + UpdateReceipt
      │
      └─ UnresolvedCredit(target, ambiguous_attribution)
         → сохранить для анализа
         → не обновлять parameters
```

Learning System владеет `LearningCoordinator`, `CreditAssignmentProgram`, `UpdatePlanner`, [[#^def-UpdateTransactionManager|`UpdateTransactionManager`]] и `UpdateDispatcher`. Belief System владеет [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]], [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]] и его lifecycle. Определения сигналов находятся в `Evaluative-Control System`; контракт Belief System — в [[Uncertainty and Belief Tracking in the World Model]].

В схемах потока показаны payload из `ProgramResult.result` по [[Process Plane/Program Layer#^def-ProgramResult|общему контракту Program]]. Поле [[Process Plane/Program Layer#^program-feedback|`feedback`]] само по себе не создаёт `LearningSignal`.

### Типы обновлений (во время обучения)

[[#^def-LearningSystem|Learning System]] различает:

```text
belief update
→ Strength, Support и Profile;

parameter update
→ параметры существующего predictor-а или policy;

structural revision
→ изменение semantics, contracts или структуры Program.
```

Внутри parameter update механизм задаётся контрактом обучаемого компонента:

```text
frequency / categorical process value
→ FrequencyEstimator с counts / Beta / Dirichlet state;

numeric / distribution model value
→ model-specific estimator с sufficient statistics;

policy parameters
→ policy-specific optimizer.
```

Belief update и предусмотренный parameter update, включая параметры политики, могут выполняться автоматически. Для конкурирующих альтернатив belief update вычисляет [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]. Structural revision передаётся в общий lifecycle программ и гипотез.

У политики могут обучаться параметры стратегии, оценщик полезности или другие явно объявленные части. [[#LearningCredit and UnresolvedCredit|LearningCredit]] относится к выбранному [[#^def-LearningTarget|LearningTarget]]; `UpdatePlanner` по контексту и цели обучения выбирает параметры для обновления, а способ обновления задаёт контракт optimizer-а. Сам вызов политики для выбора действия не запускает обучение неявно; отдельный метод `learn()` у каждой политики не требуется.

### Выбор обучаемых компонентов и режима обучения

При создании или пересмотре программы [[Cognition and Attention#^def-Consciousness|сознание]] в контексте `Task` выбирает, какие её части будут [[Process Plane/Program Layer#Обучаемые и фиксированные компоненты|обучаемыми, а какие — фиксированными]]. Эти решения можно делегировать программе в установленных сознанием пределах.

Основное правило: выбирать простейшую модель, достаточную для нужных решений, следуя [[Process Plane/Program Layer#Обобщение и сжатие моделей|стратегии обобщения и сжатия]]. Простота учитывает число параметров, стоимость входных данных, прогнозирования, обучения, проверки и хранения. Существующая общая модель, фиксированное правило или оценка могут быть дешевле нового обучаемого компонента. Пригодность обязательна: модель должна учитывать допустимые исходы и существенные для задачи зависимости. Перебирать заведомо неподходящие простые модели не требуется.

#### Правила выбора для сознания

Сознание решает следующие вопросы по мере необходимости, начиная с минимума для текущей задачи. Не требуется заранее определять все детали: можно использовать подходящие готовые механизмы и настройки по умолчанию, уточняя решения по опыту в пределах бюджета задачи.

- **Назначение:** какой [[Process Plane/Program Layer#^def-PredictionTarget|PredictionTarget]] и в какой точке программы предсказывается, для какого решения; наблюдаемый исход, условия применения, доступные признаки и история, горизонт и единицы измерения.
- **Представление и обучение:** что означает выход, какой estimator или optimizer его обновляет, предпосылки алгоритма, начальное состояние и согласованные с целью метрики. Проверяется возможность использовать существующую модель, общие знания или подходящий [[#^def-TrainingDataset|TrainingDataset]].
- **Опыт:** какие наблюдения допустимы, как учитываются их зависимости и отбор; какие исходы действительно наблюдаемы и как обрабатываются исправления и [[#PreparedUpdate, UpdateTransactionManager and UpdateDispatcher|повторный учёт]].
- **Режим:** обучение по наблюдению, batch или эпизоду, условия запуска и размер batch; накопление статистики либо явно выбранное правило адаптации к изменению процесса.
- **Проверка:** базовая модель для сравнения, нужный тип переноса на новые случаи, критерии достаточности и условия пересмотра по [[Process Plane/Program Evaluation and Testing#^prediction-quality-protocol|протоколу проверки качества]].
- **Ресурсы и память:** пределы затрат на получение данных, прогнозирование, обновления и проверки; достаточные статистики, выбранные примеры или история в артефакте. Сохранённых данных и provenance должно хватать для алгоритма, проверок и поддерживаемого пересчёта состояния.

Для конкретного прогноза должны быть определены смысл выхода и условия; для обновления — совместимые алгоритм, данные и состояние. Режим, размер batch, бюджет и проверки могут выбираться и меняться во время работы, в том числе автоматически в делегированных пределах. Изменение кода, семантики или контракта проходит через [[Process Plane/Program Lifecycle and Evolution#Общий lifecycle Program|Program Lifecycle]]; изменение настроек в пределах возможностей действующей программы этого не требует.

[[Process Plane/Program Layer#^granularity-adaptation|Обучаемый выбор подготовки и гранулярности]] подчиняется тем же правилам. Границы исходных блоков не задают автоматически точки прогнозирования и обновления; их связь и ограничения доступа к будущему описаны в [[Process Plane/Program Layer#^granularity-learning-sequence|подготовке последовательного опыта]].

#### Представление прогноза и цель обучения

Когда польза для решений оправдывает затраты, предпочтительно обучать распределение возможных исходов при заданных условиях и получать нужный конкретный прогноз из него. Это особенно полезно для оценки риска и получения нескольких характеристик одного процесса. Подходящее уже имеющееся распределение переиспользуется. Если для задачи достаточно одной характеристики, а моделирование распределения не даёт оправданного выигрыша, допустим её прямой прогноз. [[Process Plane/Program Evaluation and Testing#^prediction-quality-metrics|Функция потерь]] выбирается по смыслу этого выхода:

| Нужный прогноз | Простой начальный механизм | Критерий прогнозного качества |
|---|---|---|
| Вероятность события или категории | Сглаженные counts, Beta / Dirichlet estimator | Brier или log loss |
| Условное среднее | Накопитель среднего, таблица или регрессия | Квадратичная потеря |
| Медиана или заданный квантиль | Соответствующий estimator или регрессия | Абсолютная или квантильная потеря |
| Числовое распределение | Подходящее простое семейство распределений | Log loss или CRPS при их применимости |
| Связанные исходы или траектория | Модель существенных зависимостей | Метрика совместного прогноза и нужных горизонтов |

Если пригодное распределение уже имеется, среднее, медиану, квантили и вероятности событий обычно получают из него; отдельное обучение каждой характеристики требует обоснования. Например, для исходов `10` с вероятностью `0.9` и `30` с вероятностью `0.1` среднее равно `12`, медиана — `10`: это разные ответы одной модели. Прикладная точность используемого ответа проверяется отдельно от качества распределения.

Статистика без признаков, оценки и регрессия используют общий [[Process Plane/Program Layer#Estimator|интерфейс estimator-а]]. Обновление его достаточных статистик — parameter learning; отдельный алгоритм обучения для каждой точки программы не требуется. Сводка исторических значений сама по себе не задаёт прогноз: нужны выбранная характеристика, горизонт и условия применимости.

Для вероятностного прогноза используется подходящая strictly proper loss: её смысл и пределы гарантии определены в [[Process Plane/Program Evaluation and Testing#^prediction-quality-metrics|метриках качества]]. Обновление не обязано быть градиентным: накопление достаточных статистик и байесовское обновление также допустимы. Если optimizer использует другую внутреннюю цель, контракт объясняет её связь с обучаемым выходом; результат проверяется по объявленным метрикам. Цель policy optimizer-а задаётся последствиями решений в контексте задачи, а не автоматически loss прогнозной модели.

#### Данные и автоматические обновления

Обучающий опыт должен соответствовать смыслу прогноза: величине и её характеристике, горизонту, доступной при прогнозе информации и условиям, включая политику продолжения агента и поведение других участников. Изменение этих условий требует проверки совместимости опыта; совпадения PredictionTarget или anchor-а недостаточно.

Отбор только ошибок, проигрышей или неожиданных случаев может исказить наблюдаемые частоты. Если отбор меняет целевое распределение, для оценки исходного процесса требуется поддерживаемая коррекция с выполненными предпосылками; если намеренно оценивается другое распределение, это явно указывается. Важность уже случившегося исхода сама по себе не даёт основания увеличивать его вес при оценке вероятностей. Ненаблюдавшийся исход не считается нулём или неудачей; последствия невыбранного действия не становятся наблюдением о нём.

Предсказательная способность проверяется по прогнозу, сохранённому до исхода, либо в проверочном прогоне на материале из памяти. Во втором случае исход скрыт от модели и не использован при подгонке проверяемого прогноза. После оценки этот исход можно использовать для обучения; повторное обучение на нём не становится новой независимой проверкой качества. Редкость события сама по себе не означает ошибку источника. Ограничение влияния больших отклонений должно соответствовать целевой характеристике и предпосылкам estimator-а: оно может быть оправдано и для достоверных данных с тяжёлыми хвостами. Признание исхода недостоверным требует отдельного основания; модель не должна систематически игнорировать реальные редкие исходы.

Для устойчивого процесса можно накапливать достаточные статистики. Для меняющегося процесса выбираются окно, забывание или модель динамики с подходящими предпосылками. Программа процесса может сама отслеживать изменение условий и адаптировать модель. Пересчёт нормы необычности не заменяет изменение прогнозной модели. Алгоритм конкретного updater-а определяет величину обновления и допустимые правила забывания и взвешивания наблюдений.

В стандартном пути предусмотренные parameter updates выполняются автоматически через [[#LearningCoordinator|`LearningCoordinator`]], без нового сознательного выбора алгоритма на каждом примере. Он организует разрешённые обновления существующих компонентов; состав предикторов через этот путь не меняется. Переиспользуемый estimator может иметь отдельное обученное состояние для разных процессов. Общее состояние выбирается только для одной и той же зависимости в совместимых условиях. Отдельный путь для специализированного trainer-а описан [[#Специализированное обучение|ниже]].

#### Начальное состояние estimator-а

Встроенные estimator-ы начинают с объявленного начального прогноза — prior-оценки — либо переиспользуют подходящее обученное состояние. Новый бакет использует объявленный prior или общий estimator. Prior не является наблюдением и не увеличивает число реальных примеров. Начальный прогноз можно оценить по первому фактическому исходу и обновить компонент через обычный learning pipeline; его пригодность для действия проверяется отдельно от возможности обучения.

Подготовка и повторное использование начальных моделей следуют [[Process Plane/Program Lifecycle and Evolution#Подготовка начальных моделей|общему Program Lifecycle]]. Отсутствие обучающих примеров не требует LLM-вызова при каждом прогнозе.

Если осмысленный начальный прогноз для выбранного target недоступен, создаётся [[#LearningCredit and UnresolvedCredit|UnresolvedCredit(target, missing_prediction)]]; опыт сохраняется для выбора или пересмотра модели. Отсутствие прогноза не заменяется фиктивной метрикой и не создаёт `LearningSignal`. Обучение по накопленным данным следует [[#TrainingDataset|общему пути]], а изменение модели — [[Process Plane/Program Lifecycle and Evolution#Общий lifecycle Program|Program Lifecycle]].

#### Бюджет и пересмотр

Ресурсы выделяются по ожидаемой пользе улучшения будущих решений, включая перенос на другие задачи, и цене ошибок. Частота использования — один фактор, а не определение важности: редкое дорогое решение может оправдывать тщательную модель, а частый хорошо изученный процесс — почти не требовать дальнейшего обучения. Для редкой малозначимой задачи может хватать простых правил и имеющихся знаний.

Польза сопоставляется с полной стоимостью получения данных, обучения, проверки, будущего применения и хранения в пределах [[Cognition and Attention#Бюджеты выполнения|бюджетов Task]]. Оценка этой пользы сама ограничена бюджетом; точный расчёт перед каждым update не требуется. Важность влияет на бюджет и требования к качеству, но не повышает достоверность или статистический вес наблюдения.

Усложнение принимается при подтверждённом на новых случаях практически значимом выигрыше, оправдывающем дополнительные затраты. Обучение можно приостановить, если достигнутого качества достаточно или дальнейшие затраты не оправданы; отсутствие выявленных ошибок при малом опыте не подтверждает качество модели.

При рефлексии, сознательном анализе, структурной ревизии, существенных ошибках, неожиданных сигналах или изменении значимости процесса сознание может пересмотреть состав компонентов, режим и объём обучения, включая его возобновление. Отсутствие прогноза тоже может стать основанием для такого разбора — численный `prediction_unexpectedness` для этого не требуется. Высокий сигнал сам по себе не оправдывает неограниченные затраты. Отдельная периодическая проверка каждого приостановленного компонента не обязательна; нужные проверки выбираются для конкретного процесса.

### TrainingDataset

(def_id:: entity.TrainingDataset)

> [!definition]
> **TrainingDataset** — [[Datasets#^def-Dataset|Dataset]] для обучения: его версия фиксирует допустимый опыт и правила подготовки данных для совместимого estimator-а или optimizer-а.
> ^def-TrainingDataset

Набор позволяет повторно обучать модель или обучить нового кандидата на накопленном опыте. Для обновления по наблюдению, batch или эпизоду сохраняемый dataset необязателен. Подготовка данных соответствует контракту модели и [[Datasets|общим правилам datasets]].

В стандартном пути при обучении нового кандидата оценивается его собственный запуск на выбранном опыте. Полученные trace и [[Process Plane/Program Evaluation and Testing#EvaluationResult|EvaluatedResult]] позволяют [[#LearningCoordinator|общему learning pipeline]] назначить credit соответствующим targets и обучать кандидата. Credit прежней реализации не переносится автоматически на новую по одному совпадению target; повторные проходы соблюдают [[#PreparedUpdate, UpdateTransactionManager and UpdateDispatcher|правила учёта опыта]].

Чтобы повторить обучение, trace сохраняет связь с версиями данных, подготовки и кода, начальным и полученным состоянием, настройками updater-а и seed, если используется случайность. Перенос на новые случаи проверяется на [[Datasets#Границы обучения и проверки|независимых данных]].

### LearningCoordinator

`LearningCoordinator` — техническая дочерняя программа в контексте `Task`. Вызывающая программа передаёт выбранный опыт и цель обучения, связанную с целью задачи; coordinator не выбирает задачу, не запускает тесты и не решает самостоятельно, какие Evaluation проводить. Нужные проверки выполняются до передачи их результатов на обучение.

Для observations и результатов проверок coordinator вызывает [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]], когда они могут дать epistemic evidence. Эта ветвь не требует проверяемого прогноза. Для выбранного на обучение `EvaluatedResult` с outcome, metrics и восстановимым контекстом coordinator создаёт [[#^def-LearningSignal|LearningSignal]] и вызывает `CreditAssignmentProgram` для соответствующих [[#^def-LearningTarget|LearningTarget]]. Оцениваться может прогноз или результат Task либо процесса. Уже выполненная проверка повторно не запускается. [[#PredictionEvaluator|Ветка отсутствующего прогноза]] создаёт `UnresolvedCredit` отдельно, без фиктивной Evaluation и без `LearningSignal` для этой прогнозной проверки.

Если соответствие outcome target-у и привязка обучения к estimator-у или параметрам программы заданы контрактом, credit assignment и подготовка update выполняются детерминированно, в том числе для batch. Так стандартный pipeline обновляет средние, частоты и статистики bucket-ов без вызова LLM на каждом примере. Вызов `predict(inputs)` и запись значения в trace сами по себе не разрешают update. Неоднозначное назначение credit и невозможность подготовить update различаются по правилам ниже.

`EvidenceAssessmentProgram` и `CreditAssignmentProgram` являются независимыми ветвями и не вызывают друг друга. Вызов `EvidenceAssessmentProgram` не передаёт ownership Learning System. `LearningCoordinator` сам не оценивает evidence, не назначает learning credit и не изменяет parameters.

Связанный опыт передаётся в assessment общим пакетом по [[Uncertainty and Belief Tracking in the World Model#Жизненный цикл assessment|правилам объединения вызовов и бюджета]]. Сама модель evidence и модели ошибок источников обучаются через обычные credit и parameter updates по [[Uncertainty and Belief Tracking in the World Model#Обучение модели evidence|независимо разрешённым случаям]]; отдельного пути самоподтверждения beliefs нет.

`UpdatePlanner` по готовому `LearningCredit` и объявленным привязкам программы выбирает estimator или параметры для обновления, извлекает исходные входы и outcomes из evaluation и provenance. [[#^def-UpdateTransactionManager|UpdateTransactionManager.apply]] выполняет подготовленное обновление в общей транзакции; `UpdateDispatcher` выбирает updater по контракту выбранной реализации. Updater вычисляет новое состояние; transaction manager сохраняет его вместе с `UpdateReceipt`.

### Специализированное обучение

Для узких задач `SkillDevelopmentProgram` может вызвать специализированную обучающую подпрограмму, например CFR / self-play на NumPy или CUDA через Python. Это дополнительный путь(исключение которое должно быть строго оправдано) вне стандартного `LearningCoordinator` pipeline: подпрограмма управляет внутренними итерациями кастомного пайплайна обучения, рабочим состоянием и checkpoints без отдельного `LearningCredit` на каждый шаг. Основной подход EverTree — развитие и переиспользование программ и знаний и обучение их через LearningCoordinator. Специальное обучение кастомного бекенда (например на безе нейронной сети) может быть дорогим, а результат — трудно интерпретируемым. Этот подход может помочь решить локальную задачу где нужно специальная формуа обучения, но это обучение скорей всего не может улучить агента, не поможет генерализоваться на другие процессы.  Успех в узкой задаче сам по себе не подтверждает перенос на другие задачи; выигрыш должен оправдывать эти ограничения.

Checkpoints для продолжения обучения и экспортированная стратегия сохраняются как версионируемые [[Core data structures#^def-Artifact|Git Artifacts]], при необходимости через Git LFS, с provenance данных, кода и настроек. Кандидат проходит отдельную [[Process Plane/Program Evaluation and Testing#EvaluationTestManager|Evaluation]] перед применением. Изменение кода или используемого программой версионируемого артефакта проходит через [[Process Plane/Program Lifecycle and Evolution#Общий lifecycle Program|Program Lifecycle]]; trainer не перезаписывает активное состояние estimator-а или параметры Program в обход стандартного механизма обновлений.

---

## Observable and latent claims

Прямой [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] вычисляется для observable prediction модели при наличии наблюдений, не выведенных из самого прогноза, и достаточной основы для калибровки. Наблюдения могут зависеть друг от друга; эти зависимости учитываются в проверке.

```
predicted observable state
+ observed state
→ direct prediction_unexpectedness.
```

Latent state не получает direct `prediction_unexpectedness`. Его [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|evidence assessment]] опирается на наблюдаемые последствия и не требует этого сигнала:

```
latent state
→ observable prediction
→ observation
→ evidence assessment
→ indirect upstream evidence.
```

Если обязательный публичный observable prediction отсутствует,  
вызывается structural revision.

Внутренний anchored [[Core data structures#^def-Claim|claim]] может быть проверен напрямую, если для него
появилось independent observation. 

Expected signals являются обычным специальным случаем observable claims; их проверка описана в [[#Expected signal updates]].

---
## Fast learning

Fast learning обрабатывает выбранный для обучения опыт после evaluable event, накопления batch или завершения sub-episode. Parameter updates выполняются по [[#Выбор обучаемых компонентов и режима обучения|выбранному режиму]]; приостановка обучения параметров не запрещает обновление beliefs по новому evidence.

Он затрагивает:

```
observable claims, получившие direct evidence;
latent states и operators, от которых зависели эти claims;
competing alternatives того же CompetitionScope;
Program или policy components, участвовавшие в результате.
```

Высокий [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] — повод исследовать неожиданное расхождение, а не логическое опровержение модели или доказательство смены режима. Вероятный outcome также является evidence и может использоваться для обучения; выбор обучающих наблюдений не ограничивается неожиданными случаями.

Beliefs получают [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|EvidenceAssignment]] через [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|EvidenceAssessmentProgram]]. По `LearningCredit` для [[#^def-LearningTarget|LearningTarget]] подготавливаются разрешённые обновления конкретных реализаций. `UnresolvedCredit` сохраняется без parameter update.

---

## Credit Assignment
#topic_core

Стандартный learning pipeline последовательно отвечает на четыре разных вопроса:

```text
что произошло и как это оценено?
→ LearningSignal;

какому LearningTarget и его применению относится обучающий вклад опыта?
→ LearningCredit;

какой estimator или параметры Program обновить и как подготовить данные?
→ PreparedUpdate;

как безопасно выполнить команду?
→ UpdateTransactionManager;
→ UpdateDispatcher выбирает updater.
```

Если PredictionTarget выбран для прогнозирования в данном контексте, но прогноз отсутствует, создаётся `UnresolvedCredit` с известным target и контекстом случая. Эта ветка не требует `LearningSignal`. Когда credit уже назначен target-у, но подготовить конкретное обновление нельзя, возвращается `UpdateBlocked`.

### LearningSignal

Поля и аргументы learning pipeline содержат объекты по [[Core data structures#Объекты и ссылки|общему правилу объектов и ссылок]].

(def_id:: entity.LearningSignal)
> [!definition]  
> **LearningSignal** — пакет оценённого опыта для одного решения об обучении: observed outcome, выбранные metrics и цель улучшения. Это пакет данных, а не отдельный оценочный канал [[Evaluative-Control System]].
> ^def-LearningSignal

```python
LearningSignal {
  evaluation: <EvaluatedResult>
  outcomes: <NonEmpty[Observation | Outcome]>
  metric_samples: <NonEmpty[MetricSample]>
  objective: <LearningObjective>
}
```

Поля отвечают на простые вопросы:

```text
evaluation
→ полная проверка и её provenance;

outcomes
→ что фактически произошло;

metric_samples
→ как был измерен результат;

objective
→ что именно нужно улучшать.
```

[[#^def-LearningSignal|`LearningSignal`]] создаётся только из `EvaluatedResult`. Все его outcomes и metrics должны относиться к той же evaluation. `NotApplicableResult` и `UnresolvedEvaluationResult` learning signal не создают.

`LearningObjective` связывает смысл цели с metrics и направлением улучшения:

```python
LearningObjective {
  source?: <Criterion | Utility>
  metrics: <NonEmpty[MetricDefinition]>
  direction: "minimize" | "maximize"
}
```

Например, objective может требовать уменьшать среднюю квадратичную ошибку вероятности бинарного исхода `(p - y)²`, где `y ∈ {0, 1}`, или максимизировать долю успешных решений по критериям выбранной Evaluation. [[Attribution Plane#^def-Criterion|`Criterion`]] или `Utility` могут объяснять происхождение цели, но сами по себе не заменяют learning objective.

[[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] — диагностическая оценка, а не цель минимизации или gradient. Updater использует исходные входы и outcomes по контракту estimator-а; его внутренняя цель согласуется со [[#Представление прогноза и цель обучения|смыслом прогноза]]. Улучшение проверяется по [[Process Plane/Program Evaluation and Testing#^prediction-quality-protocol|протоколу качества]]: уменьшение необычности само по себе улучшением не считается.

### LearningCredit and UnresolvedCredit

(def_id:: role.LearningTarget)
> [!definition]
> **LearningTarget** — получатель learning credit: оцениваемая величина или результат, выбранное действие или решение, участвовавший механизм либо использованный вывод. При обучении прогноза эту роль выполняет [[Process Plane/Program Layer#^def-PredictionTarget|PredictionTarget]].
^def-LearningTarget

Эту роль выполняет существующий Concept, Program или Claim; отдельный узел или runtime-класс не требуется.

`CreditAssignmentProgram` назначает credit выбранному `LearningTarget` в конкретном контексте опыта. Для оценённого случая она получает `LearningSignal` и использует связанные traces для поиска получателей credit; для отсутствующего прогноза — известный `PredictionTarget`, контекст поиска и имеющиеся наблюдения без `LearningSignal`. Возвращает `ProgramResult[CreditAssignmentResult[]]`.

```python
CreditAssignmentResult =
  LearningCredit {
    target: <LearningTarget>
    signal: <LearningSignal>
    attribution_weight?: <float in (0, 1]> = 1.0
    resolves?: <UnresolvedCredit>
  }

| UnresolvedCredit {
    target: <LearningTarget>
    observations?: <list[Observation | Outcome]>
    reason: "missing_prediction" | "ambiguous_attribution"
    signal?: <LearningSignal>
    missing_requirements?: <string[]>
}
```

**В обеих ветвях результата target известен.** `reason="missing_prediction"` применим только к `PredictionTarget`, выбранному для прогнозирования в данном контексте, если прогноз не назначен. Он фиксирует пробел в прогнозировании; численная оценка ошибки, `LearningSignal` и parameter update для отсутствующего прогноза не создаются. Наличие прогноза ещё не гарантирует `LearningCredit`: сначала нужны применимая Evaluation и достаточные данные для `LearningSignal`. Для обучения по независимо оценённому результату действия собственный прогноз не требуется.

`context` хранит ссылки на исходный случай и условия поиска, чтобы установить, где именно прогноз отсутствует. В готовом `LearningCredit` контекст восстанавливается из `signal` и provenance работы `CreditAssignmentProgram`: какой target, какое его применение или решение получило credit и по какому оценённому результату. Исходная evaluation сохраняет собственный предмет оценки; назначение credit не переписывает его. Совпадение Concept не объединяет разные случаи и модели.

`LearningSignal`, `LearningCredit` и `UnresolvedCredit` являются immutable [[Memory#^def-OperatorOutput|OperatorOutput]]. Их identity и provenance предоставляет общий runtime; отдельные поля `id` и `created_at` не дублируются.

`attribution_weight` — беззнаковая доля learning signal, назначенная target-у в этом контексте: `1.0` означает полный вклад, `0.3` — 30%. Это не знак ошибки, gradient, parameter delta, вероятность выбора updater-а или мера доказанности причинного влияния. Направление задаёт `LearningObjective`; новое значение параметров вычисляет updater. Способ применения weight задаётся контрактом updater-а.

Если назначение вкладов нескольким targets принято как soft assignment, создаются отдельные `LearningCredit` с явными weights. Если вклад выбранного target пока неоднозначен, создаётся `UnresolvedCredit(reason="ambiguous_attribution")` с исходным signal; параметрическое обновление этого случая откладывается. Неуверенность в причине не заменяется произвольными weights.

`UnresolvedCredit` сохраняет историю. После разрешения случая новый `LearningCredit` может ссылаться на него через `resolves`. Найденный исходный прогноз оценивается обычным способом. Если вместо него создана новая модель, проверяется её собственный запуск: поздний прогноз не выдаётся за существовавший до наблюдения, а подгонка на этом исходе — за независимую проверку.

Адрес изменяемых параметров выбирает [[#PreparedUpdate, UpdateTransactionManager and UpdateDispatcher|UpdatePlanner]] по готовому credit. Неоднозначность этого технического выбора даёт `UpdateBlocked`, а не `UnresolvedCredit`.

`CreditAssignmentProgram` не создаёт [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|EvidenceAssignment]], не выбирает формулу update и не изменяет параметры. Provenance связывает credit с опытом, но сам по себе не доказывает ответственность участвовавших механизмов.

#### Credit по результату Task или процесса
^outcome-credit

Основанием может быть оценённый промежуточный или окончательный результат Task либо процесса: успешность, соблюдение условий, затраты или другое выбранное качество. Результат представлен обычным `Outcome`; критерии, metrics и связь с исполнением сохраняются в `EvaluatedResult`.

Сознание, [[Memory#^def-MemoryConsolidationProgram|консолидация памяти]] и [[Self#От опыта к подтверждённой проблеме|Reflection]] могут выбрать опыт и цель обучения, организовать необходимые проверки и передать результаты `LearningCoordinator`. Credit назначает `CreditAssignmentProgram`.

По traces программа ищет решения, действия, использованные выводы и механизмы, которым может относиться вклад. Например, выбор X вместо обычного Y или вывод о причине затруднения могли изменить ход работы. Объяснение влияния оформляется как [[Core data structures#^def-Claim|Claim]] с основаниями и границами применимости; его достоверность и истинность использованного вывода оцениваются через Belief System отдельно от полезности применения. Успех Task сам по себе не подтверждает ни причинную гипотезу, ни истинность всех использованных выводов.

Наблюдённый результат X не является результатом невыбранного Y. Утверждение о преимуществе X требует сопоставимого опыта, проверки альтернативы или явно обозначенного модельного контрфакта по [[Self#От проблемы к change hypothesis|правилам Self]]. При этом обычное обучение политики по траектории допустимо по контракту optimizer-а без доказательства точного причинного вклада каждого шага.

Если получатель credit ещё не найден, сохраняется вопрос или гипотеза для дальнейшего разбора. Выводы могут сохраняться как знание, а изменение кода или способа решения проходит [[Process Plane/Program Lifecycle and Evolution#Общий lifecycle Program|Program Lifecycle]]. Повторный разбор опыта консолидацией и Reflection соблюдает [[#PreparedUpdate, UpdateTransactionManager and UpdateDispatcher|общие правила учёта обучающего вклада]].

### PreparedUpdate, UpdateTransactionManager and UpdateDispatcher

`UpdatePlanner` выбирает конкретный estimator или параметры Program по `LearningTarget`, атрибутированному применению, исходному контексту и `LearningObjective`. Он использует объявленные в программе привязки обучения и provenance credit и evaluation; совпадение target само по себе не разрешает обновлять все реализации этого Concept. Затем проверяет контракт выбранного состояния и готовит update:

```python
UpdatePlanner.prepare(
  credit: LearningCredit
) -> UpdatePlanningResult

UpdatePlanningResult =
  PreparedUpdate {
    source_credit: <LearningCredit>
    state: <reference to estimator state or Program parameters>
    updater_input: <input for the selected updater>
  }

| UpdateBlocked {
    source_credit: <LearningCredit>
    reason: "no_learning_binding"
          | "ambiguous_learning_binding"
          | "incompatible_updater_contract"
          | "unsupported_signal"
          | "already_accounted"
  }
```

Назначение полей:

```text
source_credit
→ почему этот update разрешён;

state
→ ссылка на состояние estimator-а или параметры Program, которые обновляются;

updater_input
→ опыт и настройки обновления в формате конкретного estimator-а или optimizer-а.
```

Например, credit для `NetChipChange` при цели оценивать выигрыш может использоваться для обучения estimator-а, а при цели улучшать выбор действий — для обучения параметров политики. Привязка должна явно задавать соответствующий update. Политике не обязателен собственный прогноз: достаточно применимой оценки результатов её действий. Отсутствие требуемого прогноза остаётся отдельным `UnresolvedCredit` и не отменяет такую оценку.

`PreparedUpdate.state` — устойчивая ссылка на конкретный экземпляр состояния estimator-а или параметры Program у их владельца. Она может адресовать согласованный блок параметров для атомарного обновления; это не `PredictionTarget` и не входное состояние процесса. Подготовленный запрос фиксирует адрес: retry не выбирает заново модель по target. Несколько anchors могут использовать общее состояние, а один target — разные estimator-ы; эти отношения задаются программой и связываются с её семантикой через anchors.

Новое состояние вычисляется updater-ом по актуальным параметрам в защищённой операции runtime. Версия состояния, использованная для исходного прогноза, сохраняется в trace и не меняется после обучения.

`PreparedUpdate` означает одно разрешённое применение `LearningCredit`; оно может включать batch и несколько внутренних optimizer steps, если это предусмотрено контрактом updater-а. Запрос на отмену или ослабление уже учтённого вклада:

```python
CreditRetraction {
  credit: <LearningCredit>
  state: <reference to estimator state or Program parameters>
}
```

`PreparedUpdate` и `CreditRetraction` являются immutable [[Memory#^def-OperatorOutput|`OperatorOutput`]]. Устойчивая identity каждого request обозначает один конкретный намеренный вызов соответствующего метода и предоставляется runtime.

Для `retract` адрес состояния и учтённые вклады восстанавливаются по фактически применённым updates, receipts и ledger. Изменившаяся привязка target к новой модели не перенаправляет исправление старого состояния.

```text
новый намеренный вызов
→ новый request object
→ новая identity;

retry того же вызова после сбоя
→ та же identity, в том числе после загрузки request из памяти.
```

Один `LearningCredit` обычно применяется к выбранному состоянию один раз; несколько updates по нему допустимы только по явно заданному контракту обучения. До подготовки update `UpdatePlanner` проверяет по контракту алгоритма, provenance входов и outcome, не был ли тот же логический вклад уже учтён. Один outcome может обновлять разные адресованные состояния или давать несколько предусмотренных алгоритмом примеров при разных входах одного estimator-а или Program, например из точек решения одной раздачи. Зависимости между такими примерами учитываются; они не становятся независимыми наблюдениями. Повторная evaluation или replay того же примера не создаёт новый независимый опыт, даже если у evaluation и credit новые identity.

Несколько внутренних optimizer steps могут составлять один `PreparedUpdate`. Отдельные requests создаются, если алгоритм явно требует самостоятельного применения и сохранения каждого шага. Повторное использование credit должно быть предусмотрено контрактом; оно не увеличивает число независимых наблюдений или обеспеченность модели данными. Исправленный outcome обрабатывается по [[#Исправление уже использованного опыта|правилам исправления опыта]]. Защита от повторного учёта опыта дополняет транзакционную защиту от retry одного request.

Примеры `updater_input`:

```text
Beta / Bernoulli estimator
→ observed category + attribution weight;

numeric estimator
→ observed value + context + attribution weight;

threshold optimizer
→ features + actual outcome + objective + attribution weight;

policy updater
→ action + realized outcome or advantage + attribution weight.
```

(def_id:: entity.UpdateTransactionManager)
> [!definition]  
> **[[#^def-UpdateTransactionManager|UpdateTransactionManager]]** — единая инфраструктурная граница исполнения parameter updates в стандартном learning pipeline:
> ^def-UpdateTransactionManager

```python
UpdateTransactionManager.apply(
  update: PreparedUpdate
) -> UpdateReceipt

UpdateTransactionManager.retract(
  retraction: CreditRetraction
) -> UpdateReceipt

UpdateReceipt {
  request: <PreparedUpdate | CreditRetraction>
  status: "applied" | "retracted" | "adjusted" | "skipped" | "rejected"
  reason?: <string>
}
```

`retracted` означает точную отмену вклада в рамках контракта updater-а; `adjusted` — приблизительную коррекцию; `skipped` — отсутствие изменения с указанной причиной, например неподдерживаемый `retract`. `rejected` означает недопустимый запрос. Пустая реализация `retract` допустима, но её результат фиксируется как `skipped`.

Оба метода используют одну транзакционную схему. Устойчивая identity request отличает новый намеренный вызов от retry; равенство полей или Python `id()` для этого не используются:

```text
begin transaction
→ проверить, нет ли UpdateReceipt для identity request
→ проверить допустимость логического вклада outcome:
  исключить повторный учёт; разрешить предусмотренные optimizer steps
→ прочитать текущие значения по ссылке state
→ UpdateDispatcher выбирает updater
→ вызвать updater.apply или поддерживаемый updater.retract
→ атомарно сохранить состояние (если изменилось), учёт вкладов и UpdateReceipt[identity request]
→ commit
```

Если до `commit` возникает exception, transaction автоматически откатывается: не сохраняются новое состояние, изменения учёта или receipt. Если вызов уже был committed, retry с той же identity request находит и возвращает сохранённый receipt, не меняя parameters второй раз.

Runtime выполняет операции одного состояния последовательно: защищён весь участок чтения актуальных параметров, расчёта и применения результата, включая подготовку, зависящую от текущих параметров. Одной очереди записи недостаточно. Если расчёт выполняется вне этого участка, runtime проверяет актуальность использованного состояния перед применением и при необходимости повторяет расчёт. Это внутренняя гарантия runtime; отдельное поле revision в общем learning-интерфейсе не требуется. Замена состояния обученным кандидатом проходит через ту же границу.

Проверка логического вклада внутри транзакции окончательна: два разных requests, подготовленных до первого commit, не должны дважды учесть один и тот же обучающий вклад в одном состоянии, в том числе при обращении из разных anchor-ов. Учёт сохраняется атомарно с состоянием и отражает фактический результат коррекции. Предусмотренные алгоритмом повторные optimizer steps по одному credit разрешены; новый credit на тот же опыт сам по себе такого разрешения не даёт.

В MVP это атомарность изменения в core, а не требование немедленной записи на диск. Обновляемые состояния, учёт логических вкладов и receipts входят в [[Cognition and Attention#^agent-backup|общий backup агента]]: при восстановлении они откатываются вместе. Утраченное при аварии обучение может быть выполнено заново от восстановленного состояния.

Updater не сохраняет состояние самостоятельно, не реализует транзакционный rollback и не обрабатывает повторы. Его методы вычисляют новое состояние из текущего состояния и соответствующего request и сообщают результат операции. `UpdateDispatcher` также не назначает credit и не изменяет state: он только выбирает updater по контракту адресованного состояния. `apply` обязателен; поддержка `retract` определяется [[#Исправление уже использованного опыта|правилами ниже]].

Обычные parameter updaters не должны иметь внешних нетранзакционных side effects. Если состояние нельзя хранить и менять через общую transaction-capable storage, для него нужен специальный lifecycle с compensation, а не обычный automatic parameter update.

Если привязка обучения отсутствует или неоднозначна, контракт несовместим, updater не может принять signal или вклад уже учтён без разрешения на повторный optimizer step, `UpdatePlanner` возвращает `UpdateBlocked` с соответствующей причиной. Parameters не изменяются; семантический credit при этом остаётся назначенным. Если недопустимый повтор выявлен только внутри транзакции, возвращается `UpdateReceipt` со статусом `rejected` и причиной `already_accounted`. Retry того же request по-прежнему возвращает его ранее сохранённый receipt.

```text
UnresolvedCredit
→ сохранить / анализировать / повторно разрешить позднее;
→ никогда не передавать в UpdatePlanner или UpdateTransactionManager;

LearningCredit
→ UpdatePlanner;
→ PreparedUpdate;
→ UpdateTransactionManager.apply;
→ UpdateDispatcher;
→ updater;
→ atomic parameter update + UpdateReceipt.
```

#### Исправление уже использованного опыта

`retract` необязателен. Его контракт задаёт точность, область действия и необходимые данные:

- **Точная отмена**, если её достаточно просто реализовать: например, убрать вклад из суммы и счётчика накопителя.
- **Приблизительная коррекция**, если точная отмена сложна, но есть оправданный способ ослабить ошибочное влияние. Полное удаление вклада не гарантируется; эффект проверяется соразмерно значимости исправления.
- **Отсутствие поддержки**, если стоимость реализации, хранения данных или выполнения превышает ожидаемую пользу. Метод может отсутствовать либо возвращать результат без изменения состояния.

Даже точная отмена относится только к указанному состоянию и объявленному алгоритму. Она не отменяет уже совершённые действия, полученные после них наблюдения и обучение других программ. Вычитание старого градиента после последующих updates обычно не восстанавливает состояние, которое получилось бы без ошибочного примера: следующие градиенты могли зависеть от него.

Учёт различает признание исхода ошибочным и устранение его влияния на параметры. Исходный credit, его применения и результаты исправления сохраняются; приблизительная коррекция или пропуск не помечают вклад как полностью удалённый. Исправленный outcome не становится новым независимым примером. Дополнительное обучение на нём допустимо как явно выбранная коррекция с учётом прежнего вклада; исходный ошибочный пример больше не используется как корректный.

Способ исправления выбирает программа, управляющая обучением, с учётом влияния ошибки, будущего использования модели и затрат. Редкий или дорогой опыт повышает ценность исправления, поскольку один пример может существенно влиять на модель. Малозначимое остаточное влияние допустимо оставить с зафиксированным ограничением; отсутствие `retract` не требует обязательного structural revision.

Если польза оправдывает затраты, обучающая подпрограмма может пересчитать статистику или повторно обучить кандидата на исправленном [[#TrainingDataset|опыте]] через стандартный learning pipeline и проверить результат перед заменой состояния. Отдельный универсальный тип или метод пересборки не нужен. Точный пересчёт возможен только при сохранении необходимых данных, начального состояния, порядка и настроек обучения.

### Parameter update examples
#topic_details

```text
unfair coin outcome
→ LearningSignal: observed side + (p - y)² metric + probability-estimation objective
→ LearningCredit: target = CoinSide, weight = 1.0
→ UpdatePlanner: выбрать исходный estimator по привязке программы
→ PreparedUpdate: state = состояние estimator-а, updater_input = Bernoulli sample
→ UpdateTransactionManager.apply
→ UpdateDispatcher
→ FrequencyEstimator with Beta / Bernoulli state
→ updated α, β and process probability p;

ProgramRun with branch x > threshold + evaluated outcome
→ LearningSignal: actual outcome + metric + objective
→ LearningCredit: target = оцениваемый результат процесса, weight = 1.0
→ UpdatePlanner: выбрать threshold по объявленной привязке обучения
→ PreparedUpdate: state = threshold конкретной Program, updater_input = features + actual outcome
→ UpdateTransactionManager.apply
→ UpdateDispatcher
→ ThresholdOptimizer
→ updated threshold;

известен выбранный PredictionTarget, но прогноз для него не назначен
→ UnresolvedCredit(target, context, reason="missing_prediction")
→ сохранить и передать в Attention; LearningSignal отсутствует;

LearningCredit назначен target, но нет однозначной привязки обновления:
threshold или upstream estimator
→ UpdateBlocked(reason="ambiguous_learning_binding")
→ parameters не изменять.
```

В первом случае `p` — параметр model value, а не epistemic `Strength`. Во втором threshold — оптимизируемый параметр, а не неизвестная истина мира. Если ни одно значение threshold не устраняет устойчивый mismatch, `LearningCoordinator` передаёт случай в slow structural learning.
Тот же evaluated outcome может независимо дать [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]] о корректности модели через [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]]; это не заменяет `LearningCredit` для её параметров.

---

## Sub-episodes

Длинный [[Memory#^def-ProgramRun|`ProgramRun`]] разбивается на локальные sub-episodes, если внутри него существуют самостоятельные прогнозируемые outcomes:

```text
значимое промежуточное состояние;
изменение signal channel;
срабатывание или несрабатывание process transition;
локальное решение;
 и т.д.
```

```text
local prediction
+ local outcome
→ local evaluation
→ local credit assignment
→ local updates.
```

Это уменьшает длину dependency path и помогает связать credit с нужным target и конкретным решением длительного процесса.

---

## Slow structural learning

Если локальные updates не объясняют устойчивый mismatch, запускается slow structural analysis, который может вызывать structural revision. Сознательный пересмотр также возможен при рефлексии или существенном новом опыте, без предварительной серии parameter updates; [[#Выбор обучаемых компонентов и режима обучения|выбор компонентов и режима обучения]] пересматривается вместе с программой. При поиске причины сначала проверяют локальные механизмы; одинаковые ошибки в нескольких независимых применениях дают основание проверить общий upstream-механизм, если локальных объяснений недостаточно.

Основные triggers:

Одним из triggers является [[Evaluative-Control System#^def-ExplanatoryTension|`ExplanatoryTension`]], которое после parametric updates остаётся повышенным относительно сопоставимой истории на новых наблюдениях.

```text
высокие prediction_unexpectedness чаще, чем допускает правило последовательных проверок;
новый режим процесса;
надёжное evidence против модели с высоким Support;
ExplanatoryTension остаётся повышенным на новых сопоставимых наблюдениях;
regression в Evaluation.
```

Slow analysis может выявить:

```text
missing factor или CONDITION;
неверный context scope;
новый режим процесса;
неполный output contract;
неподходящую структуру predictor-а;
ошибочную Program.
```

Результат передаётся в `Program Lifecycle and Evolution`; исходной формой структурной гипотезы могут быть [[Core data structures#^def-Note|Note]] или [[Core data structures#^def-Claim|Claim]]:

```text
Note / Claim
→ reasoning / elaboration
→ semantic change / parametric update / Prompt revision / ProgramBranch / new Program / EvaluationCase
→ Evaluation
→ EvaluationChoice.
```

Reasoning может задать initial prior, но не `Support`; активация нового Claim
или structural change требует последующего evidence.

---

##  Expected signal updates

Прогнозы оценочных сигналов проверяются на уровне конкретного [[Memory#^def-ProgramRun|`ProgramRun`]] для каналов, которые программа фактически предсказывала. Их состав и способ получения определяются [[#Выбор обучаемых компонентов и режима обучения|при выборе компонентов]], а не добавляются для всех сигналов при каждом запуске. Исходный прогноз и итоговая оценка сопоставляются по [[#PredictionEvaluator|общим правилам PredictionEvaluator]]; совпадения канала недостаточно:

```text
сохранённый прогноз значения или распределения канала
+ полученная оценка по тому же каналу
→ EvaluationResult с применимыми метриками,
  включая prediction_unexpectedness при наличии основы для калибровки.
```

[[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] создаёт evidence для belief о корректности signal model. `CreditAssignmentProgram` назначает credit соответствующим PredictionTarget; `UpdatePlanner` затем выбирает estimator или параметры политики по контексту и цели обучения.

Способ вычисления expected signals является внутренней частью программы. Это может быть:

```text
domain model или simulation;
фиксированное значение или обучаемый скаляр V;
linear Ax+b;
categorical OutcomeProfile;
другой model-specific estimator.
```

Отдельный универсальный `PredictorState` для каждого сигнала не создаётся. Parameter update получает только обучаемый компонент, для которого предусмотрено обучение в данном случае; расхождение с фиксированным прогнозом может стать основанием для пересмотра программы.

Для [[Evaluative-Control System#^def-SupervisorFeedbackSignal|`supervisor_feedback_signal`]] числовой прогноз и его проверка относятся к `value`. Необязательный `comment` сохраняет объяснение feedback и может помогать анализу и назначению credit; его текст не подставляется вместо числового исхода.

Точечные модели `V` и `Ax+b` можно оценивать и обучать по подходящим метрикам [[Process Plane/Program Evaluation and Testing#^def-PredictionError|`prediction_error`]] без `prediction_unexpectedness`; для этого сигнала дополнительно нужно распределение ожидаемых отклонений по [[Evaluative-Control System#^def-PredictionUnexpectedness|общему контракту]].

Target, цель обучения и привязка update различаются:

```text
ошибочный прогноз доменного результата
→ credit для target этого результата
→ обучение estimator-а world/process model;

верный прогноз domain outcome,
но ошибочный expected signal
→ credit для target этого сигнала
→ обучение estimator-а сигнала;

верные predictions,
но плохой выбор
→ credit для target оцениваемого результата действий
→ обучение политики или её оценщика полезности по соответствующей цели.
```


---


## Предсказание и наблюдение

#topic_details

Предсказание и наблюдение являются разными видами опыта и сохраняются раздельно.

Model `Program` возвращает прогноз в `result` общего [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult[T]`]]: числовую оценку, предсказанное состояние, `Profile` или `OutcomeProfile`. Runtime сохраняет `ProgramResult` в `TraceEvent.output`; ссылка на прогноз адресует `result` или его нужную semantic part. Для anchored-оператора, не являющегося `Program`, сохраняется его собственный типизированный [[Memory#^def-OperatorOutput|`OperatorOutput`]]. [[Memory#^def-SemanticTrace|`SemanticTrace`]] содержит ссылку на исходное событие и является частью памяти. Python-переменная может ссылаться на тот же прогноз; отдельный объект рабочего состояния для его хранения не нужен.

Предсказанное состояние может быть представлено локальным [[Core data structures#^def-Facet|`Facet`]] внутри [[Memory#^def-SemanticTrace|`SemanticTrace`]], но не становится обычным состоянием объекта в persistent graph.

Для поиска прогноза при последующей проверке в графе материализуется факт о прогнозе:

```text
PREDICTS(
  model_run,
  subject,
  prediction_target,
  predicted_value_or_profile,
  valid_at,
  conditions?
)
```

`prediction_target` ссылается на [[Process Plane/Program Layer#^def-PredictionTarget|предсказываемый Concept]]: свойство, состояние, событие или сигнал. `subject` задаёт объект, к которому относится прогноз.

`PREDICTS` остаётся неизменной записью того, что модель ожидала в момент прогнозирования. Его [[Memory#^def-ResultProvenance|provenance]] ведёт к исходному результату в trace. После обучения модели этот результат не пересчитывается. Пока прогноз нужен для проверки или обучения, память сохраняет его и необходимый контекст.

Общий поиск прогнозов и сборку связанных наблюдений выполняет [[#^def-PredictionEvaluator|`PredictionEvaluator`]] через память и граф; журнал DBOS используется для восстановления исполнения.

[[Memory#^def-Observation|Наблюдение]] сохраняется как типизированный результат восприятия. При необходимости включить наблюдаемое состояние в persistent модель мира используется обычный путь материализации:

```text
Источник → PerceptionOperator → observation в trace
→ при необходимости: GraphDelta
→ persistent Facet
```

Наблюдаемое состояние не считается абсолютно истинным. Его надёжность выражается через `Strength` и `Support`.

### PredictionEvaluator

(def_id:: entity.PredictionEvaluator)
> [!definition]
> **PredictionEvaluator** — общая [[Process Plane/Program Layer#Program|Program]], которая находит сохранённые прогнозы, собирает связанные наблюдения и проверяет каждый прогноз по выбранным метрикам. Возвращает `ProgramResult[EvaluationResult[]]`: отдельный [[Process Plane/Program Evaluation and Testing#EvaluationResult|EvaluationResult]] для каждого проверяемого прогноза находится в `result`. Для выбранного PredictionTarget без назначенного прогноза вызывает `CreditAssignmentProgram`, чтобы сохранить `UnresolvedCredit`. Несопоставленный опыт обрабатывает с учётом ранее принятых решений о необходимости прогноза; случаи, требующие разбора, передаёт сознанию.
> ^def-PredictionEvaluator

Программа задачи или процесса передаёт ему новые наблюдения, контекст проверки — выбранный процесс, объект и эпизод — и метрики. Внутри `PredictionEvaluator` работают три функции:

1. **`match_predictions(observations, context)`** находит в памяти исходные прогнозы по `PREDICTS` и provenance. Для каждого собирает относящиеся к нему новые и ранее сохранённые наблюдения по объекту, PredictionTarget, эпизоду, времени и условиям. Возвращает наборы «прогноз + наблюдения» и наблюдения без найденного соответствия. Один прогноз может требовать нескольких наблюдений; одно наблюдение может относиться к нескольким прогнозам. Если составное наблюдение сопоставлено лишь частично, сохраняется указание на неучтённую часть и ссылка на исходное наблюдение целиком.
2. **`evaluate_prediction(prediction, observations, metrics)`** проверяет применимость прогноза и достаточность наблюдений, вычисляет метрики и возвращает `EvaluationResult`.
3. **`handle_unmatched_observations(observations, context)`** подготавливает из памяти и trace исходные наблюдения, выбранную программу процесса, текущий эпизод и результат поиска прогнозов. Если target выбран для прогнозирования в этом контексте, но прогноз не назначен или не найден, вызывает `CreditAssignmentProgram` с известным target и контекстом: сохраняется `UnresolvedCredit(reason="missing_prediction")` без `LearningSignal`. Если target ещё не выбран или прогнозирование в этом контексте признано ненужным, учитывает соответствующее сохранённое решение. Unresolved credits, новые случаи и основания пересмотреть прежнее решение передаёт через [[Cognition and Attention|Attention]] на рассмотрение в рамках `Task`.

`PredictionEvaluator` вызывает `evaluate_prediction` для найденных соответствий, а `handle_unmatched_observations` — для оставшихся наблюдений или их неучтённых частей. Отсутствие прогноза не создаёт численного `prediction_unexpectedness`, фиктивной Evaluation или `LearningSignal`; `UnresolvedCredit` фиксирует незавершённый случай для выбранного target. Не каждый наблюдаемый Concept обязан иметь прогноз. Если вызывающая программа уже располагает прогнозом и связанными наблюдениями, она может сразу использовать `evaluate_prediction` без поиска.

Решение не моделировать определённый сигнал в данном контексте сохраняется вместе с причиной и областью применения. При повторении того же случая без новых оснований оно используется снова, без нового сознательного разбора. Выход за эту область или существенное изменение частоты использования процесса, его значимости либо характера feedback требует пересмотра решения. Отказ от прогнозирования не освобождает от реакции на само наблюдение. Отсутствие обязательного по контракту прогноза нельзя объяснить этим решением.

Сознательный разбор обязателен для каждого переданного в Attention случая. Он может быть отложен; связанные случаи можно рассматривать вместе. В интерактивном режиме сознание может разобрать подготовленный контекст сразу.

Отсутствие найденного прогноза само по себе не доказывает неполноту модели. [[Cognition and Attention#^def-Consciousness|Сознание]] выясняет причину: программа не учитывает существенное поведение; предусмотренный прогноз не был сформирован или найден; наблюдение отнесено не к тому процессу; либо прогноз для него не требовался. При подтверждённом пробеле сознание запускает структурную ревизию через [[Process Plane/Program Lifecycle and Evolution#Общий lifecycle Program|Program Lifecycle]].

Например, полученный supervisor feedback может выявить полезный, но отсутствующий прогноз. Сознание определяет, к какому решению относится feedback и где прогноз помог бы: к выбору задачи, действия или конкретной ветви. Затем оно может подключить существующую модель либо добавить локальный предиктор с выбранным режимом обучения. Сам факт feedback не требует нового регрессора: недовольство тем, что агент играет в покер вместо выполнения задачи, может относиться к выбору занятия, а не к модели покерного хода.

Если необходимость нового компонента обнаружена при credit assignment, она также передаётся на пересмотр программы. Evaluator и credit assignment не добавляют предикторы сами. Изменение проходит через Program Lifecycle; после активации компонента дальнейшее обучение выполняется по текущему выбранному режиму. Сохранённые наблюдения можно использовать для начального обучения кандидата, но полученный после этого прогноз не считается прогнозом, существовавшим до этих наблюдений.

`match_predictions`, `evaluate_prediction` и `handle_unmatched_observations` — функции одной программы, а не отдельные `Program`. Подбор данных и передача несопоставленного опыта на разбор находятся в `PredictionEvaluator`, поэтому программы процессов не реализуют эти шаги каждая для себя.

```python
PredictionEvaluator.evaluate_prediction(
    prediction: T,
    observations: tuple[OperatorOutput, ...],
    metrics: tuple[MetricDefinition, ...],
) -> EvaluationResult
```

`prediction` — доменный payload исходного сохранённого прогноза; `T` задаётся контрактом модели. Для результата `Program` это значение из `ProgramResult.result` с provenance к соответствующей части исходного output; для обычного anchored-оператора — его типизированный результат. Типизированные наблюдения и их semantic projection сопоставляются с прогнозом по объекту, времени и условиям с учётом независимости и надёжности источников. Конкретная проверка принимает подходящие доменные схемы. `evaluate_prediction` не запускает и не изменяет модель; обучение, назначение credit и объяснение ошибки выполняются отдельно.

Для [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] evaluator использует сохранённый прогноз и правило проверки по общему контракту сигнала. Если нет поддерживаемого способа задать распределение ожидаемых отклонений или расчёт не оправдан по стоимости, сигнал не вычисляется. Это не аннулирует другие доступные метрики: причины пропусков и статус определяются [[Process Plane/Program Evaluation and Testing#EvaluationResult|общим контрактом `EvaluationResult`]].

`PredictionEvaluator` возвращает результаты проверки вызывающей программе в `ProgramResult.result` и сохраняет их в trace со ссылками на использованные прогнозы и наблюдения. `UnresolvedCredit` сохраняются отдельно, как типизированные результаты дочернего `CreditAssignmentProgram`, и не включаются в `EvaluationResult[]`. Вызывающая программа решает, какие результаты проверки передать [[#LearningCoordinator|`LearningCoordinator`]] для обучения в рамках задачи.

(def_id:: entity.PredictionEvaluationRun)
> [!definition]  
> **PredictionEvaluationRun** — запуск [[#^def-PredictionEvaluator|PredictionEvaluator]] для проверки сохранённых прогнозов по наблюдениям и обработки несопоставленного опыта. Его `ProgramResult.result` содержит отдельный [[Process Plane/Program Evaluation and Testing#EvaluationResult|EvaluationResult]] для каждого проверяемого прогноза.
> ^def-PredictionEvaluationRun

Статусы и причины пропуска метрик следуют [[Process Plane/Program Evaluation and Testing#EvaluationResult|общему контракту `EvaluationResult`]]. При `evaluated` рассчитана хотя бы одна выбранная метрика; `prediction_unexpectedness` входит в результат, только если он рассчитан:

```text
PredictionEvaluationRun
→ EvaluationResult для каждого прогноза
  → NonEmpty[MetricSample]
→ если результат выбран для обучения: LearningCoordinator
  → LearningSignal
```

`NotApplicableResult` и `UnresolvedEvaluationResult` сохраняются как история evaluation, но [[#^def-LearningSignal|`LearningSignal`]] не создают.

Вероятностный прогноз не получает бинарный ярлык «подтверждён» или «опровергнут». Наблюдение является новым evidence, а метрика показывает, насколько этот исход соответствовал epistemic [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] competing alternatives либо [[Uncertainty and Belief Tracking in the World Model#Probabilistic process outcomes|`OutcomeProfile`]] стохастического процесса. Эти представления не взаимозаменяемы.

Если позднее появляется более полное или исправленное наблюдение, создаётся новый [[#^def-PredictionEvaluationRun|`PredictionEvaluationRun`]]. Исходный прогноз и предыдущие оценки сохраняются как история.

### Гипотезы

Фиксируются через связь:
```python
HYPOTHESIZES(
  reasoning_run,
  proposed_fact,
  valid_at,
  created_at
)
```

Таким образом, память раздельно хранит:

```text
что ожидала модель;
при каких условиях был сделан прогноз;
что было наблюдено;
можно ли было проверить прогноз;
насколько наблюдение соответствовало прогнозу;
как результат повлиял на модель.
```


---

## Runtime Integration, simplified 

Запуск проверок и выбор опыта для обучения принадлежат вызывающей программе в контексте `Task`. Наблюдения могут поступать в evidence-ветвь coordinator-а и без Evaluation.

Ниже показана прогнозная ветвь; [[#^outcome-credit|Evaluation результатов Task или процесса]] также поступает в общий `LearningCoordinator`.

```text
ProgramRun
        ↓
prediction / epistemic Profile / OutcomeProfile / expected signals
        ↓
Observation
        ↓
PredictionEvaluator
        └─ match_predictions
             ├─ найденные соответствия → evaluate_prediction → EvaluationResult
             └─ наблюдения без прогноза → handle_unmatched_observations
                  ├─ выбранный PredictionTarget → CreditAssignmentProgram
                  │   → UnresolvedCredit(target, missing_prediction)
                  │   → сохранить → Attention; без LearningSignal и parameter update
                  └─ прочие случаи → учесть ранее принятое решение;
                      случаи для разбора → Attention → сознание

EvaluationResult, выбранные для обучения
        ↓
LearningCoordinator
        ├─→ EvidenceAssessmentProgram
        │   → EvidenceAssignment[]
        │   → Evidence lifecycle
        │
        └─→ LearningSignal, только для EvaluatedResult
            → CreditAssignmentProgram: назначить credit LearningTarget
            → CreditAssignmentResult[]
              ├─→ UnresolvedCredit(target, ambiguous_attribution)
              │   → store / analysis
              │   → no parameter update
              │
              └─→ LearningCredit(target, signal)
                  → UpdatePlanner: выбрать estimator или параметры Program
                  → PreparedUpdate
                  → UpdateTransactionManager.apply
                  → UpdateDispatcher
                  → updater по контракту состояния
                  → atomic commit: updated parametric state + UpdateReceipt

if mismatch remains unexplained:
        ↓
slow structural analysis
        ↓
Program Lifecycle and Evaluation
```

---
