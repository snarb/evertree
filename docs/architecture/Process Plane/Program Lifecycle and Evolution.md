## Эволюция, отбор и улучшение программ

Программы EverTree развиваются как проверяемые гипотезы.

`Program` — стабильная identity механизма, который моделирует или исполняет процесс.

`ProgramBranch` — временная линия изменения существующей `Program`.

Новая `Program` создаётся, если меняется сам принцип решения.
`ProgramBranch` создаётся, если основной механизм сохраняется, но уточняются детали, параметры, edge cases, contracts, локальная структура или реализация.

Любая новая программа или branch должна иметь явную гипотезу:

```text
какое изменение предлагается
→ почему оно должно помочь
→ какие сигналы или метрики должны улучшиться
→ как это будет проверено
```

Программа не становится активной только потому, что идея кажется разумной.

Reasoning, LLM, литература, память, аналогии и внешние источники создают candidates и priors. Активной программа становится только после проверки, Evaluation и `EvaluationChoice`.

Evaluation не обязана сразу завершаться принятием или отклонением. Если evidence недостаточно, кандидат может остаться кандидатом, а агент продолжает копить данные: через replay, simulation, новые ProgramRun, реальные наблюдения или специально созданные EvaluationCase.

Это не отдельный lifecycle и не отдельная сущность `LiveValidation`. Это обычное состояние незавершённого выбора: несколько альтернатив остаются живыми, пока поддержки недостаточно.

---

### Общий lifecycle Program

