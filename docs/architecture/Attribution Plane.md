---
status: draft
target_version: next
ToDo:
---
## Intro
#topic_core 

Вопрос: **«Каков объект?»**  
Плоскость Атрибуции отвечает за свойства, измерения и классификации объектов, состояний и концептов.

(def_id:: et.AttributionPlane)
> [!definition]
> **Attribution Plane** — это плоскость, чья суть состоит в том, чтобы представлять объект через его свойства: измерять их, сравнивать, нормализовать и использовать в reasoning. В EverTree сущность/состояние `x` описывается через **property facts** (факты свойств), а результат чтения свойства возвращается в едином формате `PropertyReading(U)`.
^def-AttributionPlane

Иначе говоря, **Attribution Plane** — это пространство, где агент отвечает не на вопрос *«что это по сути?»* и не на вопрос *«что произойдёт?»*, а на вопрос:

- какой у объекта цвет,
- какова его скорость,
- высокий ли у него риск,
- на какой он поверхности,
- в какой фазе находится,
- к какому классу он относится по данному критерию.

### Ключевые принципы

- `PropertyConcept` — это **тип аспекта**, который мы хотим знать про `x`  
  (например `SpeedOfMotion`, `SurfaceUnder`, `UserIntent`, `RiskLevel`).

- Свойства **не обязаны храниться готовыми внутри объекта**.  
  Их значения получают через чтение, вывод или нормализацию; сохранение результата в графе — отдельное решение.

