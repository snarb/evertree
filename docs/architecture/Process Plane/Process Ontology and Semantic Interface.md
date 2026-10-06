

Process ontology организует Concepts, процессы и связанные с ними Programs через семантические отношения.

### Program canonicalization and deduplication

Программы упорядочены через семантические связи согласно [[Core data structures#^04821b |Concept Canonicalization and Semantic Linking]]

### Program-scoped semantic links

Агент может [[Semantics Plane#^e24496|кешировать]] результаты анализа связей и факторов процесса через семантические связи. Он создаёт их только когда это оправдано. Связь может относиться к самому процессу или быть scoped by program, если зависит от конкретной реализации `Program`.

Примеры:

```
PROGRAM_CORRELATES(program, factor, target)
PROGRAM_FACTOR_ROLE(program, factor, target, role)
PROGRAM_NO_EFFECT(program, factor, target)
PROGRAM_EXCLUDES(program, concept_or_relation)
```

Такие связи не являются глобальной истиной мира. Они фиксируют знание, полезное для конкретной программы.

`PROGRAM_EXCLUDES(program, x)` означает, что программа сознательно исключает `x` из учитываемого ею представления процесса как нерелевантное, избыточное или неиспользуемое в данном подходе.

 [[#^0c1eb8|CONTROL_CONFLICT RelationType]]
 
### TransitionType (отношение)

Чтобы описать “какой переход произошёл”, существует TransitionType(отношение).

**TransitionType** — это концепт процессного отношения: тип n-арного изменения во времени.

Лингвистически `TransitionType` соответствует событийному предикату: обычно глаголу или глагольной конструкции, описывающей изменение во времени:  
`BURNS(fuel)`, `MARRIES(person_a, person_b)`, `CONVINCES(person_a, person_b)`.


Он задаёт:

- смысл изменения;
- сигнатуру аргументов;
- роли участников перехода.

Отличие:

[[Semantics Plane#^def-RelationType |RelationType]]   — статическое отношение: PART_WHOLE(wheel, car)
TransitionType — динамическое отношение: BREAKS(agent, object)


Процесс-существительное, например **“Горение”**, — это `ProcessConcept`.  
Глагольный переход **“горит / сжигает”** — это `TransitionType`.

`TransitionType` живёт в общей лестнице абстракции и учавсвует в [[Core data structures#^04821b |Concept Canonicalization and Semantic Linking]]


### ProcessConcept

**ProcessConcept — это обычно **существительное / nominalized process concept**, например :  "Горение", "Запуск двигателя". 

Лингвистически он обычно выражается существительным или номинализацией процесса.

Он отвечает на вопрос: что это за процесс?


```python
ProcessConcept: Concept {
  name: <string>
    "Имя процесса как nominalized process concept: Burning, EngineStart, PokerHandProcess."

  description?: <string>
    "Краткое описание смысла процесса и его границ."

  primary_transition_type?: <TransitionType>
    "Главный глагольный TransitionType, через который процесс обычно проявляется."

  active_model?: <Program>
    "Текущая выбранная Program с model ∈ Program.roles."

  active_exec?: <Program>
    "Текущая выбранная Program с exec ∈ Program.roles."

  belief_data?: <BeliefData>
    "Уверенность в текущем операционном понимании процесса."
}
```

**`Process`** — общий корневой концепт таксономии процессов. Все остальные типы процессов связаны с ним напрямую или через предков отношением [[Semantics Plane#^spec-SUBTYPE_OF|`SUBTYPE_OF`]]. Это конкретный концепт графа; `ProcessConcept` обозначает тип передаваемых объектов. Таксономия связывает виды процессов; составные шаги процесса описываются отдельно.
^def-ProcessRoot

Собственные процессы агента образуют поддерево `SelfProcess` (представление **Self/Process**). Оно связано с общим `Process` через `SUBTYPE_OF`, с Self — через `PART_WHOLE`. Общий `Process` не переносится под Self: он также организует процессы внешнего мира. Начальные подтипы собственной ветви — `TaskManagement`, `CognitiveControl`, `MemoryProcessing` и `Learning`; каталог `src/evertree/processes/` отражает именно эту ветвь.


### Semantic organization: Concept → ProcessConcept → Program

Основной semantic anchor — `Concept`. С ним связываются процессы, относящиеся к этому предмету, а с процессами — Programs, которые их моделируют или исполняют.
^semantic-program-organization

#### PROCESS_SUBJECT

```text
PROCESS_SUBJECT(process: ProcessConcept, subject: Concept)
```

`subject` — основной semantic Concept, относительно которого организован данный `ProcessConcept`. Связь нужна для устойчивой организации и retrieval:

```text
PROCESS_SUBJECT(PromptPreparation, Prompt)
PROCESS_SUBJECT(PromptEvaluation, Prompt)
PROCESS_SUBJECT(PromptOptimization, Prompt)
```

Она не заменяет более точные semantic relations:

```text
PromptPreparation → PRODUCES / TRANSFORMS → Prompt
PromptEvaluation → EVALUATES → Prompt
PromptOptimization → IMPROVES → Prompt
```

`PROCESS_SUBJECT` не назначается искусственно, если у процесса нет естественного основного subject.

#### PROGRAM_FOR_PROCESS

```text
PROGRAM_FOR_PROCESS(program: Program, process: ProcessConcept)
```

Связь означает, что `Program` моделирует или реализует процесс, описанный данным `ProcessConcept`; конкретная функция определяется [[Program Layer#Program roles|`Program.roles`]]. Она охватывает все Programs процесса: active, candidate, alternative, rejected и archived.

`ProcessConcept.active_model` и `ProcessConcept.active_exec` — ссылки на текущие выбранные Programs с соответствующими основными ролями среди всех `PROGRAM_FOR_PROCESS` данного процесса.

Одна `Program` обычно имеет один основной process. Если механизм действительно представляет несколько процессов как единое целое, предпочтительно создать соответствующий composite `ProcessConcept`.

#### Semantic scope and implementation contracts

Уровни не взаимозаменяемы:

```text
ProcessConcept
→ semantic scope процесса;

PROGRAM_FOR_PROCESS
→ какие Programs относятся к процессу;

Program.read_contract / Program.output_contract
→ что конкретная реализация фактически
  читает, предсказывает или изменяет.
```

Контракт конкретной `Program` может покрывать только часть semantic scope процесса. Область модели задаётся её входами, выходами и условиями применения; полное описание остальных аспектов процесса не является условием запуска и проверки. Таксономия и связи с программами сохраняют организацию и поиск, а подробности добавляются по практической необходимости, чтобы не расширять модель без пользы для её задач.

Выход контракта за границы процесса или противоречие его смыслу может потребовать [[Program Lifecycle and Evolution#Structural revision|structural revision]]. Непокрытая часть требует пересмотра конкретной программы только при нарушении её контракта или подтверждённом пробеле, мешающем её заявленному назначению. Новая связь [[#PART_WHOLE in process responsibility|`PART_WHOLE`]] или [[#PROCESS_VARIABLE|`PROCESS_VARIABLE`]] сама по себе такого требования не создаёт.

#### Examples

Оптимизация [[Core data structures#^def-Prompt|`Prompt`]]:

```text
Prompt                                      # Concept
   ↑
PROCESS_SUBJECT
   │
PromptOptimization                          # ProcessConcept
   ↑
PROGRAM_FOR_PROCESS
   │
PromptOptimizationProgram                   # Program
   └── roles = {exec}

PromptOptimization
   ↑
PROGRAM_FOR_PROCESS
   │
PromptOptimizationOutcomeModel
   └── roles = {model}
```

`Prompt` — предмет этих процессов, а подготовка, проверка и улучшение выполняются связанными `Program`. Разные варианты могут обслуживать один семантический интерфейс для разных моделей; [[Core data structures#^note-claim-prompt-evaluation|результат оценки]] относится к проверенным версиям и условиям, а не ко всем вариантам сразу.

Self-improvement:

```text
Program                                     # Concept
   ↑
PROCESS_SUBJECT
   │
ProgramImprovement                          # ProcessConcept
   ↑
PROGRAM_FOR_PROCESS
   │
ProgramLifecycleManagement
   └── roles = {exec, meta}

ProgramImprovement
   ↑
PROGRAM_FOR_PROCESS
   │
ImprovementOutcomeModel
   └── roles = {model}
```

### Маршрутизация наблюдений

(def_id:: entity.ProcessRouter)
> **ProcessRouter** — программа, которая по смыслу наблюдения и контексту задачи определяет подходящий процесс и его конкретное исполнение для вызывающего: сознания или выполняющей задачу `exec`-программы.
> ^def-ProcessRouter

Router вызывается внутри уже установленного контекста `Task`; [[Cognition and Attention#^input-reception|приём входа и первоначальная привязка к задаче]] предшествуют этому вызову. Если результат инструмента уже связан с ожидающим вызовом, runtime доставляет его напрямую. Router нужен, когда смыслового адресата требуется определить или пересмотреть; он не является обязательным шагом для каждого входа.

Router использует семантический поиск по графу: участников, временные связи, [[#^semantic-program-organization|область процесса и связанные Programs]], а также контекст недавно активных исполнений. Он сопоставляет наблюдение с конкретным объектом и эпизодом: две попытки запуска одного двигателя могут принадлежать разным исполнениям одного процесса.

Для одного контекста стандартный путь использует одну выбранную рабочую программу или композицию. При делегировании это `exec`-программа и вызываемые ею модели и подпрограммы; сознание также может непосредственно организовать отдельный вызов. Вызывающий использует результат router, чтобы продолжить подходящее существующее исполнение; новое создаётся, когда начинается отдельный эпизод или требуется новая работа по задаче. Каждое наблюдение само по себе не создаёт новый запуск. Живое или выгруженное состояние исполнения обрабатывает [[Cognition and Attention#^durable-program-execution|runtime]].

Несколько аспектов наблюдения могут требовать разных подпрограмм этой композиции. Это не означает выбор всех альтернативных моделей или независимый запуск каждого найденного процесса. Альтернативы остаются доступны для явной проверки и улучшения в отдельных задачах.

Если подходящего процесса, программы или однозначной привязки к исполнению нет, router возвращает неразрешённый случай вызывающему. Сознание разбирает его в текущей задаче, а `exec`-программа при необходимости запрашивает для своей задачи [[Cognition and Attention#Внимание (`Attention`)|сознательную обработку]]. Создание или изменение программы проходит через [[Program Lifecycle and Evolution|Program Lifecycle]]; результат поиска сам по себе не создаёт готовую модель.

После выбора исполнения вызывающий поручает runtime доставку наблюдения в его [[Program Layer#^process-observation-input|общий типизированный вход]]. Router определяет подходящего адресата, а исполняющая программа определяет смысл наблюдения внутри процесса, текущее состояние и нужные ветви обработки. Это разделение сохраняет единую ответственность за действия и не расходует ресурсы на автоматическое исполнение всех кандидатов.

Выбрав целевую программу, сознание или вызывающая `exec`-программа при необходимости организует [[Program Layer#^def-ArgumentPreparation|`ArgumentPreparation`]] по её интерфейсу и [[Program Layer#^program-input-requirements|`requirements`]], выполняет вызов и учитывает [[Program Layer#^program-feedback|feedback]]. [[Cognition and Attention#^def-Perception|`Perception`]] готовит порученные наблюдения, но не выбирает и не вызывает программу процесса. Это вложенная работа внутри [[Cognition and Attention#^agent-processing-cycle|общего цикла агента]]; взаимодействие показано в [[Program Layer#^perception-requirements-feedback|примере восприятия]].

### Process responsibility structure

#topic_core

`ProcessConcept` задаёт смысл процесса: что это за процесс и каковы его границы на концептуальном уровне.

**Process Responsibility Scope** — это рабочая структура ответственности процесса, производная от:

* `ProcessConcept.description`;
* `PART_WHOLE(part, process)`;
* `REALIZES_PROCESS(transition_type, process_concept)`;
* subtype/special-case links;
* semantic links, созданных после анализа;

Отвечает на вопрос:

```text
какие концепты, изменения, участники и outcomes относятся к этому процессу
на уровне смысла?
```

####  PART_WHOLE in process responsibility


В Process Plane связь `PART_WHOLE(part, process)` используется для задания смысловой структуры процесса: из каких значимых частей состоит процесс как целое.

Общий смысл `PART_WHOLE` остаётся мериологическим:

```text
part является частью whole (состав)
```

В контексте процесса это читается так:

```text
part является частью процесса и может участвовать в его объяснении, prediction, memory retrieval или evaluation.
```

`PART_WHOLE` сам по себе не означает, что программа обязана читать или предсказывать эту часть.

Он только говорит:

```text
эта часть принадлежит смысловой структуре процесса.
```

Дальше возможны разные случаи:

```text
part stable in episode
→ может быть input/context для программы

part changes in episode
→ может стать PROCESS_VARIABLE процесса

part changes, не покрыт программой и выявлен пробел по её контракту или назначению
→ Structural revision 

part оказался нерелевантен
→ сознание агента может удалить связь, ослабить её или оставить как weak semantic association
```

Например:

```text
PART_WHOLE(CardDeal, PokerHandProcess)
```

Если часть процесса осознана как значимая для оценки моделей процесса, агент может дополнительно создать:

```text
PROCESS_VARIABLE(process, part_or_axis)
```



#### PROCESS_VARIABLE

`PROCESS_VARIABLE(process, variable)` — семантическая связь,  
указывающая, что `variable` является значимой изменяемой величиной,  
через которую описывается динамика данного процесса.

```text
PART_WHOLE
→ из каких частей состоит процесс;

PROCESS_VARIABLE
→ значимые изменяемые величины процесса;

TRAJECTOR
→ через какую основную перспективу процесс рассматривается.
```

`PROCESS_VARIABLE` принадлежит semantic model процесса и не зависит  
от конкретной реализации `Program`.

Variable может быть:

```text
observable
→ имеет независимый observation path;

latent
→ выводится моделью и проверяется
  через observable consequences;

deterministic или random;
native property или relation/transition-backed reading.
```

Наблюдаемость определяется относительно конкретного process,  
context и evaluator-а, а не хранится как постоянный тип variable.

Связь не означает, что каждая модель процесса обязана возвращать  
prediction этой variable.

Выбранная для прогнозирования величина выступает как [[Program Layer#^def-PredictionTarget|PredictionTarget]] в контракте модели. Эта роль не создаёт отдельный Concept или estimator автоматически.

Граница между semantic scope процесса и coverage конкретной реализации задана в [[#^semantic-program-organization|Semantic organization]]. Anchored claims отдельно описывают внутреннюю семантическую структуру реализации.

Сопоставление этих уровней даёт:

```text
required output отсутствует во время ProgramRun
→ structural revision;

process variable не покрыта Program, но необходима по её контракту или назначению
→ structural revision;

prediction и observations доступны для проверки
→ применимые метрики; prediction_unexpectedness при наличии основы для калибровки.
```

Прямой [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] вычисляется для observable variable при наличии сохранённого прогноза, основы для калибровки и достаточных наблюдений, не выведенных из самого прогноза. Случайность процесса и зависимости между наблюдениями учитываются в проверке; наблюдения вне её условий и недостаток данных не создают нулевой сигнал.

Latent variable получает evidence косвенно через observable claims  
и downstream outcomes, зависящие от неё.

В `PROCESS_VARIABLE` следует ссылаться на типизированную величину  
с определённым value space и способом чтения. Сырые `RelationType`  
и `TransitionType` не используются напрямую; вместо них задаются  
relation-backed или transition-backed variables.

Примеры:

```text
PROCESS_VARIABLE(PokerHandProcess, CardDeal)

PROCESS_VARIABLE(DiseaseProcess, PatientHealthStatus)

PROCESS_VARIABLE(EngineStartProcess, EngineStartOutcome)

PROCESS_VARIABLE(VehicleMovement, SurfaceUnder)
```

Связь создаётся только если variable ожидаемо полезна для моделирования процесса и семантически опрадана.  
Она не используется для технических runtime variables и малозначимых  
изменений, которые не требуют самостоятельного моделирования.).

Если наблюдается изменение `x`, а активная программа процесса его не предсказывает, выясняется, был ли прогноз обязательным и относится ли наблюдение к scope программы. Нарушение контракта или подтверждённый пробел модели передаётся в structural revision.

Если величина действительно изменяется в рамках процесса, семантически относится к его динамике и её моделирование приносит ожидаемую пользу, она представляется как `PROCESS_VARIABLE`.

Если эти условия не выполняются, величина либо не относится к процессу в строгом смысле, либо считается недостаточно значимой для самостоятельного моделирования.

Граница между значимыми и незначимыми переменными часто неоднозначна и может меняться по мере накопления опыта и является частью обучения модели процесса. Её определяет обучаемая метапрограмма:

```
ProcessVariableCurationProgram
```

#### Random variables as process state variables

#topic_core

Мы считаем random variable тем же способом, которым конкретная программа моделирует `PROCESS_VARIABLE`.

Пример: poker hand.

```text
PART_WHOLE(CardDeal, PokerHandProcess)
PROCESS_VARIABLE(PokerHandProcess, CardDeal)
```

В начале hand:

```text
CardDeal.value = None
```

После раздачи:

```text
CardDeal.value = [Ah, Ks]
```

Неизвестное до раздачи значение `CardDeal.value` не заменяет прогноз. Если программа должна моделировать `CardDeal`, но не возвращает прогноз, требуется structural revision; числовой `prediction_unexpectedness` для отсутствующего прогноза не вычисляется.

Правильная программа не обязана угадать конкретные карты заранее. Она должна вернуть probability profile:

```text
P(card_deal | deck_state, known_cards, rules)
```

Learning dynamics:

```text
1. Наблюдается, что программа не моделирует CardDeal → разбор coverage программы.
2. Агент подтверждает, что отсутствие модели CardDeal нарушает контракт или мешает назначению данной программы → structural revision.
3. Создаётся/усиливается PROCESS_VARIABLE(PokerHandProcess, CardDeal).
4. ProgramBranch добавляет вероятностную модель CardDeal.
5. Выбранные наблюдения проверяются через prediction_unexpectedness с учётом случайности раздачи.
```



Случайность учитывается в форме и проверке прогноза. Распределение или отдельная характеристика, например среднее, выбираются по [[Learning system#Представление прогноза и цель обучения|общим правилам моделирования]].


#### TRAJECTOR

`TRAJECTOR(process, entity_or_axis)` — семантическая связь, указывающая первично выделенного участника или точку зрения, через которую обычно описывается процесс.

Смысл:

```text
entity_or_axis — главный участник/носитель перспективы процесса.
```

Примеры:

```text
TRAJECTOR(DiseaseProcess, Patient)
TRAJECTOR(PokerProcess, Player)
```

`TRAJECTOR` не задаёт `prediction_unexpectedness` и ни к чему не обязывает программу. Это подсказка для:

* retrieval процессов по участнику;
* выбора perspective при объяснении;
* memory search;
* structural alignment.

`TRAJECTOR` может быть изменён или удалён сознанием агента, если текущая перспектива процесса стала неудачной.

### Связь с концептами-существительными


Связь между ProcessConcept и  TransitionType  задаётся семантическим отношением:

```text
REALIZES_PROCESS(transition_type, process_concept)
```

Смысл:

```text
TransitionType является глагольным способом реализации или проявления ProcessConcept.
```

Пример:

```text
REALIZES_PROCESS(BURNS, Burning)
```

Через эту связь EverTree соединяет лингвистические формы одного процесса.





---

### Action Conflicts Control via RelationType
^0c1eb8

Иногда действие физически возможно, но агент понимает, что оно конфликтует с ценностью, supervisor expectation, safety constraint или устойчивым правилом поведения и его важно зафиксировать в семантической памяти для того чтобы избежать существенных рисков или лучше генерализации.


#### Motivation

Семантическая связь `CONTROL_CONFLICT` нужна не для runtime-блокировки, а для памяти, , reflection, генерализации и будущего улучшения программы, но только тогда когда это обоснованно, агент не должен засорять память без необходимости малозначительными связями.


#### RelationType

(formal_id:: relation.CONTROL_CONFLICT.schema)
```python
RelationType CONTROL_CONFLICT {
  name: "CONTROL_CONFLICT"

  description:
    "Семантическая связь, фиксирующая, что действие, оператор или программа конфликтует с управляющим ограничением, ценностью, supervisor expectation или safety constraint в заданном scope. Не является runtime-фильтром выбора действий и не исполняет запрет сама по себе."

  signature: [
    subject = ActionConcept 
      "Что конфликтует"

    constraint = Concept | SignalPattern
      "С чем конфликтует: ценность, supervisor expectation, safety constraint, goal constraint или ожидаемый негативный сигнал."

    scope =  Process | Program | ContextPattern | Global
      "Где конфликт применим."

    expected_signals? = dict[SignalChannel, ExpectedOutcomeSignal]
      "Опциональные прогнозы оценок, например отрицательного value канала supervisor_feedback_signal."
  ]
}
```

Форма `ExpectedOutcomeSignal` задана [[Program Layer#Expected signals|контрактом прогноза сигнала]].
