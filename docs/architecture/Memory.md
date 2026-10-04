
---

## status: draft  
target_version: next

## Intro

#concept #topic_intro

(def_id:: et.Memory)
> [!definition]  
> **Memory** — система фиксации, сжатия, связывания, поиска и переиспользования опыта агента EverTree.  
> Память хранит не только факты о мире, но и следы того, как агент действовал, ошибался, рассуждал, менял программы, обновлял убеждения и становился таким, какой он есть.  
> ^def-Memory

Память EverTree — не архив прошлого.  
Её задача — сделать прошлый опыт доступным для будущего действия, обучения, объяснения, проверки и самоулучшения.

Базовый принцип:

```text
Сохранять щедро.
Консолидировать умно.
Извлекать избирательно.
Удалять осторожно.
```

EverTree не должен пытаться идеально решить в момент записи, что окажется важным. Ранние критерии важности могут быть неточными. Поэтому первичная запись ориентирована на высокий recall: лучше временно сохранить больше, чем потерять важное.

Но сохранение не означает помещение в рабочий контекст. Память может хранить много, а runtime retrieval должен поднимать только то, что полезно для текущего процесса.

---

## Назначение памяти

Память выполняет пять функций. Она

1) хранит опыт: события, [[#^def-Episode|эпизоды]], [[#^def-ProgramRun|ProgramRun]], RunTrace, результаты действий, [[Core data structures#^def-Note|заметки]] с рассуждениями и выводами, ошибки, supervisor feedback, изменения графа и программ.

2) даёт [[Uncertainty and Belief Tracking in the World Model#^def-Evidence|evidence]] для `Strength/Support`. Новое наблюдение не является просто текстом; оно становится основанием для обновления [[Uncertainty and Belief Tracking in the World Model#^def-Belief|belief]], transition weights, hypotheses, process models.

3)  обеспечивает provenance сохраняемых результатов — возможность восстановить, каким вычислением и из каких входов они были получены; см. [[#^def-ResultProvenance|Provenance результата]].```

4) служит источником [[#^def-MemoryReplay|replay]], [[Datasets#^def-Dataset|датасетов]] для обучения и проверки. Сохранённый опыт также используется для анализа и инсайтов.

 5) создаёт основу для retrieval routes: связи между концептами, процессами, программами, outcomes, traces и memories, чтобы агент мог быстро находить релевантный прошлый опыт 

---

## Главное различие: хранение и доступ

Память решает два разных вопроса:

```text
что сохранить
≠
что извлечь сейчас
```

На входе память должна быть широкой.  
На выходе в runtime — избирательной.

```text
storage policy
→ сохранить потенциально ценный след

retrieval policy
→ найти примерно релевантные следы

context policy
→ использовать только малую часть найденного
```

Если воспоминание не попало в текущий retrieval, не факт что оно не забыто. Оно просто проиграло локальную конкуренцию за доступ.


---

## Гранулярность и организация памяти
#topic_core

Опыт исполнения в EverTree организован на трёх уровнях:

```text
ProgramRun
└── SemanticTrace
    └── TraceEvent
```

- **[[#^def-TraceEvent|`TraceEvent`]]** — атомарный факт исполнения семантически размеченного элемента программы.
- **[[#^def-SemanticTrace|`SemanticTrace`]]** — текущий сохраняемый упорядоченный набор `TraceEvent` одного `ProgramRun`. Изначально он может содержать весь trace, а со временем сжиматься до наиболее значимой его части.
- **[[#^def-ProgramRun|`ProgramRun`]]** — конкретный запуск программы и естественная граница одного trace.

Семантические результаты исполнения — [[Core data structures#^def-Facet|`Facet`]], relation и другие semantic objects — не являются элементами `SemanticTrace`. Они создаются outputs соответствующих `TraceEvent` и сохраняют связь с породившим их событием через provenance.

Если программа вызывает другую программу, создаётся дочерний ProgramRun.
Он связывается с точным TraceEvent родительского запуска через
caller_event. Связи `caller_event` позволяют восстановить всю иерархию вложенных `ProgramRun`.

---
## ProgramRun
^ProgramRun
#topic_core

(def_id:: entity.ProgramRun)
> [!definition]  
> **ProgramRun** — конкретный запуск конкретной версии `Program` от её вызова до завершения или прерывания. Он фиксирует контекст выполнения: стабильную identity `Program`, исходную Git revision, применённые в ходе исполнения revision changes, аргументы, режим, время и статус. Семантически значимые события выполнения записываются как связанные [[#^def-TraceEvent|`TraceEvent`]], а текущая сохраняемая часть этого опыта представлена [[#^def-SemanticTrace|`SemanticTrace`]].
> ^def-ProgramRun

Это логический запуск: [[Cognition and Attention#^durable-program-execution|восстановление через DBOS]] продолжает тот же `ProgramRun`. Запуск изменённой программы вместо прежней создаёт новый `ProgramRun`. Техническое восстановление не меняет `run_mode` и не является [[#Replay|Memory Replay]] — отдельной работой над сохранённым опытом.

Каждый корневой или дочерний `ProgramRun` принадлежит `Task`. Корневой запуск связан с задачей, а дочерние наследуют эту принадлежность через `caller_event`. Отдельный запуск не равен всему [[Cognition and Attention#^def-TaskExecution|`TaskExecution`]]: одна задача может продолжаться через несколько запусков и сознательных шагов.

#topic_details 

```python
ProgramRun {
  program: <Program>
    "Вызванная программа."

  base_commit_sha: <string>
    "Точная Git revision Program, с которой началось это исполнение"
    
  revision_changes: <ProgramRevisionChange[]> = [] 
    "Упорядоченные смены revision в необязательном интерактивном режиме; в обычном запуске список пуст."

  caller_event?: <TraceEvent>
    "TraceEvent родительской программы, вызвавший этот ProgramRun.
     Отсутствует только у корневого ProgramRun."

  arguments: <BoundArguments>
    "Аргументы конкретного вызова, автоматически связанные
     с параметрами интерфейса программы."

  run_mode: "live" | "replay" | "simulation" | "evaluation" | "test"

  started_at: <time>
  finished_at?: <time>

  status: "running" | "completed" | "failed" | "interrupted"
}
```

---

### Автоматическая фиксация аргументов программы

#topic_details 

### Интерфейс программы

Аргументы и возвращаемые значения Program всегда считаются частью semantic surface и фиксируются автоматически.

При создании [[#^def-ProgramRun|`ProgramRun`]] tracer автоматически фиксирует фактические аргументы вызова программы и связывает их с параметрами её интерфейса (используя Pydantic-модели). Фиксируются и возвращаемые значения программы.

Успешный возврат `Program` всегда имеет форму [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult[T]`]]: tracer сохраняет основной результат и опциональный текстовый feedback вместе. Их семантические роли различаются; feedback не включается в доменный прогноз или наблюдение.

Если аргумент является объектом или состоянием графа, сохраняется ссылка на соответствующий [[Core data structures#^def-Facet|Facet]] (как правило), либо [[Core data structures#^def-Concept|Concept]], [[Core data structures#^def-Instance|Instance]] или relation instance.

Небольшое значение, включая ответ LLM, может сохраняться непосредственно в аргументах или output. Большое содержимое может храниться в [[Core data structures#^def-Artifact|`Artifact`]] со ссылкой на его точную использованную версию. Способ хранения не меняет семантический смысл значения и не требует материализовать каждый payload как `Facet` в persistent graph.

---
## Вложенные вызовы программ

#topic_details 


Каждый семантически значимый вызов `Program` создаёт отдельный дочерний [[#^def-ProgramRun|`ProgramRun`]].
`caller_event` связывает дочерний запуск с точным [[#^def-TraceEvent|TraceEvent]] anchored-оператора вызова.

Пример:

```text
TreatmentPlanningRun
  ↓ EvaluateAlternative(Igor, NoTreatment)
DiseaseProgressionModelRun
  ↓ classify_mortality(...)
MortalityClassifierRun
```

По caller_event можно восстановить всю иерархию вложенных запусков:

```text
TreatmentPlanningRun
└── DiseaseProgressionModelRun
    └── MortalityClassifierRun
```

Для любого результата можно подняться по дереву:

```text
result
→ producer TraceEvent
→ ProgramRun
→ caller TraceEvent
→ parent ProgramRun
→ ...
```

Это задаёт semantic call context результата.

### Сценарные ветви

#topic_details 

Если программа моделирует несколько независимых возможных сценариев, каждый сценарий, материализующий собственные состояния, запускается как отдельный дочерний [[#^def-ProgramRun|ProgramRun]].



---

## TraceEvent

[#topic_core](https://chatgpt.com/c/6a76ef70-b45c-83eb-b38e-7e97e9e580f9#topic_core)

(def_id:: entity.TraceEvent)
> [!definition]  
> **TraceEvent** — неизменяемая запись одного семантически значимого шага исполнения `Program` внутри конкретного [[#^def-ProgramRun|`ProgramRun`]].
> ^def-TraceEvent

Он фиксирует выполненный `OperatorConcept`, фактические аргументы, результат, порядок и статус выполнения.

Каждый `TraceEvent` принадлежит ровно одному `ProgramRun`.

[[#^def-SemanticTrace|`SemanticTrace`]] данного `ProgramRun` хранит упорядоченные ссылки на те `TraceEvent`, которые в текущем состоянии памяти сохраняются как значимая часть опыта. Сразу после исполнения он может включать все события run; позднее часть событий может быть исключена при компактизации памяти.

```python
TraceEvent {
  program_run: <ProgramRun>
    "ProgramRun, внутри которого произошло событие."

  seq: <int>
    "Монотонный порядок TraceEvent внутри ProgramRun."

  occurred_at: <time>
    "Физическое время выполнения события в системе агента."

  operator: <OperatorConcept>
    "Семантически размеченный оператор Program,
     выполнение которого зафиксировано событием."

  arguments: <BoundArguments>
    "Фактические аргументы оператора, связанные
     с параметрами его интерфейса."

  output?: <OperatorOutput>
    "Неизменяемый типизированный результат оператора."

  status: "completed" | "failed" | "interrupted"
}
```

`seq` задаёт порядок исполнения внутри `ProgramRun`; сам по себе этот порядок не означает причинную связь между событиями.

`TraceEvent` после создания не переписывается. При сжатии памяти изменяется состав `SemanticTrace`, а исходный `TraceEvent` может быть физически удалён только позднее, если больше не требуется для сохраняемого опыта или provenance.

---
### Автоматическая фиксация результата

#topic_details 

Результат каждого anchored-оператора автоматически фиксируется в [[#^def-TraceEvent|`TraceEvent.output`]] как типизированный [[#^def-OperatorOutput|`OperatorOutput`]].

Его semantic projection и provenance строятся tracer-ом согласно контракту типа результата.

Локальное имя Python-переменной не влияет на смысл или identity результата, но предпочтительно, чтобы оно однозначно отражало его смысл.

Присваивание результата другой переменной не создаёт новый semantic object. Промежуточные вычисления могут оставаться обычными Python-переменными; требования к их восстановлению определяет [[Cognition and Attention#^durable-program-execution|контракт исполнения DBOS]].

---

### OperatorOutput

#topic_details

(def_id:: entity.OperatorOutput)
> [!definition]  
> **OperatorOutput** — неизменяемый типизированный результат anchored-оператора, представляющий одно семантически связное целое и задающий роли его именованных частей. Сохраняется в [[#^def-TraceEvent|`TraceEvent.output`]].
> ^def-OperatorOutput

```python
from pydantic import BaseModel, ConfigDict

class OperatorOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
```   

[[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult[T]`]] — частный случай `OperatorOutput` для границы вызова `Program`. Его смысловое целое — результат этого вызова; `result` проецируется по своему доменному контракту, а `feedback` отдельно представляет обратную связь по выполнению.
    
Если тип результата имеет самостоятельный и повторно используемый доменный смысл, ему соответствует обычный доменный [[Core data structures#^def-Concept|`Concept`]]. Concept создаётся один раз, а каждое выполнение оператора создаёт новый экземпляр результата.

---

### Семантическая интерпретация OperatorOutput
#topic_details

Тип [[#^def-OperatorOutput|`OperatorOutput`]] задаёт semantic contract: как весь output и его именованные части проецируются в trace-local semantic objects и facts.

Например, для anchored-оператора, не являющегося отдельной `Program`:

```python
health: HealthState = diagnose(igor)  # et:op=diagnose_health
```

```python
HealthState {
  instance = Igor
  valid_from = "2026-07-17T12:00"

  health_status = {
    belief_data = Profile {
      strengths = {Healthy: 0.05, Sick: 0.90, Recovering: 0.05}
      support = ...
      prior_support = ...
    }
  }

  temperature = {
    value_U = 39.1 Celsius
    belief_data = BeliefData(...)
  }
}

TraceEvent_E19.output = health
```


Семантический контракт `HealthState` задаёт его проекцию в [[Core data structures#^def-Facet|Facet]]; эпистемические поля используют [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] или [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]:

```
output
→ Facet F;

output.instance
→ STATE_IDENTITY(F, Igor);

output.health_status
→ CompetitionScope {
     alternatives = [
       CLASSIFIED_AS(F, Healthy),
       CLASSIFIED_AS(F, Sick),
       CLASSIFIED_AS(F, Recovering)
     ]
   };

output.temperature
→ HAS_NUMERIC_VALUE(
     F,
     Temperature,
     39.1,
     Celsius
   ).
```

Поля `health_status` и `temperature` не содержат ручную ссылку на `F`.  
Согласно контракту `HealthState`, они описывают тот же `Facet`, который  
представляет весь output. Поэтому их невозможно случайно отнести к другому состоянию.

Tracer не выводит этот смысл из имени локальной переменной или значения  
строки. Он использует тип результата и семантические роли его полей.

После выполнения операторa tracer автоматически:

```
1. создаёт TraceEvent;
2. сохраняет OperatorOutput;
3. строит его trace-local semantic projection;
4. назначает provenance каждому semantic result.
```

Все поля здесь описывают части одного результата `HealthState`; domain-код не связывает их с `Facet F` вручную. Tracer использует тип результата и семантические роли его полей.

### Составной результат

Один [[#^def-OperatorOutput|`OperatorOutput`]] может содержать несколько semantic objects, если вместе они образуют одно смысловое целое. В этом случае результат представляется экземпляром соответствующего доменного [[Core data structures#^def-Concept|`Concept`]].

Такой `Concept` может уже существовать в графе либо быть сознательно создан агентом, если выявленный тип результата имеет самостоятельный и повторно используемый смысл.

Например:

```text
TransferOutcome#42
├── sender_state: Facet
└── receiver_state: Facet
```

```
TransferOutcome
→ устойчивый Concept результата;

TransferOutcome#42
→ экземпляр результата конкретного выполнения.
```

Если несколько результатов не образуют одного смыслового целого, их следует вычислять отдельными anchored-операторами.

Созданные semantic results по умолчанию остаются trace-local. Если результат должен стать частью persistent модели мира, программа явно применяет `GraphDelta`.

Связь результатов с создавшим их `TraceEvent.output` описана в [[#^def-ResultProvenance|Provenance результата]].

### Observation

(def_id:: entity.Observation)
> [!definition]
> **Observation** — типизированный доменный [[#^def-OperatorOutput|`OperatorOutput`]] в роли наблюдения: результат [[Cognition and Attention#^def-Perception|восприятия]], чтения источника или инструмента, описывающий полученные сведения о мире или агенте.
> ^def-Observation

Это роль результата, а не обязательная обёртка `Observation(data=...)`. Например, `EngineState` может быть результатом прогноза или наблюдения; их различают конкретные экземпляры и provenance.

Если производитель — `Program`, её [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult.result`]] для доставки как наблюдения должен иметь доменную схему `OperatorOutput` с этой семантической ролью. Оболочка с feedback не становится наблюдением. Произвольный `str` или `float`, возвращённый другой программой, не поступает в канал наблюдений автоматически. Доставка сохраняет тип, identity и provenance доменного результата.

Схема задаёт доступные поля и их смысл: например, значение температуры и единицу измерения. Семантические ссылки связывают результат с объектом, свойствами и понятиями графа. Новое понятие не требует отдельного Python-класса, если его выражает существующая схема. Для интерпретации сохраняются источник, время наблюдаемого события и время получения; неизвестные значения и неоднозначность остаются явными. Типизация не делает сообщение источника достоверным фактом.

Память сохраняет собственный опыт агента и сведения о чужом опыте из рассказов, документов и других внешних источников. Для внешнего опыта сохраняются происхождение, основания оценки надёжности источника и известные зависимости между сообщениями. Результаты simulation и синтетические примеры остаются различимы с наблюдениями реальных событий.

Наблюдение может содержать несколько признаков одного состояния или исходный блок с несколькими связанными сведениями, в том числе о разных моментах. Полное разбиение на отдельные утверждения до выбора процесса не требуется. Исходное содержимое, его порядок, известные временные связи и provenance сохраняются для последующего разбора. [[Process Plane/Program Layer#^observation-granularity|Детализация]] выбирается при подготовке данных для конкретной обработки.

Наблюдения по умолчанию сохраняются в trace. Если наблюдаемое состояние нужно в persistent модели мира, оно материализуется через [[Core data structures#Изменение persistent graph|`GraphDelta`]]. Отдельный persistent `Facet` для каждого поступившего значения не обязателен.

[[Cognition and Attention#^input-reception|Приём входа]] связывает его с существующей или минимальной новой `Task`. Runtime доставляет результат известному ожидающему вызову напрямую. Если адресата нужно определить по смыслу, сознание или выполняющая задачу `exec`-программа использует [[Process Plane/Process Ontology and Semantic Interface#^def-ProcessRouter|`ProcessRouter`]] и поручает runtime доставку выбранному исполнению. Правила чтения, типизации и ветвления описаны в [[Process Plane/Program Layer#^process-observation-input|общем входе наблюдений]]. Доставка и повторное чтение при восстановлении сохраняют identity исходного наблюдения и его producer provenance; события его использования не превращают его в новый опыт.

---

## SemanticTrace
^SemanticTrace

#topic_core


(def_id:: entity.SemanticTrace)
> [!definition]  
> **SemanticTrace** — сохраняемая упорядоченная часть [[#^def-TraceEvent|`TraceEvent`]] конкретного [[#^def-ProgramRun|`ProgramRun`]]. Он представляет ту часть исполнения программы, которая в текущем состоянии памяти считается полезной для сохранения.
> ^def-SemanticTrace

`SemanticTrace` не копирует содержимое событий, а хранит ссылки на них:

```python
SemanticTrace {
  run: <ProgramRun>
  events: ordered List<TraceEvent>
}
```

Все события принадлежат этому же `ProgramRun` и сохраняют исходный порядок по `TraceEvent.seq`.

Сразу после выполнения `SemanticTrace` обычно содержит все `TraceEvent`
данного `ProgramRun`. Позднее [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] может оставить
только ту их часть, которую полезно или необходимо сохранять.

Детальный lifecycle описан в разделе
[[#Компактизация SemanticTrace]].



### Полный trace вложенного исполнения

Каждый [[#^def-ProgramRun|`ProgramRun`]], включая дочерний, имеет собственный [[#^def-SemanticTrace|`SemanticTrace`]].

```text
Root ProgramRun
├── SemanticTrace(root)
├── Child ProgramRun A
│   └── SemanticTrace(A)
└── Child ProgramRun B
    └── SemanticTrace(B)
```

Связи `caller_event` между родительскими и дочерними `ProgramRun` образуют дерево вызовов. Полный сохранённый опыт корневого запуска восстанавливается обходом этого дерева и чтением `SemanticTrace` каждого `ProgramRun`.

Глобальный [[#^def-TraceEvent|`TraceEvent.seq`]] позволяет при необходимости представить все сохранённые события дерева как одну временную последовательность.


---

### Эпизод

(def_id:: entity.Episode)
> [!definition]  
> **Эпизод** — доменная единица опыта с определяемыми границами: например, одна poker hand, один запуск двигателя, один диалог или один эксперимент.
> ^def-Episode

Эпизод представлен обычным [[Core data structures#^def-Instance|Instance]] соответствующего процесса или события. Его текущее lifecycle-состояние выражается через [[Core data structures#^def-Facet|Facet]].

Эпизод не является техническим контейнером trace. Связанные с ним [[#^def-ProgramRun|ProgramRun]], [[#^def-TraceEvent|TraceEvent]] и semantic results находятся через semantic links и provenance.

Каждый элемент опыта относится к одному наиболее конкретному `primary Episode`.
Связи с более крупными Episode, Task, Goal и Process задаются отдельно
и не меняют его primary episode.

Одна `Task` может работать с несколькими эпизодами, а один эпизод — использоваться несколькими задачами. Список эпизодов внутри представления задачи содержит ссылки и не задаёт исключительного владения. Время помогает найти подходящий эпизод, но поздний вход может относиться к прежнему эпизоду; выбор учитывает смысл и известные связи, а не только близость поступления.

### Task, Goal и другие организующие концепты

Задачи, цели, намерения, наблюдения и [[Core data structures#^def-Note|заметки]] являются обычными семантическими объектами графа. Связь с исходной задачей восстанавливается через цепочку родительских [[#^def-ProgramRun|ProgramRun]] и их caller_event.

Подзадачи и более крупные задачи могут связываться обычными семантическими отношениями:

```text
PART_WHOLE(subtask, task)
```

К семантическим организующим концептам могут быть привязаны `Program`, но отдельная `Program` не обязательна для каждой `Task`: одноразовая задача может выполняться через task-local `Plan`. [[Cognition and Attention#^def-TaskExecution|`TaskExecution`]] обозначает весь процесс выполнения задачи, который может включать множество `ProgramRun` и сознательных шагов. Условия создания переиспользуемого механизма определены в [[Cognition and Attention#Планирование (Planning)|`Planning`]], а каждый фактический запуск `Program` сохраняется как [[#^def-ProgramRun|`ProgramRun`]].

Основу семантического графа отвечающую за таксономия планирования и управления активностью агента мы опредляем в отдельном подразделе:   ...

### Кэш активных задач и эпизодов
^active-state

`active_state` — часть Memory: оперативный кэш ссылок на недавно активные `Task` и связанные с ними эпизоды для быстрого доступа. Объекты хранятся в памяти, а кэш содержит восстанавливаемые ссылки на них. Политика памяти ограничивает его объём выделенным бюджетом и пересматривает состав по давности использования и состоянию задач. Начальный способ освобождения места — вытеснять давно неиспользуемые ссылки; стратегия удержания может уточняться по опыту. Удаление ссылки из кэша оставляет объект доступным через обычный поиск в памяти; срок хранения самого объекта определяется [[#Удержание, сжатие и забывание|общим lifecycle памяти]].

Выбор текущего эпизода, текущая версия собираемого объекта и условие ожидания — существенное состояние выполнения. Оно сохраняется в [[Cognition and Attention#^working-context|`TaskState`]], [[#^def-ProgramRun|`ProgramRun`]] или восстанавливается из trace, а не существует только в кэше. Память управляет хранением и временем жизни записей; программа определяет содержательные изменения, которые runtime применяет через действующие интерфейсы.


---

## Provenance результата

#topic_core

(def_id:: et.ResultProvenance)
> [!definition]  
> **Provenance результата** — вычисляемый подграф его происхождения и использования: каким [[#^def-TraceEvent|`TraceEvent`]] результат был создан, в каком [[#^def-ProgramRun|`ProgramRun`]] и версии `Program`, из каких входов и существенных промежуточных результатов он был получен и где затем использовался.
> ^def-ResultProvenance

Provenance нужен для:

- объяснения результатов и изменений системы;
- audit и debugging;
- replay и Evaluation;
- пересчёта и отзыва belief;
- безопасного сжатия памяти.

Provenance не хранится как отдельная текстовая история или дублирующий semantic graph. Он восстанавливается из `TraceOutputRef`, сохранённых `TraceEvent`, их input/output dependencies и соответствующих `ProgramRun`.

### Фиксация происхождения

#topic_details

Каждый выполненный anchored-оператор создаёт [[#^def-TraceEvent|`TraceEvent`]]. Конкретный semantic result внутри output адресуется неизменяемой ссылкой:

```python
TraceOutputRef {
  event_ref: <TraceEvent identity>
    "Устойчивый адрес TraceEvent, создавшего результат."

  output_path: <OutputPath>
    "Стабильный именованный путь к результату внутри TraceEvent.output."
}
```

`output_path` может указывать на весь output или его именованную semantic part. `TraceOutputRef` является сохраняемым адресом по [[Core data structures#Объекты и ссылки|общему правилу объектов и ссылок]].

У возврата `Program` пути различают `result`, его именованные части и `feedback`. Чтение `.result` не создаёт новый semantic object или независимое evidence. Если программа возвращает уже существующий результат, его исходные identity и producer provenance сохраняются; новая оболочка фиксирует возврат этого значения, а не повторное получение опыта.

Semantic result, материализованный из output, получает:

```text
created_by: <TraceOutputRef>
```

`created_by` назначается tracer-ом автоматически.

Аргументы `TraceEvent` сохраняют ссылки на использованные semantic results. Аргументы и возвращаемые значения `Program` всегда входят в его semantic surface и фиксируются tracer-ом автоматически, поэтому provenance не обрывается на границах вызова программы.

Происхождение восстанавливается обратным проходом:

```text
result
→ created_by
→ producer TraceEvent
→ его inputs
→ producers этих inputs
→ существенные control-flow events
→ ProgramRun
→ Program и его версия
```

Если вычисление проходило через вложенные программы:

```text
child ProgramRun.caller_event
→ TraceEvent родительского ProgramRun
```

связывает их provenance.

Поэтому provenance обычно является подграфом зависимостей, а не одной линейной цепочкой.

### Trace-local и persistent results

Semantic result может существовать в двух состояниях.

(def_id:: entity.TraceLocalResult)
> [!definition]  
> **Trace-local result** — результат конкретного вычисления, принадлежащий опыту данного [[#^def-ProgramRun|`ProgramRun`]]. Он доступен последующим операторам этого выполнения и сохраняется вместе с trace, но **не является частью persistent semantic graph** агента.
> ^def-TraceLocalResult

(def_id:: entity.PersistentResult)
> [!definition]  
> **Persistent result** — semantic object или relation, который агент явно сохранил в своей долговременной модели мира или самого себя. Он доступен другим `ProgramRun`, обычному graph reasoning и долговременному retrieval независимо от исходного запуска.
> ^def-PersistentResult

По умолчанию **все результаты anchored-операторов являются trace-local**.

Это позволяет свободно вычислять:

```text
гипотезы;
промежуточные состояния;
simulation results;
временные выводы;
и т.п.
```

не превращая каждый промежуточный результат в долговременный факт.

Если программа/сознание агента решает сохранить результат как часть persistent модели, она делает это явно через `GraphDelta`:

```text
trace-local result
→ GraphDelta
→ persistent semantic graph
```

Таким образом, `GraphDelta` является явной границей:

```text
вычислить
≠
сохранить как долговременное знание
```

#### Provenance

#topic_details 

Trace-local result получает `created_by`, указывающий на [[#^def-TraceEvent|`TraceEvent`]], который его вычислил.

При записи в persistent graph graph-writing `TraceEvent` фиксирует `GraphDelta` и исходные semantic results, на основании которых выполняется изменение.

Поэтому provenance persistent result остаётся прослеживаемым:

```text
persistent result
→ graph-writing TraceEvent
→ source trace-local result
→ producer TraceEvent
→ ...
```

`GraphDelta` не делает результат истинным или более уверенным. Он только фиксирует решение поместить его в persistent semantic graph. Истинность и уверенность по-прежнему определяются `Belief_data`.

#### Lifecycle

Trace-local results обычно живут вместе со своим [[#^def-SemanticTrace|`SemanticTrace`]] и могут быть сжаты или удалены при компактизации памяти, если больше не нужны для provenance, evidence, replay или других обязательств сохранности.

Присваивание нового значения локальной переменной или завершение Python-функции не удаляет сохранённые результаты, ещё нужные для продолжения задачи, восстановления или проверки; они защищаются общими [[#Обязательства сохранности|обязательствами памяти]].

Persistent results имеют независимый от исходного trace lifecycle и сохраняются в semantic graph, пока сами не будут обновлены, обобщены, отозваны или удалены согласно lifecycle persistent graph.

### SemanticTrace и сохранение provenance
#topic_details

[[#^def-SemanticTrace|`SemanticTrace`]] содержит упорядоченную сохраняемую часть [[#^def-TraceEvent|`TraceEvent`]] своего [[#^def-ProgramRun|`ProgramRun`]].

Он не задаёт зависимости происхождения: они определяются `TraceOutputRef`, inputs/outputs событий и связями между `ProgramRun`.

Но `SemanticTrace` участвует в lifecycle provenance, поскольку определяет, какая часть trace переживает компактизацию; необходимые зависимости образуют [[#^def-RetentionClosure|`Retention closure`]]:

```text
TraceOutputRef + event dependencies
→ задают provenance

retention closure
→ определяет минимальные trace-данные,
  которые необходимо сохранить

SemanticTrace
→ хранит сохраняемую часть опыта ProgramRun
```

Сразу после выполнения trace может сохраняться полностью. Позже [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] оставляет только события и данные, необходимые для будущего использования.

Если полная raw-форма retained `TraceEvent` компактизируется, его identity и данные, необходимые для разрешения `TraceOutputRef` и обещанного provenance, должны сохраняться. Это не создаёт новый тип события: логически это остаётся тот же `TraceEvent`.

### Retention provenance

#topic_details 

Пока результат защищён и его provenance должен быть восстановим:

```text
created_by
→ защищает producer TraceEvent;

retention closure
→ защищает необходимые upstream events,
   inputs и control-flow dependencies;

ProgramRun
→ сохраняется в объёме, необходимом для
   program/version и call provenance.
```

Нельзя физически уничтожить [[#^def-TraceEvent|`TraceEvent`]], на который указывает действующий `created_by`, оставив dangling `TraceOutputRef`.

Остальные события могут быть удалены из сохраняемого [[#^def-SemanticTrace|`SemanticTrace`]], переведены в холодное хранение и позднее физически удалены, если они не требуются для:

```text
provenance защищённых результатов;
evidence и пересчёта belief;
replay или Evaluation;
сохраняемого решения или изменения Program;
других обязательств сохранности.
```

После проверенного сжатия или обобщения глубина сохраняемого provenance может быть уменьшена, если соответствующие старые зависимости больше не входят в [[#^def-RetentionClosure|`Retention closure`]].

### Основные views

#topic_details

```text
producer_of(value)
→ TraceOutputRef, создавший value

consumers_of(value)
→ сохранённые TraceEvents и input slots,
  где value использовался

provenance_of(value, max_depth?)
→ upstream-подграф происхождения value

dependents_of(value, max_depth?)
→ сохранённые downstream-зависимости value
```

Эти views вычисляются над trace storage и не создают дублирующих semantic relations.

Для защищённого результата `provenance_of(...)` должен оставаться восстановимым в пределах сохранённого `retention closure`.

`consumers_of(...)` и `dependents_of(...)` отражают сохранённую историю и после допустимого удаления старых traces не обязаны представлять все когда-либо существовавшие downstream-использования.

`dependents_of` показывает вычислительную зависимость, но сам по себе не утверждает причинный эффект.

---

## Semantic relations и память

#topic_core

`RelationInstance` подчиняется общему lifecycle semantic results: по умолчанию она trace-local, а при долговременной ценности материализуется через `GraphDelta`.

Persistent semantic relations используются как:

```text
факты и обобщения модели мира;
knowledge cache результатов reasoning;
retrieval routes между связанными концептами и опытом.
```

При консолидации нескольких случаев может быть создана обобщённая relation:

```text
scenario results
+ observations
+ evaluations
→ ConsolidationProgram
→ generalized relation
```

Например:

```text
CAUSES_UNDER(
  cause = Infection,
  effect = Death,
  condition = NoTreatment
)
```


---




## Извлечение памяти

#topic_details

Память извлекается из двух связанных хранилищ:

```text
persistent semantic graph
→ долговременные Facets, facts, relations и обобщения;

trace storage
→ опыт выполнения программ:
   ProgramRun,
   SemanticTrace,
   сохранённые TraceEvent,
   их arguments и OperatorOutput.
```

Исходные сообщения пользователя, фактически отправленные ответы, вызовы инструментов и их результаты сохраняются как источники и соответствующий опыт в trace. Для восстановления контекста сохраняются автор или роль, порядок, известные времена и связи с задачей, эпизодом или вызовом. Запись попытки отправки или неизвестного исхода не выдаётся за подтверждённую доставку; внутренний ответ LLM сам по себе не является сообщением пользователю.

[[Cognition and Attention#^context-preparation|`ContextPreparation`]] извлекает нужные недавние и более ранние источники и результаты для задачи, эпизода и текущей работы. Ему доступно точное сохранённое содержимое либо уже сжатое представление с известной потерей подробностей. Сжатие представления для конкретного вызова не удаляет исходник: срок его хранения определяется [[#Удержание, сжатие и забывание|общим lifecycle памяти]].

[[#^def-SemanticTrace|`SemanticTrace`]] определяет, какие [[#^def-TraceEvent|`TraceEvent`]] конкретного [[#^def-ProgramRun|`ProgramRun`]] сохраняются как доступная часть его опыта.

Смысл события задаётся:

```text
operator;
типизированными arguments;
контрактом TraceEvent.output.
```

Контракт [[#^def-OperatorOutput|`OperatorOutput`]] предоставляет trace-local semantic projection результата. Её элементы адресуются через `TraceOutputRef`, но не являются отдельным источником памяти.

Если результат должен стать частью долговременной модели мира, программа материализует соответствующие semantic objects или facts через `GraphDelta`:

```text
TraceEvent.output
→ GraphDelta
→ persistent semantic object / fact
```

Persistent-объект сохраняет provenance к исходному `TraceEvent.output`.

Основные пути извлечения:

```text
persistent semantic object
→ created_by / TraceOutputRef
→ TraceEvent
→ ProgramRun
→ SemanticTrace;

Program / Task / time range
→ ProgramRun
→ SemanticTrace
→ retained TraceEvent
→ arguments и output;

semantic query
→ persistent semantic graph
   и semantic indexes над сохранёнными TraceEvent.output
→ соответствующие semantic objects или TraceEvents.
```

Поиск может начинаться, например, с [[Core data structures#^def-Instance|Instance]], [[Core data structures#^def-Facet|Facet]], [[Core data structures#^def-Concept|Concept]] или [[Semantics Plane#^def-RelationType|RelationType]]:

```text
Instance;
Facet;
Concept;
RelationType;
Program;
ProgramRun;
Task;
Note;
Claim;
Prompt;
SignalSample;
time range.
```



---
---


## Удержание, сжатие и забывание

### Мотивация и базовая модель

(def_id:: concept.Forgetting)
> [!definition]  
> **Забывание в EverTree** — управляемое уменьшение объёма памяти при сохранении того, что ещё необходимо для действия, обучения, пересмотра знаний, объяснения и генерализации.
> ^def-Forgetting

Ценность опыта часто становится понятна только позже.. Рутинный сегодня [[#^def-ProgramRun|`ProgramRun`]] может оказаться важным после обнаружения новой зависимости, ошибки модели или изменения оценки источника. Поэтому исходный опыт сначала сохраняется достаточно полно, а необратимое удаление выполняется только после проверки.

Память и применимые к данному опыту `ProcessModel` развиваются совместно: новый опыт уточняет модели процесса, а достаточно подтверждённые модели позволяют компактнее представлять уже объясняемый ими повторяющийся опыт. **Сжимается не просто то, что модель объясняет, а то, чья детализация обоснованно признана избыточной.**

Память не обязана обеспечивать точное восстановление всего прошлого или обучение любой будущей модели. Она сохраняет достаточно сведений для текущих обязательств и ожидаемо полезного дальнейшего обучения, включая возможность пересмотреть нынешнее понимание опыта.

Есть две базовые операции:

```text
compact
→ уменьшить сохраняемую подробность опыта,
  при необходимости создав компактную замену;

delete
→ поместить ненужные данные в очередь на удаление.
```

Обычный lifecycle:

```text
полное зарегистрированное представление опыта
на протяжении initial_full_retention_period
        ↓
review
        ↓
keep / compact / delete
        ↓
для данных, получивших delete:
восстановимость на протяжении deleted_protection_period
        ↓
повторная проверка обязательств сохранности
        ↓
физическое удаление
```

Каждый объект памяти периодически рассматривается [[#^def-ExpirienceCompactionJob|`expirience_compaction_job`]] по [[#Сроки пересмотра памяти|расписанию пересмотра]]. **Полнота относится к semantic surface опыта**, а не ко всем техническим деталям исполнения.

Также агент может сознательно запустить компактизацию.

#### Сроки пересмотра памяти

**`memory_compaction_ladder`** — задаваемая разработчиком обязательная лестница пересмотров в конфигурации runtime: непустой Python-кортеж положительных, строго возрастающих длительностей **от создания объекта**. Пример с фиксированными длительностями в днях:

```python
from datetime import timedelta

memory_compaction_ladder: tuple[timedelta, ...] = (
    timedelta(days=7),
    timedelta(days=30),
    timedelta(days=365),
    timedelta(days=3650),
)

initial_full_retention_period = memory_compaction_ladder[0]
```

`initial_full_retention_period` — используемое далее имя первой ступени, вычисляемое из лестницы; отдельного параметра конфигурации нет. После последней ступени пересмотры повторяются с периодом `memory_compaction_ladder[-1]`: в примере следующие сроки — 7300 и 10950 дней от создания.

`CompactExpirienceProgram` или сознание может назначить более ранний пересмотр с указанием причины, но не отодвинуть обязательный срок или изменить лестницу. Досрочная проверка не сдвигает последующие сроки и не отменяет очередную обязательную. Засчитать её вместо ближайшей обязательной можно только в пределах небольшого допуска до этой даты, заданного в конфигурации.

Существенное изменение объекта через `GraphDelta`, завершение связанной задачи, изменение [[#Обязательства сохранности|обязательств сохранности]], обнаруженная ошибка или более подходящее обобщение также ставят затронутые записи на досрочный пересмотр. Уже учтённые при проверке изменения не создают повторную заявку. Лестница ограничивает ожидание регулярной проверки, но не заменяет реакцию на новые обстоятельства.

Срок означает обязательное включение объекта в `review batch` ближайшего запуска job. Обработка проходит через [[Cognition and Attention#^sequential-tasks|общий порядок последовательного исполнения]]; наступивший пересмотр остаётся ожидающим до фактической проверки. Постановка в очередь или неудачная попытка не считаются выполненным пересмотром.

Runtime сохраняет выполненные и ожидающие пересмотры. Решение `keep`, изменение существующего объекта или его сжатие не обнуляют возраст и расписание; при замене компактным представлением обязательства пересмотра переносятся на него.

При каждой проверке выбирается `keep / compact / delete` по [[#Проверка сжатия и ответственность|общим правилам]]. Досрочный пересмотр не сокращает `initial_full_retention_period` и не отменяет обязательств сохранности. Для `delete` действует [[#Delete и deleted_protection_period|lifecycle удаления]] без ожидания следующей ступени; отмена `delete` возвращает объект к прежнему расписанию, включая ожидающие пересмотры.

#### Адаптивная подробность хранения

#topic_details 

Подробность выбирает  `CompactExpirienceProgram` учитывая давность, [[#^def-MemorySignificance|значимость]] и воспроизводимость опыта, применимость моделей, их `BeliefData`, незавершённые задачи и общий бюджет памяти.

**Недавний опыт сохраняется подробнее независимо от уверенности модели.** Он нужен для проверки прогнозов, выявления неучтённых зависимостей и обнаружения изменений процесса. При решении о дальнейшем сжатии учитываются количество подходящих наблюдений, задержки outcomes и временной масштаб процесса: одной давности недостаточно.

**Уверенность и `BeliefData` влияют на допустимость потери информации.** При прочих равных подтверждённая закономерность позволяет сильнее сжимать её повторяющиеся проявления. Недостаточное основание, сомнительная применимость, противоречия или конкурирующие объяснения требуют сохранять больше различающих их подробностей.

**Вариативность процесса не равна незнанию его закономерностей.** Подтверждённое распределение может компактно представлять случайные outcomes без хранения каждого случая. Обратимое сжатие возможно и без объясняющей модели: например, «50 нулей `[t0,t1]`, затем 50 единиц `[t1,t2]`» точно сохраняет существенную временную структуру.


#### Что сохраняет компактное представление
#topic_details 

Консолидация сохраняет не только исключения, но и **общий вид наблюдавшегося опыта с необходимой точностью**: характерные значения, частоты, разброс и существенные зависимости, включая временные.

Для этого используются модели, правила, агрегаты, квантили и отдельные representative cases. Сама модель не всегда достаточна: например, `y ≈ 2x` не описывает распределение `x` и отклонений `y`, поэтому необходимые характеристики сохраняются отдельно в компактной форме.

В пределах бюджета сохраняются представители типичных групп и редких значимых случаев. Подробность распределяется с учётом частоты, разнообразия внутри группы и важности её сохранения: распространённые группы требуют представления существенных вариаций и шума, а редкие не должны теряться из-за малой частоты. При необходимости представители сохраняются с более широким контекстом, чем использует текущая модель. Их отбор не зависит исключительно от ошибки модели: неучтённая зависимость может существовать и среди внешне обычных случаев.

Повторяющиеся исключения также могут обобщаться, если сохраняются их особенности, частоты и необходимый контекст. Необычность сама по себе не требует бессрочного хранения каждого случая.

Это представление служит общей основой [[Datasets#^def-Dataset|датасетов]] для обучения и проверки. Для будущей модели могут понадобиться признаки или зависимости, которых обобщение уже не сохраняет; нужную подробность защищают по [[Datasets#Жизненный цикл|назначению датасета]].

Если представление зависит от конкретной версии модели, сохраняется необходимая revision, чтобы последующее обучение модели не меняло смысл прошлого.

#### Частоты сохранённого опыта
#topic_core

Если группа, представитель или [[Core data structures#^def-Prototype|Prototype]] заменяет множество наблюдений, сохраняется их исходное количество. Иначе после сжатия один редкий случай и один представитель тысячи обычных выглядели бы одинаково частыми. Для интерпретации нужны:
^experience-frequency

- **Единица счёта:** события, эпизоды, исходы или сообщения.
- **Количество и знаменатель:** сколько случаев представлено и среди какого опыта считается их доля.
- **Область наблюдения:** условия включения, период, источники и известные правила отбора.
- **Точность:** точное число либо оценка с методом и неопределённостью; неизвестные значения не подменяются догадкой.

#topic_details 

Статистика может храниться в общих агрегатах. Наблюдения учитываются до отбора представителей; сжатие переносит их количества, соотношения и достигнутую точность. Переотбор или удаление избыточных записей не уменьшает представленный объём. Новые наблюдения, исправления и смена окна либо условий учёта меняют статистику.

При объединении групп исключается повторный учёт исходного опыта. Сведения о пересечениях сохраняются в объёме, нужном для объединения и исправлений; неизвестное пересечение не позволяет считать сумму точной. Несколько рассказов об одном событии могут быть несколькими сообщениями, но одним событием. Retrieval, replay и повторное обучение не добавляют исходных событий.

Частота в собранном опыте не гарантирует ту же частоту в мире: это зависит от источников и отбора. Она также не задаёт число независимых подтверждений, `Strength/Support` или обучающий вес; для них действуют правила [[Uncertainty and Belief Tracking in the World Model#^def-Evidence|evidence]] и [[Learning system#Данные и автоматические обновления|обучения]].

### Проверка сжатия и ответственность

`CompactExpirienceProgram` выбирает форму хранения, при необходимости вызывает `MemoryConsolidationProgram` для построения обобщения и `CompactionValidationProgram` для проверки допустимости потерь.

Проверяется не только соответствие текущей модели, но и сохранение необходимых свойств опыта: частот, разброса, значимых зависимостей, временных различий, evidence и provenance. При повторном сжатии учитывается уже утраченная точность.

Хорошее соответствие модели не отменяет обязательств сохранности. Случай может оставаться необходимым для другой модели, проверки, объяснения или незавершённой задачи.

```text
подробность ещё необходима
→ keep;

необходимая информация сохранена
в проверенном компактном представлении
→ compact;

данные больше не имеют достаточной ожидаемой ценности,
не защищены обязательствами сохранности
и удаление прошло проверки
→ delete.
```


### Хранение и доступ

Lifecycle хранения и retrieval решают разные вопросы:

```text
storage lifecycle
→ какие данные продолжают существовать
  и в каком виде;

retrieval policy
→ какие из существующих данных
  и в каком приоритете находятся
  в обычном поиске.
```

Низкая частота использования может влиять на оценку будущей ценности опыта, но сама по себе не доказывает его избыточность и не разрешает удаление.

---

### Trace-local и persistent results

ToDO:  частичный дубликат с. Trace-local  выше
**[[#^def-TraceLocalResult|Trace-local result]]** — результат anchored-оператора, сохранённый в [[#^def-TraceEvent|`TraceEvent.output`]] и адресуемый через `TraceOutputRef`.

Он принадлежит конкретному исполнению:

```text
TraceOutputRef
→ TraceEvent
→ ProgramRun
```

По умолчанию семантические объекты и relations, построенные из такого результата, остаются локальными для trace.

**[[#^def-PersistentResult|Persistent result]]** — semantic object или relation, которые программа явно поместила в persistent graph через `GraphDelta`.

Persistent result может использоваться независимо от исходного запуска, но сохраняет provenance к trace, из которого был получен.

Переход результата в persistent graph не означает, что весь исходный trace должен храниться бессрочно. После консолидации может остаться только его `retention closure`.

Trace-local result обычно сжимается раньше, если он:

```text
не был материализован через GraphDelta;
не использовался downstream;
не стал evidence;
не повлиял на решение, belief или Program;
не нужен для replay, Evaluation или debugging.
```

Persistent result сохраняется дольше, поскольку участвует в долговременном reasoning и retrieval, но также может быть позднее сжат, заменён или поставлен в очередь на удаление по общим правилам памяти.

---

### Компоненты lifecycle памяти

Lifecycle сжатия и удаления распределён между несколькими компонентами с непересекающимися обязанностями.

Все компоненты типа `Program` являются обучаемыми и развиваются через общий lifecycle программ EverTree. Jobs и системные инварианты являются инфраструктурой и не обучаются.

#### ProgramRunRecorder

`ProgramRunRecorder` автоматически фиксирует исполнение:

```text
ProgramRun;
TraceEvent;
SemanticTrace;
arguments и outputs;
связи вложенных ProgramRun.
```

Он не оценивает ценность опыта и не принимает решений о его дальнейшем хранении.

#### Оценка опыта

[[Learning system#^def-PredictionEvaluator|`PredictionEvaluator`]] использует память для поиска прогнозов и связанных наблюдений через `match_predictions`, затем проверяет их через `evaluate_prediction`. `handle_unmatched_observations` обрабатывает несопоставленный опыт: отсутствие прогноза известного выбранного target фиксирует через [[Learning system#LearningCredit and UnresolvedCredit|UnresolvedCredit]], требующие разбора случаи передаёт сознанию. Результаты сохраняются в trace.

Оценка опыта выполняется отдельно от сжатия памяти.

#### expirience_compaction_job

(def_id:: entity.ExpirienceCompactionJob)
> [!definition]  
> **`expirience_compaction_job`** — периодическая инфраструктурная job, которая формирует `review batch`: набор накопленных memory и persistent semantic results, для которых наступило время пересмотра.
> ^def-ExpirienceCompactionJob

В batch входят trace experience и persistent semantic objects / facts, для которых наступил первый, повторный или досрочный [[#Сроки пересмотра памяти|пересмотр]]. Ранее оставленные или сжатые объекты и просроченные проверки также учитываются. Один объект включается один раз; уже ожидающая обработки заявка не дублируется.

Job не решает, что с ними делать. Она ставит служебную [[Cognition and Attention#Goal, Task и спецификация задачи|Task]] обработки review batch через [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] в [[Cognition and Attention#^sequential-tasks|общий порядок последовательного исполнения]].

### CompactExpirienceProgram

(def_id:: entity.CompactExpirienceProgram)
> [!definition]  
> **CompactExpirienceProgram** — основная обучаемая программа, которая получает `review batch` и выбирает форму дальнейшего хранения его элементов, максимизируя ожидаемую долгосрочную ценность при ограниченной стоимости памяти и обработки.
> ^def-CompactExpirienceProgram

Сжатие связано с генерализацией: если несколько случаев полезнее представить общей структурой, программа может передать их в [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]], сохранить полученное обобщение и уменьшить подробность исходного опыта.

```text
review batch
        ↓
CompactExpirienceProgram
        ↓
keep / delete
или
related experiences
        ↓
MemoryConsolidationProgram
        ↓
обобщённое / агрегированное представление
        ↓
validation
        ↓
финальное keep / compact / delete
```

Программа выбирает:

```text
keep
→ исходное представление сохраняет самостоятельную будущую ценность;

compact
→ полезная информация сохранена в более компактном
  или обобщённом представлении;

delete
→ данные больше не дают достаточной ожидаемой ценности
  и не защищены обязательствами сохранности.
```

Для обнаружения возможной общей структуры программа может группировать элементы `review batch` по semantic structure, [[#^def-Episode|Episode]] / Process, объектам, типам отношений, [[Uncertainty and Belief Tracking in the World Model#^def-BeliefTarget|`BeliefTarget`]], provenance и другим релевантным признакам.

Один или несколько связанных случаев передаются в `MemoryConsolidationProgram`. Та при необходимости использует retrieval, чтобы найти похожие, контрастные или исключающие случаи в более ранней памяти. Retrieval строится относительно уже переданного опыта; consolidation не начинается с произвольного поиска по всей памяти.

После успешной генерализации сохраняются необходимые evidence, provenance, representatives, exceptions и детали, которые обобщение ещё не заменяет.

Финальное решение `keep / compact / delete` принимает `CompactExpirienceProgram`. `MemoryConsolidationProgram` строит предлагаемое обобщение, а [[#^def-CompactionValidationProgram|`CompactionValidationProgram`]] проверяет допустимость потери исходной детализации.

```text
CompactExpirienceProgram
├── MemoryConsolidationProgram?
└── CompactionValidationProgram?
```

#### Обязательства сохранности

#topic_details 


**Обязательства сохранности** определяют, какой опыт или результат сейчас нельзя потерять и почему.

```text
операционное
→ опыт нужен действующему result, belief, claim,
  Program, TrainingDataset, EvaluationDataset, EvaluationCase,
  анализу, инсайту, решению или действию;

эпистемическое
→ опыт или его compact representation нужны для корректных
  BeliefData / EvidenceStats, revise/retract,
  переоценки источника или сохранения значимого противоречия;
  
→ релевантные неразличающие проверки
  (`Δ = 0`, `evidence_mass = 0`) также сохраняются,
  если они нужны для корректного EvidenceStats.

аудитное
→ опыт нужен, чтобы восстановить основания
  значимого изменения агента;

coverage
→ опыт нужен как edge case, counterexample,
  представитель режима, плохо объяснённый случай
  или контрольный routine-example.
```

Явные требования пользователя, supervisor-а, safety или retention policy также запрещают потерю соответствующего опыта.

Обязательство требует сохранить необходимую информацию, но не обязательно исходный опыт: после корректной consolidation достаточно compact representation, сохраняющего требуемые инварианты.

[[Datasets#Жизненный цикл|Требования действующего датасета]] защищают нужную детализацию и при продолжающемся сборе данных. После прекращения соответствующей потребности защита снимается, если её не требует другая задача или обязательство. Сохранение результата обучения или проверки само по себе не требует бессрочно хранить весь набор: сохраняются зависимости, необходимые для заявленного дальнейшего использования результата.

Для восстанавливаемого запуска дополнительно сохраняются необходимые версии кода, входы, результаты и журнал [[Cognition and Attention#^durable-program-execution|DBOS]]. Сжатие `SemanticTrace` не разрешает удалять данные, ещё необходимые для продолжения запуска; технический журнал исполнения имеет собственный срок хранения.

Данные для [[Cognition and Attention#^program-restart-continuation|продолжения Task без повторов]] сохраняются, пока нужны задаче, включая после завершения заменённого `ProgramRun`.

В MVP сохранность опыта после аварии ограничена [[Cognition and Attention#^agent-backup|последним общим backup]]: последующий опыт может быть потерян. Зависимости хранимых backups также защищены от удаления.

---

#### Retention closure

(def_id:: entity.RetentionClosure)
> [!definition]  
> **Retention closure** — минимальный набор зависимостей, который необходимо сохранить **вместе с уже защищённым объектом**, чтобы не потерять его происхождение, существенное evidence и контекст получения или использования.
> ^def-RetentionClosure

В него при необходимости входят:

```text
producer TraceEvent;
существенные inputs и их producers;
branch conditions и ключевые alternatives;
comparison / decision events;
существенное evidence;
ProgramRun;
graph-writing event;
необходимая часть caller chain.
```

То есть:

```text
Обязательства сохранности
→ определяют, что нельзя потерять;

Retention closure
→ распространяет эту защиту
  только на необходимые зависимости.
```

Само присутствие события в upstream provenance не создаёт обязательства сохранности. Оно входит в `retention closure` только если без него защищённый объект нельзя корректно использовать, пересчитать, объяснить или воспроизвести.

После проверенного сжатия или обобщения `retention closure` пересчитывается и может быть сокращён, если часть прежних зависимостей больше не нужна.

`Retention closure` — вычисляемый view, а не отдельная сущность или программа.

#### Сжатие 
##### Компактизация SemanticTrace

После `initial_full_retention_period` [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] может сократить `SemanticTrace`, оставив события, которые необходимо или ожидаемо полезно сохранить:

```text
[E1, E2, E3, E4, E5]
→ compact
[E1, E3, E5]
```

#topic_details 

Все [[#^def-TraceEvent|`TraceEvent`]], необходимые актуальным `retention closure`, должны оставаться в соответствующих [[#^def-SemanticTrace|`SemanticTrace`]]. Относительный порядок оставшихся событий не меняется; сами immutable `TraceEvent` не переписываются.

Каждый вложенный [[#^def-ProgramRun|`ProgramRun`]] compact-ится независимо. Его `SemanticTrace` может сократиться вплоть до пустого, при этом сам `ProgramRun` сохраняется, если ещё необходимы его metadata, call context или provenance.

Исключение `TraceEvent` из `SemanticTrace` не означает `delete`: решение об удалении принимается отдельно по общим правилам lifecycle.

---

##### Сжатие persistent graph

Persistent result также может быть compact или получить `delete` по общим правилам памяти: например, если он дублируется, заменён более актуальным представлением или лучше выражен обобщением.

#topic_details 

То, что состояние стало историческим, ошибочным или было позднее отозвано, само по себе не делает его ненужным. Оно может сохраняться, если повлияло на действие, изменение `Program` или belief, стало существенным evidence, представляет важный редкий случай или необходимо для реконструкции истории.

Lifecycle persistent result и породившего его trace независимы:

```text
persistent result сохранён
≠ весь source trace должен сохраняться;

persistent result получил delete
≠ source trace автоматически удаляется.
```

Достаточно сохранить ту часть source trace, которую требуют его собственные обязательства сохранности и `retention closure`.

---

#####  Сжатие дочернего ProgramRun

Каждый вложенный [[#^def-ProgramRun|`ProgramRun`]] compact-ится независимо; те же правила рекурсивно применяются ко всему дереву вложенных запусков.

---
### Сжатие evidence

[[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] является производным view и не заменяет evidence, необходимое для последующего `revise`, `retract` или переоценки belief.

Повторяющиеся совместимые [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]] могут быть консолидированы программой [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]]:

```text
EvidenceAssignment[]
        ↓
MemoryConsolidationProgram
        ↓
consolidated EvidenceAssignment
```

Консолидация должна сохранять эквивалентность evidence для поддерживаемых способов чтения belief, включая `Support` и [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceStats|`EvidenceStats`]]:

```text
belief before consolidation
≈
belief after consolidation
```

При этом сохраняется минимальная информация, необходимая для temporal/dependency adjustments, idempotency и требуемой гранулярности `revise/retract`, а также значимые различия: существенные dependency branches, разные источники или режимы, подтверждения и опровержения, exceptions и минимум один representative experience для каждой схлопнутой группы.

После успешной консолидации избыточные исходные `EvidenceAssignment`, routine observations и детали provenance могут получить `delete`, если consolidated representation сохраняет требуемую информацию и они больше не входят в актуальный `retention closure`.

---
##### Сжатие содержимого отдельных объектов

[[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] может уменьшать объём отдельного большого объекта опыта без объединения его с другими случаями и без создания более общей модели.

Например:

```text
длинная Note или другой текст
→ summary;

большой внешний документ
→ сокращённое содержание;

длинный числовой ряд
→ aggregate statistics / quantiles / sketch;

большой structured result
→ более компактное representation.
```

Такое сжатие отличается от [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]]:

```text
сжатие одного объекта
→ уменьшает его подробность;

consolidation нескольких случаев
→ выделяет общую повторяющуюся структуру
  и создаёт обобщённое знание.
```

`ContentCompactionProgram` создаёт compact representation содержимого одного объекта. Если исходные детали после этого предполагается удалить, `CompactExpirienceProgram` проверяет, достаточно ли нового представления для дальнейшего использования этого опыта.

### MemoryConsolidationProgram

#topic_core

(def_id:: entity.MemoryConsolidationProgram)
> [!definition]  
> **MemoryConsolidationProgram** — обучаемая программа генерализации памяти. Она получает от [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] один или несколько конкретных связанных случаев опыта и проверяет, можно ли представить их вместе с релевантным прошлым опытом более общим и переиспользуемым знанием.
> ^def-MemoryConsolidationProgram

При необходимости программа использует retrieval для поиска сходных, контрастных и исключающих прошлых случаев. Запрос строится относительно переданного опыта и его semantic structure / provenance; консолидация не начинается с произвольного поиска темы.

При каждом запуске консолидация рассматривает значимые изменения, успехи и затруднения переданного опыта. По необходимости и в пределах бюджета она сопоставляет их с [[Evaluative-Control System#^aggregate-queries|агрегатами]] и инициирует [[Learning system#^outcome-credit|назначение credit по результату Task или процесса]].

```text
related experience
        ↓
MemoryConsolidationProgram
        ↓
optional retrieval of related history
        ↓
generalized representation / aggregate
```

#topic_details

Типичные формы генерализации:

```text
повторяющиеся Facets одного Instance
→ более устойчивая модель / обобщение Instance;

сходные Instances
→ Prototype;

повторяющиеся observations, Claims, relations или ProgramRun
→ aggregate / generalized semantic representation;

совместимое повторяющееся evidence
→ consolidated EvidenceAssignment.
```

Так консолидация одновременно выполняет сжатие и генерализацию: повторяющаяся структура становится доступна для prediction, reasoning и дальнейшего learning без необходимости каждый раз анализировать все исходные случаи.

Если результат должен стать persistent knowledge:

```text
consolidation result
→ GraphDelta
→ persistent semantic graph
```

Если обнаруженная закономерность требует изменения `Program`, она передаётся в structural revision / Program Lifecycle; `MemoryConsolidationProgram` сама программы не изменяет.

Для конкретной консолидации программа должна:

```text
выделить общую структуру;
создать обобщённое представление;
определить его границы применимости;
указать, какие source cases оно покрывает;
выделить необходимые representatives и exceptions;
зафиксировать существенные различия и потерю детализации.
```

Обобщение не должно сводить опыт только к среднему случаю. При необходимости сохраняются:

```text
существенное evidence и provenance;
representative cases;
различающиеся regimes;
edge cases и counterexamples;
редкие или противоречащие outcomes;
неразрешённые противоречия;
небольшая контрольная выборка routine-опыта.
```

Иначе последовательная консолидация может уничтожить evidence против собственной модели.

Например:

```text
1000 сходных успешных ProgramRun
        ↓
MemoryConsolidationProgram
        ↓
generalized model / aggregate
+ representatives
+ exceptions
+ необходимое provenance
        ↓
CompactExpirienceProgram
        ↓
избыточные source traces могут получить compact / delete
```

Частота сама по себе не является основанием ни для генерализации, ни для удаления. Консолидация считается полезной, если более общее представление сохраняет или улучшает способность агента:

```text
предсказывать;
переносить знание;
различать существенные случаи;
обнаруживать отклонения;
продолжать учиться.
```

`MemoryConsolidationProgram` не принимает финальное решение о сохранении исходных данных. Она возвращает обобщение и информацию о том, какие source cases оно покрывает и какие детали необходимо сохранить.

```text
MemoryConsolidationProgram
→ ConsolidationResult
        ↓
CompactExpirienceProgram
→ при необходимости CompactionValidationProgram
→ keep / compact / delete
```

Финальное решение ограничено retention obligations, `retention closure` и системными инвариантами памяти. Защищённый исходный опыт сохраняется независимо от того, насколько хорошо он покрывается обобщением.

#### Example: experience → Instance generalization
#topic_details 

В отдельных poker hands агент получает beliefs о конкретных действиях Игоря:

```text
BLUFFS(Igor, Bet#17)
BLUFFS(Igor, Bet#83)
BLUFFS(Igor, Bet#124)
```

При review похожие случаи становятся источниками для [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]], которая при необходимости извлекает дополнительный прошлый опыт и обобщает его:

```text
конкретные bluff / non-bluff cases
        ↓
MemoryConsolidationProgram
        ↓
BluffTendency(Igor)
        ↓
CLASSIFIED_AS(Igor, BluffProne)
```

Так опыт отдельных действий становится обученным знанием о самом [[Core data structures#^def-Instance|`Instance`]].

#### Provenance и ссылочная целостность

Не допускаются:

```text
ссылки на физически отсутствующий TraceEvent;
TraceOutputRef на отсутствующий output;
caller_event на отсутствующее событие;
защищённый результат без необходимого provenance.
```

Это системные инварианты. Обучаемая программа не может их отменить.


#### CompactionValidationProgram

#topic_details 

(def_id:: entity.CompactionValidationProgram)
> [!definition]  
> **CompactionValidationProgram** —  программа проверки предложенного сжатия.
> ^def-CompactionValidationProgram

Она вызывается, когда compaction предполагает потерю исходных деталей, и проверяет, сохранились ли жёсткая ссылочная целостность, обязательный `retention closure` способности reasoning и retrieval; возможности revise и retract. Она не отвечает за семантику, она отвечает за ссылочную и структурную валидацию и проверяет инварианты [[#^def-ResultProvenance|provenance результата]] и ссылочной целостности [[#^def-Memory|Memory]].

#### DeletionFinalizationJob

#topic_details 

`delete` не уничтожает данные физически.

После него данные остаются восстановимыми на протяжении:

```text
deleted_protection_period
```

По окончании периода `DeletionFinalizationJob` повторно проверяет обязательные условия сохранности.

Если новых зависимостей не возникло:

```text
→ physical deletion
```

Если возникли:

```text
→ delete отменяется
→ данные возвращаются в обычный lifecycle.
```

`DeletionFinalizationJob` не принимает нового семантического решения о ценности памяти. Она только завершает или отменяет уже принятое решение `delete`.

---


### Delete и deleted_protection_period

`delete` означает решение прекратить долговременное хранение данных, но не их немедленное физическое уничтожение.

```text
delete
→ deleted_protection_period
→ final recheck
→ physical deletion
```

В течение `deleted_protection_period` данные остаются восстановимыми.

Если обнаруживается:

```text
новая dependency;
retrieval failure;
regression;
ошибка обобщения;
необходимость revise;
потребность в replay;
другая потерянная способность,
```

`delete` отменяется.

Для [[#^def-TraceEvent|`TraceEvent`]] это означает возможность вернуть его ссылку в [[#^def-SemanticTrace|`SemanticTrace`]] на исходную позицию по `seq`.

Такой случай становится новым evidence для обучения [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]], [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] или [[#^def-CompactionValidationProgram|`CompactionValidationProgram`]] — в зависимости от того, какое решение оказалось ошибочным.

После окончания `deleted_protection_period` `DeletionFinalizationJob` повторно проверяет обязательные retention conditions и либо физически удаляет данные, либо отменяет `delete`.

---



## Сигналы памяти

Память использует существующие сигналы EverTree. Они выполняют роли:

```text
при записи
→ пометить потенциально важный опыт

при learning
→ определить credit по выбранным LearningTarget и контексту опыта

при consolidation
→ решить, что сжать, связать, закрепить или удалить

при replay
→ выбрать, какой прошлый опыт переиграть

при retrieval
→ помочь ранжировать кандидатов, если их слишком много
```


---

### Значимость памяти

(def_id:: concept.MemorySignificance)
> [!definition]
> **Значимость памяти (`significance`)** — пересматриваемая оценка ожидаемой долгосрочной ценности сохранения и доступности воспоминания или элемента графа для будущих задач, понимания и развития агента.
> ^def-MemorySignificance

```text
significance: "baseline" | "elevated" | "exceptional" | null = null
```

| Уровень | Значение |
| --- | --- |
| `baseline` — базовая | Объект оценён; оснований для повышенной значимости не установлено. Объединяет обычную и низкую значимость. |
| `elevated` — повышенная | Ожидается заметная дополнительная ценность для будущей работы, но оснований для исключительной значимости нет. |
| `exceptional` — исключительная | Ожидаемая ценность особенно велика, либо глобально для долгосроного самоулучшения и генерализации агента  либо даже в отдельной области: например, существенное расширение понимания или возможностей. |

`null` означает отсутствие оценки: объект ещё не рассматривали либо оценку пока не удалось обосновать. Это состояние вне шкалы; оно не подменяется `baseline`.

При оценке выбирается наивысший обоснованный уровень. Шкала [[Attribution Plane#2. Ранговая ось (Ordinal)|порядковая]]: границы оценочны, числовые расстояния между уровнями не заданы. Исключительная значимость не требует незаменимости для агента: её может иметь прорывной математический метод, полезный в своей области.

Оценка назначается выборочно при содержательном разборе [[#^def-CompactExpirienceProgram|компактизацией]], [[#^def-MemoryConsolidationProgram|консолидацией]], [[Self#От опыта к подтверждённой проблеме|рефлексией]] или [[Cognition and Attention#^def-Consciousness|сознанием]]. Краткое основание и область применения сохраняются в результате разбора с обычным [[#^def-ResultProvenance|provenance]]. Оценку можно повышать и понижать; оценивать каждый объект при создании необязательно. Для неизменяемых trace-объектов она хранится отдельно со ссылкой на объект.

`significance` используется как дополнительный признак в [[#^def-RankMemories|RankMemories]] и при выборе подробности хранения в [[#^def-CompactExpirienceProgram|CompactExpirienceProgram]]. Это оценка для управления памятью; итоговый retrieval score определяется текущим запросом.

#### Предостережения

- Новизна, частота извлечения, использования и повторный разбор одного опыта сами по себе не обосновывают повышение значимости; оценка не распространяется автоматически по связям или на обобщение.
- Значимость не повышает достоверность и не задаёт [[Learning system#LearningCredit and UnresolvedCredit|learning credit]] или вес обучающего примера.
- Выделение значимого не должно вытеснять типичный опыт и контрпримеры; подробность хранения учитывает [[#Обязательства сохранности|обязательства сохранности]] и ценность информации, которую ещё не сохраняет компактное представление.

### ExplanatoryTension и [[Evaluative-Control System#^def-TensionReduction|tension_reduction]]

[[Evaluative-Control System#^def-ExplanatoryTension|`ExplanatoryTension`]] — относительное напряжение по выбранным процессам, а не свойство отдельного воспоминания. Оно агрегирует уже полученные `prediction_unexpectedness` из обычной работы.

Снижение `ExplanatoryTension`, выраженное положительным `tension_reduction`, может быть поводом разобрать traces связанных обновлений и рассмотреть их полезность. Provenance устанавливает путь зависимости, а не доказывает полезность; назначение credit выполняет Learning system.



---

## Projection to process and program

Для [[Datasets#^def-Dataset|обучения и проверки]] EverTree строит проекцию сохранённого опыта на конкретный process и program, используя:

```text
process lens 
→ что относится к смыслу процесса

program lens
→ что конкретная программа читает, предсказывает или меняет
```

Для проверочного `EvaluationCase` см. [[Process Plane/Program Evaluation and Testing#Contract-based Evaluation|Contract-based Evaluation]].

Факты, не прошедшие проекцию, не участвуют в подготовленном примере. Они остаются в памяти и могут стать важными позже.

---

## Retrieval

#topic_core

Retrieval находит и упорядочивает сохранённый опыт относительно конкретного запроса. Результаты группируются в [[#^def-MemoryCandidateGroup|`MemoryCandidateGroup`]] и ранжируются [[#^def-RankMemories|`RankMemories`]].

Единая публичная программа:

```text
RetrieveMemories(query, limit)
→ ordered MemoryCandidateGroup[]
```

`MemoryQuery` описывает, какой опыт нужен потребителю. Помимо semantic anchors он может содержать явные ограничения по process, Program, объектам, времени, сигналам или provenance/dependencies. Точная структура `MemoryQuery` уточняется по мере появления реальных use cases.

Retrieval работает с двумя связанными источниками памяти:

```text
persistent semantic graph
→ Facets, facts, relations, обобщения и другие persistent results;

trace storage
→ ProgramRun, SemanticTrace, retained TraceEvent
  и их arguments / outputs.
```

Они связаны provenance, поэтому поиск может переходить между semantic knowledge и породившим его опытом:

```text
persistent result
↔ TraceOutputRef / provenance
↔ TraceEvent
↔ ProgramRun / SemanticTrace
```

### Pipeline

```text
MemoryQuery
  ↓
recall по доступным retrieval routes
  ↓
explicit constraints
  ↓
deduplication and grouping
  ↓
RankMemories(query, candidate groups)
  ↓
первые limit групп
```

Retrieval routes — независимые пути к памяти:

```text
direct references;
semantic graph и provenance dependencies;
process / Program / operator / task links;
semantic indexes над persistent и trace memory;
signal и time indexes;
fallback semantic search.
```

`Explicit constraints` исключают только кандидатов, явно несовместимых с запросом. Неуверенная релевантность не является основанием для исключения и учитывается при ranking.


### Deduplication and grouping

Перед ranking результаты разных retrieval routes сворачиваются в группы.

Дедупликация объединяет несколько ссылок на одну и ту же memory. Grouping объединяет близкий избыточный опыт, чтобы множество почти одинаковых случаев не вытесняло остальные результаты.

При этом нельзя объединять случаи, различия между которыми могут быть существенны для query.

(def_id:: entity.MemoryCandidateGroup)
> [!definition]  
> **MemoryCandidateGroup** — локальный view текущего retrieval-вызова, а не новая persistent-сущность памяти.
> ^def-MemoryCandidateGroup

### RankMemories

(def_id:: entity.RankMemories)
> [!definition]  
> **RankMemories** — обучаемая дочерняя Program `RetrieveMemories`, которая упорядочивает уже найденные candidate groups относительно того же `MemoryQuery`.
> ^def-RankMemories

```text
RankMemories(query, candidate groups)
→ ordered candidate groups
```

Она не ищет новые memories, не применяет explicit constraints и не изменяет lifecycle памяти.

Основной критерий ranking:

```text
ожидаемая полезность candidate group
для текущего query.
```

В зависимости от query могут учитываться:

```text
semantic relevance;
Strength / Support и применимость evidence;
temporal applicability;
signal samples;
provenance и downstream dependencies;
история использования;
стоимость доступа и обработки.
```

Эти признаки не являются универсальными множителями. Например, высокий `Support` полезен при поиске надёжного evidence, низкий — при поиске сомнительных случаев; recency важна для time-sensitive query, но не обязательно для audit; provenance показывает зависимости, но не является универсальным scalar score.

Поэтому у memory нет постоянного общего `retrieval score`. Score, если он используется, относится только к конкретному вызову `RankMemories`.

В MVP используется одна общая `RankMemories`, интерпретирующая `MemoryQuery`. Специализированные rankers добавляются только если Evaluation покажет систематическую проблему общего механизма.


### Learning

`RetrieveMemories` и [[#^def-RankMemories|`RankMemories`]] обучаются через обычную [[Learning system#^def-LearningSystem|Learning System]] по downstream-результатам использования найденной памяти.

Ключевое разделение ошибок:

```text
нужная memory не попала в candidate groups
→ retrieval / recall error;

нужная memory была найдена,
но получила слишком низкий rank
→ ranking error.
```

Аналогично систематическая ошибочная фильтрация или grouping получают evidence соответствующим решениям retrieval.

[[#^def-ResultProvenance|Provenance]] показывает, какие решения участвовали в результате. `CreditAssignmentProgram` связывает [[Learning system#LearningCredit and UnresolvedCredit|learning credit]] с выбранным [[Learning system#^def-LearningTarget|LearningTarget]] и его применением в контексте evaluated outcome; конкретные параметры для обновления выбирает `UpdatePlanner`.


## Replay

### Определение

#topic_core 

(def_id:: entity.MemoryReplay)
> [!definition]  
> **Memory replay** — механизм возврата выбранного сохранённого опыта в отдельную обработку как [[Cognition and Attention#Goal, Task и спецификация задачи|Task]], чтобы продолжить его незавершённую интеграцию, переосмыслить его или использовать для обучения относительно вопроса либо цели.
> ^def-MemoryReplay

```
текущий опыт 
→ cognition / analysis; 

завершённый опыт анализируется постфактум
в рамках той же обработки
→ reflection (replay не требуется); 

выбранный прошлый опыт возвращается из памяти в отдельную обработку
→ replay (может включать reflection).
```

`ReplayTask` может быть выбран сразу после завершения [[#^def-Episode|эпизода]] или значительно позже. Важен отдельный проход обработки, а не физическая длительность паузы. Replay создается только при обоснованной неободимости.

`ReplayTask` может охватывать один или несколько эпизодов, связанных общим вопросом либо целью. Для сознательного шага [[Cognition and Attention#^context-preparation|`ContextPreparation`]] загружает необходимые части выбранного опыта, сохраняя контекст, нужный для их интерпретации. Использование памяти внутри текущей `Task` само по себе не является Replay.

> **Replay не имеет отдельного learning pipeline. Он создаёт новый опыт внутренней обработки, который проходит через те же [[#^def-ProgramRun|`ProgramRun`]], [[#^def-TraceEvent|`TraceEvent`]], evaluation, credit assignment и episode integration, что и live-опыт.**

### Когда нужен replay

#topic_core 


Replay нужен, когда повторная обработка прошлого опыта имеет ожидаемую обучающую ценность: может помочь объяснить произошедшее, правильнее назначить credit, уточнить модель, улучшить policy или извлечь переносимый вывод.

Типичные причины:

```
неожиданный плохой outcome
+ причина не ясна;

неожиданный успех
+ не понятно, что именно сработало;

неоднозначный credit assignment;

сильный supervisor_feedback_signal
+ неясно, какое решение или действие его вызвало;

высокий prediction_unexpectedness
+ обычный belief / parameter update
  не объясняет mismatch;

редкий или необычный случай;

предполагаемая смена режима;

противоречие между эпизодами
или внутри одного эпизода;

новая Claim или модель,
которая позволяет по-новому интерпретировать
старый опыт;

regression или Evaluation gap,
для понимания которых полезен прошлый опыт.
```

Высокий [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] или сильный / необычный outcome сами по себе не требуют replay.

```
сильный outcome
+ причина понятна
+ необходимое learning уже выполнено
→ replay обычно не нужен;

существенный outcome
+ причина, credit или границы применимости неясны
→ хороший кандидат на replay.
```

Replay может быть запланирован сразу после эпизода либо значительно позже, когда новое знание, гипотеза или проблема делает старый опыт снова информативным.

Поводом может быть и цель улучшить уже работающую стратегию на накопленном опыте, если ожидаемая польза оправдывает стоимость. Ошибка или незавершённая интеграция для этого не обязательны.

### Replay и сигналы

#topic_details 

Сигналы помогают обнаруживать опыт, который может требовать повторного анализа, но сами по себе не определяют необходимость replay.

`ReplaySelectionProgram` учитывает сигналы совместно с:

```
BeliefData и EvidenceStats; provenance;
текущей моделью;
редкостью;
противоречиями;
предыдущими replay attempts;
стоимостью;
похожими и контрастными эпизодами.
```


### ReplaySelectionProgram

#topic_core 

Упрощенный интерфейс:

```python
ReplaySelectionProgram(
  source_episode? = None,
  reason: str? = None,  # пример: "почему я получил негативный supervisor_feedback?"
)
→ ReplayTask[]
```


`reason` — вопрос или цель Replay. Необязательный `source_episode` задаёт отправную точку отбора, но не ограничивает Replay одним эпизодом. `ReplaySelectionProgram` при необходимости использует [[#Retrieval|общий retrieval]] для отбора и дополнения эпизодов по `reason` и релевантным сигналам.


---

### Планирование replay

#topic_core 

`ReplayTask` использует обычный [[Cognition and Attention#^def-TaskExecution|цикл выполнения задачи]] и runtime без отдельного scheduler. Готовая разрешённая `exec`-программа может выполнять replay автоматически; для нужного сознательного шага задача помещается в общую `AttentionPriorityQueue`.

Период «сна» — время, выделенное на внутреннюю обработку опыта, — может использоваться для таких задач с общим бюджетом и той же очередью сознательной обработки. Рефлексия может инициировать `ReplayTask` или выполнить анализ и simulation внутри текущей `Task`, если отдельный возврат опыта не требуется.

Для задачи, ожидающей сознательной обработки, динамически вычисляется:

```
attention_priority.
```
программой EstimateAttentioPriority(task)

---

### Выполнение replay

#topic_details 

Содержательная работа `ReplayTask`:

```
ReplayTask
  ↓
восстановить relevant observations,
predictions, decisions, actions,
outcomes и signal samples
  ↓
добавить похожие и контрастные episodes
  ↓
выполнить анализ делегированной программой
или сознанием после получения Focus,
при необходимости — simulation и policy optimization
  ↓
получить результаты интеграции.
```

Replay создаёт новый [[#^def-Episode|Episode]] внутренней обработки, связанный с исходными episode(s).

Внутри него создаются обычные [[#^def-ProgramRun|ProgramRun]], включая

```python
ProgramRun(run_mode="replay")
```

Replay может вызывать обычные Programs для [[Process Plane/Program Evaluation and Testing#3. Simulation Tests and Optimization|simulation и policy optimization]]. Дочерние simulation-запуски имеют `run_mode="simulation"`; вызывающий replay-run сохраняет `run_mode="replay"`.

Исходные Episode и [[#^def-TraceEvent|TraceEvent]] не изменяются. Новые [[Core data structures#^def-Note|заметки]] с рассуждениями, выводы, решения и updates относятся к новому Episode и сохраняют [[#^def-ResultProvenance|provenance]] к использованному прошлому опыту.

Некоторые возможные результаты, включая [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]], [[Learning system#LearningCredit and UnresolvedCredit|`LearningCredit`]] и [[Core data structures#^def-Claim|`Claim`]]:

```
EvidenceAssignment
→ belief update;

LearningCredit
→ UpdatePlanner → parameter update;

Claim
→ дальнейшая проверка;

structural revision request
→ ProgramBranch / new Program / semantic change;

generalized relation или prototype
→ переносимое знание;

EvaluationCase
→ проверка конкретной гипотезы или Program;

experiment / action proposal
→ обычная задача planning и action selection;

no justified update
→ имеющегося evidence недостаточно.
```

[[#^def-MemoryReplay|Replay]] никогда автоматически не повторяет внешнее действие. Он может только создать предложение эксперимента или action task, которое затем проходит обычные planning, commitment и safety-механизмы.

#### Пример: улучшение игры против конкретного соперника

`ReplaySelectionProgram(reason="Как улучшить игру против Игоря?")` может создать задачу со следующим планом:

1. **Собрать опыт.** Через [[#Retrieval|retrieval]] выбрать раздачи с Игорем и уже усвоенные [[#Example: experience → Instance generalization|обобщения о нём]]. Зафиксировать текущую policy для сравнения. Восстановить ситуации выбора: доступные тогда карты, ставки, размеры банка и оставшихся фишек, наблюдавшиеся действия и результаты. Выборка включает разные исходы, а не только проигрыши.

2. **Уточнить модель соперника.** По реальным действиям оценить вероятности сброса карт, уравнивания и повышения ставки в зависимости от ситуации и действий агента. Нераскрытые карты остаются неизвестными; возможные руки соперника представлены распределением, согласованным с доступной историей. Уже учтённый опыт переиспользуется по [[Learning system#PreparedUpdate, UpdateTransactionManager and UpdateDispatcher|правилам повторного учёта и обновления параметров]].

3. **Смоделировать альтернативы.** Из выбранных ситуаций запускать продолжения с разными действиями агента. Обычная Program перебирает или сэмплирует допустимые карты, моделирует ответы Игоря и вычисляет результат по правилам покера. Для заданных карт и действий результат вычисляется точно; ожидаемый выигрыш стратегии зависит также от модели скрытых карт и поведения соперника. Policy видит только информацию игрока, даже если симулятор знает все карты. Анализ задаёт варианты и бюджет, а многочисленные численные прогоны выполняются без LLM-вызова на каждую раздачу.

4. **Улучшить policy.** Сравнить текущую стратегию и кандидатов по ожидаемому чистому выигрышу фишек с учётом заданных ограничений риска. Проверять преимущество при правдоподобных вариантах неопределённой модели Игоря. Выбранные результаты simulation используются для [[Process Plane/Program Evaluation and Testing#3. Simulation Tests and Optimization|policy optimization]] через общий learning pipeline; анализ, прогоны и обновления можно повторять в пределах бюджета задачи.

5. **Проверить и сохранить результат.** Отложенные реальные раздачи проверяют прогнозы модели Игоря; отдельные simulation-прогоны — выигрыш policy внутри модели. Улучшение сохраняется с областью применимости «против Игоря при таких условиях» и provenance исходного опыта, модели и прогонов. Разрешённые parameter updates идут через Learning System, изменения кода или контракта — через [[Process Plane/Program Lifecycle and Evolution#Общий lifecycle Program|Program Lifecycle]]. Последующие реальные игры проверяют перенос и дают опыт для следующего цикла.

---

### Replay и lifecycle памяти

Незавершённый `ReplayTask` создаёт обязательство сохранности для необходимой части исходного опыта..


---


## Общий heigh level  lifecycle обработки и интеграции опыта

#topic_core

Cхема для удобства, не является источником истины (им являются секции выше):

Это представление [[Cognition and Attention#^agent-processing-cycle|общего цикла агента]] со стороны памяти: сознательная и автоматическая обработка принадлежат `Task`, включая наблюдение, ожидание или рефлексию. Доставка наблюдений выполняется по [[Process Plane/Program Layer#^process-observation-input|правилам входа исполнения]]; смысловая маршрутизация нужна только при неизвестном или пересматриваемом адресате.


```text
new experience
        ↓
Memory → Episode
        ↓
TaskExecution: delegated Program work
and, when needed, Attention → Consciousness
        ↓
new observations / notes / decisions / actions / outcomes
        ↓
Memory + online Learning 
        ↓
Episode continues
        │
        └── Episode completion
                    ↓
            episode-level integration
                    ↓
        ┌───────────────────────────────┐
        │ sufficiently integrated      │
        │ → no additional work now     │
        │                              │
        │ needs further analysis       │
        │ → Cognition / reflection     │
        │                              │
        │ structural revision needed   │
        │ → Program Lifecycle          │
        │                              │
        │ useful as separate reprocess │
        │ → ReplayTask                 │
        └───────────────────────────────┘
```

Learning выполняется по мере появления evaluable evidence и не ждёт завершения `Episode`.

После завершения `Episode` выполняется episode-level integration: учитывается evidence, которое требует контекста эпизода целиком. Её результаты не взаимоисключающие: например, reflection может породить structural revision или `ReplayTask`.

Replay возвращает сохранённый опыт в тот же общий цикл обработки:

```text
ReplayTask
→ TaskExecution: delegated Programs; Attention → Consciousness when needed
→ new internal Episode
→ Memory + Learning
→ episode-level integration
```
