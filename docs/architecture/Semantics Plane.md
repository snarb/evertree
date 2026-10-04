---
status: draft
target_version: next
---

## Intro
#topic_core 

**Вопрос подсистемы:** «Какое это?»

Подсистема Семантики описывает **статическую суть**: концепты и факты связей между ними.

**Инструмент семантики — связи.**
Связи представлены **гиперрёбрами** (n-арными). Разные типы гиперрёбер задаются **типами отношений** (`RelationType`).
Экземпляр связи — это **Instance** (инстанс) отношения с заполненными аргументами.

- **Состав (Axes):**
- _Abstraction Ladder:_ Род-вид (`SUBTYPE_OF`).
- _Mereology:_ Часть-целое (`PART_WHOLE`).

**Ключевые Операции:**

1. **Обобщение (Ascend):** Подъем по лестнице абстракции (поиск супер-типа).
2. **Детализация (Descend):** Спуск к инстансам или частям.
3. **Композиция:** Сборка системы из частей.

---

## RelationType: прототип факта
#topic_core 

(def_id:: entity.RelationType)
> [!definition]
> **`RelationType`**
> это концепт, который определяет:
> 1. **Смысл факта** (что утверждается и что не утверждается).
> 2. **Сигнатуру (Signature)**: какие слоты существуют, их labels, роли/типы и кратности.
> 3. **Views (проекции)**: именованные “виды” на тот же факт (как получать аргументы в разных направлениях) **без создания обратных отношений и без копирования данных**.
^def-RelationType

> [!important]
> Принцип: **есть один факт**. “Обратность” и “направления” — это **views/проекции** (запросы), а не отдельные relation-instances.

**RelationType** участвует в лестнице абстракции на ряду со всеми концептами.