- **Входы чтения** определяет контракт свойства или связанной `Program`: какие условия уточняют вопрос и какие данные нужны для ответа. Они передаются через [[#Параметры операций|объявленные параметры]].

- Ось в этой плоскости — это **операционная утилита над свойством**:
  она читает, вычисляет, сравнивает и нормализует значения свойства, давая агенту рабочий доступ к нему.


---

## Attribution Axis
#topic_core 

(def_id:: et.AttributionAxis)
> [!definition]
> **Attribution Axis** — это ось внутри Attribution Plane, которая задаёт одно свойство объекта как измерение на некоторой шкале `U` и определяет, как это свойство читать, сравнивать, нормализовать и использовать в reasoning.
^def-AttributionAxis

Интуитивно ось — это способ ответить на вопрос вида:

- “какова скорость этого объекта?”  
- “насколько высок риск?”  
- “в какой фазе находится процесс?”
- и т.д.

Ось задаёт не только **что именно измеряется**, но и **в какой форме это значение существует** и **какие операции над ним допустимы**.

### Что задаёт ось

Каждая ось в Плоскости Атрибуции задаёт:

- **Домен (`X`)** — к каким объектам, состояниям или концептам применимо свойство.
- **Шкалу (`U`)** — пространство допустимых значений.
- **Результат измерения** — в какой форме ось возвращает значение свойства.
- **Алгебру операций** — какие операции допустимы для значений на этой шкале  
  (сравнение, расстояние, принадлежность, нормализация, фильтрация).
- **Динамику обновления** — Правила работы со значениями на шкале `U`;


> [!note]
> Ось не является самим свойством.  
> `PropertyConcept` задаёт смысл свойства, а `AttributionAxis` задаёт операционный интерфейс доступа к нему.


> [!note] Специфика Attribution Plane
> В Attribution Plane ось возвращает не просто `Belief(U)`, а атрибутивное чтение:
>
> ```text
> PropertyReading(U) := <value_U?, belief_data>
> ```
>
> `belief_data` — `BeliefData` отдельного значения / утверждения либо `Profile` одного `CompetitionScope`. Точный контракт задан в [[#Formal definition]].

---

## Attribution Plane

### Formal definition
#topic_core 

В **Attribution Plane** ось задаёт свойство объекта как отображение:

$$
a_p: X \times I_p \rightarrow \mathrm{PropertyReading}(U_p) \cup \{\mathrm{unknown}\}
$$

где:

- **`p`** — `PropertyConcept`, то есть измеряемое свойство;
- **`X`** — пространство объектов, состояний или концептов, к которым применяется свойство;
- **`I_p`** — допустимые наборы входов по [[#Параметры операций|контракту чтения свойства]]; это математическое обозначение, а не отдельный тип данных;
- **`U_p`** — шкала (_scale_) значения данного свойства;
- **$\mathrm{PropertyReading}(U_p)$** — атрибутивный результат вида:

$$
\mathrm{PropertyReading}(U_p) := \langle value_{U_p}?,\ belief\_data \rangle
$$

где:

- **`value_U`** — значение свойства на шкале `U`;
- **`belief_data`** — [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] отдельного значения / утверждения либо [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] mutually exclusive + exhaustive alternatives одного [[Uncertainty and Belief Tracking in the World Model#^def-CompetitionScope|`CompetitionScope`]].

С `BeliefData` поле `value_U` обязательно. В scope-backed reading каноническим результатом является `Profile`; `value_U` возвращается только как производный point-view по явной selection policy и не материализует достоверный property fact.

Смена источника не меняет шкалу `U_p`: качественная интерпретация числового свойства возвращается на своей шкале `U_norm` через [[#Numeric ↔ Qualitative via Criterion|Criterion]].


Конкретные формы **`value_U`** по типам шкал описаны в разделе [[#Scale types]].  
Общие правила belief update описаны в [[Uncertainty and Belief Tracking in the World Model]].
`unknown` означает недоступность применимого чтения; см. [[#5. Unknown]].


---

## Scale types
#topic_core 

Шкала `U` определяет, **какого рода значения** возвращает ось и **какие операции** над ними допустимы.

В Плоскости Атрибуции используются четыре базовых типа шкал:

1. **Nominal** — категориальная,
2. **Ordinal** — ранговая,
3. **Numeric** — числовая,
4. **Circular** — циклическая.

> [!note]
> Тип шкалы определяет не только форму значения, но и набор допустимых операций.  
> Именно поэтому важно различать, например, “класс” и “число”, даже если оба используются для описания одного и того же объекта.

---

### 1. Категориальная ось (Nominal)

**Смысл:**  
Ось задаёт классы или категории **без естественного порядка** между ними.

Это подходит для свойств, где корректно спрашивать **“какой класс?”**, но некорректно спрашивать **“больше или меньше?”**.

**Типичные примеры:**

- язык,
- домен,
- роль,
- тип интента,
- класс ошибки,
- категория поверхности.

Форма `value_U`:

- `value_U = C`, где `C` — одно из допустимых значений nominal scale `U`.

Сам тип nominal scale ещё не гарантирует взаимоисключаемость значений. Epistemic representation выбирается по semantic contract конкретного Property:

```text
values mutually exclusive + exhaustive
→ один CompetitionScope
→ один Profile в belief_data;

несколько values могут быть истинны одновременно
→ отдельные binary BeliefTarget.
```

Например, `SQLProblemSolvingLevel(AgentA)` со шкалой `Low | Medium | High` использует общий `CompetitionScope` и `Profile`, если `Criterion` действительно делает эти значения взаимоисключающими и исчерпывающими. Независимые свойства `GoodAtSQL`, `GoodAtPython`, `GoodAtDebugging` таким scope не являются.

**Как представляется в графе:**

- обычно через `CLASSIFIED_AS(entity, C)`,  
  где `C` — допустимое значение шкалы данного `PropertyConcept` по критерию, соответствующему смыслу классификации и условиям запроса.

**Допустимые операции:**

- `equals(C1, C2)` — равенство,
- `membership(C, S)` — принадлежность множеству,
- предикаты вида `=` / `∈` / `NOT(...)`.

**Важно:**  
Если значения не образуют естественного порядка, это **не ordinal** и не numeric, а именно **nominal**.

**Мини-пример:**

- Property: `Language`
- Value: `CLASSIFIED_AS(Message#77, UA)`

---

### 2. Ранговая ось (Ordinal)

**Смысл:**  
Ось задаёт **порядок** значений, но не задаёт корректной числовой дистанции между ними.

Это подходит для свойств, где можно сказать:

- выше / ниже,
- лучше / хуже,
- важнее / менее важно,

но нельзя строго и универсально сказать **“на сколько”**.

**Типичные примеры:**

- `RiskLevel`,
- важность,
- срочность,
- приоритет,
- степень релевантности.

Форма `value_U`:

- `value_U ∈ OrderedClassConcept`, где классы образуют явно упорядоченное множество.

Если ordinal values mutually exclusive и exhaustive, `belief_data` является тем же `Profile` соответствующего `CompetitionScope`. Порядок alternatives не меняет epistemic updater.

**Как представляется в графе:**

- обычно через `CLASSIFIED_AS(entity, RiskHigh)` и аналогичные классы,
- а сам порядок задаётся явно структурой `ValueOrder`, а не именем класса.

**Допустимые операции:**

- `compare(c1, c2) -> {less, equal, greater, incomparable}`,
- сортировка,
- top-k,
- предикаты `>=`, `<=`.

В ordinal-шкале нельзя безопасно считать разности типа:

- `High - Mid`
- “в два раза выше”

Если для свойства важны корректные дельты и расстояния, нужна уже **numeric** шкала.

**Мини-пример:**

- Property: `RiskLevel`
- Value: `CLASSIFIED_AS(Task#A, RiskHigh)`

---

### 3. Числовая ось (Numeric)

**Смысл:**  
Ось задаёт свойство как величину на числовой шкале, где корректны:

- сравнение,
- расстояние,
- диапазоны,
- дельты,
- а иногда и агрегирование.

Это основной тип оси для количественных измерений.

**Типичные примеры:**

- скорость,
- масса,
- температура,
- стоимость,
- время,
- latency,
- вероятность,
- риск-скор.

**Форма `value_U`**:

- число (`float`, `int`);
- интервал;
- параметры распределительной оценки;
- sketch / квантили, если сама форма значения является приближённой оценкой.
- `Belief_data` отдельно 



**Как представляется в графе:**

- скалярное значение — через `HAS_NUMERIC_VALUE(entity, property, value[, unit])`;
- интервал, распределение или другая числовая оценка — как типизированный результат по [[#4. Типизированный результат или вычисление|контракту источника оси]].

**Допустимые операции:**

- `<, >, <=, >=`,
- `in [a,b]`,
- `≈` с допуском,
- `distance(v1, v2)`,
- дельта,
- нормализация относительно домена.

**Нормы и сопоставимость:**  
Numeric-оси почти всегда требуют интерпретации **относительно домена**:

- `112 km/h` для машины и для самолёта означают разное,
- `50 ms latency` может быть хорошим или плохим в зависимости от типа системы.

Поэтому numeric-значения часто дополняются доменными распределениями и критериями нормализации.

**Мини-пример:**

- `HAS_NUMERIC_VALUE(MyCarNow, SpeedOfMotion, 112 km/h)`

---

### 4. Циклическая ось (Circular)

**Смысл:**  
Ось задаёт значения, живущие **по кругу**, а не на линейной прямой.

В такой шкале начало и конец совпадают:

- `0° ≡ 360°`,
- конец цикла возвращает нас в ту же точку.

Это важно для фаз, углов, периодов и ритмов.

**Типичные примеры:**

- угол,
- фаза,
- сезонный цикл,
- периодичность,
- стадии повторяющегося процесса.

**Форма значения:**

- число с циклической топологией,
- либо дискретные фазы, если цикл разбит на этапы.

**Как представляется в графе:**

- числовой вариант:  
  `HAS_NUMERIC_VALUE(entity, property, θ[, unit])`
- дискретный вариант:
  `CLASSIFIED_AS(entity, Phase3)`

**Допустимые операции:**

- `circular_distance(θ1, θ2)` — расстояние по кратчайшей дуге,
- `≈` с допуском по окружности,
- `shift(θ, Δ)` — фазовый сдвиг (опционально).

**Важно:**  
Линейная метрика здесь ломает смысл.

Например:

- расстояние между `350°` и `10°` равно `20°`, а не `340°`.

**Мини-пример:**

- `HAS_NUMERIC_VALUE(EngineNow, PhaseAngle, 350 deg)`

---

### Связь типа шкалы и reasoning

Тип шкалы определяет, **какие вопросы можно корректно задавать оси**.

- **Nominal** — “это то же значение или нет?”
- **Ordinal** — “что выше / ниже?”
- **Numeric** — “на сколько больше / ближе / дальше?”
- **Circular** — “насколько близко по циклу?”

Поэтому выбор типа шкалы — это не косметика, а часть контракта смысла свойства.

---

## Property facts and relation-backed readings
#topic_core 

Ось Атрибуции не хранит значение свойства сама по себе. Она читает факты или типизированные результаты либо вычисляет значение через связанную со свойством модель или правило.

Нужно различать:

- **native property facts** — факты, которые прямо хранят значение свойства в Attribution Plane;
- **relation-backed readings** — атрибутивные чтения, где значение свойства извлекается из semantic relation-instance.

Property facts нужны, чтобы разделить:

- **что измеряем** — `PropertyConcept`, например `SpeedOfMotion`, `UserIntent`;
- **у какой сущности измеряем** — `Entity`, `Facet`, `Instance`, `Prototype`;
- **какое значение получили** — число или класс;
- **каково epistemic состояние чтения** — `BeliefData` либо общий `Profile` scope-а.

Ось Атрибуции использует применимые к её шкале источники значения свойства:

1. numeric property fact;
2. membership property fact;
3. relation-backed reading из Semantics Plane;
4. [[#4. Типизированный результат или вычисление|Типизированный результат или вычисление]] по объявленной семантической привязке.

---

### 1. Numeric property fact

Используется, когда значение свойства является числом.

```python
RelationType HAS_NUMERIC_VALUE {
  name: "HAS_NUMERIC_VALUE"
  description: "Числовой факт свойства: entity имеет числовое значение по property. Значение хранится как число (не как Concept) и несёт Belief_data на ребре. Не является классификацией (CLASSIFIED_AS) и не задаёт таксономию/мериологию."
  signature: [
    entity   = Entity   "сущность, к которой привязываем измерение (Facet/Instance/Prototype/...)",
    property = Property "какое свойство измеряем (Concept смысла: SpeedOfMotion, Latency, ...)",
    value    = Number   "числовое значение (float/int)",
    unit?    = Unit     "единица измерения (если применимо)"
  ]
}
```

**Примеры:**

- `HAS_NUMERIC_VALUE(MyCarNow, SpeedOfMotion, 112, km/h)`
- `HAS_NUMERIC_VALUE(ServerNow, Latency, 84, ms)`
- `HAS_NUMERIC_VALUE(Object#7, Mass, 12.5, kg)`

---

### 2. Membership property fact

Используется, когда значение свойства выражено принадлежностью к классу.

```python
RelationType CLASSIFIED_AS {
  name: "CLASSIFIED_AS"
  description: "Факт принадлежности entity к class_concept. Является значением Property, если class_concept входит в его шкалу и Criterion соответствует смыслу классификации и условиям запроса."
  signature: [
    entity        = Entity       "сущность, которую классифицируем (Facet/Instance/Prototype/...)",
    class_concept = ClassConcept "класс/категория как Concept (Fast, OnRoad, RefundIntent, UA, ...)"
  ]
}
```

`CLASSIFIED_AS(entity, C)` считается значением свойства `property`, если `C` входит в его шкалу, а применимый `Criterion` связывает класс со свойством и сохраняет смысл оцениваемого утверждения. Класс вроде `Fast` может быть качественной интерпретацией числового свойства, но не заменяет значение на его Numeric-шкале. Без такой связи классификация остаётся самостоятельным утверждением.

Если допустимые values Property mutually exclusive и exhaustive, каждое допустимое proposition `CLASSIFIED_AS(entity, C)` обозначает alternative одного [[Uncertainty and Belief Tracking in the World Model#^def-CompetitionScope|`CompetitionScope`]]. Evidence назначается scope целиком, а `Strength(C)` читается из общего [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]; отдельные belief, `Support` или `PriorSupport` для каждого `C` не создаются.



(def_id:: et.Criterion)
> [!definition]
> **`Criterion`** — правило, задающее условия интерпретации или проверки утверждения либо результата в определённой области применения.
^def-Criterion

При классификации `Criterion` связывает `ClassConcept` с `PropertyConcept` и задаёт область применения, необходимые входы и условия принадлежности классу. Вместе со шкалой он определяет, являются ли alternatives mutually exclusive и exhaustive. Правило не утверждает принадлежность конкретного объекта; например, оно задаёт, при какой скорости и в каком домене объект считается `Slow`, `Normal` или `Fast`.

Критерий может быть частью семантического определения или [[Process Plane/Program Layer#Program Contracts|контракта Program]]; отдельный узел и копия правила не обязательны. Для оценки числовых значений и моделей действует [[Uncertainty and Belief Tracking in the World Model#Numeric and distributional values|общий контракт numeric belief]].

`Profile` выражает только epistemic uncertainty между заданными alternatives и не компенсирует неполную или неоднозначную scale.

Если существует только разовый claim вроде «AgentA хорошо решает SQL-задачи», но нет полезных общих `PropertyConcept` + scale + `Criterion`, искусственный факт `SQLProblemSolvingLevel(AgentA) = High` не создаётся. Утверждение остаётся [[Core data structures#^def-Claim|`Claim`]] до появления достаточно строгой semantic structure.

**Примеры:**

- `CLASSIFIED_AS(MyCarNow, Fast)`  
    является качественной интерпретацией `SpeedOfMotion` по критерию `Fast-from-SpeedOfMotion`.
    
- `CLASSIFIED_AS(Message#77, UA)`  
    считается значением свойства `Language`, если `UA` входит в допустимые значения `Language`.
    
- `CLASSIFIED_AS(UserMessage#12, RefundIntent)`  
    считается значением свойства `UserIntent`, если есть критерий классификации интента.
    

---

### 3. Relation-backed attribution projection

Используется, когда значение свойства не хранится как отдельный native-факт Attribution Plane, а получается как проекция structural relation fact.  
  
Сам structural relation fact принадлежит своей native-плоскости: Semantic / Structural / Hierarchy, в зависимости от типа отношения.

Пример:

```python
ON_SURFACE {
  vehicle = MyCar
  surface = Road#17
}
```

Его атрибутивная проекция:

```python
SurfaceUnder(MyCar) = Road#17
```

Здесь:

- `ON_SURFACE(vehicle, surface)` — native structural relation fact;
- `SurfaceUnder` — `PropertyConcept` в Attribution Plane;
- `Road#17` — `value_U`, полученное из output-slot `surface`;
- `belief_data` наследуется из исходного relation fact.

Attribution Plane не дублирует structural relation fact. Она только задаёт правило, как читать его как значение свойства.


Ось использует [[Semantics Plane#Общий исполнитель и результат|общий исполнитель views]], передавая [[#Чтение свойств состояния|временные параметры запроса]]. Для `ON_SURFACE` view `get_surface` объявляет `inputs=["vehicle"]`, `outputs=["surface"]`, `output_arity="list0"`. В примере `select_one` применяет `latest` к метаданным `source_fact` и возвращает `None`, если кандидатов нет или политика не разрешает выбор:

```python
matches = ON_SURFACE.get_surface(
  vehicle=MyCar,
  valid_at=valid_at, known_at=known_at,
)
if matches is unknown:
  return unknown
match = select_one(matches, policy="latest")
if match is None:
  return unknown

return PropertyReading(
  value_U = match.value,  # Road#17
  belief_data = match.source_fact.belief_data
)
```

Здесь `source_fact.belief_data` обозначает общее чтение belief с теми же `valid_at` и `known_at`. Такое чтение не создаёт новый relation fact и не дублирует исходную связь.

Если нужна быстрая фильтрация, нормализация или объяснимость, можно дополнительно материализовать summary-класс:

```python
CLASSIFIED_AS(MyCarNow, OnRoad)
```

Но только если это даёт операционную пользу: ускорение поиска, сжатие, объяснимость, нормализацию или кеширование дорогого вывода.

Такой summary-class регулируется через `Criterion` / mapping rule и Materialization Policy.


---

## Axis interface
#topic_details 

Ось Атрибуции читает или вычисляет значение через заданные для свойства источники и возвращает [[#Formal definition|`PropertyReading(U)`]] либо `unknown`.

`measure`, `read_property` и `reconstruct_property` используют общий контракт источников и [[#Чтение свойств состояния|временных ограничений]]. Эти ограничения действуют и при чтении нормы или правила для `normalize`. Чтение выполняет предусмотренное контрактом вычисление в пределах бюджета задачи; оно не ищет и не обучает новые модели. Результат получает обычный [[Memory#^def-ResultProvenance|provenance]]; материализация в persistent graph выполняется отдельно через [[Core data structures#Изменение persistent graph|`GraphDelta`]].

В примерах `fact.belief_data` обозначает вычисляемое [[Uncertainty and Belief Tracking in the World Model#Read-time computation and provenance|чтение belief]] соответствующего target. Сохранённый исторический snapshot не подменяет текущую оценку.

### Параметры операций

Контракт свойства, критерия или связанной `Program` объявляет необходимые параметры, их типы и [[Process Plane/Program Layer#^program-semantic-interface|семантические роли]]. Входами могут быть условия вопроса, сведения о самом объекте, внешние факты или предположения. Постоянные условия закрепляются контрактом; изменяемые передаются именованными аргументами. Для сохранённого результата используются закреплённые за ним условия, если они соответствуют запросу.

[[Cognition and Attention#^def-PreparedContext|`PreparedContext`]] задачи служит одним из источников для [[Process Plane/Program Layer#^def-ArgumentPreparation|подготовки аргументов]] конкретного вызова. Готовые аргументы можно передать напрямую. Обязательного общего параметра `context` у операций оси нет.

Условия, меняющие смысл вопроса, учитываются в [[Uncertainty and Belief Tracking in the World Model#Belief and BeliefTarget|каноническом target]]; дополнительные наблюдения о том же вопросе уточняют его оценку. Гипотетические условия задаются явно как предположения и сохраняют этот статус в результате.

В сигнатурах ниже `...` обозначает дополнительные именованные параметры конкретного контракта. Параметр можно опустить, если его значение или способ получения определён контрактом; нехватка необходимых данных или неоднозначность вопроса дают `unknown`.

---
### `measure`

```text
measure(x, property, *, valid_at=now, known_at=now, ...)
    -> PropertyReading(U) | unknown
```

`measure` читает свойство уже выбранного объекта или состояния `x`. Ось и источники заданы контрактом свойства; разрешение состояния Instance выполняет [[#Чтение свойств состояния|`read_property`]].

---

### Правило чтения: применимость источников

Источник должен соответствовать свойству, его шкале и условиям запроса, включая объявленные параметры, `valid_at` и `known_at`. Порядок подразделов ниже не задаёт приоритет: выбор между применимыми источниками определяется контрактом чтения свойства. Отсутствие числового значения не разрешает вернуть класс вместо него.

#### 1. Numeric fact

Если существует:

```python
HAS_NUMERIC_VALUE(x, property, v)
```

ось возвращает:

```python
PropertyReading(  
value_U=v,  
belief_data=fact.belief_data  
)
```

где:
`belief_data` соответствующего `HAS_NUMERIC_VALUE` fact.

---

#### 2. Membership fact

Если семантика свойства задаёт `CompetitionScope` с mutually exclusive + exhaustive alternatives, ось возвращает его общий `Profile` независимо от выбора или материализации отдельного `CLASSIFIED_AS(x, C)`:

```text
PropertyReading(
  belief_data = Profile {
    strengths = {
      Low:    0.05,
      Medium: 0.25,
      High:   0.70
    },
    support = ...,
    prior_support = ...
  }
)
```

По явной selection policy чтение может дополнительно вернуть `value_U = High`; это производный point-view, а не замена `Profile`. Evidence обновляет весь scope через общий `CompetitionScopeUpdater`; остальные инварианты определены в [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]].

При отсутствии собственного evidence действует предусмотренный scope prior. Чтение не создаёт scope или alternatives: одна nominal-шкала не гарантирует их взаимоисключаемость и исчерпываемость.

Для независимой binary classification `CLASSIFIED_AS(x, C)` чтение возвращает:

```python
PropertyReading(
   value_U = C,
   belief_data = fact.belief_data
)
```

В обоих случаях классы должны входить в запрошенную шкалу, а `Criterion` — связывать их со свойством, быть применимым к домену и контексту и соответствовать смыслу target. Для binary classification `Strength` оценивает принадлежность классу, а `Support` отражает назначенное ей evidence, учитывающее применимость критерия.

Если известно только `Fast`, соответствующее `CLASSIFIED_AS(x, Fast)` находится через [[Semantics Plane#Views: проекции над одним фактом|view отношения]] или retrieval. [[Uncertainty and Belief Tracking in the World Model#Read-time computation and provenance|Общее чтение belief]] возвращает `BeliefData` независимой классификации либо `Profile` её scope с учётом условий и временных ограничений запроса. Это знание доступно для фильтрации без числовой оценки.

Числовое чтение `SpeedOfMotion` остаётся недоступным, пока нет применимой числовой оценки. При наличии числового значения качественную интерпретацию возвращает [[#Numeric normalization|`normalize`]].

---

#### 3. Relation-backed attribution projection

Если свойство задано как атрибутивная проекция structural relation fact, например:

```python
ON_SURFACE { vehicle=x, surface=s }
```

ось применяет заданное правило источника (`PropertySource`):

```python
source_relation = ON_SURFACE
source_view = "get_surface"
selection_policy = "latest"
```

и возвращает:

```python
PropertyReading(value_U = s, belief_data = belief_data)
```
    
- исходный `ON_SURFACE` остаётся native relation fact своей плоскости;
- если создаётся summary-class вроде `OnRoad`, он должен быть разрешён через `Criterion` / Materialization Policy.

Если нужен сам relation fact или его аргументы, используется view соответствующего `RelationType`. `read_property` используется только тогда, когда для relation определена проекция на конкретный `PropertyConcept`.

```text
ON_SURFACE.get_surface(vehicle=MyCar)
→ проекции подходящих facts с сохранением source_fact;

read_property(MyCar, SurfaceUnder)
→ атрибутивное чтение по правилу свойства, включая выбор кандидата.
```

Оба интерфейса используют одни исходные facts без дублирования.

---
#### 4. Типизированный результат или вычисление

Источником может быть сохранённый типизированный результат или вычисление уже связанной со свойством Program, модели либо правила. [[Process Plane/Program Layer#Семантические типы аргументов и результатов|Семантическая привязка]] определяет, к какому объекту, свойству и условиям относится результат; совпадения Python-типа недостаточно. Это позволяет читать интервалы, распределения и другие numeric estimates, сохраняя скалярный контракт `HAS_NUMERIC_VALUE`.

Сохранение и адресация результата используют [[Core data structures#Объекты и ссылки|общие правила объектов и ссылок]]. Исторический результат сохраняет использованное значение, а не ссылку на изменяемое текущее состояние estimator-а. Typed output не становится persistent property fact автоматически: применяются [[Memory#Trace-local и persistent results|общие правила материализации]].

---
#### 5. Unknown

Если применимое чтение недоступно, в том числе из-за недостающих необходимых входов:

```python
unknown
```

Отсутствие выбранного класса или собственного evidence само по себе не означает `unknown`: для заданного scope применяются [[#2. Membership fact|правила чтения Profile]].

---

### `compare(v1, v2)` / `distance(v1, v2)`

Эти операции применимы только если их поддерживает шкала `U` данного свойства.

- **Nominal:**  
    `equals`, `membership`, канонизация/синонимия при необходимости.  
    Нет порядка и нет расстояния.
    
- **Ordinal:**  
    `compare`, сортировка, top-k.  
    Есть порядок, но нет корректной дельты.
    
- **Numeric:**  
    `compare`, `distance`, дельта, диапазоны, оптимизация.
    
- **Circular:**  
    циклическая близость, фазовый сдвиг, расстояние по минимальной дуге.
    

Пример:

```python
distance(350 deg, 10 deg) -> 20 deg
```

а не `340 deg`.

---

### `normalize`

```text
normalize(v | dist, property, domain, *, valid_at=now, known_at=now, ...)
    -> PropertyReading(U_norm) | unknown
```

**Назначение:** перевести raw-значение в форму “относительно нормы домена”.

Нормализация нужна, потому что одно и то же числовое значение может иметь разный смысл для разных типов объектов и разных контекстов.

Пример:

- `112 km/h` для машины — возможно нормально;
- `112 km/h` для человека — невозможно или аномально;


---

#### Numeric normalization

Для числовых шкал нормализация использует распределение домена (квантили/z-score и т.п.)

Пример:

```python
normalize(112 km/h, SpeedOfMotion, domain=Vehicle)
```

Нормализация возвращает `PropertyReading(U_norm)`.

Пример:

```python
PropertyReading(  
    belief_data = Profile {
        strengths = {Slow: 0.05, Normal: 0.20, Fast: 0.75}
    }
)
```

По явной selection policy чтение может дополнительно вернуть `value_U = Fast`.

---

#### Ordinal / Nominal derived-from-numeric

Для качественных классов, производных от чисел, нормализация означает применение критерия banding к переданному значению. Например, значение из:

```python
HAS_NUMERIC_VALUE(MyCarNow, SpeedOfMotion, 112 km/h)
```

интерпретируется по критерию:

```python
Fast-from-SpeedOfMotion
```

Результат — качественное чтение по [[#Numeric normalization|правилам нормализации]]. Сохранённая классификация `CLASSIFIED_AS(MyCarNow, Fast)` читается независимо по [[#2. Membership fact|правилам membership facts]]; `normalize` не ищет её по объекту.

> [!note]  
> Нормализация не обязана материализовывать derived fact.  
> Она может вернуть результат лениво, а решение о записи в граф регулируется Materialization Policy.

---

### Чтение свойств состояния

#topic_details 

Для чтения состояния используется конкретный `PropertyConcept`, а не абстрактный `state_variable`.

Основной интерфейс:

```
read_property(
    subject: Concept,
    property: PropertyConcept,
    *,
    valid_at: time = now,
    known_at: time = now,
    ...
) -> PropertyReading | unknown
```

- `subject` — объект, к которому применимо свойство: Instance, выбранный Facet или другой Concept.
- `property` — требуемое свойство.
- `valid_at` — время мира, к которому относится значение.
- `known_at` — момент, знаниями на который ограничивается чтение.

Примеры для контрактов с указанными параметрами:

```
read_property(Igor, HealthStatus)
read_property(car, SpeedOfMotion, reference_frame=road_frame)
read_property(source, SourceReliability, domain=Programming)
```

Общий порядок чтения:

```
1. Разрешает объект или состояние по контракту свойства и временным ограничениям.
2. Получает значение из применимого источника по общим правилам оси.
3. Читает BeliefData или Profile соответствующего target по общему belief-контракту.
4. Возвращает PropertyReading либо unknown.
```

При чтении состояния Instance первый шаг использует [[Semantics Plane#get_facets|persistent Facets]], применимые в `valid_at` и известные в `known_at`; переданный Facet читается непосредственно. Для факта на самом Instance, relation projection или связанной Program создание промежуточного Facet не требуется.

Если `HealthStatus` задаёт mutually exclusive + exhaustive values, `read_property` возвращает общий `Profile` по правилу [[#2. Membership fact]].

---

### Историческая реконструкция свойства
#topic_details 

Для восстановления знаний агента на прошлом этапе используется обёртка того же чтения:

```
reconstruct_property(
    subject: Concept,
    property: PropertyConcept,
    *,
    valid_at: time,
    known_at: time,
    ...
) -> PropertyReading | unknown
```

Она вызывает `read_property` с теми же аргументами и обязательными `valid_at` и `known_at`.

Ограничение `known_at` распространяется на evidence, фактические входы, код, правила, нормы и состояние моделей во всех источниках чтения, включая `measure` и `normalize`. Реконструкция использует сохранённый результат либо вычисление по согласованным историческим версиям; доступная точность ограничена [[Memory#Удержание, сжатие и забывание|сохранённой детализацией памяти]].

**Начальная реализация должна быть простой:** в MVP достаточно поддержать чтение на моменты доступных завершённых [[Cognition and Attention#^agent-backup|backup агента]]:

1. Загрузить backup, соответствующий `known_at`, в отдельное окружение только для чтения, без возобновления workflows.
2. Использовать сохранённые данные, действовавшие evidence, модели и правила. Зависящие от времени расчёты учитывают заданные `valid_at` и `known_at`.
3. Выполнить обычное чтение свойства в этом окружении.
4. Если нужного состояния или зависимости нет, вернуть `unknown`; сегодняшние данные и модели не подставляются.

Полное восстановление любого момента не требуется. Между backup оно допустимо при достаточной истории изменений; ближайший backup нельзя выдавать за состояние на другой `known_at`.

[[Memory#^def-TraceEvent|Сохранённый trace]] показывает фактически выполненное прежнее вычисление. Новый расчёт по историческому состоянию сам по себе не означает, что агент уже получил этот результат тогда.


---

## Операционные роли осей Атрибуции
#topic_core 

Attribution Plane не просто хранит свойства. Она даёт агенту операционный доступ к ним:

```text
измерить → сравнить → наложить ограничение → отфильтровать → выбрать → нормализовать
```

Важно различать два независимых уровня:

- **тип шкалы `U`** — какие значения возвращает ось: `Nominal`, `Ordinal`, `Numeric`, `Circular`;
    
- **роль оси в задаче** — что агент делает с этим значением: фильтрует, выбирает, ранжирует, ищет ближайшее, нормализует, проверяет согласованность.
    



---

### 1. Filtering role

Ось используется как ограничение для отбора кандидатов.

Это predicate-based filtering: агент не ищет “лучшее”, а отбрасывает всё, что не проходит условие.

Примеры:

- **Nominal:**  
    `Color = Red`  
    `Language ∈ {EN, UA}`  
    
- **Ordinal:**  
    `RiskLevel >= Medium`  
    `Priority <= Low`
    
- **Numeric:**  
    `Latency >= 50 ms AND Latency < 120 ms`  
    
- **Circular:**  
    `circular_distance(Phase, θ) <= 20 deg`  
    `Phase ≈ 180 deg`
    

В этом режиме ось должна поддерживать предикаты, применимые к её шкале:

```python
=, !=,  <, >, <=, >=, ≈, (AND/NOT)
```

Форма равенства зависит от типа шкалы:

- для дискретных значений — точное равенство;
    
- для числовых и циклических — равенство с допуском;
    
- для scope-backed Property — порог `Strength` alternative в общем `Profile`.
    

Фильтры можно компоновать из нескольких свойств:

```python
Color = Red AND Weight < 10 kg AND SurfaceType = Road
```

или:

```python
Intent = RefundIntent AND AngerLevel >= Medium AND LegalThreat = false
```

Так агент формирует рабочие множества кандидатов для reasoning, planning и action selection.

---

### 2. Selection / Retrieval role

Ось используется как пространство выбора, когда агенту нужно не просто проверить условие, а выбрать, ранжировать или найти подходящие значения.

В этом режиме ось помогает:

- ранжировать кандидатов;
    
- искать top-k;
    
- находить ближайшее значение;
    
- искать “чуть больше / чуть меньше”;
    
- выбирать минимум или максимум;
    
- находить кандидатов в диапазоне и ранжировать их;
    
- выбирать следующее значение или кандидата, ближайшего к целевому диапазону.
    

Примеры:

- выбрать задачу с максимальным `Priority`;
    
- найти объект с размером, ближайшим к целевому;

- сначала отфильтровать пользователей по `RiskLevel >= Medium`, затем ранжировать оставшихся по `RiskScore`.
    

Selection / Retrieval естественно поддерживают:

- **Ordinal** — сортировка, top-k, min/max;
    
- **Numeric** — distance, delta, nearest, range search, optimization;
    
- **Circular** — circular distance, nearest phase, phase shift;
    
- **Nominal** — только если есть similarity / canonicalization layer или selection policy над `Profile`.
    

> [!note]  
> Selection / Retrieval по оси — это не graph navigation в общем смысле.  
> Это выбор или поиск в пространстве значений конкретного свойства.

---

### 3. Normalization role

Ось может переводить raw-значение в форму “относительно нормы домена”.

Нормализация нужна, потому что одно и то же значение может иметь разный смысл для разных типов объектов, популяций и контекстов.

Пример:

- `112 km/h` для машины — возможно нормально;
    
- `112 km/h` для человека — невозможно или аномально;

Нормализация может вернуть qualitative class:

```python
High
```

или epistemic `Profile` mutually exclusive + exhaustive classes:

```python
Profile {
  strengths = {Low: 0.05, Mid: 0.20, High: 0.75}
}
```

Нормализация может использоваться перед filtering:

```python
LatencyLevel >= Medium
```

или перед selection:

```python
filter RiskLevel >= Medium, then rank by normalized RiskScore
```

Но сама нормализация не выбирает объект.  
Она меняет форму интерпретации значения.

> [!note]  
> Нормализация не обязана материализовывать derived fact.  
> Она может вернуть результат лениво, а решение о записи в граф регулируется Materialization Policy.

---

### 4. Consistency checks / sanity checks

Оси помогают проверять, не является ли новое значение химерой, ошибкой источника или артефактом наблюдения.

Пример:

- скорость слишком велика для данного типа объекта;

Sanity checks используют:

- нормы prototype/type;
    
- `Support`;
    
- распределения популяции;
    
- совместимость свойств;
    
- историю наблюдений instance-level.
    

---

### 5. Counterfactual / what-if reasoning

Ось позволяет мысленно изменить одно свойство и проверить, что изменится.

Примеры:

- что будет, если увеличить `Mass`;
    
- что будет, если снизить `Latency`;
    
- что будет, если `UserIntent` изменится с `RefundIntent` на `CancellationOnly`;
    
- что будет, если объект окажется `Fragile`.
    

Контрфактуальность требует, чтобы свойства были отделены друг от друга достаточно чётко.

Если ось не представляет реальное различие, а только случайный ярлык, what-if reasoning по ней будет давать ложные выводы.
Plane как быстрый слой практического reasoning до запуска более дорогого анализа.

---

### 6. Learning hooks

Оси Атрибуции дают стабильные точки привязки для новых наблюдений: значение свойства можно записать, сравнить с прошлым состоянием, использовать для нормализации или передать в общий механизм belief update.

Детали обновления `Strength`, `Support`, instance-level исключений и prototype-level статистики описаны в [[Uncertainty and Belief Tracking in the World Model]].

---


## Numeric ↔ Qualitative via Criterion
#topic_details 

Качественные классы вроде `Fast`, `Slow`, `HighRisk`, `LowTrust` часто основаны на числовых или структурных данных, но в графе остаются отдельными `ClassConcept`.

Важно разделять:

- **raw value** — точное или исходное значение свойства;
- **qualitative class** — удобная для мышления категория;
- **Criterion классификации** — правило, которое связывает одно с другим.
Пример:

```text
HAS_NUMERIC_VALUE(E_now, SpeedOfMotion, 112 km/h)
CLASSIFIED_AS(E_now, Fast)
```

Число `112 km/h` хранится как точное значение свойства `SpeedOfMotion`.

Класс `Fast` хранится как качественная интерпретация этого значения.

Условия, при которых значение считается `Fast`, задаёт [[#^def-Criterion|Criterion]] классификации.

Epistemic representation качественных classes определяется контрактом nominal / ordinal scale из [[#Scale types]], а не способом их получения из numeric value.

### Пересмотр качественной интерпретации

Смысл классификации задаётся её canonical target, а не текущим mapper-ом или текстом метки. Использованные правило, данные нормы и существенный контекст сохраняются через [[Memory#^def-ResultProvenance|общий provenance]]. Нужно различать:

- изменение определения класса — [[Uncertainty and Belief Tracking in the World Model#Semantic target revision|semantic revision]], с новым target при изменении смысла вопроса;
- изменение нормы как входа прежнего правила, например «выше текущего q80 этой популяции», — изменение условий, к которым относится результат;
- обучение mapper-а при прежнем смысле класса — изменение способа оценки того же вопроса.

Зависимое evidence пересматривается по [[Uncertainty and Belief Tracking in the World Model#Evidence reassessment and belief recomputation|общим правилам reassessment]]. Новая норма или модель не переопределяет исторический результат; изменение реального состояния объекта следует обычному [[Core data structures#Завершение временного состояния|lifecycle Facet]].

---

### Materialization rule

Качественный класс можно:

1. **вычислять лениво** при запросе;
2. **материализовать** как `CLASSIFIED_AS`, если это даёт пользу.
    

Материализация разрешена, если класс:

- часто используется в фильтрации или правилах;
- ускоряет reasoning;
- улучшает перенос опыта;
- повышает объяснимость;
- снижает стоимость повторного вычисления.

Материализация запрещена, если класс является дешёвым алиасом без новой операционной пользы.


---

## Axis Validity Criteria
#topic_details 

Ось Атрибуции — это гипотеза о том, что отдельное свойство заслуживает собственного представления.

Ось считается валидной, если она окупается в предсказании, выборе действий, обучении или снижении вычислительной стоимости.

---

### I. Три критерия валидной оси

#### 1. Discrimination

Ось должна различать объекты или состояния.

Если все релевантные объекты имеют одинаковое значение по этой оси, ось не добавляет информации.

```text
Нет различия → нет оси.
```

Примеры валидного различения:

- объекты выглядят одинаково, но имеют разную массу;
- пользователи пишут похожие сообщения, но имеют разный intent;
- задачи кажутся похожими, но различаются по risk level.

---

#### 2. Semantic Stability / Non-Artifactuality

Ось должна фиксировать устойчивое различие, а не случайный артефакт наблюдения.

Свойство должно сохранять смысл при изменении несущественных условий наблюдения.

Пример:

- `Color` валиден, если объект остаётся красным при разных условиях освещения.
    
- `BrightnessInCurrentPhoto` может быть полезным измерением изображения, но не должно подменять собой устойчивый `Color`.
    

Граница:

```text
Semantic Stability означает не абсолютную неизменность,
а устойчивость смысла при допустимых изменениях контекста.
```

---

#### 3. Operational / Interventional Relevance

Ось должна быть связана с проверяемыми последствиями.

В идеальном случае агент может совершить интервенцию и увидеть, как значение по оси влияет на поведение объекта.

Пример:

- агент толкает предмет;
- лёгкий объект сдвигается;
- тяжёлый объект почти не двигается;
- возникает ось `Mass`.
    

Если прямое вмешательство невозможно, ось может быть валидна через устойчивую предсказательную проверку.


---

### II. Анти-паттерны

#### 1. Спутанность

Ось фиксирует мусорную корреляцию без устойчивой причинной или предсказательной связи.

Пример:

```text
Пираты ↔ глобальное потепление
```


---

#### 2. Тавтология

Ось дублирует уже существующую ось без новой операции.

Пример:

```text
LengthMeters
LengthFeet
```




---

#### 3. Химеричность

Ось зависит от сиюминутного состояния наблюдателя, а не от объекта или устойчивого отношения между объектом и контекстом.

Пример плохой оси:

```text
FeelsImportantToMeRightNow
```

Она может быть состоянием агента, но не должна подменять свойство объекта.

---

#### 4. Чистый алиас

Ось не добавляет новой структуры, а только переименовывает уже доступный факт.

Пример:

```text
ON_SURFACE(MyCar, Road#17)
```

Не нужно материализовать отдельный derived fact или Facet для `SurfaceUnder`, если значение всегда дешево получается стандартной навигацией и не даёт новой операционной пользы.

---

### III. Практический тест принятия оси

Новая ось принимается, если выполняется хотя бы одно:

1. она улучшает прогнозы по заранее выбранным [[Process Plane/Program Evaluation and Testing#Evaluation  (количественные)|метрикам качества]];
2. она улучшает выбор действия;
3. она ускоряет фильтрацию или поиск;
4. она улучшает перенос опыта между похожими случаями;
5. она снижает стоимость вычисления;
6. она делает reasoning объяснимее без потери точности.

Если ни одно условие не выполняется, ось должна быть отклонена или деградирована.

---

## Genesis of New Attribution Axes
#topic_details 

AGI создаёт новую ось Атрибуции, когда существующих свойств недостаточно для предсказания, выбора, объяснения или сжатия опыта.

По умолчанию осей должно быть минимально необходимое число.

```text
Больше осей ≠ лучше модель.
Хорошая ось уменьшает неопределённость или стоимость мышления.
Плохая ось увеличивает шум и переобучение.
```

---

### 1. Prediction Gain / Surprise Reduction

> [!IMPORTANT] Правило: Возникновение новой оси
> **Концепт:** Новая ось возникает, когда объекты выглядят одинаково по существующим свойствам, но ведут себя по-разному.
> 
> **Действие:** Если объекты неразличимы в текущем пространстве свойств, но дают разные последствия — создай кандидата на новую ось.

> [!EXAMPLE] Пример: Взаимодействие с физическим миром
> AGI видит два визуально идентичных чёрных ящика:
> - первый легко сдвигается;
> - второй почти не двигается.
> 
> По текущим свойствам они одинаковые, но реакция на действие разная. 
> 
> **Возникает новая ось:** `Mass`
> 
> > [!SUCCESS] Валидация оси
> > После введения оси `Mass` поведение становится предсказуемым согласно закону:
> > $$F = m \cdot a$$
> > Ось `Mass` **повышает точность прогноза поведения** и поэтому признается системой как валидная.

---

### 2. Decision Utility

Новая ось возникает, когда отдельное свойство улучшает выбор, ранжирование или фильтрацию объектов.

> [!TIP] Правило: Выделение скрытой оси
> Если для достижения цели нужно стабильно выбирать между объектами, и существующие свойства **плохо объясняют успешность выбора** — создай ось, которая кодирует **релевантное различие**.

> [!EXAMPLE] Пример: Оценка источников
> AGI должен выбрать, какому источнику верить при наличии противоречий.
> 
> **Входящие данные:**
> - пост с форума;
> - статья из PubMed;
> - внутренний лог системы;
> - сообщение пользователя.
> 
> **Возникает новая ось:** `Credibility` (Достоверность)
> 
> Теперь источники можно сравнивать по этой оси как объекты:
> ```text
> Credibility(RedditPost) = low
> Credibility(PubMedArticle) = high
> Credibility(SystemLog) = very_high
> ```
> 

---
### 3. Compression Gain (Выигрыш от сжатия)


> [!TIP] 
> **Концепт:** Новая ось возникает, когда множество наблюдаемых признаков устойчиво меняются вместе и могут быть заменены одной более компактной переменной.
> 
> **Правило:** Если несколько сенсоров или признаков синхронно меняются как следствие одной скрытой причины — создай ось-кандидат для этой скрытой переменной.

> [!EXAMPLE] Пример: Вращающаяся монета
> AGI видит вращающуюся монету. Одновременно меняются:
> - форма эллипса;
> - блики;
> - видимый контур;
> - соотношение сторон;
> - тени.
> 
> Хранить все пиксельные изменения как независимые свойства неэффективно.
> 
> **Возникает ось:** `RotationAngle`
> Одна координата по этой оси объясняет множество наблюдаемых изменений.

---

###  4. Normalization Gain (Выигрыш от нормализации))

> [!TIP] 
> **Концепт:** Новая ось или Criterion может появиться, когда сырые значения (`raw values`) сами по себе плохо сопоставимы между доменами.

> [!EXAMPLE] Пример: Оценка задержки
> Имеется параметр: `Latency = 300 ms`
> Для одного сервиса это нормально, для другого — критично.
> 
> В таком случае полезна нормализованная ось (или derived qualitative class).
> **Возникает ось:** `LatencyLevel = High`
> 


---

###  5. Деградация оси (Когда удалять)

Ось пересматривается, если нарушает [[#Axis Validity Criteria|критерии валидности]] или её польза по [[#III. Практический тест принятия оси|критериям принятия]] больше не оправдывает затраты. По результатам пересмотра её сохраняют, объединяют, понижают или удаляют.

Редкое использование само по себе не означает бесполезности: ось может быть важна для редких дорогих ошибок. Недостаток данных о пользе также не доказывает её отсутствия. Прекращение активного использования не требует физического удаления определения: изменения сохраняют необходимые зависимости по [[Memory#Обязательства сохранности|общим обязательствам памяти]].


---
## Numeric Attribute Representation
#topic_details 
Этот раздел описывает, как числовые атрибуты представлены в EverTree: от текущего `value_U` на numeric-шкале до доменных распределений и qualitative-интерпретаций вроде `Low / Mid / High`.
### Numeric Facets: Scalar Metrics & Distributions
#topic_details 


Этот раздел описывает формы хранения скалярных измерений и статистики нормы по популяции или типу. Они используются при необходимости, с [[Core data structures#Объекты и ссылки|общими правилами хранения объектов]].

Назначение:

- хранить текущее числовое значение свойства;
- сохранять неопределённость оценки в её представлении, а эпистемическую уверенность — через [[Uncertainty and Belief Tracking in the World Model#Numeric and distributional values|numeric belief]];
- поддерживать нормализацию относительно типа/популяции;
- позволять переводить число в qualitative labels вроде `Low`, `Mid`, `High`.

---

### ScalarMetric
#topic_details 

(def_id:: entity.ScalarMetric)
> [!definition]
> **ScalarMetric** — абстрактное представление числовой оси или числового свойства.
^def-ScalarMetric

(formal_id:: entity.ScalarMetric.schema)
```python
ScalarMetric: <AbstractConcept> {
  name: <string> "Имя числового свойства или оси измерения: Speed, Temperature, RiskScore, Latency."
}
```
^spec-ScalarMetric

Минимальный смысл:

```text
ScalarMetric = числовое PropertyConcept, значения которого лежат на Numeric scale.
```

Примеры:

```text
SpeedOfMotion
Mass
Temperature
Latency
RiskScore
CredibilityScore
```

---

### FacetScalarMetric
#topic_details 


(def_id:: entity.FacetScalarMetric)
> [!definition] **FacetScalarMetric** хранит конкретное числовое значение объекта по конкретной оси в конкретном состоянии/окне.
> 
^def-FacetScalarMetric

(formal_id:: entity.FacetScalarMetric.schema)
```python
FacetScalarMetric: <Facet> {
  axis: <Axis> "Ссылка на числовую ось/свойство."
  value: <float> "Текущее числовое значение."
  unit?: <Unit> "Единица измерения, если применимо."
  t?: <time> "Момент или окно, к которому относится измерение."
  confidence?: <float> "Техническая оценка точности измерения, если нужна отдельно от Belief_data."
  precision?: <float> "Ожидаемая погрешность измерения, если известна."
}
```
^spec-FacetScalarMetric

Канонический графовый факт для такого значения:

```text
HAS_NUMERIC_VALUE(entity, property, value[, unit])
```

`FacetScalarMetric` — необязательная реализационная форма хранения того же скалярного значения, а `HAS_NUMERIC_VALUE` — смысловая форма факта. Они не требуют двух независимо изменяемых копий значения или отдельного Facet для каждого измерения.

---

### Instance-level numeric state
#topic_details 

Если числовая ось динамическая и важна локальная история конкретного объекта, Instance может хранить компактное состояние по этой оси.

Допустимые формы:

1. **RecentSamples**
    
    Ring buffer последних `N` значений.
    
    Используется, если важна краткосрочная динамика.
    
2. **InstanceSketch**
    
    Компактный sketch распределения значений конкретного instance.
    
    Используется, если значение часто измеряется и важна локальная норма объекта.
    

Принцип:

```text
Facet хранит рабочее значение "прямо сейчас".
Instance хранит устойчивую локальную статистику объекта.
История остаётся в памяти/эпизодах с детализацией по общему lifecycle памяти.
```

---

### MetricDistribution на уровне Prototype / Type
#topic_details 

(def_id:: entity.MetricDistribution)
> [!definition] Каждый Prototype или Type может хранить статистику популяции по числовым метрикам через **MetricDistribution**. 
^def-MetricDistribution

(formal_id:: entity.MetricDistribution.schema)
```python
MetricDistribution: <InternalNode> {
  axis: <Axis> "Ссылка на числовую ось/свойство."
  domain: <Concept> "Тип, prototype, population или другой домен, для которого распределение задаёт норму."
  sketch: <Sketch> "t-digest, DDSketch или другой компактный sketch распределения."
  drift_policy: <enum> "ema_decay | sliding_window | fixed_window"
  updated_at?: <time> "Когда распределение последний раз обновлялось."
  belief_data: <Belief_data> "Убеждение в том, что это распределение корректно описывает норму данного домена."
}
```
^spec-MetricDistribution

Назначение:

- хранить норму типа;
- вычислять квантили;
- сравнивать объект с популяцией;
- переводить raw value в qualitative class;
- отслеживать drift нормы.

Пример:

```text
MetricDistribution(Vehicle, SpeedOfMotion)
MetricDistribution(Query, Latency)
MetricDistribution(UserMessage, AngerScore)
```

---

### QualitativeMapper внутри MetricDistribution
#topic_details 

Маппинг "число → qualitative label" не должен быть глобальным.

Классы вроде `Low`, `Mid`, `High`, `Fast`, `Slow`, `Expensive` обычно относительны типу, популяции и контексту.

(def_id:: entity.QualitativeMapper)
> [!definition] **QualitativeMapper** — модель перевода числового значения в качественную интерпретацию по Criterion. Для нормы популяции mapper может использовать MetricDistribution и храниться вместе с ним.
> 
^def-QualitativeMapper

(formal_id:: entity.QualitativeMapper.schema)
```python
QualitativeMapper: <InternalNode> {
  mode: <enum> "quantile_bins | peak_modes | learned_monotonic"
  labels: <ClassConcept[]> "Качественные метки: Low, Mid, High или другие."
  boundaries?: <float[]> "Границы интервалов, если используется жёсткий binning."
  membership_functions?: <Callable[]> "Soft-membership функции, если границы плавные."
  hysteresis?: <float> "Защита от частого переключения меток из-за шума."
}
```
^spec-QualitativeMapper

### Quantile bins


Дефолтный режим.

Используется, когда нужна простая и стабильная нормализация относительно распределения типа.

Пример:

```text
Low  = below q33
Mid  = q33..q66
High = above q66
```

или более консервативно:

```text
Low  = below q20
Mid  = q20..q80
High = above q80
```

Стабилизация:

- границы обновляются не на каждом наблюдении;
    
- требуется достаточный `support`;
    
- используется hysteresis, чтобы метки не "флипались" от шума.

Изменение границ обрабатывается по [[#Пересмотр качественной интерпретации|общим правилам пересмотра интерпретации]]; само по себе обновление параметров не создаёт новый target.
    

### Peak modes

Используется, когда распределение реально имеет несколько устойчивых режимов.

Пример:

Скорость движения может иметь режимы:

```text
standing
walking
running
driving
```

Если пики распределения устойчивы, qualitative labels можно привязать к модам.

Если моды нестабильны, fallback:

```text
peak_modes → quantile_bins
```

### Learned monotonic



Используется, когда qualitative class должен соответствовать полезности, риску или supervised signal.

Пример:

```text
RiskScore → LowRisk / MidRisk / HighRisk
```

Маппинг может обучаться так, чтобы `HighRisk` соответствовал не просто верхнему квантилю, а реальному росту вероятности плохого исхода.

Допустимые модели:

- isotonic regression;
    
- monotonic calibration;
    
- monotonic binning;
    
- learned thresholds with constraints.
    

Ограничение:

```text
Если свойство должно быть монотонным, модель не должна нарушать порядок.
```

---

### Point-view, Profile and overlapping membership
#topic_details 

Для mutually exclusive + exhaustive scale qualitative mapper возвращает общий `Profile`. Hard label, например `RiskHigh`, может быть только производным point-view по явной selection policy; собственные `Support` и `PriorSupport` ему не назначаются.

Если membership functions намеренно допускают одновременную принадлежность нескольким classes, это не `CompetitionScope`: каждая classification является отдельным binary target. Membership degree тогда является значением model, а не epistemic `Strength`.

---


### Composite Axes
#topic_intro  #future_versions 

(def_id:: et.CompositeAxis)
> [!definition]
> **Композитная ось** —атрибутивная ось, значение которой вычисляется из нескольких более простых свойств.
^def-CompositeAxis

Композитная ось возникает, когда отдельные свойства менее полезны, чем их совместная проекция. Она не просто дублирует признаки, а выделяет **новое прагматически полезное свойство**, помогающее быстрее сравнивать, выбирать, прогнозировать или объяснять.



---

> [!EXAMPLE] Примеры и их прагматика
> - **Крупность** $= f(\text{Рост}, \text{Вес})$
>   *Назначение:* Быстро понять масштаб объекта и выбрать стратегию взаимодействия, не анализируя рост и вес по отдельности.
> - **Импульс** $= \text{Масса} \times \text{Скорость}$
>   *Назначение:* Прогнозировать силу столкновения и оценивать опасность движущегося объекта.
> - **Опасность** $= f(\text{Размер}, \text{Агрессия}, \text{Дистанция}, \text{Оружие}, \text{Скорость})$
>   *Назначение:* Быстро ранжировать угрозы и запускать safety behavior.
> - **Надёжность источника** $= f(\text{История точности}, \text{Provenance}, \text{Тип})$
>   *Назначение:* Решать конфликты противоречивой информации.

---

### Механизмы синтеза

Ось может быть создана тремя основными путями в зависимости от доступной информации о предметной области:

1. **Явная формула**
   Используется, когда физическая или логическая связь точно известна (например, $Momentum = Mass \times Velocity$).
2. **Линейная комбинация (Score)**
   Используется для эвристических оценок: $RiskScore = w_1x_1 + w_2x_2 + \dots + w_nx_n$.
   *Требует контроля:* нормализации входов, устойчивости весов, проверки на переобучение.
3. **Incremental PCA / Low-rank decomposition**
   Используется для поиска латентных координат и снижения размерности, когда множество признаков меняются совместно, но точной формулы нет.

---

> [!NOTE] Математика: Правило выбора $k$ для IPCA
> Для выбора оптимального количества компонент используется порог накопленной объясненной дисперсии. Пусть $\lambda_i$ — собственные значения (дисперсии) по компонентам IPCA.
> 
> Берём **минимальное** $k$, при котором выполняется условие:
> $$\frac{\sum_{i=1}^{k}\lambda_i}{\sum_{i=1}^{m}\lambda_i} \ge \tau$$
> *Где $m$ — число доступных компонент, а $\tau$ — целевой порог.*
> 
> **Робастные гиперпараметры:**
> 
> | Параметр | Значение | Описание |
> | :--- | :--- | :--- |
> | **$\tau$** | `0.95` | Целевой порог накопленной дисперсии (по умолчанию). |
> | **$k_{max}$** | *Custom* | Верхний предел компонент (ограничение памяти/скорости). |
> | **$N_{min}$** | `200–1000` | Стабилизация: пересчитывать $k$ не чаще, чем раз в $N_{min}$ новых наблюдений. |
> | **$\Delta$** | `0.01–0.02` | Гистерезис: обновлять $k$, только если это улучшает дисперсию минимум на $\Delta$ (1–2%). |

> [!WARNING] Ограничение латентных осей
> **Интерпретируемость не гарантирована.** > Если полученная через PCA латентная ось не получает ясного смысла или полезного критерия (Criterion), она должна оставаться *внутренней технической координатой*, а не превращаться в полноценный онтологический `PropertyConcept`.