Все Programs независимо от набора [[Program Layer#Program roles|ролей]] проходят один общий lifecycle.

```text
trigger
→ gather_relevant_info
→ reasoning_and_synthesis
→ candidate change
→ implementation / semantic update
→ verification
→ program tests
→ training on TrainingDataset if needed
→ Evaluation
→ evidence accumulation if needed
→ EvaluationChoice
→ merge / activate / continue / reject / archive / keep alternatives
```

Кандидата можно предварительно обучить на [[Learning system#^def-TrainingDataset|TrainingDataset]]. При сравнении на [[Program Evaluation and Testing#EvaluationDataset|EvaluationDataset]] базовая модель и кандидат используют одну версию набора с соблюдением [[Datasets#Границы обучения и проверки|независимости проверки]]. Управление наборами следует [[Datasets#Жизненный цикл|общему lifecycle datasets]].

Разница между Programs не в lifecycle, а в проверяемых требованиях к их основной роли и модификаторам.

При создании и пересмотре программы выбирается и заполняется профиль [[Program Layer#ProgramDesign|ProgramDesign]]. Проверка сопоставляет заявленные решения с реализацией, включая ветвления до выбора действия, адаптацию, исследование и путь обучения; проверяемые поведенческие требования входят в tests и Evaluation.

#### Подготовка начальных моделей
#topic_core

Сначала переиспользуются подходящие программы, правила, таблицы и обученные состояния. Если их недостаточно, ограниченная сессия сознания с использованием LLM и внешнего исследования готовит недостающую реализацию и её область применимости.

Это общий путь подготовки разных начальных предположений:

| Что подготавливается | Смысл результата |
|---|---|
| Начальная policy | Правило выбора, предпочтения действий или начальные параметры стратегии |
| Epistemic prior | Вероятность target до собственного evidence |
| Модель наблюдений | Вероятность результата наблюдения при каждом состоянии target |

Общими являются подготовка, сохранение, проверка и последующее обучение. Эти выходы сохраняют свои типы и не объединяются в универсальную сущность `Prior`. Начальное предпочтение политики не является вероятностью истинности belief и не создаёт epistemic `Support`.

Результат сохраняется как код, настройки или модельный артефакт существующей Program с типизированным интерфейсом. Приблизительная модель может исполняться кодом с первого дня; качество её оснований проверяется отдельно. Evaluation может обосновать применение ограниченного fallback до накопления точной калибровки, если соблюдены контракт, область применения и пределы влияния. Это решение проходит обычный `EvaluationChoice`.

Новый экземпляр процесса, target или состояние в известных условиях не требует повторной подготовки. Новые данные обновляют предусмотренные параметры; существенные различия условий могут потребовать отдельного состояния или версии. Замена LLM-пути кодом выбирается по качеству и полной стоимости, включая сопровождение и проверки. Конкретный путь для belief описан в [[Uncertainty and Belief Tracking in the World Model#Жизненный цикл assessment|жизненном цикле assessment]].

#### Primary role: model

`Program` с `model ∈ Program.roles` отвечает за вопрос:

```text
как устроен процесс и что он предсказывает?
```

Её стартовая версия должна быть минимально достаточной, чтобы:

```text
- делать ключевые прогнозы переходов по данному процессу;
```

Стартовый пример:
```text
в ситуации S
если происходит transition/action X
то вероятен outcome/profile Y
```

Типичные начальные sources:

```text
memory 
similar ProcessConcept и TransitionType
LLM/general priors
simulation / dataset
```

Такая `Program` не выбирает действие напрямую. Она возвращает predictions, profiles или expected signals, которые могут использоваться `Program` с основной ролью `exec`, [[Action Selection and Planning|локальной политикой выбора]], planning или consciousness selection.

---

#### Primary role: exec

`Program` с `exec ∈ Program.roles` отвечает за вопрос:

```text
что агент делает в этом процессе?
```

Её минимальная стартовая версия — рабочая структура действий агента в данном процессе.


Типичные начальные источники:

```text
similar executable programs
expert strategies/imitation
LLM/general priors
dual model program
```


`Program` с основной ролью `exec` может использовать `Program` с основной ролью `model`:

```text
model ∈ Program.roles
→ predictions / expected signals / process understanding

exec ∈ Program.roles
→ candidates / control flow / policy programs / actions
```

Declarative model не выбирает действие напрямую.  
Executable program выбирает действие через обычный control flow, программу политики, planning или consciousness selection.

#### Candidate change

Результат `reasoning_and_synthesis` не обязан сразу быть кодом.

Он может породить разные типы изменений:

```text
semantic change
→ уточнение ProcessConcept, relation, PROCESS_VARIABLE, contract или scoped semantic link

parametric update
→ изменение весов, priors, values, probabilities или других параметров без смены структуры

ProgramBranch
→ изменение существующей Program при сохранении основного механизма

new Program
→ альтернативный подход с другим принципом решения

EvaluationCase
→ новый проверочный сценарий, если проблема пока лучше выражается как тест
```

Если изменение требует правки кода, оно идёт через `ProgramBranch` или новую `Program`.

Если изменение касается только графа, semantic links или contracts, оно всё равно должно быть проверяемым: через replay, EvaluationCase, ProgramRun, simulation или последующие observations.

#### Verification and program tests

Candidate `Program` или `ProgramBranch` после implementation проходит общую `Verification`. `Verification` определяет, какие дополнительные проверки необходимы и достаточно ли полученных результатов.

`program tests` — обычные качественные тесты разработки: unit, behavioral, adversarial, property-based, smoke и другие подходящие проверки.

Для `exec` с effects проверяется [[Cognition and Attention#^program-restart-continuation|контракт продолжения без повторов]], если поддерживается замена во время Task, включая замену родителя.

Program tests не являются главным механизмом выбора между конкурирующими программами. Их роль:

```text
- найти ошибки реализации;
- предотвратить регрессии;
- уточнить candidate;
- помочь довести branch до состояния, пригодного для Evaluation.
```

Сравнение кандидатов выполняется через `Evaluation`.

#### Evaluation

`Evaluation` — количественная проверка программы, branch или гипотезы на `EvaluationCase` или `EvaluationDataset`, построенных из памяти, simulation, offline data, сгенерированных сценариев и других источников evidence.

Evaluation возвращает метрики результата, в том числе оценки по каналам [[Evaluative-Control System]]:

```text
prediction_unexpectedness
supervisor_feedback_signal
tension_reduction
и другие target metrics
```

[[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] помогает обнаружить расхождение для анализа; его минимизация не является критерием выбора модели. Прогностическое качество кандидатов сравнивается на независимых данных по одинаковым заранее фиксированным критериям, учитывающим и соответствие исходам, и информативность прогноза.

Evaluation не равна реальному новому опыту. Реальные события могут дать evidence, но они становятся частью выбора только после проекции на процесс, программу и проверяемые метрики.

#### Evidence accumulation

Если данных недостаточно, агент не обязан принимать или отклонять кандидата сразу.

Он может оставить одну или несколько альтернатив в статусе candidate и продолжить накапливать evidence

```

Кандидат остаётся кандидатом, пока:

```text
- есть несколько живых альтернатив;
- активная версия ещё не выбрана;
- evidence/support недостаточны для EvaluationChoice.
```

Если программа одна и она уже принята как рабочая, отдельный статус накопления evidence не нужен. Новые observations просто обновляют belief, параметры, contracts или порождают следующий trigger для улучшения.

#### EvaluationChoice

`EvaluationChoice` — сознательное решение о судьбе кандидата после Evaluation и накопления evidence.

Evaluation предоставляет метрики.
EvaluationChoice принимает решение.

Возможные исходы:

```text
merge_branch
→ изменение существующей Program принято; branch мержится в main

continue_branch
→ данных недостаточно или candidate нужно доработать; branch остаётся живой

reject_branch
→ branch-гипотеза не получила достаточной поддержки; branch архивируется или удаляется

create_new_program
→ стало ясно, что изменение уже не является branch, а требует отдельной Program

activate_program
→ связанная через PROGRAM_FOR_PROCESS Program становится
  ProcessConcept.active_model или ProcessConcept.active_exec

reject_program
→ alternative Program проиграла и получает lifecycle_status="rejected"

keep_alternatives
→ несколько программ остаются candidates, потому что evidence пока недостаточно

archive_program
→ программа больше не нужна как активный candidate, но сохраняется для истории, replay или будущих аналогий
```

Активные слоты процесса (`ProcessConcept.active_model` и `ProcessConcept.active_exec`) обновляются только через `EvaluationChoice`.

#### Operational flows

Улучшение текущей программы:

```text
active code is in main
→ create ProgramBranch
→ write / edit code
→ update program tests
→ commit changes
→ run EvaluationDataset
→ EvaluationRun → EvaluationResult[]
→ create EvaluationChoice
→ merge / continue / reject / archive
```

Проверка альтернативной программы:

```text
create new Program
→ create PROGRAM_FOR_PROCESS(new_program, process)
→ Program.alternative_to = current active Program
→ write code in its own git_path
→ run comparable Evaluation
→ compare EvaluationRuns
→ activate if better
→ reject or keep as candidate if not enough support
```

Текущая active Program остаётся активной до `EvaluationChoice`.
Candidate Program или ProgramBranch не заменяет active slot автоматически.

#### Meta-program lifecycle safety

Усиленные требования этого раздела применяются только при `meta ∈ Program.roles`. `ProgramLifecycleManagement` управляет lifecycle программ и имеет `roles = {exec, meta}`.

Meta-программы влияют на множество будущих решений и могут изменять механизмы собственного обучения. В пределах [[Self#^meta-improvement-mvp|ограничения MVP на изменение процедуры принятия улучшений]] они улучшаются через тот же lifecycle, но консервативнее обычных программ:

```text
- реже запускать self-improvement;
- требовать больше support/evidence;
- проводить более широкую Evaluation, включая сравнение старой и новой версий
  на историях успешного и неуспешного улучшения программ;
- усиливать regression checks;
- учитывать стоимость ошибок выше, чем у обычных domain-программ;
- применять более осторожные updates;
- требовать более высокий порог evidence перед activation;
- использовать упрощённые tests для дорогих meta-evaluation, если полная проверка слишком затратна.
```

Для разрешённых изменений meta-механизмов сначала нужны сильные свидетельства, что новая версия улучшает качество, стоимость, стабильность или безопасность lifecycle. Накопление таких свидетельств не снимает ограничение MVP на изменение окончательной проверки и принятия улучшений.

Моделирование self-improvement само по себе не делает `Program` meta. Например:

```text
ImprovementOutcomeModel.roles = {model}
ProgramLifecycleManagement.roles = {exec, meta}
```



---

### Stage 1: gather_relevant_info

`gather_relevant_info(Program | ProcessConcept)` собирает материал для построения или улучшения программы.

Это не planning и не action selection.
Эта стадия не выбирает действие и не меняет программу напрямую.

Она отвечает на вопрос:

```text
что агент уже знает или может узнать, чтобы построить лучшую гипотезу программы?
```

Источники:

```text
memory
→ прошлые эпизоды, failures, wins, ProgramRun, EvaluationRun

semantic graph
→ похожие ProcessConcept, TransitionType, ActionConcept, OperatorConcept, relations

existing programs
→ Programs связанного процесса во всех lifecycle statuses,
  а также siblings и prototypes

LLM general knowledge
→ первичные priors, edge cases, возможная структура модели

external research
→ литература, документация, статьи, domain guides, deep research

simulation / datasets
→ synthetic episodes, offline evidence, self-play, benchmark cases
```

`gather_relevant_info` создаёт evidence и context для мышления. Оно не создаёт финальную программу само по себе.

Внешнее исследование запускается для конкретного пробела, если ожидаемая польза оправдывает стоимость: например, для поиска модели теста, характеристик измерения или статистики ошибок источника. Сохраняются источник, версия и условия применимости; найденная публикация не подтверждает перенос на текущий процесс автоматически. Пересмотр запускается при существенном изменении условий или используемых оснований; обязательного периодического LLM / web research нет.

---

### Stage 2: reasoning_and_synthesis

`reasoning_and_synthesis` превращает собранную информацию, ошибки, наблюдения и цели в проверяемые объяснения и возможные способы улучшения модели или программы.

На этой стадии есть два взаимосвязанных процесса.

**Анализ** разбирает доступный материал: ищет повторяющиеся ошибки, противоречия, missing variables, скрытые факторы, разные режимы процесса, границы применимости модели и полезные аналогии.

**Синтез** строит новые объяснения и подходы, комбинируя memories, похожие процессы, semantic structure, rejected alternatives, внешние источники, контрфакты и LLM/general-knowledge priors.

Агент поэтому не только находит готовую гипотезу. Он может построить новую идею из нескольких частичных наблюдений или аналогий, которых по отдельности недостаточно для вывода.
Начальная гипотеза обычно не является программой и не равна конкретной реализации.

Например:

```
"Возможно, текущая модель не учитывает важный фактор X."
```

Такая идея может быть записана в [[Core data structures#^def-Note|`Note`]].

Если утверждение нужно проверять и обновлять отдельно, агент оформляет [[Core data structures#^def-Claim|`Claim`]]:

```
Claim G:
"X существенно влияет на Y."
```

`Claim` — проверяемое утверждение и может быть самостоятельным `BeliefTarget`; целую `Note` также можно оценивать без обязательного разбиения по [[Core data structures#^note-claim-prompt-evaluation|общему контракту оценки]].

**Гипотеза** здесь не отдельный тип данных, а роль `Claim`: Claim является гипотезой, когда агент рассматривает его как возможное объяснение, prediction, способ улучшения и собирает evidence для его проверки.
### Уточнение гипотез

Reasoning может разворачивать общий Claim в несколько более конкретных и конкурирующих объяснений:

```
general Claim
        ↓ reasoning / elaboration
specific Claims
```

Например:

```
G:
"Текущая модель смешивает разные режимы процесса."

        ↓

C1:
"Высокий prediction_unexpectedness возникает из-за смешения режима A и режима B."

C2:
"Режим один, а mismatch объясняется фактором X."
```

Общий и конкретные Claims являются самостоятельными `BeliefTarget`.

Уровень общности Claim не задаётся отдельным типом или полем. Он выражается
его семантикой: более общий Claim использует более общие Concepts, ProcessConcept,
Prototype или условия; более конкретный относится к более узким объектам,
механизмам или context.

Если persistent Claim создаётся как уточнение другого Claim, это явно
фиксируется semantic relation: `REFINES_CLAIM(specific, general)`.

Так Claims образуют навигируемую структуру от общих гипотез к более конкретным.
Связь не означает истинность Claims и не переносит evidence автоматически. `EvidenceAssessmentProgram` назначает evidence каждому Claim только тогда, когда фактическая проверка действительно информативна относительно него.

Поэтому:

```
specific Claim false
≠
general Claim автоматически false.
```

Несколько независимых результатов могут дать evidence более общему Claim, если вместе действительно проверяют его содержание.

---

### Claims о проблеме и Claims о способе улучшения

Reasoning может создавать Claims разных ролей.

```
explanatory Claim
→ что, вероятно, объясняет наблюдаемую проблему;

change Claim
→ какое изменение, вероятно, улучшит результат.
```

Это роли одного типа `Claim`, а не отдельные классы.

Например:

```
Claim G:
"Высокий prediction_unexpectedness возникает из-за смешения режимов A и B."

        ↓ reasoning

Claim A:
"Явное разделение режимов A и B
через отдельную model branch объяснит наблюдаемое расхождение
и улучшит качество прогнозов относительно текущей модели
на независимой проверке по фиксированным критериям."
```

`Claim A` описывает **подход**, а не его конкретную реализацию.

Reasoning может создать несколько альтернативных change Claims:

```
A:
"Использовать отдельные branches для режимов A и B."

B:
"Использовать continuous latent regime variable."

C:
"Сохранить одну модель, но добавить factor X."
```

Именно на этом уровне происходит поиск и сравнение разных подходов.

Reasoning само по себе не является сильным evidence. Оно может создать Claim, задать initial prior и повысить ожидаемую ценность его проверки, но не увеличивает `Support` только потому, что объяснение кажется убедительным.

Проверка происходит через независимые observations, Evaluation, simulation, experiments, replay или live experience.

---

### Реализация выбранного подхода

Один change Claim может быть реализован несколькими способами.

Например:

```
Claim A:
"Отдельная branch для режима B объяснит наблюдаемое расхождение
и улучшит качество прогнозов на независимой проверке
по фиксированным критериям."

        ↓ implementation generation

ProgramBranch A1
ProgramBranch A2
ProgramBranch A3
```

`A1`, `A2` и `A3` могут отличаться:

```
разными prompts;
разными LLM;
несколькими stochastic runs одного LLM и prompt;
последующим refinement или debugging.
```

Это **несколько concrete implementations одного и того же подхода**, а не несколько разных Claims.


**Implementation candidate** — это роль конкретного native artifact, реализующего change Claim (отдельная сущность `ImplementationCandidate` не требуется).

В зависимости от изменения таким artifact является:

```
изменение существующей Program (тот же основной механизм)
→ ProgramBranch;

принципиально другой механизм
→ candidate Program;

semantic изменение
→ candidate semantic change;

изменение существующих параметров
→ candidate parametric update;

изменение шаблона инструкций или placeholders
→ candidate Prompt revision;

новый проверочный сценарий
→ EvaluationCase.
```

[[Core data structures#^def-Prompt|`Prompt`]] имеет собственные revisions и [[Core data structures#^note-claim-prompt-evaluation|контракт оценки]]. Если изменение Prompt меняет код, семантику или контракт использующей его `Program`, оно также проходит [[#Общий lifecycle Program|lifecycle этой Program]].

### Проверка подхода и реализации

Нужно различать проверку подхода и его конкретной реализации. Провал отдельной реализации сам по себе не опровергает underlying `Claim`. Однако повторяющиеся неудачи достаточно разных и корректных реализаций могут становиться evidence против `Claim`, если их нельзя лучше объяснить ошибками реализации, недостатком ресурсов или другими внешними ограничениями.

**Evaluation, evidence assessment и credit assignment**
Evaluation даёт проверяемый result. `EvidenceAssessmentProgram` создаёт evidence для непосредственно проверяемой реализации и связанных `Claim`; `CreditAssignmentProgram` назначает learning credit соответствующим [[Learning system#^def-LearningTarget|LearningTarget]] в контексте опыта. Конкретное состояние для обновления выбирает `UpdatePlanner`. Verification и program tests используются до Evaluation, чтобы отделять ошибки реализации от слабости подхода.

####  Belief update across hypothesis levels

Evaluation обновляет тот уровень, который реально был проверен постепенно генерализуясь от конкртеных реализация к самой идеи (что бы зафиксировать насколько она валидна)

### Parametric update vs structural revision


---



### Parametric update

Parametric update — это изменение параметров внутри уже существующей структуры программы. Автоматический parameter learning применяется к [[Program Layer#Обучаемые и фиксированные компоненты|обучаемым компонентам]] по [[Learning system#Выбор обучаемых компонентов и режима обучения|выбранному режиму обучения]]; он не превращает фиксированные части в обучаемые.

Он применяется, когда опыт можно учесть в существующей структуре, уточнив веса, priors, values, probabilities и другие параметры. Для такого обновления не требуется неожиданное расхождение: обычные ожидаемые исходы также дают обучающие данные.

В стандартном пути состояние estimator-а или параметры программы обновляются через [[Learning system#PreparedUpdate, UpdateTransactionManager and UpdateDispatcher|parameter learning pipeline]]. Для узких задач допустим [[Learning system#Специализированное обучение|отдельный путь специализированного обучения]]. Связанные epistemic beliefs обновляются через [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|evidence lifecycle]]. Изменение значений, закреплённых в коде или версионируемом артефакте самой программы, проходит через `ProgramBranch`.

Критерий:

```text
если можно улучшить программу, не меняя её структуру и contracts
→ parametric update
```

---

### Structural revision

`Structural revision` — непараметрическое изменение модели, программы  
или её смысловых границ.

К structural revision относятся:

```
добавление, удаление или изменение ветви control flow или operator-а;

изменение read_contract или output_contract;

добавление, удаление, замена или перенос обучаемого компонента;

и т.д.
```

Несоответсвие контракта является обычным частным случаем structural revision.

Критерий:

```
если проблему нельзя устранить изменением значений
уже существующих параметров или beliefs
→ требуется structural revision.
```

Structural revision проходит через `ProgramBranch`, semantic change  
или новую `Program` и проверяется через Evaluation.

При таком пересмотре сознание выбирает, какие части программы должны обучаться и как. Новый предиктор и, если предусмотрено обучение, его updater проверяются и активируются вместе с изменением программы; затем parameter updates идут по выбранной схеме. Приостановка или возобновление уже предусмотренного обучения сама по себе не меняет структуру программы.


---

### Dual development of Declarative and Executable Programs

Declarative и Executable программы часто развиваются вместе.

```text
Declarative Model improves process understanding
→ better expected signals
→ better ExecutableProgram / policy program

ExecutableProgram acts and explores
→ produces new experience
→ improves Declarative Model

Evaluation finds mismatch
→ update model, exec, or both
```





## Program Versioning in Git

### Core principle

Код программ EverTree версионируется через Git.

`main` branch репозитория является **активным состоянием программ**.  
Активная версия программы — это код этой программы в `main`.

```text
main branch = текущая активная версия всех программ
feature/fix branch = кандидат изменения
```

`Program` задаёт стабильную идентичность программы, а Git хранит её версии. Epistemic belief относится к конкретной revision, а не безусловно ко всей истории стабильной identity `Program`.


---

### ProgramBranch

**ProgramBranch** — metadata-запись о Git branch, созданной для изменения программы.

Branch используется, когда агент улучшает, чинит или расширяет существующую `Program`, не меняя её принципиальный механизм.

Branch технически относится ко всему репозиторию, но metadata `ProgramBranch.program` показывает, ради какой программы он был создан.

```python
ProgramBranch: Node {
  program: <Program>
  git_ref: <string> # e.g. feature/add_price_sensitivity

    change_claim: <Claim>
    "Проверяемое утверждение о том, почему предлагаемый подход должен улучшить программу."

  source_memory?: <MemoryFact>

  status: "active" | "merged" | "rejected" | "archived"

  created_at: <datetime>
  closed_at?: <datetime>
}
```

Примеры branch:

```text
feature/add_price_sensitivity
fix/enterprise_edge_cases
refactor/negotiation_state_tracking
```


---

### Active code

Активная версия программы всегда читается из `main`. При успешной проверке branch мержится в `main` и автоматически становится активной.

---

### Организация репозитория

Код программ хранится в одном Git-репозитории. При большом количестве моделей единая таксономия задаёт устойчивое размещение и сокращает затраты на поиск и поддержку отдельной классификации файлов.

- **Размещение по таксономии.** Папки процессов и связанных с ними программ следуют [[Semantics Plane#Ось Taxonomy: Таксономия типов (Type → SuperType → …)|`SUBTYPE_OF`]] с одним родителем. Разные модели одного процесса располагаются рядом. Глубина вложенности определяется обоснованной структурой таксономии.
- **Прямой доступ.** Текущая выбранная программа доступна через [[Process Ontology and Semantic Interface#PROGRAM_FOR_PROCESS|`ProcessConcept.active_model` / `active_exec`]]; связь `PROGRAM_FOR_PROCESS` позволяет найти все программы процесса, включая кандидатов и архивные. Код адресуется по [[Program Layer#Program|`Program.git_path`]] — пути к её Python-файлу или модулю. Повторный доступ не требует обхода каталогов или чтения файлов для поиска программы.
- **Согласованное перемещение.** Изменение родителя или имени, затрагивающее размещение, выполняется одной операцией: обновляются граф, папки и `git_path`; перед активацией проверяется их согласованность. Идентичности процессов и программ и их история обучения сохраняются; прежние пути и код остаются доступны в соответствующих Git revisions.
- **Другие пути поиска.** [[Process Ontology and Semantic Interface#Semantic organization: Concept → ProcessConcept → Program|Семантические связи]] позволяют находить процесс по предмету, участникам и другим полезным признакам без второго таксономического родителя и копирования кода в разные папки.
- **Общий код.** `common/` содержит пакеты и модули, не привязанные к конкретному процессу или предметному концепту и переиспользуемые разными программами. Внутри него разрешена обычная организация Python-пакетов по ответственности. Модели разных процессов могут [[Program Layer#Обобщение и сжатие моделей|переиспользовать общий алгоритм]] с разными признаками, параметрами и весами; в папках процессов остаются их привязки и специфический код. Изменение `common/` требует считать затронутыми все программы, зависящие от изменённых файлов.

#### Модули и импорты

Связанный функционал оформляется Python-модулем; начинают с одной функции, добавляя функции и классы по необходимости. Каждому программному модулю соответствует `ProgramModule` — концепт для его организации, поиска и анализа.

- Стандартная библиотека, внешние пакеты и вспомогательные модули собственной программы импортируются обычным способом.
- Общие утилиты разных программ импортируются из `common/`.
- Другие самостоятельные EverTree `Program` вызываются через их объявленные интерфейсы и [[Cognition and Attention#Выполнение задачи (`TaskExecution`)|runtime]], без прямого импорта их внутренней реализации.

Эти границы сохраняют управляемость межпрограммных вызовов и позволяют разбивать одну реализацию на несколько файлов.

---

### Branch management

Правило:

```
active/paused branches — остаются Git branches до принятия решения(EvaluationChoice)
merged branches — удаляются после merge
история есть в main.rejected branches — архивируются, branch ref удаляется.
```