Используем небольшой набор базовых отношений; доменные `RelationType` добавляются по [[Core data structures#Concept Canonicalization and Semantic Linking|общим правилам переиспользования и создания концептов]].

### Signature и стабильные labels
#topic_details 

Мы **всегда** допускаем эволюцию `RelationType`, поэтому **каждый слот имеет стабильный `label`**.
Совместимость и маппинг делаются **по `label`**, порядок — вторичен.

#### Slot (inline)

```text
<label> = <ConceptSlot>  "описание"     # 1
<label> = <ConceptSlot>? "описание"     # 0..1
<label> = <ConceptSlot>* "описание"     # 0..N
<label> = <ConceptSlot>+ "описание"     # 1..N
```

- `label` — технический ключ (адресация + версионирование), **не концепт**.
- `ConceptSlot` — один Concept, задающий семантический тип или роль позиции:
    - чаще `Role`-концепт (`Parent`, `Owner`…),
    - иногда “не роль” (`Person`, `Entity`), если роль формулировать невыгодно.

**Хранение аргументов в инстансе связи:**

`args` — словарь с ключами `label`; значение каждого слота соответствует типу, заданному контрактом `ConceptSlot`, и объявленной кратности. Аргумент может быть `Concept`, скаляром или другим типизированным объектом по [[Core data structures#Типизация данных|общим правилам типизации]]; числовое значение не требуется превращать в Concept. Сохранение объектов и связей между ними подчиняется [[Core data structures#Объекты и ссылки|общим правилам объектов и ссылок]].

### Views: проекции над одним фактом
#topic_details 

(def_id:: entity.View)
> [!definition]
> **View** -
> именованная проекция relation-instances: фиксируем слоты **inputs**, применяем необязательный фильтр `constraints` и возвращаем значения **outputs**, сохраняя исходный факт для каждого результата.
^def-View

`AccessView` — декларация внутри `RelationType`. Общий механизм предоставляет объявленные views как методы `RelationType` и исполняет их. Для нового view достаточно декларации; отдельная Python-функция или `Program` не требуется. Именованные views задаются для используемых способов чтения, а не для всех возможных комбинаций слотов.

#### `AccessView` (структура)

(formal_id:: entity.AccessView.schema)
```python
AccessView: <InternalNode> {
  name: <string>             "стабильное имя view, уникальное внутри RelationType",
  description?: <string>     "смысл проекции, если он неясен из имени и слотов",
  inputs: <string[]>         "labels слотов, значения которых задаются при вызове",
  outputs: <string[]>        "labels возвращаемых слотов; порядок задаёт порядок элементов tuple",
  output_arity: <enum>       "кратность совпадений: one | optional | list0 | list1",
  constraints?: <Predicate>  "фильтр(pandas-friendly)  по слотам и доступным полям чтения relation-instance"
}
```
^spec-AccessView

#### Общий исполнитель и результат

```python
PARENTAGE.get_parent(child=Bob, valid_at=None, known_at=None)
```

Входы передаются именованными аргументами по labels слотов; их типы и кратности берутся из `RelationType.signature`. Служебные параметры `valid_at` и `known_at` необязательны; эти имена зарезервированы и не могут входить в `inputs`. При вызове исполнитель проверяет, что переданы все объявленные входы, их значения соответствуют контрактам слотов и нет лишних аргументов.

При объявлении проверяются уникальность имени view, его допустимость как имени метода Python и отсутствие конфликтов с полями и методами `RelationType`. Также проверяются существование labels, отсутствие повторов в `inputs` и `outputs`, непустой `outputs` и корректность `constraints`.

Если отношение и имя view выбираются динамически, тот же объявленный view вызывается через `getattr(relation_type, view_name)(**inputs)`, где `inputs` — словарь `label → значение`.

`valid_at` и `known_at` имеют [[Attribution Plane#Чтение свойств состояния|общий смысл времени мира и времени знания]]. Без `valid_at` временной фильтр не применяется; без `known_at` используется текущее знание. Факты, их поля и вычисляемый belief читаются в одних временных границах по контракту источника. Если необходимых сохранённых данных недостаточно, возвращается `unknown` до проверки кратности; недоступное чтение не подменяется пустым результатом.

Исполнитель находит факты по равенству входных слотов, применяет `constraints`, строит проекцию и проверяет `output_arity`. Каждый подходящий факт даёт одну техническую запись с полями:

```text
value       — значение единственного output-слота либо tuple в порядке outputs;
source_fact — исходный RelationInstance в прочитанной версии.
```

Значение list-слота остаётся списком внутри `value`: оно не разворачивается в дополнительные совпадения. Разные факты с одинаковой проекцией сохраняют отдельные результаты и свои `source_fact`; это само по себе не означает независимости их evidence.

| `output_arity` | Результат |
| --- | --- |
| `one` | Ровно одна запись |
| `optional` | Одна запись либо `None` |
| `list0` | Список из 0..N записей |
| `list1` | Список из 1..N записей |

Нарушение кратности — ошибка контракта. Кратность слота ограничивает одну запись факта, а `output_arity` — число найденных фактов; последнее не выводится автоматически из первого. Выбор `latest/max_support/...` выполняется отдельной явной операцией над результатами, а не скрывается в `one` или `optional`.

Проекция не создаёт новый факт или evidence. `source_fact` сохраняет исходные identity и provenance по [[Core data structures#Объекты и ссылки|общим правилам объектов и ссылок]]. Сохранённое `value` фиксирует прочитанное значение по [[Process Plane/Program Layer#^local-values-and-results|правилам результатов чтения]]. `BeliefData` / `Profile` читаются для target исходного факта через [[Uncertainty and Belief Tracking in the World Model#Read-time computation and provenance|общий belief-интерфейс]], с временными ограничениями исходного запроса; view не хранит отдельную копию belief.

В обозначениях ниже стрелки показывают тип `value`, сохраняя описанную привязку к `source_fact`. Вычисление новых значений, объединение нескольких запросов и разрешение гипотез выполняются обычными программами поверх views.

### `constraints`: формат Predicate
#topic_details

`constraints` задаётся одним структурированным предикатом по слотам и доступным полям чтения relation-instance. Он ограничивает набор фактов, например оставляет только biological parentage. Формат допускает табличное исполнение, но не зависит от pandas; query-строки, вызовы программ и условия вида «существует другой факт…» в него не входят.

(formal_id:: entity.Predicate.schema)
```python
Predicate: <InternalNode> {
  all: <Clause[]> "AND-клаузулы"
}
Clause: <InternalNode> {
  field: <string>          "label слота или поле, объявленное контрактом чтения relation-instance",
  op: <enum>               "== | != | in | not_in | < | <= | > | >= | contains | is_null | not_null",
  value?: <any>            "значение или список значений"
}
```
^spec-Predicate

Исполнитель проверяет существование и однозначность поля, допустимость операции для его типа и тип `value`. Для `is_null/not_null` значение не задаётся; для остальных операций оно обязательно. Отсутствующее значение optional-слота проверяется через `is_null/not_null`; остальные сравнения с ним не дают совпадения.

Доступны слоты (`parent`, `child`, `kind`, …) и явно предоставляемые поля чтения (`t`, `window_id`, `source_id`, `rule_version`, …). Фильтры по `strength/support`, если эти поля предоставлены, используют общее вычисляемое чтение belief соответствующего target, а не сохранённый snapshot.

```python
constraints = Predicate(all=[
  Clause(field="kind", op="==", value="biological")
])
```

### Формальные сущности
#topic_details 
#### `<RelationType>` (тип отношения)

(formal_id:: entity.RelationType.schema)
```python
RelationType: <SemanticNode> {
  signature: <Slot[]>      "список слотов (labels + arity + смысл)",
  views?: <AccessView[]>   "именованные проекции над тем же фактом"
}
```
^spec-RelationType

#### `<Slot>` (элемент сигнатуры)


> [!note]
> Slot — схемный internal-элемент RelationType (не участвует в “лестнице абстракции” как смысловой узел).

(formal_id:: entity.Slot.schema)
```python
Slot: <InternalNode> {
  label: <string>           "стабильный ключ слота (contract для версионирования)",
  concept: <Concept>        "семантический тип или роль позиции; его контракт задаёт допустимый тип аргумента",
  arity: <enum>             "one | optional | list0 | list1",
  description?: <string>    "минимальный контракт смысла (что это / что не это)"
}
```
^spec-Slot

### Примеры
#topic_details 

> [!example]
> PARENTAGE (нейтральный факт + views)
>
> ```python
> RelationType PARENTAGE {
>   name: "PARENTAGE"
>   description: "Факт родительства: parent является родителем child. Не включает наставничество/учительство/опеку, если это не оформлено как родительство."
>   signature: [
>     parent = Parent "кто является родителем",
>     child  = Child  "кто является ребенком",
>     kind?  = ParentageKind "biological | legal | ... (если нужно различать)"
>   ]
>   views: [
>     {
>       name: "get_parent"
>       description: "Получить родителя(ей) для ребенка"
>       inputs: ["child"]
>       outputs: ["parent"]
>       output_arity: "list0"
>     },
>     {
>       name: "get_child"
>       description: "Получить ребенка(детей) для родителя"
>       inputs: ["parent"]
>       outputs: ["child"]
>       output_arity: "list0"
>     }
>   ]
> }
> ```
>
> Пример факта:
> - `PARENTAGE { parent=Alice, child=Bob, kind='biological' }`

```python
matches = PARENTAGE.get_parent(child=Bob)
# Каждый match содержит value=родитель и source_fact=факт родительства.
```

> [!note]
> Обратная навигация (`get_child`) — это view. Отдельного `CHILD_OF` как факта не требуется.

### Правила и ограничения
#topic_details 

> [!important]
> 1. **Один факт — много видов.** Не создаём “обратные RelationType” ради навигации. Навигация делается через `views`.
> 2. **Проекция не дублирует факт.** Сохранение результата чтения в trace не создаёт копий исходных relation-instances в графе.
> 3. **`constraints` — только фильтр** в едином [[#^spec-Predicate|формате Predicate]].
> 4. **Выбор одного элемента — вне RelationType.** View соблюдает объявленную кратность; `latest/max_support/...` — отдельная операция с явной политикой.
> 5. **Нейминг RelationType — по сути факта.** Используем читаемые и однозначные названия, как нейтральные (`PARENTAGE`), так и направленные (`ON_SURFACE`).

---


### Создание Facet
#topic_details 

Anchored-оператор может создать `Facet` как локальный semantic result конкретного `ProgramRun` (все результаты создаются trace-local).
 
Пример:

```python
health_status = diagnose(igor)  # et:op=igor_health_status
```

В `SemanticTrace` фиксируется не только техническое распределение:

```python
health_status = {"healthy": 0.05, "sick": 0.90, "recovering": 0.05}
```

а семантическое состояние Игоря:

```python
Facet_IgorHealth42 {
  valid_from = "2026-07-17T12:00"
  valid_until = None

  created_by = TraceOutputRef(
    event_ref = <identity of TraceEvent_E19>,
    output_path = "facets.igor_health"
  )
}

HealthStatus(Facet_IgorHealth42) {
  alternatives = [
    CLASSIFIED_AS(Facet_IgorHealth42, Healthy),
    CLASSIFIED_AS(Facet_IgorHealth42, Sick),
    CLASSIFIED_AS(Facet_IgorHealth42, Recovering)
  ]
  belief_data = Profile {
    strengths = {Healthy: 0.05, Sick: 0.90, Recovering: 0.05}
    support = ...
    prior_support = ...
  }
  created_by = TraceOutputRef(
    event_ref = <identity of TraceEvent_E19>,
    output_path = "properties.health_status"
  )
}
```

Один `Facet` может быть описан несколькими согласованными фактами:

```text
HealthStatus(Facet_IgorHealth42)
→ один CompetitionScope / Profile;

HAS_NUMERIC_VALUE(
  Facet_IgorHealth42,
  Temperature,
  39.1,
  Celsius
)
```

Один `TraceEvent` может одновременно создать `Facet` и связанные с ним facts.

По умолчанию такой результат остаётся локальным для `SemanticTrace` и интерпретируется в контексте своего `Semantic Call Tree`.

Чтобы состояние стало частью долговременного графа, программа явно создаёт `GraphDelta`:

```
local Facet + related facts
→ graph-writing operator
→ GraphDelta
→ persistent Facet + related facts
```

После этого состояние становится доступно обычному retrieval и `read_property(...)`.

Запись в persistent graph не меняет содержание или достоверность состояния. Она означает только, что агент решил сохранить его как долговременное утверждение- активную модель мира. Достоверность по-прежнему задаётся через `Belief_data`.


---

## Operational role of semantic relations

^e24496

#topic_core

Семантическая связь в EverTree — это не только декларативный факт о мире. Она также выполняет две операционные роли:

1. **Knowledge cache** — сохраняет результат уже выполненного reasoning, измерения, ProgramRun или Evaluation, чтобы не вычислять его заново. Если relation является материализованным результатом, её происхождение восстанавливается общим механизмом provenance; отдельные дублирующие memory-ссылки не создаются.
    
2. **Retrieval index** — создаёт быстрый путь поиска между концептами, процессами, программами, факторами, outcomes и memories.
    

Semantic relation материализуется **строго** если имеет ожидаемую операционную пользу:

- ускоряет retrieval;
- уменьшает повторное reasoning;
- фиксирует важное сомнение или его разрешение;
- поддерживает routing memory/process/program;
- участвует в  prediction, planning.

Отрицательная или исключающая связь создаётся только если фактор реально рассматривался, создавал сомнение, давал ложный кандидат, участвовал в ошибке модели.


Отрицательная или исключающая связь создаётся только если фактор реально рассматривался, создавал сомнение, давал ложный кандидат, участвовал в ошибке модели или нужен для pruning конкретной программы.


---




## Evidence dependency relation

---
```python
RelationType EVIDENCE_DEPENDS_ON {
  name: "EVIDENCE_DEPENDS_ON"

  description:
    "Фиксирует существенную информационную зависимость evidence от общего источника, observation, premise или другого основания. Не означает причинную зависимость объектов мира."

  signature: [
    evidence = Node | RelationInstance
      "Semantic result, содержащий evidence."

    basis = Node | RelationInstance
      "Информационное основание, от которого evidence существенно зависит."
  ]

  views: [
    {
      name: "get_evidence_dependencies"
      inputs: ["evidence"]
      outputs: ["basis"]
      output_arity: "list0"
    },
    {
      name: "get_dependent_evidence"
      inputs: ["basis"]
      outputs: ["evidence"]
      output_arity: "list0"
    }
  ]
}
```


---

## Оси Лестницы абстракции

### Intro
#topic_core 

Лестница абстракции в EverTree — это набор **иерархических осей**, которые обеспечивают:

- распространение **активации** (и вместе с ней — релевантности, свойств, priors),
- перенос **наград / ценности** и обобщение опыта (частное ⇄ общее),
- несколько **параллельных треков** обобщения, которые сознание агента может комбинировать при прогнозе исхода эпизода и выборе действий.

> [!important]
> “лестница” — это не одна связь, а **две разные оси**, потому что в реальности существуют два разных смысла “подняться к более общему”:
> 1. _тот же объект на другом уровне гранулярности_ (состояние → объект → тип)
> 2. _более общий тип_ (вид → род → …)

### Concept plane
#topic_core 

`<HierarchyAxis>`: `<Axis>`

(def_id:: entity.HierarchyAxis)
> [!definition]
> **Hierarchy Axis** (иерархическое включение)
> ось задаёт **частичный порядок** “более общее / более частное” и служит для **обобщения и детализации** без смешивания с атрибуцией. Не обязана делать все элементы сравнимыми напрямую (частичный порядок), но должна быть достаточно стабильной для переноса priors/активации.
^def-HierarchyAxis

**Ascend:** движение к более общему (specific → general)
**Descend:** движение к более частному (general → specific) — реализуется **views/проекциями** над теми же фактами, отдельные “обратные RelationType” не создаются.

**Операции (минимум):**

- `ancestors(x) / descendants(x)` — навигация вверх/вниз по иерархии
- `common_ancestor(x,y)` — общий предок (для аналогий/обобщения)
- `distance(x,y)` (опционально) — грубая дистанция для затухания/декэя активации

> [!important]
> **Важно (граница смысла):**
> - Hierarchy Axis **не про свойства** (это Плоскость Атрибуции: `HAS_NUMERIC_VALUE`, `CLASSIFIED_AS`, structural property facts).
> - Hierarchy Axis **не про “конъюнкции ограничений”** и не про построение новых классов из фасетов. Если нужны summary-классы (“OnRoad”, “Fast”) — это материализация в Атрибуции по критериям, а не иерархическая ось.

Ниже определены `RelationType` для иерархий в “контрактном” стиле. Важно: **Descend везде делается через views**, поэтому отдельные RelationType вида `CHILD_OF / HAS_PARTS / SUBTYPES_OF` не нужны.

#### RelationTypes для осей Лестницы абстракции
#topic_details 

##### `SUBTYPE_OF` (Type ↔ SuperType)

(formal_id:: entity.SUBTYPE_OF.schema)
```python
RelationType SUBTYPE_OF {
  name: "SUBTYPE_OF"
  description: "Таксономический факт: type является подтипом своего непосредственного supertype в строгом дереве. Используется только между Prototype/Type. Не применяется к Instance/Facet и не означает 'обладает свойством'."
  signature: [
    type      = Prototype "более конкретный тип/схема",
    supertype = Prototype "более общий тип/схема (родитель в дереве)"
  ]
  views: [
    {
      name: "get_supertype"
      description: "Получить supertype для type"
      inputs: ["type"]
      outputs: ["supertype"]
      output_arity: "optional"   # у корневого типа родителя нет
    },
    {
      name: "get_subtypes"
      description: "Получить подтипы (types) для supertype"
      inputs: ["supertype"]
      outputs: ["type"]
      output_arity: "list0"
    }
  ]
}
```
^spec-SUBTYPE_OF

> [!note]
> **Примечания**
> - Это **ось Taxonomy** (Type → SuperType).
> - **Descend-Taxonomy = обратный запрос: “найди подтипы данного supertype”.

##### `IDENTITY_TYPE` (Instance ↔ Type)

(formal_id:: entity.IDENTITY_TYPE.schema)
```python
RelationType IDENTITY_TYPE {
  name: "IDENTITY_TYPE"
  description: "Связь идентичности с типом: instance (якорь идентичности) реализует type (Prototype). Не означает таксономию типов (SUBTYPE_OF) и не описывает текущее состояние (STATE_IDENTITY)."
  signature: [
    instance = Instance  "конкретный объект-идентичность (якорь), протяжённый во времени",
    type     = Prototype "тип/схема (нормы и priors применимы к instance)"
  ]
  views: [
    {
      name: "get_type"
      description: "Получить type для instance"
      inputs: ["instance"]
      outputs: ["type"]
      output_arity: "one"
    },
    {
      name: "get_instances"
      description: "Получить instances для type"
      inputs: ["type"]
      outputs: ["instance"]
      output_arity: "list0"
    }
  ]
}
```
^spec-IDENTITY-TYPE

> [!note]
> **Примечания**
> - Это часть **оси Granularity** (Facet → Instance → Type), а именно участок **Instance → Type**.
> - **Descend-Granularity для этого участка = обратный запрос: “найди инстансы данного type”.

##### `STATE_IDENTITY` (Facet ↔ Instance)

(formal_id:: entity.STATE_IDENTITY.schema)
```python
RelationType STATE_IDENTITY {
  name: "STATE_IDENTITY"
  description: "Связь состояния с идентичностью: facet — срез состояния instance в окне/моменте. Facet не является отдельной идентичностью и не задаёт тип (это IDENTITY_TYPE)."
  signature: [
    facet    = Facet    "срез состояния (instance-state) в окне/моменте; самый пластичный уровень",
    instance = Instance "якорь идентичности, к которому принадлежит это состояние"
  ]
  views: [
    {
      name: "get_instance"
      description: "Получить instance для facet"
      inputs: ["facet"]
      outputs: ["instance"]
      output_arity: "one"
    },
    {
      name: "get_facets"
      description: "Получить facets (состояния) для instance"
      inputs: ["instance"]
      outputs: ["facet"]
      output_arity: "list0"
    }
  ]
}
```
^spec-STATE-IDENTITY

> [!note]
> **Примечания**
> - Это часть **оси Granularity, участок **Facet → Instance**.
> - **Descend-Granularity** для этого участка = обратный запрос: “дай фасеты (состояния) этого инстанса”.

### Ось Granularity: Гранулярность (Facet → Instance → Type)
#topic_core 

**Суть**
Эта ось отвечает на вопрос: **“это тот же объект, но на каком уровне описания?”**

Она связывает три уровня одной линии:

- **Facet** — “что сейчас / в этом эпизоде” (срез состояния) см. [[Core data structures#^def-Facet|Facet]] ^27292c
- **Instance** — “кто/что это как идентичность” (якорь)
- **Type (Prototype)** — “каков он по норме / схеме” (класс-предсказатель)

**Почему это часть лестницы абстракции**
Потому что это строгое обобщение: от текучего состояния к стабильной идентичности и далее к общей схеме, по которой наследуются priors.

**Распространение (зачем ось нужна в рантайме)**
По этой оси естественно распространяются:

- активация и релевантность (если активен Facet, вероятно важен Instance и его Type),
- priors/ожидания (Facet наследует priors от Instance/Type),
- награды и обобщение опыта (эпизодная награда может аккуратно поднимать статистику на Instance и Type уровнях, не переписывая их напрямую).

**Связи и операции (нейтральные факты + views)**

- `STATE_IDENTITY(facet, instance)` — связь состояния с идентичностью
    - view: `get_instance(facet) -> instance` _(one)_
    - view: `get_facets(instance) -> facet*` _(list0)_

#### get_facets
```
get_facets(
    instance: Instance,
    valid_at?: time, # оставить Facets, применимые к указанному времени мира;
    known_at?: time, # ограничить результат знаниями агента на этот момент.
) -> list[Facet] | unknown
```

Это стандартная операция временного чтения над базовым view `STATE_IDENTITY.get_facets` и историей графа. Она передаёт временные параметры при вызове view по [[#Общий исполнитель и результат|общему контракту чтения]], проверяет интервалы связанных `Facet` по `valid_at` в состоянии на `known_at` и извлекает persistent `Facet` из результатов view. При недостаточной сохранённой истории возвращается `unknown` по [[Attribution Plane#Историческая реконструкция свойства|общим правилам исторического чтения]].

Trace-local Facets извлекаются из соответствующего `SemanticTrace`. Операция `get_facets` используется, когда вызывающему процессу нужна структура самих состояний:

```
get_facets(Igor)
→ какие Facets Игоря материализованы;
```

Для получения значения конкретного свойства используется Attribution Plane:

```
read_property(Igor, HealthStatus)
→ какое значение здоровья агент приписывает Игорю.
```

Обычная доменная программа использует `read_property`, если её вопрос  
относится к определённому `PropertyConcept`. `get_facets` нужен для  
структурной навигации, исторической реконструкции, debugging и replay.


- `IDENTITY_TYPE(instance, type)` — связь идентичности с типом
    - view: `get_type(instance) -> type` _(one)_
    - view: `get_instances(type) -> instance*` _(list0)_

**Ascend-Granularity (к более общему):**

- `facet → instance` через `STATE_IDENTITY.get_instance`
- `instance → type` через `IDENTITY_TYPE.get_type`

**Descend-Granularity (к более частному):**

- `type → instances` через `IDENTITY_TYPE.get_instances`
- `instance → facets` через `STATE_IDENTITY.get_facets`

#### Связь с [[Uncertainty and Belief Tracking in the World Model]]
#topic_details 

> [!abstract]
> **Подход:** не создавать отдельный “граф веры” для Semantics Plane. Отдельные semantic values и relation-instances используют обычный `BeliefData`; mutually exclusive + exhaustive alternatives одного `CompetitionScope` используют один общий `Profile`, а не независимые belief-записи.
>
> Форматы `BeliefData` и `Profile` остаются общими и не переопределяются здесь: см. [[Uncertainty and Belief Tracking in the World Model#Belief representations]].
>
> Когда нужно рассматривать уверенность по уровням Лестницы абстракции, используется не новая форма `Belief_data`, а вычисляемый профиль над несколькими belief-записями:
>
> ```text
> SemanticBeliefProfile = List[LevelBelief]
> LevelBelief = <level, value_U?, belief_data>
> ```
>
> где `level` указывает уровень `facet/episode → instance → prototype₁ → ...`, а `belief_data` является `BeliefData` или `Profile`.

**Назначение:** разделить три типа семантической неопределённости, не смешивая их внутри одной `Belief_data`-записи:

- **[[Semantics Plane#STATE_IDENTITY Facet ↔ Instance|Facet]] / Episode** — текущий постериор для конкретного случая: “что именно происходит / что именно произошло сейчас?”. Самый пластичный уровень.
- **[[Semantics Plane#IDENTITY_TYPE Instance ↔ Type|Instance]]** — устойчивые особенности конкретного объекта/системы относительно общего prototype: “этот конкретный объект ведёт себя иначе”. Уровень персональных параметров и локальных исключений.
- **Prototype / Type** — обобщённая уверенность в типовых связях, механизмах и priors: “как обычно устроен мир и насколько мы в этом уверены”. Самый инертный уровень.

В Semantics Plane [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] концептуально похож на [[Semantics Plane#Views проекции над одним фактом|AccessView]] по роли, но не является `AccessView`-объектом: это вычисляемый epistemic view одного `CompetitionScope`, а не новый semantic fact и не набор копий [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] для alternatives.

**Интерпретация scalar Strength / Support по уровням:**

- **[[Semantics Plane#STATE_IDENTITY Facet ↔ Instance|Facet]] / Episode:**
    - [[Uncertainty and Belief Tracking in the World Model#Scalar Strength базовая форма|Strength]] = скалярная уверенность в конкретном semantic value / relation-instance / hypothesis в текущем контексте.
    - [[Uncertainty and Belief Tracking in the World Model#Belief Representations|Support]] = качество текущих свидетельств: сенсоры, наблюдения, подтверждения.

- **[[Semantics Plane#IDENTITY_TYPE Instance ↔ Type|Instance]]:**
    - Strength = уверенность в локальной особенности / поправке конкретного объекта относительно prototype.
    - Support = насколько стабильно эта особенность проявлялась именно у этого instance.

- **Prototype / Type:**
    - Strength = уверенность в типовой связи, правиле, prior или механизме.
    - Support = объём и качество подтверждений: статистика, эксперименты, надёжные источники.

> [!note]
> Для `CompetitionScope` один `LevelBelief` содержит общий [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] scope-а. `SemanticBeliefProfile` остаётся view по уровням, а не отдельным epistemic updater-ом.

##### Пример данных в разрезе уровней

> [!example] Вопрос «Каков основной источник воды на мокром асфальте?» задаёт `CompetitionScope` `{дождь, мойка, другой/смешанный источник}`.
> 
> - **Episode-level**:
>     - Profile-view: `{дождь: 0.55, мойка: 0.35, другой/смешанный: 0.10}`, общий `Support: low`.
>
> - **Prototype-level**:
>     - связь `дождь → мокро` хранит обобщённую Strength;
>     - Support копится медленно на основе повторяющихся подтверждений.

##### Belief_data → Semantic Runtime

Runtime использует уровни `SemanticBeliefProfile` по-разному:

- **Facet / Episode level** — для текущего выбора semantic interpretation: активная гипотеза, текущий тип объекта, текущая причина, текущая relation-instance.
- **Instance level** — для локальных исключений, персональных поправок и instance-specific priors.
- **Prototype level** — для общих semantic priors, иерархий, мериологии, планирования и обобщённых механизмов.

**Правило обновления:** episode-level belief может быстро меняться, но не должен напрямую переписывать prototype-level belief. Prototype-level обновляется медленнее и требует достаточного Support.

### Ось Taxonomy: Таксономия типов (Type → SuperType → …)
#topic_core 

**Суть**
Эта ось отвечает на вопрос: **“что это по сути как класс механизмов?”**

Это привычная онтологическая таксономия:

- `Такса ⊂ Собака ⊂ Животное ⊂ …`

**Почему здесь одиночное наследование (строгое дерево)**
Потому что типовая таксономия используется как “скелет” для:

- наследования норм и ограничений,
- совместимости фасетов и интерфейсов,
- стабильного обобщения знаний.

> [!important]
> Множественное наследование почти всегда порождает двусмысленность “какие нормы наследовать”, поэтому правило — **не более одного таксономического родителя**.

Дополнительные классификации задаются через [[Attribution Plane#2. Membership property fact|CLASSIFIED_AS]] и не добавляют родителей в дерево наследования.

**Связь и операции (нейтральный факт + views)**

- `SUBTYPE_OF(type, supertype)` — таксономическая связь типов
    - view: `get_supertype(type) -> supertype?` _(optional)_
    - view: `get_subtypes(supertype) -> type*` _(list0)_

**Ascend-T (к более общему):**

- `type → supertype → …` через `SUBTYPE_OF.get_supertype`

**Descend-T (к более частному):**

- `supertype → subtypes → …` через `SUBTYPE_OF.get_subtypes`

---

## Ось Композиции (Mereology)
#topic_core 

`<MereologyAxis>`: `<Axis>`

**Суть**
Ось композиции моделирует отношение **часть–целое** для систем и объектов: “из чего состоит?” и “частью чего является?”.

(formal_id:: entity.PART_WHOLE.schema)
```python
RelationType PART_WHOLE {
  name: "PART_WHOLE"
  description: "Мериологический факт часть–целое: part является частью whole. Не является таксономией типов (SUBTYPE_OF) и не описывает состояние/идентичность (STATE_IDENTITY/IDENTITY_TYPE). Не означает 'похожесть' или 'обладает свойством'."
  signature: [
    part  = Part  "часть (подсистема/компонент/элемент)",
    whole = Whole "целое (система/агрегат/объект, включающий part)"
  ]
  views: [
    {
      name: "get_wholes"
      description: "Получить целое(ые) для части"
      inputs: ["part"]
      outputs: ["whole"]
      output_arity: "list0"
    },
    {
      name: "get_parts"
      description: "Получить части для целого"
      inputs: ["whole"]
      outputs: ["part"]
      output_arity: "list0"
    }
  ]
}
```
^spec-PART-WHOLE


**Ascend-Mereology (к более общему целому):**

- `part → whole(s)` через `PART_WHOLE.get_wholes`

**Descend-Mereology (к более частным компонентам):**

- `whole → parts` через `PART_WHOLE.get_parts`

> [!note]
> **Примечания**
> - Мериология — это **не** таксономия типов (`SUBTYPE_OF`) и **не** гранулярность идентичности (`STATE_IDENTITY`, `IDENTITY_TYPE`).
> - Отдельные RelationType ради навигации не нужны: Descend/Ascend реализуются через views и атомарные программы выбора/фильтрации.

---
