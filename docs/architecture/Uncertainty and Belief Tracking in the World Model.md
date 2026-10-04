---
status: draft
target_version: next
ToDo:
---


## Introduction
#topic_core

EverTree использует belief-модель там, где знание агента может быть неполным или ошибочным: для наблюдений, гипотез, состояний, семантических связей, моделей процессов и других утверждений о мире или самом агенте.

В EverTree [[#^def-BeliefData|`BeliefData`]] не обновляется напрямую: релевантный опыт преобразуется в [[#^def-EvidenceAssignment|`EvidenceAssignment`]], а текущие `Strength`, `Support` и, при наличии конкурирующих альтернатив, [[#^def-Profile|`Profile`]] вычисляются из активного evidence. Сходное evidence может консолидироваться в более компактное представление, если сохраняются его совокупное влияние и гранулярность, необходимая для дальнейшего обучения, `revise/retract`, учёта зависимостей и временной динамики.


---

## Belief model
#topic_core

### Core concepts and semantic boundaries
#topic_core

#### Belief and BeliefTarget
#topic_core

(def_id:: entity.Belief)
> [!definition] **Belief** — текущее эпистемическое отношение агента к канонически определённому semantic target: насколько имеющееся evidence позволяет считать утверждение, значение или один из допустимых ответов верным либо обоснованным. ^def-Belief

(def_id:: entity.BeliefTarget)
> [!definition] **BeliefTarget** — канонически определённая semantic единица, которая обновляется как одно epistemic целое: binary-утверждение, оцениваемое значение / модель либо [[#^def-CompetitionScope|`CompetitionScope`]]. Alternative scope-а не является независимым target с собственным `Support`. ^def-BeliefTarget

#topic_details

Примеры с [[Core data structures#^def-Facet|Facet]] и [[Core data structures#^def-Claim|Claim]] как формами target-а:

```text
HealthStatus(IgorHealth@T1)
→ какое состояние здоровья в данном(T1) Facet инстанса Igor;

PART_WHOLE(Wheel#7, Car#1)
→ является ли Wheel#7 частью Car#1;

"Земля может закончить существование в любой момент" → Claim, если более подходящая semantic structure ещё не определена.
```

#topic_core

[[#^def-BeliefTarget|`BeliefTarget`]] всегда относится к канонически определённому объекту, свойству или утверждению semantic graph EverTree:

```text
property target
→ (semantic_object, PropertyConcept) с условиями, определяющими смысл оцениваемой величины / модели;

independent classification target
→ CLASSIFIED_AS(semantic_object, ClassConcept);

scope-backed property target
→ CompetitionScope вопроса об (semantic_object, PropertyConcept) при заданных смысловых условиях;

relation target
→ RelationType + полностью заданные аргументы;

transition target
→ TransitionType + полностью заданные аргументы;

CompetitionScope
→ semantic question + полный набор его alternatives;

Program target →
(Program, program_revision);

Claim → 
явно сформулированное проверяемое утверждение, для которого пока нет подходящего структурированного представления.

```


[[Core data structures#^def-Note|`Note`]] и [[Core data structures#^def-Prompt|`Prompt`]] также могут быть целыми semantic targets по [[Core data structures#^note-claim-prompt-evaluation|общему контракту оценки]] с заданными `Criterion` и scope. Произвольный Python-объект или техническая структура не может быть `BeliefTarget`.

Существующая semantic структура также определяет, **какие значения допустимы**:

```text
HealthStatus + AttributionAxis
→ Healthy | Sick | Recovering | ...

PART_WHOLE(...)
→ true | false

CompetitionScope
→ его alternatives.

Claim
→ true | false
```

Условия, определяющие смысл вопроса, должны быть однозначно заданы в semantic представлении target. Например, надёжность одного источника в программировании и медицине относится к разным targets. Дополнительные наблюдения или смена estimator-а для того же вопроса сами по себе не меняют target; текущее значение belief также не является частью его identity.

---

#### Generic Belief(U) interface
#topic_core

(def_id:: entity.BeliefU)
> [!definition] **`Belief(U)`** — общий интерфейс belief относительно значения из пространства `U`:
> `value_U` — само утверждаемое или оцениваемое значение.  Оно может быть классом, состоянием, числом, интервалом, параметрами модели, профилем outcomes или другой типизированной структурой, необходимой соответствующей Program.
> [[#^def-BeliefData|`BeliefData`]] — насколько агент эпистемически уверен в этом значении. ^def-BeliefU

(formal_id:: entity.BeliefU.schema)
```text
Belief(U) := <value_U, BeliefData>
```
^spec-BeliefU

`U` может представлять класс, состояние, гипотезу, relation, число, параметр, распределение или другую типизированную величину.

#topic_details

Например:

```text
value_U = transition_probability = 0.7
```

#topic_core

Любая величина, описывающая сам мир или процесс, относится к `value_U` или параметрам модели, а не к `BeliefData`.

---

#### BeliefData
#topic_core

(def_id:: entity.BeliefData)
> [!definition] **BeliefData** — стандартное вычисляемое read-представление эпистемического состояния belief:
> `BeliefData` не изменяется напрямую.
> - `Strength ∈ [0,1]` — насколько агент сейчас верит в соответствующее `value_U`;
> - `Support ≥ 0` — суммарная effective discriminative mass собственного active evidence данного target;
> - `PriorSupport ≥ 0` — effective discriminative mass трассируемого upstream evidence, которое обосновывает текущий prior данного target. `PriorSupport` может быть ненулевым до появления собственного опыта агента, если prior подкреплён трассируемым внешним или upstream evidence. Неподкреплённое parametric knowledge LLM `PriorSupport` не создаёт. ^def-BeliefData

(formal_id:: entity.BeliefData.schema)
```text
BeliefData = <Strength, Support, PriorSupport>
```
^spec-BeliefData

#topic_details

`Support` учитывает только собственное evidence target. Prior в него не входит.

`PriorSupport` нужен, чтобы различать beliefs с одинаковыми `Strength` и `Support`, но разным основанием prior:

```text
Strength = 0.9
Support = 0
PriorSupport = 0
→ сильный prior без трассируемого evidence;

Strength = 0.9
Support = 0
PriorSupport = high
→ собственного evidence target ещё нет,
  но prior подкреплён переносимым upstream evidence.
```

Это особенно важно при переносе знания между уровнями [[Core data structures#^def-Prototype|Prototype]], [[Core data structures#^def-Instance|Instance]] и [[Core data structures#^def-Facet|Facet]]:

```text
Prototype
→ prior для Instance
→ prior для Facet
```

`PriorSupport` не является копией `Support` source belief. При переносе учитываются применимость к текущему target, зависимости между evidence и запрет повторного учёта одного underlying evidence через `Support` и `PriorSupport`.

Поэтому `Support` и `PriorSupport` нельзя автоматически складывать в общую меру уверенности.

`Support` также не равен количеству observations. Релевантная проверка может не различать альтернативы и иметь `evidence_mass = 0`; количество и структура проведённых проверок учитываются отдельно через [[#^def-EvidenceStats|`EvidenceStats`]].

Точные правила вычисления `Strength`, `Support`, `PriorSupport` и [[#^def-Profile|`Profile`]], включая prior resolution и перенос upstream evidence, задаются в [[#Belief updating]].


---
#### EvidenceStats
#topic_core

(def_id:: entity.EvidenceStats)
> [!definition] **EvidenceStats** — вычисляемый view, описывающий объём и структуру **собственного active evidence** target-а. Он не входит в `BeliefData` и не является semantic object. ^def-EvidenceStats

```python
EvidenceStats {
  evidence_count: int
    "Число logical evidence units после устранения повторов
     и учёта зависимостей, включая неразличающие проверки."

  max_component_mass: float
    "Максимальная effective evidence mass одного logical unit."

  max_component_effect: float
    "Максимальный effective эффект одного logical unit
     на состояние updater-а."
}
```

#topic_details

различаются состояния:

```text
Support = 0
evidence_count = 0
→ target ещё не исследовался;

Support = 0
evidence_count > 0
→ проводились релевантные проверки,
  но они не дали discriminative evidence.
```

Consolidation не изменяет `EvidenceStats`: статистика относится
к представленным logical evidence units, а не к количеству физических
[[#^def-EvidenceAssignment|`EvidenceAssignment`]].

[[#^def-EvidenceStats|`EvidenceStats`]] не описывает evidence, лежащее за `PriorSupport`.
При необходимости его структура восстанавливается через provenance prior;
отдельный `PriorEvidenceStats` в MVP не вводится.
---
#### Epistemic uncertainty vs model variability

#topic_core

EverTree различает:

```text
model uncertainty / variability
→ что сама модель утверждает о возможных состояниях мира;

epistemic uncertainty
→ насколько агент уверен, что эта модель или оценка корректна.
```

#topic_details

Например:

```text
value_U:
OutcomeProfile {
    Success = 0.5
    Failure = 0.5
}

BeliefData:
Strength = 0.95
Support = high
```

означает, что агент достаточно уверен: процесс действительно имеет примерно равновероятные outcomes.

#topic_core

Поэтому высокая вариативность процесса не означает низкую epistemic уверенность, а почти детерминированный прогноз не означает, что агент хорошо в нём уверен. Эпистемическая уверенность читается через [[#^def-BeliefData|`BeliefData`]].

Аналогично, неопределённость между `Low | Medium | High` у categorical / ordinal Property является epistemic uncertainty и представляется [[#^def-Profile|`Profile`]]. Она не превращает эти значения в `OutcomeProfile`: `OutcomeProfile` описывает вариативность самого моделируемого процесса, а не незнание агента о том, какая alternative истинна.

Это различие применяется ко всем последующим формам beliefs и updater-ов.


### Belief representations
#topic_core

Для отдельного утверждения или оцениваемого `value_U` используется общий интерфейс [[#^def-BeliefU|`Belief(U)`]]: `value_U` + [[#^def-BeliefData|`BeliefData`]]. Для одного вопроса с mutually exclusive + exhaustive alternatives общим epistemic read-представлением является [[#^def-Profile|`Profile`]]: он заменяет набор независимых `Belief(U)`, а не становится новым видом `value_U`.

---

#### Binary belief
#topic_core

Используется для утверждения, которое может быть истинным или ложным и не требует явного представления альтернативы `¬H`.

#topic_details

Например:

```text
value_U = "Sensor#7 calibrated"

BeliefData:
  Strength = 0.91
  Support = ...
```

#topic_core

`Strength` выражает текущую эпистемическую уверенность агента в этом утверждении.

Внутреннее состояние updater-а может использовать подходящие sufficient statistics; наружу belief читается через [[#^def-BeliefData|`BeliefData`]].

---

#### CompetitionScope and mutually exclusive alternatives

#topic_core

(def_id:: entity.CompetitionScope)
> [!definition] **CompetitionScope** — semantic scope одного вопроса с mutually exclusive и exhaustive alternatives: в каждом допустимом состоянии истинна ровно одна alternative. ^def-CompetitionScope

`CompetitionScope` определяется вопросом и alternatives, а не их semantic типом. Он одинаково применяется к конкурирующим hypotheses и к categorical / ordinal значениям Property, если scale и [[Attribution Plane#^def-Criterion|`Criterion`]] задают такой набор.

#topic_details

```text
Где находится единственная награда?

CompetitionScope:
  BehindDoorA
  BehindDoorB
  BehindDoorC
```

Тот же scope используется для дискретного Property:

```text
Каков SQLProblemSolvingLevel(AgentA)?

CompetitionScope:
  Low
  Medium
  High
```

`Low`, `Medium` и `High` являются alternatives одного target, а не тремя независимыми beliefs.

Если несколько утверждений или classifications могут быть истинны одновременно, они не образуют `CompetitionScope` и представлены отдельными binary beliefs.

```text
Rain contributed to WetRoad
StreetWasher contributed to WetRoad

GoodAtSQL(AgentA)
GoodAtPython(AgentA)
GoodAtDebugging(AgentA)
```

Такие statements могут одновременно иметь высокий `Strength`.

Набор alternatives должен покрывать все допустимые ответы. Если именованные варианты этого не делают, добавляется обычная semantic alternative для оставшегося случая.

```text
Какой источник вызвал событие?

CompetitionScope:
  SourceA
  SourceB
  OtherSource
```

```text
Что вызвало alarm?

CompetitionScope:
  Fire
  Intrusion
  NoTrigger
```

`OtherSource` покрывает иной источник, а `NoTrigger` — отсутствие trigger. Это обычные alternatives конкретного scope.

`CompetitionScope` содержит только возможные состояния мира; отсутствие знания о том, какая alternative истинна, выражается epistemic state, а не отдельной alternative.

Если observation показывает, что две alternatives могут быть истинны одновременно или существует допустимое состояние, не покрытое scope, значит неверна сама структура `CompetitionScope`:

```text
scope invariant violation
→ structural revision
```

Набор alternatives является частью semantic identity `CompetitionScope`. Его изменение создаёт новую версию scope; старое evidence при необходимости переоценивается, а простая перенормировка запрещена.

Если совместимые утверждения требуют совместного распределения или взаимодействий, используется model-specific joint model. Универсальная joint model для MVP не требуется.



---

##### CompetitionScope Profile
#topic_core

(def_id:: entity.Profile)
> [!definition] **Profile** — общее вычисляемое представление epistemic belief между alternatives одного `CompetitionScope`, независимо от того, являются alternatives hypotheses или значениями Property. ^def-Profile

```python
Profile {
  strengths: <dict[alternative, float]>
  support: <float>
  prior_support: <float>
}
```

Для каждой alternative `a`:

```text
Strength(a)
→ текущая epistemic probability alternative.
```

$$  
\sum_k Strength(a_k)=1
$$

`Support` относится ко всему `CompetitionScope`:

```text
Support
→ суммарная effective discriminative evidence mass;

PriorSupport
→ backing prior distribution, если он получен из других beliefs.
```

Отдельные `Support(a)` и `PriorSupport(a)` не используются: evidence и prior оценивают вопрос / scope целиком.

При отсутствии собственного evidence:

$$  
Strength(a_k)=p_{0,k}, \qquad Support=0
$$

`Profile` вычисляется при чтении и отдельно не хранится.
Неизменяемый [[Memory#^def-OperatorOutput|`OperatorOutput`]] может зафиксировать исторический read-snapshot `Profile` для provenance; он не обновляется и не является источником текущего `Profile`.

Scope-backed Property использует тот же `Profile` и `CompetitionScopeUpdater`, что и competing hypotheses.


---

#### Probabilistic process outcomes
#topic_core

Некоторые процессы могут иметь несколько возможных outcomes даже при корректной и полной модели процесса.

#topic_details

Например:

```text
CardDeal
→ множество возможных карт;

unfair coin
→ Heads 0.7
→ Tails 0.3
```

#topic_core

В этом случае вероятности относятся к самому моделируемому процессу и являются частью `value_U`, а не `Strength`.

Для дискретных outcomes используется:

```python
OutcomeProfile {
  Heads: 0.7
  Tails: 0.3
}
```

Эпистемическая уверенность агента в корректности этого распределения выражается отдельно через [[#^def-BeliefData|`BeliefData`]]:

```text
Belief(
  value_U = OutcomeProfile(...),
  BeliefData = ...
)
```

Для непрерывных случайных outcomes используется соответствующее `OutcomeDistribution`.

#topic_details

Сам `OutcomeProfile` может обучаться собственным estimator-ом, например через counts / Beta / Dirichlet statistics. Это обновляет `value_U`, а не epistemic `Strength`.

---

#### Numeric and distributional values
#topic_core

Числовое `value_U` может быть представлено в форме, необходимой конкретной модели:

```text
single value;
interval;
параметры модели;
empirical или parametric distribution;
другая типизированная numeric structure.
```

#topic_details

Например:

```text
value_U = 12.4 kg
```

или:

```text
value_U = Interval(12.1, 12.7) kg
```

Model-specific uncertainty самого `value_U` хранится в representation или sufficient state соответствующего estimator-а.

Например:

```text
Beta / Dirichlet concentration;
Gaussian variance / precision / covariance;
posterior interval;
sample count
```

не являются generic `BeliefData.Support`.

#topic_core

[[#^def-BeliefData|`BeliefData`]] для numeric или distributional `value_U` относится к явно определённому [[#^def-BeliefTarget|semantic target]]: утверждению о корректности конкретной оценки или модели в заданных условиях. Утверждение о конкретном измерении и утверждение о качестве модели — разные targets. Если смысл уже представлен свойством или моделью, используется существующий target; отдельный [[Core data structures#^def-Claim|`Claim`]] нужен только при отсутствии подходящего представления.

[[Attribution Plane#^def-Criterion|`Criterion`]] задаёт правило и условия проверки в контракте target или проверяющей Program. Metric / loss используется, если её требует смысл проверки; отдельная численная метрика не обязательна для binary-предиката. Утверждение о пригодности модели требует определённого условия приемлемости в заявленной области применения.

#topic_details

Empirical distributions основываются на сохранённых observations; summaries вроде mean, variance и quantiles вычисляются по запросу. При слишком большом объёме [[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] или специализированная model Program может создать компактное representation с явно допустимой потерей детализации.

Для параметрической модели её параметры являются частью `value_U`, а их model-specific uncertainty — состоянием estimator-а.

Выбор representation определяется потребностями reasoning, prediction и control. Более сложное представление используется только если более простое теряет практически важную информацию.

### Belief updating
#topic_core

```
prior
+ active EvidenceAssignment[]
        ↓
target-specific updater
        ↓
internal sufficient state
        ↓
BeliefData / Profile
```


> Если обновляется само сложное `value_U`, например параметры числовой модели или `OutcomeDistribution`, model-specific estimator из [[Learning system#^def-LearningSystem|Learning System]] обновляет `value_U`, а belief updater отдельно оценивает уверенность в полученной модели.



---


#### Prior resolution and PriorSupport

#topic_core

Prior может быть задан непосредственно либо получен переносом более общего или связанного belief между [[Core data structures#^def-Prototype|Prototype]], [[Core data structures#^def-Instance|Instance]] и [[Core data structures#^def-Facet|Facet]]:

```text
Prototype
→ prior для Instance;

Instance
→ prior для Facet.
```

`resolve_prior(target)` определяет состояние target до его собственного active evidence; для competing alternatives исходное распределение задаётся [[#^def-Profile|`Profile`]]:

```text
prior
→ исходный Strength / Profile;

PriorSupport
→ effective discriminative mass трассируемого upstream evidence,
  обосновывающего этот prior.
```

#topic_details

При создании нового target `resolve_prior` переиспользует применимую prior model или сохранённый результат для того же target и состояния входов. LLM и retrieval / web search могут использоваться при подготовке или пересмотре модели через [[Process Plane/Program Lifecycle and Evolution#Общий lifecycle Program|Program Lifecycle]]; новый target сам по себе не требует нового LLM-вызова. Найденные основания оцениваются по надёжности, применимости и зависимостям и разделяются по их отношению к target:

```text
direct evidence текущего target
→ EvidenceAssignment(target)
→ Support;

evidence другого, более общего или связанного belief
→ перенос в prior
→ PriorSupport.
```

#topic_core

Одно underlying evidence не может одновременно учитываться через `Support` и `PriorSupport`.


#topic_details

Общий pipeline:

```text
upstream beliefs / models
+ при необходимости LLM / web research
        ↓
assessment + dependency filtering
        ↓
┌──────────────────────────────┐
│ direct evidence              │
│ → EvidenceAssignment[]       │
│                              │
│ upstream evidence            │
│ → prior + PriorSupport       │
└──────────────────────────────┘
        ↓
target-specific updater
        ↓
initial Strength / Profile + Support
```

#topic_core

Если достаточного трассируемого основания нет, используется подготовленный bounded base prior от LLM или явно заданный программой fallback. Точная калибровка не является условием начала работы:

```text
base prior
→ PriorSupport = 0.
```

При переносе `PriorSupport` не копируется из `Support` source belief. Учитывается только та effective evidence mass, которая остаётся применимой к target после учёта зависимостей и overlap с его собственным evidence.

Основные инварианты:

```text
prior не увеличивает собственный Support target;

Prototype → Instance → Facet
сам по себе не создаёт нового evidence, только через проверку resolve_prior ;

PriorSupport создаётся только трассируемым upstream evidence;

одно underlying evidence не учитывается повторно
через Support и PriorSupport;

PriorSupport выражается в той же Support-scale,
что и Support updater-а текущего target.
```

`resolve_prior` не назначает итоговый `Strength`: он определяет prior и его backing. `Strength / Profile` вычисляется target-specific updater-ом после учёта собственного active evidence.  
:::


##### LLM prior proposal

#topic_details

LLM prior proposal используется для подготовки или пересмотра prior model, когда готовой применимой оценки недостаточно. Один вызов может оценить несколько targets; повторные чтения prior и новые evidence не требуют повторной elicitation — запроса оценки у LLM. Retrieval / web search выполняются в пределах бюджета подготовки; сам факт поиска `PriorSupport` не создаёт.

Для binary target LLM возвращает числовую `P(target is true)`, для `CompetitionScope` — один нормированный [[#^def-Profile|`Profile`]] по всем alternatives. Это вероятность истинности target; качество метода оценки отражается отдельно через backing и [[#Calibration|calibration]].

Числовой выход выбран для непосредственного использования updater-ом. Словесные категории вероятности допустимы как альтернативный протокол с заранее заданными значениями и преобразованием в числа. Категории `low / medium / high` для applicability и reliability в ответе описывают основания и не заменяют `P(target)`. Ни формат ответа, ни инструкция «будь откалиброван» сами по себе не обеспечивают calibration.

Вероятностные оценки LLM чувствительны к формулировке, framing и порядку elicitation. Поэтому используются стабильные versioned prompt, модель, настройки генерации и преобразование выхода. Их изменение учитывается как изменение prediction mechanism при дальнейшем calibration.

`target`, [[Attribution Plane#^def-Criterion|`Criterion`]], context, horizon, `known_at`, допустимый background и ссылки на исключённое direct evidence передаются структурированно. Основания разделяются до оценки prior: собственное evidence target обрабатывается updater-ом отдельно.

Базовый prompt(черновик который нужно будет адаптировать):

> Estimate `P(target is true)` given the Criterion, context, horizon, `known_at`, and allowed prior background. For a CompetitionScope, return one normalized probability vector over all supplied alternatives.
>
> Start from an applicable base rate if available; identify its reference class and source. If none is available, say so. Consider material background both for and against the target. Discount weak, inapplicable, stale, unreliable, or dependent background. Exclude direct evidence that the updater will account for separately.
>
> Return your raw probability estimate before programmatic limits, the source references that materially informed it, and a short summary of assumptions and missing information. Use only information available by `known_at`. Do not invent sources or base rates. If traceable backing is unavailable, return a rough estimate and explicitly state that limitation.

Если proposal уже учитывает direct evidence, его нельзя использовать как prior вместе с тем же evidence в updater-е: prior пересчитывается по допустимому background. Инструкция с `known_at` не гарантирует отсутствия знания будущего outcome в весах LLM; для исторической evaluation требуется отдельная проверка утечки.

Если доступны релевантные [[#^def-CalibrationStats|`CalibrationStats`]], они могут использоваться как feedback о прошлой over/underconfidence prediction mechanism. Они не увеличивают `PriorSupport`.

LLM возвращает:

```python
LLMPriorProposal {
  raw_prior: probability | Profile;
  basis_summary; // base rate / reference class, если доступны; допущения и пробелы

  material_evidence: [
    {
      source_refs;
      direction: supports | opposes;
      applicability: low | medium | high;
      reliability: low | medium | high;
      dependency_refs?;
      summary;
    }
  ];
}
```

`LLMPriorProposal` не попадает автоматически в `PriorSupport`. `resolve_prior` сначала проверяет его `material_evidence` на применимость, надёжность, зависимости и трассируемость; только прошедшая эту проверку effective evidence mass учитывается в `PriorSupport`.

`material_evidence` содержит только основания, существенно повлиявшие на `raw_prior`. Несколько сообщений, основанных на одном observation, dataset или исследовании, считаются зависимым evidence.

Retrieval увеличивает доступный evidence, но сам по себе не делает prior надёжнее: шумные, нерелевантные или зависимые источники могут, наоборот, создавать ложную уверенность. Поэтому учитывается содержание и provenance material evidence; репутация источника является лишь одним признаком его reliability.

Числовой и категориальный протоколы сравниваются на независимо разрешившихся случаях своего семейства targets по [[Process Plane/Program Evaluation and Testing|правилам evaluation]]: proper scores, calibration и полезность различий между прогнозами. Повторное семплирование и отдельный LLM-судья не входят в обязательный путь оценки.

Основания для выбора протокола:

- [Tao et al. (2025)](https://arxiv.org/html/2505.23854v1): словесная неопределённость лучше в среднем по исследованным моделям, но не для каждой; её оценивал отдельный LLM-судья. Это не доказательство преимущества трёх фиксированных категорий.
- [Subramani et al., ACUTE (2026)](https://arxiv.org/abs/2606.07822): обучаемые оценки по внутренним активациям повышают полезность оценок уверенности при низкой ошибке calibration на исследованных задачах. Метод требует данных и доступа к активациям; одного изменения prompt недостаточно для воспроизведения результата.

Эти работы изучают преимущественно правильность ответов моделей. Перенос результатов на priors произвольных процессов проверяется отдельно.

##### Unsupported LLM prior

#topic_details

Часть prior без трассируемого backing evidence имеет:

```text
PriorSupport = 0
```

и в MVP ограничивается:

```text
binary:
prior ∈ [0.25, 0.75];

CompetitionScope:
max_k prior_k ≤ 0.75.
```

Код сначала ограничивает собственную силу неподкреплённого proposal, затем его совокупное влияние с приблизительными contributions по [[#Ограничение неподтверждённого влияния|общему правилу]]. Для допустимого binary proposal без backing и других вкладов результат равен `clamp(raw_prior, 0.25, 0.75)`. Для scope сохраняются нормировка и положительность компонент [[#^def-Profile|Profile]]. Ограничение не является эмпирической калибровкой.

При наличии material evidence final prior может выйти за этот предел только настолько, насколько более сильная оценка действительно им обоснована. Само наличие источника cap не снимает.

При добавлении приблизительных assessments неподкреплённый prior и их contributions используют [[#Ограничение неподтверждённого влияния|один общий предел влияния на target]]. Ослабление каждого вклада по отдельности не заменяет это ограничение суммы.

##### Evidence-backed prior

#topic_details 

Backing evidence может происходить из:

```text
собственного опыта и upstream beliefs / models;
переноса Prototype → Instance → Facet;
внешних observations, datasets и retrieved sources.
```

Поэтому новая Program может иметь `PriorSupport > 0` ещё до собственного опыта агента.

`resolve_prior` определяет effective backing с учётом:

```text
applicability;
reliability;
dependencies;
temporal applicability.
```

`PriorSupport` не является числом источников, confidence LLM или оценкой репутации источника. Он выражается в support-scale updater-а текущего target.

При переносе upstream belief его `Support / PriorSupport` не копируются: учитывается только применимая часть underlying evidence.


---

#### Evidence contribution and Support

#topic_core

Для epistemic updater-а `contribution` и `evidence_mass` образуют единый математический контракт:

```text
contribution
→ направление и величина воздействия evidence на belief;

evidence_mass ≥ 0
→ discriminative mass этого воздействия.
```

#topic_details

`evidence_mass` не является количеством observations или общей мерой того, насколько вопрос исследован. Поэтому релевантное [[#^def-Evidence|evidence]] может иметь:

```text
contribution = 0
evidence_mass = 0
```

и всё равно учитываться в [[#^def-EvidenceStats|`EvidenceStats`]].

Для atomic evidence `evidence_mass` не задаётся независимо, а детерминированно выводится из `contribution` по правилам конкретного updater-а.

Для `BinaryBeliefUpdater` и `CompetitionScopeUpdater` используются натуральные логарифмы; `evidence_mass` и `Support` для них измеряются в `nats`.

После consolidation `evidence_mass` может превышать net effect assignment, поскольку contributions представленных компонентов могут частично компенсировать друг друга.

При чтении temporal, dependency policies и ограничение неподтверждённого влияния преобразуют:

```text
(contribution, evidence_mass)
        ↓
current adjustment
        ↓
(effective contribution, effective evidence_mass)
```

Adjustment должен сохранять updater-specific invariant между effect и mass: ослабление discriminative evidence не может оставить эффект на `Strength` или [[#^def-Profile|`Profile`]], превышающий соответствующую effective mass.

Для простого scalar attenuation `a ∈ [0,1]`:

```text
Δ̃ = aΔ
m̃ = am
```

Dependency adjustment может учитывать несколько связанных evidence совместно и не обязан сводиться к независимому множителю каждого assignment.

#topic_core

Текущий собственный Support target-а:

```text
Support = Σ effective evidence_mass
```

после необходимой dependency-свёртки.

Prior в `Support` не входит.

#topic_details

Для consolidated evidence adjustment должен использовать retained representation, достаточную для сохранения consolidation invariant. Один общий adjustment к net contribution допустим только тогда, когда он эквивалентен adjustment представленных компонентов.

##### Ограничение неподтверждённого влияния
#topic_core

В MVP все приблизительные оценки, влияющие на один target в данном контексте чтения, используют общий предел. В него входят неподкреплённый prior, contributions непроверенных моделей наблюдений и влияние предположений о неизвестных источниках. Новый обработчик, версия программы или повторный assessment не создают дополнительного предела.

Оценка считается обоснованной в данной области, если используемая модель и существенные предположения поддержаны применимыми внешними основаниями или независимой проверкой. Уверенность LLM, наличие ссылки и число запусков сами по себе этого не доказывают. При частичном обосновании отделяется неподтверждённая часть; если разделение не поддерживается моделью, весь соответствующий вклад считается приблизительным.

Предел применяется после учёта времени и зависимостей, к совокупному влиянию приблизительных оценок. Обоснованное evidence сохраняет свой вклад и может вывести итоговую вероятность за границы неподкреплённого prior. Итоговый posterior целиком не обрезается.

#topic_details

Во внутренних данных расчёта различаются:

- `z_base` — обоснованная часть prior: log-odds для binary target или центрированные log-weights для scope. Если её нет, используется ноль, соответствующий `0.5` или равномерному профилю. Это точка отсчёта ограничения, а не утверждение о реальных базовых частотах.
- `v₀` — неподтверждённое остаточное смещение prior в тех же координатах, ещё не представленное отдельными contributions.
- `W` — приблизительные собственные и переносимые upstream contributions после temporal / dependency adjustment; `W_prior` — переносимая часть этого набора.

Если proposal не позволяет отделить обоснованную часть, всё его смещение считается неподтверждённым; использованные в нём основания не добавляются повторно отдельными contributions. Перед логарифмированием prior должен удовлетворять [[#Target-specific belief updaters|контракту updater-а]]: конечные вероятности строго между `0` и `1`, для scope также нормировка. Недопустимый proposal заменяется объявленным fallback.

Величина смещения определяется как `d(x) = |x|` для binary target и `d(x) = max(x) − min(x)` для центрированного вектора scope. Сначала ограничивается сила самого proposal:

```text
u₀ = v₀                       при d(v₀) ≤ B
u₀ = [B / d(v₀)] × v₀         при d(v₀) > B
```

Это не позволяет крайней самооценке LLM занять почти весь общий предел за счёт большого raw logit. Затем ограничивается сумма предположений:

```text
M = d(u₀) + Σ_{i ∈ W} m_i
a = 1                         при M = 0
a = min(1, B / M)             при M > 0

u₀_eff = a × u₀
Δ_i_eff = a × Δ_i             для i ∈ W
m_i_eff = a × m_i             для i ∈ W
```

Суммарная mass ограничиваемого влияния не превышает `B`. Она считается до взаимной компенсации противоположных contributions, чтобы их сумма не скрывала величину неподтверждённых влияний.

`B` — версионируемая настройка политики расчёта, измеряемая в `nats`. Для MVP значения согласованы с [[#Unsupported LLM prior|пределами начального prior]]:

```text
binary: B = ln(3)
scope с K ≥ 2 alternatives: B = ln(3 × (K − 1))
```

Без обоснованного evidence это даёт binary probability в `[0.25, 0.75]` и `max_k p_k ≤ 0.75`. Для scope также ограничивается отношение вероятностей любых двух alternatives: `p_i / p_j ≤ 3 × (K − 1)`. При большом числе alternatives это не гарантирует большой абсолютной вероятности каждой из них.

Неподкреплённый prior расходует предел влияния, но не создаёт `Support` или `PriorSupport`. Effective mass собственного evidence входит в `Support`, переносимого upstream evidence — в `PriorSupport`; одно основание учитывается один раз. Исходные contributions сохраняются, а коэффициент `a` вычисляется при чтении. В формулах updaters `p₀` означает prior после этого adjustment; исходное предложение prior от числа собственных observations не меняется.

Prior собирается в тех же координатах:

```text
z_prior = z_base + a × u₀ + Σ_{i ∈ W_prior} a × Δ_i
```

Для binary target `p₀ = sigmoid(z_prior)`, для scope — `p₀ = softmax(z_prior)`. Обоснованные upstream contributions уже входят в `z_base`. Собственное evidence добавляется updater-ом отдельно; ни один из этих вкладов не дублируется внутри `v₀`.

Это консервативная эвристика MVP, а не гарантия точного Bayesian posterior или эмпирической calibration. Изменение предела или снятие ограничения для конкретного семейства требует применимых независимых оснований и обычной проверки изменения программы. Переименование модели, увеличение числа непроверенных примеров или перенос через другой belief не снимают ограничение.

Применимость модели, её версия, использованные основания и признаки неподтверждённого влияния сохраняются во внутренних данных assessment и [[Memory#^def-ResultProvenance|provenance]]. Consolidation сохраняет разделение таких вкладов, исходные masses и зависимости, необходимые для пересчёта. Их нельзя слить в один net contribution, если после этого невозможно воспроизвести ограничение или обоснованный пересмотр.

---

#### Calibration

#topic_core

(def_id:: entity.Calibration)
> [!definition] **Calibration** — соответствие вероятностных predictions агента наблюдаемой частоте исходов. Если для множества сопоставимых случаев агент возвращает вероятность около `p`, соответствующий outcome должен наблюдаться примерно с частотой `p`. ^def-Calibration

Калибровка не требует отдельной подсистемы. Systematic miscalibration является evidence для обучения механизма, который создаёт prediction, через обычную [[Learning system#^def-LearningSystem|Learning System]]: parameter update или structural revision. При необходимости этот механизм может включать обучаемое преобразование выхода — калибратор. Его проверка, включая покрытие интервалов и значимые контексты, следует [[Process Plane/Program Evaluation and Testing#^prediction-calibration-sharpness|общим правилам калибровки прогнозов]]; отдельный калибратор не обязателен.

##### CalibrationStats

#topic_core

(def_id:: entity.CalibrationStats)
> [!definition] **CalibrationStats** — опциональная компактная статистика calibration для **повторяемого semantic типа** [[#^def-BeliefTarget|**BeliefTarget**]], накопленная по собственным predictions агента и их независимо наблюдаемым outcomes. ^def-CalibrationStats

#topic_details

Конкретные targets:

```
DIES_WITHIN_30D(Patient#1)
DIES_WITHIN_30D(Patient#2)
DIES_WITHIN_30D(Patient#3)
```

могут использовать общую статистику:

```
DIES_WITHIN_30D
→ CalibrationStats
```

если представляют один и тот же тип prediction и относятся к сопоставимым условиям.
Для target types, по которым такая статистика не накоплена или неприменима:

```
CalibrationStats = None
```

Для scalar probability в MVP:

```python
CalibrationStats {
  bins: <CalibrationBin[]>
}

CalibrationBin {
  probability_range: <Interval[float]>
    "Диапазон predicted probabilities."

  count: <int>
    "Число представленных logical resolved predictions."

  probability_sum: <float>
    "Сумма predicted probabilities."

  positive_count: <int>
    "Число случаев, в которых predicted outcome произошёл."
}
```

Для каждого bin:

```text
mean predicted probability = probability_sum / count
observed frequency         = positive_count / count
```

Их расхождение показывает miscalibration.

Для других форм probabilistic prediction используется соответствующее model-specific mergeable sufficient state.

##### Calibration lifecycle

#topic_details 

Одна calibration unit соответствует одному логическому prediction, сделанному **до** независимо наблюдаемого outcome. Повторное чтение или технический пересчёт того же prediction новой unit не создаёт.

```text
own probabilistic prediction
        ↓
independently observed outcome
        ↓
update CalibrationStats
        ↓
обычный Learning ответственного механизма
```

Не разрешённый или неоднозначный outcome не учитывается как отрицательный.

[[#^def-CalibrationStats|`CalibrationStats`]] пополняются результатами проверки собственных predictions агента. Проверочный случай может происходить как из live-опыта, так и из внешнего источника, если агент может сформировать prediction из информации, доступной до outcome, а затем независимо сравнить её с надёжным observed outcome. Чужие predictions или опубликованные calibration-оценки напрямую в `CalibrationStats` не объединяются.

При существенной смене режима новый опыт накапливается в отдельных `CalibrationStats` нового regime; произвольное окно `recent` не используется.

После стандартной memory consolidation должно сохраняться достаточно статистики, чтобы оценка calibration существенно не менялась:

```text
calibration(raw compatible predictions)
≈
calibration(retained CalibrationStats)
```

:::

---
#### Target-specific belief updaters
#topic_details

##### Binary belief updater
#topic_details 

Для binary [[#^def-BeliefTarget|`BeliefTarget`]] contribution из [[#^def-Evidence|`Evidence`]] задаётся signed log-evidence:

```text
Δ > 0
→ evidence поддерживает target;

Δ < 0
→ evidence поддерживает его отрицание;

Δ = 0
→ evidence релевантно, но не различает две возможности.
```

Для atomic evidence `m_i = |Δ_i|`. При consolidation сохраняются `Δ_merge = Σ_i Δ_i` и `m_merge = Σ_i m_i`, поэтому `|Δ_merge| ≤ m_merge` даже при взаимной компенсации вкладов.

При prior $p_0$:

$$  
z =  
\operatorname{logit}(p_0)  
+  
\sum_i \tilde{\Delta}_i  
$$

$$  
Strength = \sigma(z)  
$$

[[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] вычисляет contribution как log-likelihood ratio по известной, обученной или явно приблизительной [[#Расчёт Evidence → contribution|модели наблюдений]]. Приблизительные contributions допустимы до калибровки и подчиняются общему пределу влияния.

`Support` вычисляется по общему контракту `Evidence contribution` из effective evidence mass и здесь повторно не определяется.

Для пересматриваемого belief:

$$  
0 < p_0 < 1  
$$

Жёстко невозможные состояния задаются semantic constraints, а не значениями prior $0$ или $1$.

---

##### CompetitionScope updater
#topic_details 

`CompetitionScopeUpdater` является общим для любого `CompetitionScope`: он не различает hypotheses и значения categorical / ordinal Property и работает в пространстве ненормированных log-weights.

Один [[#^def-EvidenceAssignment|`EvidenceAssignment`]] оценивает scope целиком. Его contribution — вектор relative log-evidence:

```text
Δ_i = {
  a1: Δ_i,1,
  ...
  ak: Δ_i,k
}
```

Общий additive offset не имеет значения: добавление одной константы ко всем компонентам не меняет результат. Поэтому contribution хранится в канонической форме, например с нулевым средним.

Для atomic assignment:

$$
m_i = \max_k \Delta_{i,k} - \min_k \Delta_{i,k}
$$

Для consolidated assignment:

$$
\Delta_{\text{merge},k} = \sum_i \Delta_{i,k}
$$

$$
m_{\text{merge}} = \sum_i m_i
$$

Следовательно:

$$
\max_k \Delta_{\text{merge},k}
- \min_k \Delta_{\text{merge},k}
\le m_{\text{merge}}
$$

Для каждой alternative $a_k$:

$$  
z_k =  
\ln p_{0,k}  
+  
\sum_i \widetilde{\Delta}_{i,k}  
$$

[[#^def-Profile|`Profile`]] вычисляется через softmax:

$$
Profile(a_k) =
\frac{\exp(z_k)}
{\sum_j \exp(z_j)}
$$

Следовательно:

$$  
\sum_k Profile(a_k)=1
$$

и:

$$  
Strength(a_k)=Profile(a_k)
$$

Общий `Support` scope:

$$  
Support =  
\sum_i \widetilde m_i  
$$

Для всех alternatives:

$$  
p_{0,k}>0,  
\qquad  
\sum_k p_{0,k}=1  
$$

Все contributions конечны. Жёсткая невозможность alternative задаётся структурным ограничением `CompetitionScope`, а не через $p_{0,k}=0$ или $\Delta=-\infty$.

Одно source [[#^def-Evidence|evidence]] увеличивает `Support` scope ровно один раз, даже если различает несколько alternatives.

Evidence:

```text
A: +5
B: +5
C: +5
```

эквивалентно нулевому relative contribution и поэтому имеет:

```text
evidence_mass = 0
```

Оно не изменяет `Profile` или `Support`, но остаётся релевантной проверкой и учитывается в [[#^def-EvidenceStats|EvidenceStats.evidence_count]].

#### Consolidation invariant
#topic_core

Несколько совместимых [[#^def-EvidenceAssignment|`EvidenceAssignment`]] могут быть заменены одним консолидированным `EvidenceAssignment`.

Для каждого поддерживаемого read context, текущих temporal/dependency policies и общего предела неподтверждённого влияния должно выполняться:

```text
belief(E1, ..., En)
≈
belief(merge(E1, ..., En))
```

с точностью, допускаемой конкретным updater-ом.

То есть консолидация не должна существенно изменять:

```text
Strength / Profile;
Support;
EvidenceStats.
```

#topic_details

При merge сохраняются совокупная evidence mass и logical multiplicity:

```text
m_merge     = Σ m_i
count_merge = Σ count_i
```

где `count` — число представленных logical evidence units, а не физических `EvidenceAssignment`.

Консолидированное representation также сохраняет минимальную структуру, необходимую для поддерживаемых temporal/dependency adjustments и ожидаемо нужного `revise/retract`.

[[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] дополнительно сохраняет:

```text
минимум один характерный исходный observation / experience;
значимые exceptions и counterexamples.
```

Существенно разные источники, dependency branches, regimes, независимые проверки или значимые подтверждения и опровержения не объединяются, если их различие остаётся эпистемически полезным.

После успешной консолидации остальные взаимозаменяемые routine observations и исходные `EvidenceAssignment` могут быть удалены согласно общему lifecycle [[Memory#^def-Memory|Memory]].

Таким образом:

```text
consolidated EvidenceAssignment
→ сохраняет совокупное эпистемическое влияние группы
  и необходимую статистику её структуры;

representative observation
→ сохраняет конкретный пример опыта,
  который эта группа представляет.
```


## Evidence model
#topic_core

### Evidence
#topic_core

(def_id:: entity.Evidence)
> [!definition] **Evidence** — опыт или результат проверки, релевантный конкретному belief, независимо от того, изменяет ли он belief. ^def-Evidence

Релевантная проверка, не различившая alternatives, тоже является evidence: 
Δ = 0 
evidence_mass = 0 

Она не изменяет Strength и не увеличивает Support, но создаёт [[#^def-EvidenceAssignment|EvidenceAssignment]] и фиксирует, что вопрос действительно исследовался.


Нужно различать:

Observation / EvaluationResult / другой опыт
→ что произошло или было получено;

EvidenceAssignment
→ какой вклад этот опыт получает в конкретном belief.

Один источник опыта может дать evidence нескольким beliefs.


---

### Evidence sources
#topic_core

Основные источники evidence:

```text
Observation
→ независимо полученный факт о мире или состоянии;

EvaluationResult
→ результат явной проверки prediction,
  Note, Claim, Prompt, Program или другого проверяемого объекта;

realized outcome
→ фактический результат действия или процесса;

derived result
→ результат reasoning, simulation или другой Program,
  если его использование как evidence явно обосновано.
```

Derived result, включая [[Core data structures#^def-Note|Note]] и [[Core data structures#^def-Claim|Claim]], не становится evidence автоматически. Его основания и зависимости должны быть восстановимы через [[Memory#^def-ResultProvenance|provenance]], чтобы один и тот же исходный опыт не усиливал belief многократно через несколько производных выводов.

Prior не является новым evidence. Он задаёт исходное состояние belief до накопления собственного evidence данного target.

---


### EvidenceAssignment

#topic_core

(def_id:: entity.EvidenceAssignment)
> [!definition] **EvidenceAssignment** — неизменяемый вклад одного logical evidence unit или допустимо консолидированной группы evidence в конкретный target. ^def-EvidenceAssignment

```python
EvidenceAssignment {
  target: <BeliefTarget>
    "Канонический semantic target, которому назначено evidence."

  contribution: <UpdaterContribution>
  "Updater-specific sufficient representation воздействия данного evidence на target."

  evidence_mass?: <float>
    "Discriminative evidence mass для epistemic updater-а,
     поддерживающего generic Support.
     Для atomic evidence детерминированно вычисляется из contribution;
     после consolidation сохраняет суммарную mass компонентов."

  observed_scope?: <time | TimeInterval>
    "Время мира, к которому относится evidence;
     после consolidation может охватывать интервал."
}
```

[[#^def-EvidenceAssignment|`EvidenceAssignment`]] является обычным immutable [[Memory#^def-OperatorOutput|`OperatorOutput`]]; отдельное evidence-хранилище не создаётся. Источники, использованные при assessment данные и версии программ восстанавливаются через общий [[Memory#^def-ResultProvenance|provenance]].

`contribution` не является `Strength`, `Support` или `value_U`: его форма и смысл определяются epistemic updater-ом target-а.

`evidence_mass` связана с `contribution` математическим контрактом epistemic updater-а и не назначается независимо.


#topic_details

После consolidation representation должна сохранять минимальные sufficient statistics, необходимые для восстановления [[#^def-EvidenceStats|`EvidenceStats`]] после удаления исходных assignments:

```text
evidence_count;
max_component_mass;
max_component_effect.
```

Эта component-summary является технической частью consolidated representation, а не отдельным semantic object или публичным полем `EvidenceAssignment`.


---

#### UpdaterContribution contract
#topic_core

Форма `UpdaterContribution` определяется механизмом обновления target-а.

```text
BinaryBeliefUpdater →
signed log-evidence; 

CompetitionScopeUpdater → 
relative log-evidence vector; 

other epistemic belief updater →
updater-specific sufficient evidence representation.
```

UpdaterContribution должен быть достаточен для детерминированного
reduce, merge, revise/retract и пересчёта belief.

---

### EvidenceAssessmentProgram
#topic_core

(def_id:: entity.EvidenceAssessmentProgram)
> [!definition] **EvidenceAssessmentProgram** — Program модели evidence, которая определяет, каким [[#^def-BeliefTarget|`BeliefTarget`]] релевантен полученный опыт, оценивает его epistemic contribution и создаёт [[#^def-EvidenceAssignment|`EvidenceAssignment[]`]]. ^def-EvidenceAssessmentProgram

Это обучаемая программа. Её основной численный вопрос: насколько полученное наблюдение ожидаемо при каждом возможном состоянии target. Из этих оценок код вычисляет вклад в belief. Приблизительная начальная модель допустима; её [[#Ограничение неподтверждённого влияния|совокупное влияние ограничивается]], пока нет достаточных оснований доверять расчёту.

```text
Observation / EvaluationResult / derived result
+ source + provenance
        ↓
EvidenceAssessmentProgram
        ↓
EvidenceAssignment[BeliefTarget][]
```

Belief System владеет [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]], создаваемыми ею `EvidenceAssignment` и их lifecycle. `LearningCoordinator` только вызывает этот контракт.

#topic_details

При assessment результата prediction используется следующий поток, сохраняемый как [[Memory#^def-ProgramRun|`ProgramRun`]]:

```text
ProgramRun → observable claim
+ independent Observation
→ EvaluationResult
+ provenance
→ EvidenceAssessmentProgram
→ EvidenceAssignment[]
```

Assessment различает:

```text
observable claim
→ direct evidence из его проверки;

latent claim
→ indirect evidence через зависимые observable predictions;

OperatorConcept / Program
→ evidence о корректности или применимости механизма;

policy / action-selection mechanism
→ evidence о качестве сделанного выбора.
```

Evidence сначала назначается наиболее непосредственно проверенному уровню. Более общий belief получает отдельный `EvidenceAssignment` только когда локальные объяснения недостаточны и повторяющиеся независимые результаты действительно информативны относительно общего механизма.

Provenance ограничивает множество возможных `BeliefTarget`, но сам по себе не доказывает, какому из них относится evidence.

```text
provenance
→ какие BeliefTarget могли быть затронуты;

EvidenceAssessmentProgram
→ каким BeliefTarget назначается evidence;

belief updater
→ как contributions агрегируются в epistemic state.
```

#topic_core

Program не назначает learning credit и не обновляет belief или parametric state. `CreditAssignmentProgram` определяет [[Learning system#LearningCredit and UnresolvedCredit|credit по выбранному LearningTarget]], `UpdatePlanner` выбирает состояние для обновления. Belief updater пересчитывает [[#^def-BeliefData|`BeliefData`]], estimator или optimizer вычисляет новое parametric state, которое сохраняет общий механизм обновлений.

Обычно `LearningCoordinator` вызывает `EvidenceAssessmentProgram`; `resolve_prior` также может вызвать её для retrieved sources. Для assessment evidence не требуется evaluable `ProgramRun` или обучаемый компонент.

#topic_details

`EvidenceAssessmentProgram` может учитывать:

```text
надёжность источника;
качество измерения или observation;
применимость к target;
прямой или косвенный характер evidence;
известные зависимости от другого evidence.
```

Релевантная неразличающая проверка всё равно создаёт `EvidenceAssignment` с `contribution = 0` и `evidence_mass = 0`.

Для `CompetitionScope` один source создаёт один `EvidenceAssignment` на весь scope с contribution по всем alternatives. Если тот же source относится к нескольким совместимым beliefs, каждый из них может получить отдельный assignment.

Если отношение evidence к target остаётся неоднозначным, assessment либо создаёт assignments по применимой модели, учитывающей эту неоднозначность, либо не создаёт assignment и оставляет случай `unresolved`. Приблизительные оценки подчиняются общему ограничению неподтверждённого влияния. Незаанкоренные детали реализации не получают самостоятельного evidence.

Внутренняя численная оценка возвращает `UpdaterContribution`; публичный результат программы — `EvidenceAssignment[]`.

Для epistemic updaters `evidence_mass` затем детерминированно вычисляется из contribution и не назначается независимо.

Не используется универсальное правило вида:

```text
contribution = reliability × applicability
```

поскольку вклад зависит от условной модели наблюдений. Если наблюдение одинаково ожидаемо при истинном и ложном target, оно даёт `Δ = 0`; условно независимые повторения таких неразличающих наблюдений не усиливают belief.

Использованные входы и версия `EvidenceAssessmentProgram` сохраняются через обычный `ProgramRun` и provenance.

Важно:

> `Contribution` фиксирует assessment evidence, принятый в момент создания assignment. Последующее изменение знания об источнике не изменяет старый assignment автоматически.

#### Расчёт Evidence → contribution
#topic_core

Модель наблюдений описывает, какие результаты проверки или сообщения источника возможны при каждом состоянии target:

```text
H — состояние target: 0/1 для binary target либо alternative scope-а;
h — конкретное состояние;
R — возможный результат наблюдения, r — полученный результат;
C — контекст, источник, способ получения наблюдения и режим;

q_h(r | C) — модельная вероятность результата r для дискретного R
             или плотность для непрерывного R при H = h и контексте C.
```

Для binary target нужны две оценки: при истинном утверждении (`H = 1`) и при ложном (`H = 0`). Одного числа «доверие к evidence» недостаточно: наблюдение информативно, если оно по-разному ожидаемо при этих двух состояниях.

```text
полученный опыт и уже извлечённый смысл
→ подходящий target и модель наблюдений
→ likelihood полученного r при каждом состоянии target
→ log-evidence contribution
→ EvidenceAssignment
→ учёт зависимостей, времени и ограничений влияния
→ BeliefData / Profile
```

Программа задаёт пространство результатов `R` и нормированное распределение по ним для каждого `h`; для дискретных результатов `Σ_r q_h(r | C) = 1`. Полученное `r` выбирает элемент распределения; сам факт `R = r` не включается в условия `C`. Если отрицание binary target объединяет разные состояния, модель задаёт их состав и используемую смесь.

#topic_details

Для binary target:

$$
\Delta = \ln \frac{q_1(r\mid C)}{q_0(r\mid C)}.
$$

Например, проверка выдаёт положительный результат в `80%` случаев при истинном `H` и в `20%` при ложном. Положительный результат даёт `Δ = ln(4)`. При prior `0.5` обоснованная модель даёт posterior `0.8`; если эти частоты пока только предположены LLM, применяется ограничение неподтверждённого влияния.

Для `CompetitionScope` вычисляются `ℓ_k = ln q_k(r | C)` и `Δ_k = ℓ_k − mean_j ℓ_j`. Один assignment содержит весь вектор. Mass и агрегация определяются [[#Target-specific belief updaters|контрактами updaters]].

Likelihoods и prior используют согласованный контекст. Сумма отдельных log-likelihood ratios задаёт точный Bayesian update в выбранной модели при условной независимости наблюдений при каждом состоянии target. Разные источники и отсутствие известных зависимостей сами по себе этого не гарантируют. Для зависимых наблюдений нужна совместная модель или [[#Evidence dependencies|условный прирост с учётом уже использованного evidence]]; эвристическая коррекция даёт приблизительный расчёт и подчиняется ограничению неподтверждённого влияния.

Для непрерывного наблюдения сравниваются плотности относительно одной меры либо вероятности заранее заданных интервалов. Модель объявляет сглаживание, обеспечивающее конечные используемые log-likelihoods; оно сохраняет нормировку. Нулевые частоты малой выборки не доказывают невозможность исхода. Жёсткая невозможность задаётся semantic constraints.

#### Способы получить модель наблюдений
#topic_core

Одна версия программы может выбирать способ оценки по типу evidence и контексту. Для одного logical evidence выбирается одна итоговая оценка; результаты разных способов не складываются как независимые подтверждения.

| Способ | Когда применяется | При недостаточных основаниях |
|---|---|---|
| Известная модель наблюдений | Есть применимый протокол теста, модель измерения или опубликованные характеристики ошибок | Проверить перенос на данный источник и контекст; неподтверждённую часть считать приблизительной |
| Обученная модель | Есть сопоставимые наблюдения и независимо разрешённые состояния `H` | Переиспользовать более общую модель или сглаженную начальную оценку; ограничивать влияние до независимой проверки |
| Явная эвристика | Есть осмысленный способ оценить условные распределения, но пока мало данных; правило или начальную таблицу может подготовить LLM | Сохранять допущения и пробелы, применять общий предел влияния; если осмысленная оценка невозможна, оставить случай `unresolved` |

LLM может подготовить таблицу, правило или код модели сразу для семейства процессов. Ей задаются состояния `H`, протокол наблюдения, возможные результаты `R` и допустимый контекст `C`. Она возвращает нормированные условные распределения, источники и краткие ограничения применимости. Числовой формат и требования к основаниям следуют [[#LLM prior proposal|общему протоколу вероятностных предложений]], но выход здесь — `P(R | H, C)`, а не `P(H)`.

Отсутствие точной калибровки не блокирует работу. Отсутствие осмысленного отношения evidence к target не подменяется нулевым contribution: `Δ = 0` означает, что модель оценила проверку как неразличающую.

Для MVP достаточно условных таблиц, счётчиков и вычисления логарифмов. Универсальная библиотека вероятностного программирования или дифференцируемого inference не обязательна; специализированная модель может использовать её внутри своей реализации, если это оправдано задачей.

#### Обучение модели evidence
#topic_core

Начальный обучаемый вариант — таблица частот результатов `R` отдельно для истинного и ложного `H`, либо для каждой alternative scope-а, в сопоставимых контекстах. Контексты группируются по объявленным признакам модели; identity нового target сама по себе не создаёт новую строку. Общая таблица используется для семейства процессов; отдельное состояние создаётся, когда данные показывают существенное различие источников, условий или режимов.

#topic_details

Простой estimator со сглаживанием:

$$
q_h(r\mid C)=
\frac{n_{h,r,C}+\kappa\pi_{h,r,C}}
{\sum_{r'}n_{h,r',C}+\kappa}.
$$

Здесь `n` — counts разрешённых случаев, `π` — начальное нормированное распределение с `π_{h,r,C} > 0` для всех допустимых результатов, `κ > 0` — сила сглаживания. Начальное распределение берётся из применимой общей модели, внешних данных или ограниченного LLM proposal. Его pseudocounts не являются реальными observations и не создают `Support / PriorSupport`.

Обучающий случай содержит контекст, наблюдение `r` и независимо установленное состояние `h`. После разрешения случая обновляется соответствующая строка таблицы через [[Learning system#LearningCoordinator|обычный learning pipeline]]. Сначала оценивается сохранённый прогноз, затем этот случай может использоваться для обучения. Для проверки `q_h` прогноз распределения должен быть сформирован без доступа к оцениваемому `r`: заранее либо в независимом проверочном прогоне.

Текущий belief агента, согласие другой LLM и повтор сообщения того же источника не становятся независимыми метками истины. Неразрешённый исход не считается ложным. Исправление метки корректирует прежний обучающий вклад по [[Learning system#Исправление уже использованного опыта|общим правилам]]; повторное разрешение того же случая не увеличивает число независимых примеров.

Применимость выборки, смещение отбора и разделение обучения и проверки следуют [[Process Plane/Program Evaluation and Testing#Протокол проверки прогнозов|общему протоколу]]. Проверяются условные распределения и получаемые из них beliefs в значимых контекстах. Counts модели ошибок и [[#^def-CalibrationStats|CalibrationStats]] имеют разный смысл: первые обучают модель, вторые описывают качество её прогнозов.

При появлении данных таблицу можно заменить регрессией, калибратором или специализированной моделью по [[Process Plane/Program Lifecycle and Evolution#Подготовка начальных моделей|общим правилам выбора и проверки]].

#### Жизненный цикл assessment
#topic_core

Подготовка и изменение программы проходят [[Process Plane/Program Lifecycle and Evolution#Подготовка начальных моделей|общий Program Lifecycle]]. Для первой версии достаточно следующего пути:

1. **Подготовить семейство.** Переиспользовать подходящие модели и правила; определить наблюдения, targets, контексты и начальные условные распределения. При необходимости одна ограниченная сессия LLM / research заполняет пробелы. Результат сохраняется как код, настройки или модельный артефакт программы.
2. **Обрабатывать обычные события кодом.** По типу наблюдения и контексту выбрать обработчик, получить параметры модели и вычислить contributions. Новый экземпляр процесса, target или semantic anchor в известном контракте не требует LLM-вызова.
3. **Разбирать новый случай общим пакетом.** Сначала использовать применимый общий обработчик. Если его недостаточно, один владелец assessment собирает связанные targets и уже извлечённые данные в общий пакет для программы и события. На пакет формируется один LLM-запрос. Он возвращает оценки для нескольких targets, из которых код создаёт assignments, или предлагает переиспользуемое правило.
4. **Накапливать независимые проверки.** Разрешённые случаи обучают модель наблюдений и модель ошибок источника. До подтверждения качества действует общий предел неподтверждённого влияния; само число обработанных сообщений его не снимает.
5. **Пересматривать существенные изменения.** При устойчивой ошибке, новых условиях или неподходящем формате evidence уточнить модель либо выделить режим. Один необычный исход сам по себе не требует новой программы. Затронутое старое evidence переоценивается через `revise`.

#topic_details

Пакет — набор входных данных существующей программы. Если смысл сообщения уже извлечён perception или другой программой, assessment использует этот результат. Когда извлечение и оценку выполняет LLM в данном пути, они объединяются в одном вызове.

Чтения prior и [[#^def-SourceReliability|SourceReliability]], обработчики отдельных anchors и дочерние программы используют готовые модели. Их потребность в LLM передаётся владельцу пакета; отдельных запросов оценки для каждого anchor нет. Повтор технически неуспешного запроса использует тот же пакет и бюджет; дополнительные ответы ради согласования оценок не запрашиваются. Все расходы входят в бюджет [[Cognition and Attention|Task и её дочерних запусков]]. При недоступности LLM, таймауте или исчерпании выделенного бюджета LLM применяется объявленный приблизительный путь либо сохраняется `unresolved`; обработка известных случаев продолжается в пределах бюджета Task. Исчерпание общего бюджета подчиняется обычным правилам остановки и пересмотра Task.

Повторная обработка пакета использует сохранённый результат, пока его входы, модели и условия применимости сохраняют силу. При reassessment сохраняется [[#Logical evidence identity and duplicate prevention|identity исходного evidence]] и выполняется `revise`.

Внешнее исследование следует [[Process Plane/Program Lifecycle and Evolution#Stage 1: gather_relevant_info|общим правилам подготовки программы]]. Обычные чтения и новые evidence не запускают web search.

При смене режима прежние проверки не переносятся автоматически на новые условия. Сначала пересматривается применимость модели; для неподтверждённого режима используется общий fallback с ограниченным влиянием. Стабильные случаи продолжают обслуживаться прежним обработчиком. Новый код или модель проверяются на независимых случаях с учётом затрат до замены действующей версии.

#### Частые случаи и границы применимости
#topic_details

| Случай | Правило |
|---|---|
| Проверка pass / fail или измерение | Использовать модель ошибок теста, плотность либо заранее заданные интервалы; величина ошибки сама по себе не является contribution |
| Сообщение источника | Использовать [[#Source reliability estimation|условную модель его сообщений]]; высокая общая accuracy не равна большому likelihood ratio |
| Несколько alternatives | Оценить scope целиком одним вектором; добавление или удаление alternatives требует проверки применимости модели |
| Повторы, пересказы, общая предпосылка | Учесть [[#Evidence dependencies|зависимости]] до суммирования; несколько текстов не гарантируют несколько подтверждений |
| Нет ожидаемого сообщения | Это evidence только при заданном протоколе наблюдения и основаниях считать, что сообщение было бы обнаружено |
| Противоречивые наблюдения | Сохранить обе стороны с их provenance, проверить источник, зависимости и режим; противоречие не превращает редкий исход в недостоверный автоматически |
| Меняются параметры оцениваемой модели | Evidence о фиксированной версии не подтверждает новую версию автоматически; evidence о механизме обучения применимо лишь при соответствующем Criterion и контексте |

#### Evidence for TRIGGER and CONDITION
#topic_details

[[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] создаёт для beliefs о `TRIGGER` и `CONDITION` evidence разных типов:

```text
TRIGGER:
обновляется как активная причинная связь
"что реально привело к переходу"

CONDITION:
обновляется как граница применимости
"при каких условиях переход возможен / невозможен"
```

Если переход сработал, создаются:

```text
active TRIGGER
→ supporting EvidenceAssignment

valid CONDITION
→ supporting EvidenceAssignment

Если переход не сработал:

failed TRIGGER
→ opposing EvidenceAssignment
  или evidence за более узкий context;

missing/false CONDITION
→ blocking evidence
  для соответствующей границы применимости.
```

Если опыт оценён и выбран для обучения, `CreditAssignmentProgram` может отдельно выдать [[Learning system#LearningCredit and UnresolvedCredit|LearningCredit]] для соответствующего [[Learning system#^def-LearningTarget|LearningTarget]]; состояния связанных обучаемых компонентов выбирает `UpdatePlanner`. [[#^def-EvidenceAssignment|`EvidenceAssignment`]] и `LearningCredit` не являются одним и тем же output.



---

### Evidence dependencies
#topic_core

Несколько [[#^def-Evidence|evidence]] могут иметь общий источник, observation, предпосылку или
вычислительный результат и поэтому не должны автоматически считаться
независимыми.

Зависимости определяются из:

```text
provenance
+ EVIDENCE_DEPENDS_ON relations
        ↓
dependency view
        ↓
updater
```

`provenance` показывает вычислительные зависимости.
`EVIDENCE_DEPENDS_ON` фиксирует дополнительные информационные зависимости,
выявленные reasoning или learning.

#topic_details

Например:

```text
EVIDENCE_DEPENDS_ON(SiteAReport, ReutersReport)
EVIDENCE_DEPENDS_ON(SiteBReport, ReutersReport)
EVIDENCE_DEPENDS_ON(SiteCReport, ReutersReport)
```

означает, что три публикации не являются тремя независимыми подтверждениями.

`dependency view` является вычисляемым представлением; отдельная сущность
`DependencyGroup` и поле `dependency_group_id` в [[#^def-EvidenceAssignment|`EvidenceAssignment`]]
не нужны.

В MVP пересказы одного первоисточника используют один вклад исходного наблюдения. Если зависимые сообщения содержат дополнительную информацию, применяется совместная модель либо модель условного прироста с учётом уже использованного evidence. При отсутствии такой модели используется одно заранее выбранное наиболее прямое представление источника; выбор не зависит от того, какой вклад сильнее поддерживает target. Остальные сообщения сохраняются для provenance и пересмотра, но не увеличивают `Support` как независимые подтверждения.

Evidence, использованное как условие такого прироста, сохраняется в dependencies. Его изменение или отзыв требует переоценки зависимого contribution.

#### Dependency-aware consolidation
#topic_details

Dependency structure консолидируется вместе с evidence.

Если множество evidence имеет один общий первоисточник, оно может быть
свёрнуто в один [[#^def-EvidenceAssignment|`EvidenceAssignment`]], сохраняющий зависимость от этого
источника.

Например:
```text
700 reposts ← Reuters
250 reposts ← AP
50 independent checks
```
может быть представлено как:

```text
Reuters-derived evidence → consolidated EvidenceAssignment
AP-derived evidence      → consolidated EvidenceAssignment
independent checks       → отдельные или независимо consolidated EvidenceAssignment
```

[[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] не объединяет evidence через существенно разные
dependency branches, если это изменит belief или уничтожит ожидаемо нужную
возможность `revise/retract`, переоценки источника или анализа независимых
подтверждений.

Понимание зависимостей само пересматриваемо: если позднее обнаружен другой
общий источник или независимая проверка, semantic relations и зависимые
belief contributions могут быть пересмотрены.

---

### Logical evidence identity and duplicate prevention
#topic_core


Один и тот же logical evidence не должен несколько раз влиять на один target.

#topic_details

Logical identity назначения evidence задаётся ключом:

```text
evidence_key =
(
  source_evidence_ref,
  target_ref
)
```

`target_ref` — устойчивая identity [[#^def-BeliefTarget|`BeliefTarget`]] согласно [[Core data structures#Объекты и ссылки|общему правилу объектов и ссылок]]. `source_evidence_ref` адресует один logical evidence unit, обычно через:

```text
TraceOutputRef(event_ref, output_path)
```

где `output_path` указывает на соответствующий semantic result.

Для одного `evidence_key` существует не более одного текущего logical assignment.

Если один source влияет на target несколькими способами, [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] объединяет их в один `contribution`, а не создаёт несколько независимых assignments.

Если один [[Memory#^def-OperatorOutput|`OperatorOutput`]] содержит несколько независимых evidence units, они должны иметь разные semantic `output_path`.

Повторная обработка:

```text
тот же evidence_key + эквивалентная оценка
→ no-op;

тот же evidence_key + изменившаяся оценка
→ revise существующего assignment.
```

Роль assignment и версия `EvidenceAssessmentProgram` не входят в `evidence_key`: изменение способа оценки того же source evidence не создаёт новое независимое evidence.

`evidence_key` предотвращает повторный учёт одного и того же logical source result. Зависимость разных evidence, восходящих к одному основанию, обрабатывается отдельно через `dependency view`.

Повторная доставка или retry используют identity исходного события. Два действительно разных наблюдения с одинаковыми значениями имеют разные identities; совпадение текста не является правилом дедупликации. Исправленное наблюдение сохраняет связь с прежним logical evidence и пересматривает его вклад.

При consolidation logical evidence identities сохраняются; правила их компактного представления определены в `Consolidation invariant`.

После lossy consolidation lifecycle работает на фактически сохранённой гранулярности representation.

---

### Evidence lifecycle
#topic_core

#### Active evidence
#topic_core

[[#^def-EvidenceAssignment|`EvidenceAssignment`]] immutable, но его оценка может быть пересмотрена, отозвана или заменена consolidated representation. Поэтому отдельно определяется, какое representation каждого logical evidence используется сейчас.

#topic_details

Lifecycle относится к logical evidence (`evidence_key`), а не к конкретной immutable записи `EvidenceAssignment`: после revise или consolidation один logical evidence может представляться другой записью, а один consolidated assignment — сразу несколькими `evidence_key`. Поэтому текущее состояние хранится отдельно от самого assignment.

Текущее состояние logical evidence задаётся mapping:

```text
current_evidence[evidence_key]
→ assignment_ref | RETRACTED
```

(def_id:: entity.ActiveEvidence)
> [!definition] **Active evidence** target-а — уникальные `EvidenceAssignment`, на которые сейчас указывают его `evidence_key`. ^def-ActiveEvidence

```text
active_assignments(target)
→ unique active EvidenceAssignment[]
```

Так `revise`, `retract` и consolidation меняют current mapping, не переписывая прошлые `EvidenceAssignment`.

#topic_core

Нужно различать:

```text
active
→ assignment сейчас выбран как представление logical evidence;
  применимость к чтению проверяется отдельно;

effective
→ величина его текущего вклада после temporal
  и dependency adjustment и общего ограничения влияния.
```

Поэтому active evidence может иметь нулевой effective вклад — например релевантная неразличающая проверка с `Δ = 0`.

---
#### Evidence revision and retraction
#topic_core


Обычное новое evidence создаёт новый [[#^def-EvidenceAssignment|`EvidenceAssignment`]] и не изменяет прошлые записи.

`revise` и `retract` используются только когда меняется оценка **ранее назначенного evidence**.


---
##### Revising evidence

#topic_details

`revise` заменяет текущий assignment данного `evidence_key` новым:

```text
K: E_old
   ↓ revise
K: E_new
```

`E_old` остаётся immutable исторической записью. Для atomic evidence оно больше не входит в active evidence; при consolidated representation применяются правила согласованной замены ниже.

##### Retracting evidence

#topic_details

`retract` исключает ранее назначенное evidence из текущего belief:

```text
K: E_old
   ↓ retract
K: RETRACTED
```

`retract` не создаёт evidence за противоположное утверждение.

Если собственного active evidence target больше нет, его состояние отражает [[#^def-EvidenceStats|`EvidenceStats`]]:

```text
active evidence = ∅
→ Strength определяется prior
→ Support = 0
→ PriorSupport определяется backing prior
→ EvidenceStats отражает отсутствие active evidence
```

##### Lifecycle state
#topic_details 

Изменение применяется атомарно только при совпадении ожидаемого состояния:

```text
current_evidence[K] == expected_old_state
```

Если состояние уже изменено другим process, операция пересчитывается относительно нового состояния.

При публикации нового или пересмотренного assignment runtime также проверяет [[#Актуальность чтения|актуальность использованных оснований]] в той же защищённой операции. Устаревший результат не публикуется как текущий; повторный assessment следует общему lifecycle.

Успешный `revise` или `retract` атомарно обновляет `current_evidence` и фиксируется [[Memory#^def-TraceEvent|`TraceEvent`]], сохраняющим [[Memory#^def-ResultProvenance|provenance]] и историю операции.

Если один consolidated assignment представляет несколько `evidence_key`, пересмотр компонента согласованно заменяет представление всех затронутых ключей: новый вклад компонента и остаток агрегата не должны содержать одно и то же evidence. Старый агрегат исключается из active evidence целиком. Если данных для выделения компонента уже нет, пересмотр выполняется на сохранённой гранулярности группы с явным указанием потери точности; частичное исключение одного ключа не выдаётся за удаление его вклада из оставшегося агрегата.

`GraphDelta` для evidence lifecycle не используется: он относится к изменениям semantic graph.
##### Semantic target revision

#topic_core

Изменение epistemic оценки нужно отличать от изменения состояния мира и от изменения семантики самого target.

```text
изменилась оценка ранее назначенного evidence
→ revise / retract EvidenceAssignment;

новое evidence изменило belief о том же target
→ target не меняется;
→ пересчитываются value_U / BeliefData / Profile;

изменилось состояние самого мира
→ обычное temporal / semantic изменение модели мира
  через GraphDelta;

изменился смысл property, relation, Criterion
или CompetitionScope
→ semantic structural revision;
→ если изменилась identity оцениваемого вопроса,
  создаётся новый target.
```

Само изменение текущего `value_U` не создаёт новый target. Каноническое определение критерия проверки см. в [[Attribution Plane#^def-Criterion|Criterion]]; read-представлениями остаются [[#^def-BeliefData|`BeliefData`]] и [[#^def-Profile|`Profile`]].

#topic_details

Например:

```text
Mass(Object#7):
12.4 → 12.5
```

может означать новую оценку той же величины `Mass(Object#7)`.

Изменение реального состояния мира также не является `retract` evidence:

```text
close_facet_state
→ состояние действительно существовало,
  но перестало быть актуальным;

retract EvidenceAssignment
→ конкретное evidence больше
  не используется как основание belief.
```

#topic_core

Semantic изменения persistent graph выполняются через `GraphDelta`.  
`revise/retract` относятся к lifecycle [[#^def-EvidenceAssignment|`EvidenceAssignment`]] и не требуют отдельной сущности `BeliefUpdate`; их история сохраняется через immutable assignments, lifecycle records и `TraceEvent` с provenance.



---

#### Temporal consolidation
#topic_details

Время мира, к которому относится [[#^def-EvidenceAssignment|`EvidenceAssignment`]], задаётся через `observed_scope`:

```text
atomic evidence
→ конкретный момент времени;

consolidated evidence
→ интервал [t_from, t_until).
```

`known_at` — момент знания агента, используемый при историческом read; он не входит в `observed_scope` и не является частью semantic identity evidence.

[[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] может объединять evidence разных моментов времени только если потеря временной детализации не меняет существенно его дальнейшее использование.

```text
близкое и однородное evidence
→ может быть объединено;
```

Размер интервала выбирается адаптивно: плотное и старое routine-evidence обычно может быть представлено крупнее, а недавнее, редкое, изменчивое или находящееся около предполагаемой смены режима — подробнее.

Temporal и dependency adjustments, если необходимы, применяются при вычислении belief, а не путём изменения сохранённого evidence. Консолидация допустима только если retained representation сохраняет достаточную информацию для поддерживаемых adjustments.

Если последующее изменение adjustment policy требует утраченной детализации:

```text
retained aggregate достаточен
→ recompute;

сохранён source experience
→ reassessment;

source details удалены
→ aggregate используется с известной потерей точности.
```

Консолидация через подтверждённую границу существенно разных regimes не выполняется. При неопределённости границы `MemoryConsolidationProgram` предпочитает меньшую степень сжатия.

Как и при другой консолидации evidence, сохраняются характерные representatives, exceptions, counterexamples и случаи, необходимые для анализа изменений режима.

---

## Provenance, reassessment, and recomputation
#topic_core

### Read-time computation and provenance

#topic_core

Текущий epistemic state вычисляется при чтении:

```text
prior + PriorSupport
+ active EvidenceAssignment[]
        ↓
temporal / dependency adjustment
+ общий предел неподтверждённого влияния
        ↓
target-specific updater
        ↓
BeliefData / Profile
+ EvidenceStats
```

Если само `value_U` обучается estimator-ом, оно вычисляется отдельно из его observations / sufficient state.

Read ничего не записывает. Новый [[#^def-EvidenceAssignment|`EvidenceAssignment`]] создаётся только при новом evidence или явной переоценке старого; provenance каждого assignment сохраняется обычным механизмом provenance.
Успешное чтение возвращает вычисляемые [[#^def-BeliefData|`BeliefData`]], [[#^def-Profile|`Profile`]] и [[#^def-EvidenceStats|`EvidenceStats`]]; при недоступной актуальной оценке — `unknown` по правилам ниже.

#### Актуальность чтения
#topic_core

Чтение использует согласованное состояние prior, active evidence, применимых моделей и политик. Сохранённые оценки и кеши пригодны, пока использованные входы, состояния моделей и условия применимости сохраняют силу для запроса. Это включает производные входы, используемые как текущее знание; изменение вне их области применимости не требует переоценки.

Если нужный пересчёт выполняется обычным read-time computation, возвращается пересчитанный результат. Если нужен новый assessment и он ещё не выполнен, чтение возвращает `unknown` с причиной и указанием затронутых оснований. Устаревший вклад нельзя молча исключить или обнулить: это может убрать опровергающее evidence. Ожидание переоценки само по себе не является `retract`.

Вызывающая программа или сознание при необходимости организует [[#Жизненный цикл assessment|пакетную переоценку]] через существующий Learning pipeline в текущей [[Cognition and Attention#Goal, Task и спецификация задачи|Task]] и повторяет чтение. Пока применимая оценка не получена, результат остаётся `unknown`; старое число не используется как текущее.

Эти правила действуют также для чтений через плоскости и материализованные результаты. При [[Attribution Plane#Историческая реконструкция свойства|историческом чтении]] применимость проверяется на `known_at`; последующие изменения не переписывают прежние snapshots и их основания.

---

### Finding affected EvidenceAssignments
#topic_details

Старое evidence переоценивается, если изменилось релевантное знание, использованное при его создании: например, модель ошибок источника, его dependencies или логика [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]]. Provenance фиксирует версии и использованное состояние этих моделей, чтобы найти затронутые assignments.

Затронутые assignments находятся через существующие зависимости:

```
provenance
+ EVIDENCE_DEPENDS_ON
→ affected EvidenceAssignment[]
```

### Evidence reassessment and belief recomputation
#topic_details

Если изменилось знание, использованное при оценке старого evidence, затронутые [[#^def-EvidenceAssignment|`EvidenceAssignment`]] переоцениваются через [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]]:

```
изменилось релевантное знание
→ affected EvidenceAssignment[]
→ повторный `EvidenceAssessmentProgram`
→ old assignment заменяется новой оценкой с актуальными основаниями,
  даже если численный contribution не изменился
→ belief пересчитывается
```

#topic_core

Updater пересчитывает только свой target. Влияние результата на другие beliefs проходит через обычный Learning pipeline с созданием нового evidence, а не через скрытый каскад обновлений.

Изменение likelihoods требует нового assessment и `revise`: сохранённый raw contribution immutable. Изменение только применимой политики ослабления или общего предела требует пересчёта effective view. Переоценка сохраняет identity исходного evidence и его зависимостей; история прежних оценок и прогнозов остаётся доступной для evaluation.

### Recomputation after consolidation
#topic_core

После удаления исходных [[#^def-EvidenceAssignment|`EvidenceAssignment`]] точность будущего `revise/retract` ограничена гранулярностью сохранённого консолидированного evidence. consolidation не обязана быть обратимой. Она может сознательно обменивать возможность индивидуального пересмотра routine evidence на более компактное representation, если [[Memory#^def-CompactionValidationProgram|`CompactionValidationProgram`]] считает такую потерю допустимой.

---

### Source reliability estimation
#topic_core

(def_id:: entity.SourceReliability)
> [!definition] **SourceReliability** — обычный `PropertyConcept`, описывающий ожидаемую корректность информации источника в данном scope. С ним связывается обучаемая Program оценки этого свойства. ^def-SourceReliability

```text
read_property(source, SourceReliability, domain=Programming)
        ↓
SourceReliability Program
        ↓
value_U + BeliefData
```

#topic_details

В этом примере контракт свойства объявляет `domain` как область оцениваемой надёжности. Program может использовать prior, прошлый опыт, [[Memory#^def-ResultProvenance|provenance]] и semantic relations источника и улучшается через обычную [[Learning system#^def-LearningSystem|Learning System]]. Надёжность в одной области не переносится автоматически в другую.

Для расчёта contribution нужна условная модель сообщений: например, `P(report positive | H, C)` и `P(report positive | ¬H, C)`. Её предоставляет та же программа или связанный модуль, переиспользуемый разными assessments. Общая accuracy источника сама по себе не определяет эти вероятности. Источник, всегда отвечающий «да», не различает `H` и `¬H`, даже если часто прав из-за высокой базовой частоты `H`.

Когда target извлечён из утверждения самого источника, результат «источник утверждает H» задан способом отбора. Частота истинности таких утверждений не позволяет восстановить две условные вероятности без модели отбора. Для обучения нужна явно заданная процедура получения сообщений и пространство ответов; при их отсутствии применяется приблизительная модель полного сообщения с ограниченным влиянием либо сохраняется `unresolved`.

Если модель наблюдений уже учитывает ошибки источника, его reliability не применяется второй раз множителем к тому же contribution. Проверка источника меняет модель assessment и затронутые оценки, а не создаёт ещё одно независимое подтверждение каждого сообщения.

Для нового пользовательского источника начальная презумпция кооперации задаёт оценку корректности `0.75` в объявленном scope. Это эвристика без backing; она не подменяет условную модель ошибок. Принадлежность к системным логам или API также не делает любое содержание безошибочным: подтверждённый факт получения сообщения и истинность его содержания — разные targets.

Знания об источнике хранятся в обычном semantic graph: область компетенции, способ получения сведений, известные ограничения и зависимости. Численные counts и параметры принадлежат состоянию estimator-а. Крупные данные, таблицы моделей и checkpoints могут храниться в [[Core data structures#^def-Artifact|версионируемых артефактах]] со ссылками из графа и provenance.

У каждого набора параметров один владелец записи. Штатное обучение идёт через [[Learning system#PreparedUpdate, UpdateTransactionManager and UpdateDispatcher|общий механизм обновлений]]; кеш в графе и артефакт не накапливают те же counts независимо. Кешированная оценка фиксирует использованную версию состояния.

Оценка выполняется лениво: для редко используемого источника используется общая модель без отдельного состояния. При частом или значимом взаимодействии могут появиться собственные статистики и кеш. Чтение использует готовую модель и не запускает скрытые LLM / research; неизвестный источник обрабатывается по [[#Жизненный цикл assessment|общему fallback]]. Обучение опирается на независимо разрешённые случаи по [[#Обучение модели evidence|тому же протоколу]], что и модель evidence.

`Truthfulness` при необходимости моделируется аналогично отдельным `PropertyConcept`: источник может быть честным, но ненадёжным из-за недостатка знаний.

---
### Updater or Program changes
#topic_details

Если новый updater может использовать сохранённые contributions напрямую:

```text
active EvidenceAssignment[]
→ new updater
→ recomputed belief
```

Если новое правило требует информации, которой в contributions уже нет:

```text
retained source experience
→ повторный assessment
→ новые EvidenceAssignment.
```

Если необходимые исходные данные уже были необратимо удалены, точный пересчёт по новой модели невозможен. Система использует оставшееся консолидированное evidence с известной гранулярностью либо получает новое evidence.

#topic_details

Таким образом, provenance обеспечивает возможность найти и переоценить основания belief, а степень возможного пересчёта определяется фактически сохранённой детализацией памяти.

---

## World-model integration
#topic_core

### Runtime use of beliefs

#topic_core

Runtime использует текущий [[#^def-Belief|belief]] как один из входов reasoning, planning и control.

Базовый интерфейс отдельного утверждения или значения:

```text
value_U
+ BeliefData {
    Strength,
    Support,
    PriorSupport
  }
```

При необходимости вместе с ним используется вычисляемый [[#^def-EvidenceStats|`EvidenceStats`]].

Для `CompetitionScope` вместо независимых belief-записей alternatives используется один вычисляемый [[#^def-Profile|`Profile`]], а не только наиболее вероятная alternative.

Высокий `Support` не устраняет неопределённость между альтернативами:

```text
Profile:
A = 0.5
B = 0.5

Support = high
```

означает, что накоплено много discriminative evidence, но оно не даёт достаточного преимущества одной alternative над другой. Высокий `Support` сам по себе не является основанием выбрать одну из них.

#topic_details

Если `value_U` является числовой или распределительной структурой, runtime использует необходимые для задачи представления, например:

```text
point estimate;
interval;
mean / variance;
quantile;
P(value_U ∈ range).
```

Они вычисляются из `value_U` соответствующей Program и не являются дополнительными полями `BeliefData`.

`Strength` / `Profile` выражают текущую степень belief и могут непосредственно использоваться для prediction и expected-value reasoning. Они не являются самостоятельной мерой того, насколько belief подкреплён evidence.

[[#^def-BeliefData|`BeliefData`]], `Profile`, `EvidenceStats`, характеристики `value_U`, [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] и другие релевантные сигналы могут использоваться управляющими механизмами при вычислении `attention_priority`, [[Self#Исследование|локальном выборе исследования]] и определении commitment.

Для решений, где существенно качество основания belief, управляющая Program должна учитывать не только `Strength` / `Profile`, но при необходимости также `Support`, `PriorSupport`, `EvidenceStats`, entropy и стоимость ошибки.


---

### Beliefs across abstraction levels
#topic_core

Beliefs могут относиться к разным уровням представления объекта: [[Core data structures#^def-Facet|Facet]], [[Memory#^def-Episode|Episode]], [[Core data structures#^def-Instance|Instance]] и [[Core data structures#^def-Prototype|Prototype]].

```text
Facet / Episode
→ belief о конкретном состоянии или конкретном случае;

Instance
→ belief о конкретном объекте;

Prototype
→ belief о типе / классе объектов.
```

#topic_details

Например:

```text
Facet:
"Игорь сейчас болен"

Instance:
"У Игоря есть хроническое заболевание X"

Prototype:
"Для людей с заболеванием X характерен симптом Y"
```

#topic_core

Для всех уровней `Strength` и `Support` имеют один и тот же смысл:

```text
Strength
→ насколько агент верит утверждению;

Support
→ сколько effective evidence его обосновывает.
```

[[#^def-Evidence|Evidence]] первоначально относится к тому уровню, который оно непосредственно подтверждает.

#topic_details

```text
наблюдение конкретного состояния
→ Facet / Episode belief;

повторяющийся опыт конкретного объекта
→ может стать evidence для Instance belief;

опыт разных объектов одного типа
→ может стать evidence для Prototype belief.
```

Перенос evidence на более общий уровень выполняется через [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]], только если такое обобщение обосновано.

В обратном направлении более общий уровень может использоваться как prior:

```text
Prototype
→ prior для Instance;

Instance
→ prior для конкретного Facet / Episode.
```

Prior не считается собственным evidence дочернего target и не увеличивает его Support. Если prior получен из другого belief, его effective backing возвращается отдельно как PriorSupport. 

Одно исходное evidence также не должно учитываться повторно через несколько уровней. Например, опыт конкретного `Instance`, уже использованный для построения `Prototype`, не должен вернуться к этому же `Instance` через Prototype как независимое подтверждение.

---

### Beliefs across planes
#topic_core

Все плоскости используют одни и те же epistemic representations:

```text
отдельное утверждение / значение
→ value_U + BeliefData;

mutually exclusive + exhaustive alternatives
→ CompetitionScope + Profile.
```

Различается только semantic target. Форма отдельного `value_U` определяется природой моделируемой величины и потребностями соответствующей Program.

#### Attribution Plane
#topic_core

[[#^def-Belief|Belief]] относится к значению свойства объекта или к scope его дискретной шкалы.

```text
Igor.HealthStatus
→ Profile {Healthy: ..., Sick: ..., Recovering: ...};

MyCar.Speed = 112 km/h
→ BeliefData.
```

Взаимоисключающие и исчерпывающие values используют общий [[#^def-Profile|`Profile`]]; отдельное `value_U` использует [[#^def-BeliefData|`BeliefData`]].

#### Semantics Plane
#topic_core

[[#^def-Belief|Belief]] относится к semantic relation fact.

```text
PART_WHOLE(Wheel, Car)
CAUSES_UNDER(Infection, Death, NoTreatment)
```

`Strength` означает уверенность агента в самой связи.

Если relation содержит величину, например коэффициент наследования или силу эффекта, эта величина является частью `value_U` или параметров relation, а не `Strength`.

#### Process Plane
#topic_core

[[#^def-Belief|Belief]] относится к утверждению о состоянии, переходе, условии, причине или модели процесса.

Например:

```text
"FuelPresent является CONDITION запуска двигателя"

"Rain является причиной WetRoad в данном случае"
```

Нужно отличать belief от параметров самой модели:

```text
transition probability;
OutcomeProfile;
effect magnitude;
expected signal
→ значения модели;

BeliefData
→ насколько агент уверен,
  что соответствующая модель или оценка корректна.
```

`Program` с `model ∈ Program.roles` сама является проверяемой моделью процесса. Аналогичный принцип применяется к семантически значимым `OperatorConcept`, `TRIGGER` и `CONDITION`.

#### Association Plane
#topic_core

Activation, co-activation и associative weights описывают динамику распространения активности и сами по себе не являются beliefs.

[[#^def-BeliefData|`BeliefData`]] появляется только если агент превращает обнаруженный ассоциативный паттерн в явное утверждение о мире или своей модели.

---

Один факт может использоваться в нескольких плоскостях без создания нового evidence.

```text
native fact
→ projection / view в другой Plane
→ то же основание belief
```

Новый [[#^def-EvidenceAssignment|`EvidenceAssignment`]] создаётся только когда появляется новое основание или отдельный вывод, который [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] обоснованно назначает соответствующему belief.
