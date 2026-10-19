# Завершение Attribution Plane

Аудит от 19 октября 2026 года, исходная ревизия `6b5b0e6`. Полностью рассмотрен [Attribution Plane](../architecture/Attribution%20Plane.md), включая числовые распределения, обучение, исторические чтения и интерфейс сознания.

**Текущий итог: необходимые механизмы плоскости реализованы и приняты.** На финальной версии прошли 766 fast tests, 159 integration tests, 22 native tests и 11 разных live-сценариев обучения/использования. Четыре native tests пропущены по явным платформенным/opt-in условиям. Точная приёмка, границы доказательства и сохранённая история ошибок приведены ниже.

**В исходной ревизии был реализован фундамент чтения свойств, но отсутствовал замкнутый путь «агент определяет свойство → учится на наблюдениях → применяет качественные понятия к новым объектам».** Главная работа — соединить существующие граф, источники, убеждения, обучение и интерфейс агента. Новая универсальная система машинного обучения для этого не нужна.

Этот план разделяет завершение полезного MVP и последующее расширение до всей архитектуры. «80 процентов кейсов» здесь — гипотеза приоритизации по принципу Парето: статистики реальных обращений к плоскости пока нет. Это не измеренная доля покрытия и не процент готовности кода.

Первоначальный аудит и результаты описательного MVP сохранены как история. Текущий этап начат с `main 4ab5dcf`, где уже объединён общий evidence assessment; он завершает необходимые механизмы плоскости без внедрения отдельного ML framework. Его состояние и приёмка приведены непосредственно ниже. Результаты прежних live-прогонов не считаются проверкой нового кода.

## Текущий этап: качественные нормы и полный путь чтения

К описательному MVP добавлены объявленные качественные свойства, обучаемые квантильные нормы, автоматическая оценка качественного вопроса через общий BeliefStore, typed результаты, Program readers, точное чтение сохранённого backup и общий выбор по свойствам. Реализация использует существующие graph history, sources, evidence assessment и Program execution. Ни отдельного хранилища моделей, ни фиктивных Evaluation/LearningSignal для накопления измерений нет.

| Механизм | Реализованный контракт | Проверка |
| --- | --- | --- |
| Объявления и применимость | `create_property` задаёт scale, source, domain, classes, selection, typed parameters и при необходимости Program/view. Numeric/circular не превращаются в categorical; классы — реальные Concept, domain проверяется через тип и предков. | [Selection](../../tests/component/test_attribution_selection.py), [tools](../../tests/component/test_attribution_tools.py): атомарный отказ неверным определениям, общие class labels требуют согласованного Criterion. |
| Наученная норма | `create_qualitative_property` создаёт одну ordinal Property с `source=norm`, `qualitative_norm` и `norm_state`; `revise_property_norm` меняет объявленный criterion. Данные — полная выборка latest_recorded либо один явно выбранный внешний distribution. | [Norm tests](../../tests/component/test_attribution_norms.py): 8/5/10, полная выборка за preview, frequencies, intervals, условия, породы, малые/вырожденные данные, correction, hysteresis и restore. |
| Качественный Profile | `evidence.pending_properties` готовит конкретные subject/property/state questions; `evidence.record_property` оценивает их источники через общий scope. GraphEvidenceAssessment запускает эту фазу после оценки графа. Read ничего не регистрирует и не оценивает. | [Evidence tests](../../tests/component/test_attribution_evidence.py): источник измерения, domain, повтор, withdrawal, origin reassessment, stale inputs, old meaning, default/explicit time, Facets и JSON restore. |
| Typed/Program sources | `source=result` читает сохранённый семантически связанный scalar/interval/normal/quantiles; `source=program` вызывает объявленный model Program и проверяет subject/property/conditions/time/unit результата. | [Source tests](../../tests/component/test_attribution_sources.py): типы, units, ошибочный результат, временная применимость, async child и computed selection. |
| Исторические чтения | Exact verified backup восстанавливает graph, beliefs, attribution и memory в отдельный runtime. Завершённый Program result читается из execution trace с точными arguments/world time и actual revision/output reference. Отсутствующий trace даёт UNKNOWN; новый запуск текущего кода не подменяет историю. | [Persistence integration](../../tests/integration/test_attribution_persistence.py): реальные backup files, integrity/isolation, worker IPC, child execution/replay и исторический read сохранённого выполнения. |
| Выбор по свойствам | `select_properties` фильтрует явных кандидатов, упорядочивает numeric/ordinal либо ищет numeric/circular nearest; Profile требует explicit alternative и сравнения Strength. Unknown сохраняются отдельно. | Selection/source tests: nominal без порядка, circular 350°/10°, Profile без implicit argmax, интервалы без вымышленного среднего, единое время всех чтений. |

Приёмочный checkpoint этого этапа — `51f6e0ae2d76372ce70d1cddc3552709d85b0529eb74eff680b639d363376400`. Последующий review и IDE harness описаны ниже отдельно; исходные результаты не переименованы в проверки нового checkpoint.

| Приёмка текущего checkpoint | Фактический итог |
| --- | --- |
| Полный fast suite после всех source/test edits | **766 passed, 2.84 s** |
| Portable integration с настоящим Redis | **159 passed, 173.65 s** |
| Native boundaries | **22 passed, 4 skipped, 43.52 s**; три Windows-only, один external HTTPS opt-in |
| Learned norms: отдельные наблюдения и внешняя таблица | **Оба live cases прошли**, новые acquisitions, restore и использование |
| Descriptive regression | **Все 9 live cases прошли**, новые acquisitions и независимый review 4/4 для каждого |
| Статические проверки | Ruff, format 309 files, Program layout и diff check прошли |

Boundary suites подтвердили одинаковый hash до/после. Их logs, XML и `validation.json` находятся в `/private/tmp/evertree-attribution-final-08`; fast log — `/private/tmp/evertree-attribution-final-fast-08.log`. Связанные наборы отдельно к общим suites не прибавляются.

На одной финальной версии и фактической конфигурации приложения `gpt-6-luna/high` прошли **11 разных live-сценариев**. Первый запуск дал **4 passed, 7 deselected, 516.39 s**: оба learned norm пути, selection и parcels. Второй — **7 passed, 2 deselected, 467.92 s**: остальные descriptive cases. Это два дополняющих запуска с новыми acquisitions, не один общий запуск и не повторное использование старых snapshots. Source hash одинаков до/после каждого case и в текущем коде.

Observation/norm case включает assessed Profiles, JSON restore, новый reader, selection/interpretation, независимый review и correction с сохранением истории. Table/norm case проверяет условное применение обученной нормы без выдуманных собак. Ранние live helpers принудительно использовали ту же модель с effort `medium`; теперь они используют настройки приложения и сохраняют explicit override запроса. Более ранние результаты и ошибки не смешиваются с финальной приёмкой и не переименованы в passes.

### Повторный review и отладка из IDE

Повторный независимый review выявил два дефекта. При выборе последнего сохранённого typed
результата правка описания старого результата могла вернуть устаревшее значение. Теперь
порядок меняет только изменение содержимого `attribution_result`, как для числовых фактов.
Кроме того, неверный числовой фильтр мог запустить вычисляющий Program до проверки своего
значения. Проверка перенесена перед вычислениями. Регрессии проверяют обе политики выбора
(`latest` и `max_support`) и отсутствие Program calls при неверных аргументах.

Существенного неоправданного усложнения в проверенных механизмах не обнаружено; отдельный
framework или перестройка существующих слоёв не потребовались. В новом
[`debug_attribution.py`](../../src/evertree/debug_attribution.py) переиспользованы debug session,
KnowledgeIntegration, EvidenceAssessment и публичные semantic tools. Три отдельных сообщения
про собак 8/5/10 kg проходят интеграцию и assessment, затем вопрос запускает обнаружение или
обучение нормы; после assessment новый read-only вызов отвечает из сохранённых данных.
Редактируются только `OBSERVATIONS` и `QUESTION`; IDs, пороги и ожидаемые ответы не зашиты.
Состояния каждого этапа и вызовы сохраняются для IDE. Планировщик, worker transport и restart
этот harness не моделирует.

После этих исправлений и добавления harness прошли **773 fast tests**, связанные
**109 component** и **3 integration** tests (связанные component уже входят в полный fast
набор), Ruff, format и Program layout. Настоящий запуск IDE-сценария на checkpoint
`2cffe16f214d26abc8be051817bdcf3242eca8bb98b78930d9a50664c0f15481`
также прошёл: три отдельных наблюдения, mean=23/3 kg, learned boundaries=7 и 26/3 kg,
оценённые Profiles и условный ответ 7 kg → Small. Последнее чтение не изменило graph,
beliefs или attribution; гипотетическая четвёртая собака не создана. Артефакты находятся
в `tmp/debug-attribution/ide-review-20261019/`, проверки — в `smoke-check.json`.

### Наблюдение → обученная норма → использование

1. Отдельные сообщения сохраняют числовые факты 8, 5 и 10 kg с исходными источниками. `summarize_property` сразу даёт `23/3 kg`; никакой нормы для этого не требуется.
2. На естественный вопрос «кого из них по весу можно назвать маленькой, средней и большой собакой?» агент объявляет относительные Small/Medium/Large. Пользователь не передаёт IDs и не вызывает train. Одна качественная Property связывает эти классы, numeric BodyMass, domain и conditions. Это не универсальный размер, высота в холке или медицинский стандарт.
3. Простая модель по умолчанию — weighted quantiles с линейной интерполяцией порядковых статистик; для трёх классов точки 1/3 и 2/3 дают границы **7 и 26/3 kg**. Граница включена в нижний класс: 7 kg условно Small, 8 kg Medium, 10 kg Large. Минимум три sample — техническое условие построения, а не доказательство репрезентативности. Одинаковые границы дают `degenerate`, недостаток данных — `needs_data`.
4. Checkpoint сохраняет criterion semantic revision, fit revision, data revision, границы и их точность, sample count, rows и pinned graph dependencies. Изменение данных делает старый текущий fit недоступным до refresh вне read. KnowledgeIntegration обновляет существующие нормы после записи; небольшой сдвиг удерживается объявленным hysteresis. Старые версии остаются в graph history/backup. Исправление 8→9 kg даёт новые границы 23/3 и 28/3 без создания четвёртой собаки.
5. Общий GraphEvidenceAssessment отдельно оценивает применимость нормы по её фактическим источникам и качественную категорию конкретной собаки. В categorical scope голосуют первичные источники её измерения; остальные training sources объясняют criterion, но не становятся независимыми голосами за эту собаку. Dependency roots, origin reliability и withdrawal используют существующий belief pipeline. Sample count не становится Support; belief нормы не копируется на объект и не перемножается с confidence измерения.
6. `read_property` возвращает общий Profile и provenance только пока fingerprint оценки соответствует norm revision, измерению и текущим BeliefReadings всех training dependencies, включая другой объект или внешний distribution. Canonical question включает identity subject/property/criterion/conditions и выбранные state identities, а не буквально каждый timestamp; два момента одного Facet и чтение через Instance либо тот же Facet используют один вопрос. Новый Facet или изменённый смысл criterion — другой вопрос. Значения имён/описаний class Concepts закреплены в checkpoint: их изменение требует refresh и нового semantic target, без наследования старого prior. Повторное чтение неизменно; `point_policy=argmax` по явному запросу добавляет point view только при единственном победителе.
7. Гипотетический вопрос «а 7 kg?» идёт через `interpret_property`: условный класс, границы, версия нормы и отдельная оценка её применимости. Запрос не создаёт собаку, измерение или epistemic Profile. Реальный новый объект получает Profile после сохранения источника измерения и обычной оценки evidence.

Сохранённый Profile — результат существующей модели оценки evidence, а не доказанная эмпирическая калибровка вероятностей. Приёмочные tests с контролируемыми likelihoods проверяют общий updater, а live-проверка — реальный путь моделей и источников. Для supervised нормы нужны настоящие labels/outcomes и существующий Learning pipeline; эмпирические квантили таких labels не требуют.

В live-проверке класс пограничного гипотетического значения определяется фактически сохранёнными quantiles и точными boundaries. Если модель явно задала округлённые quantiles, отображение первой границы как «примерно 7» не делает её ровно 7. Отдельный component test проверяет точный default Criterion: 7 kg относится к Small. Live assertion не подменяет выбранный Criterion воображаемым точным значением.

Live norm harness дополнен независимым semantic review после строгих runtime checks: область сравнения, условность confidence, смысл газетного сообщения и гипотетического 7 kg. Reviewer получает только синтетические исходные сообщения, фактический ответ, краткие сведения о норме и Profile strengths, без полного graph/memory/transcript. Проверка не требует особых слов и не трактует unassessed как ненадёжность. В полном observation/norm case прогона 08 все четыре критерия прошли; это проверка конкретного выполненного пути, не оценка частоты ошибок модели.

Начальный learned mapper обучается по объявленному numeric source и source-backed distributions. Произвольные Program/result outputs доступны для чтения и выбора, но не вызываются автоматически ради формирования обучающей популяции. Такое расширение потребует явных sampling semantics, а не скрытого запуска всех вычислений при read.

Assessment context использует полный набор dependencies для freshness. Модели показываются до 20 training belief records и до 20 текстов norm-context sources, с полными totals; все actual measurement sources конкретного вопроса сохраняются. Оценённые inputs с меньшим Strength приоритетно попадают в preview вместе с их источниками, даже если они стояли за первыми 20. Это порядок показа, а не новые веса обучения и не синтетическая агрегированная confidence.

Одна автоматическая assessment phase обрабатывает не более 20 pending качественных вопросов. Остальные unassessed или stale объекты сохраняют UNKNOWN до следующей фазы; read не запускает дооценку. Этот предел работы за один вызов не обрезает данные fit или fingerprint freshness.

### Приёмочная матрица текущего этапа

| Сценарий | Проверяемый результат | Статус |
| --- | --- | --- |
| N01: 8/5/10 и удержанное значение 7 | Среднее 23/3; границы 7 и 26/3; условное 7 не увеличивает count; Profile конкретных объектов появляется только после evidence assessment. | Component pass; полный live observation/norm case 08 pass, включая независимый review. |
| N02: correction и обновление | 8→9 сохраняет число объектов, новый fit, тот же semantic criterion; stale assessment не принимается; старый checkpoint воспроизводится. | Component pass; correction/reassessment/history в live case 08 pass. |
| N03: count, повторы и источники | Training samples не превращаются в независимые class votes; одна primary source не усиливается от повторного чтения; её dependency root переиспользуется. Изменение belief другого sample/reference делает Profile stale даже за пределами preview; слабый оценённый input виден модели. | Component pass. |
| N04: withdrawal/reliability | Withdrawal или переоценка origin инвалидирует прошлый Profile; полная новая оценка может вернуть prior с evidence_count=0. | Component pass. |
| N05: scope/time/meaning | Породная норма не оценивает другую породу; conditions совпадают точно; default/explicit/describe и Instance/Facet views одного состояния согласованы. Другие Facets и изменённое описание класса создают отдельный смысловой вопрос. | Component pass. |
| N06: interval/weighted/sparse | Частоты влияют на fit как частоты; interval bounds и возможные классы сохраняют неточность; sparse/degenerate не выдумывают разделение. | Component pass. |
| N07: typed computation | Scalar, interval, normal и quantiles сохраняют unit/semantics; wrong binding/type отвергается; model child не материализует read. | Component и worker IPC/replay integration pass. |
| N08: exact backup и unknown | Проверенный snapshot и точный completed ProgramRun читаются без current fallback и мутаций live stores; отсутствующий/повреждённый snapshot, trace или несовпавшее world time даёт UNKNOWN. Более новый UNKNOWN не воскрешает старый estimate. | Backup/worker integration pass; сохранённые categorical results также сохраняют shared Profile. |
| N09: property selection | Numeric/ordinal order, circular distance, explicit Profile threshold, unknown isolation, computed source bridge. | Component pass; Profile alternative-strength ranking через actual `select_properties` в live case 08 pass. |
| N10: внешняя таблица → норма | Частоты 3×1/6×3/9×4/12×2 обучают norm с count=10 и boundaries 6/9; после restore гипотетические 7 kg дают условный Medium. Анонимные строки не создают собак или индивидуальных Profiles. | Component pass; полный table/norm live case 08 pass. |

### История проверок и исправлений текущего этапа

До последних исправлений freshness, class meanings и temporal/relation contracts полный fast suite дал **725 passed**, portable integration — **159 passed**, native — **22 passed, 4 skipped**; Ruff, format и Program layout прошли. Это промежуточный checkpoint, а не финальная проверка последующего кода.

Четыре live-регрессии описательного пути — отдельные 8/5/10, справочник, frequency table и посылки — прошли вместе: **4 passed, 216.85 s**. Все case artifacts в `/private/tmp/evertree-attribution-regression-live-01/test_model_learns_attribution_{0..3}/attribution-learning.json` фиксируют неизменный production hash `8c95acf7ae5d25263d8ffadd4b823d13e13d456c8129acfdaf113b09770a9cda`. Это положительная регрессия существующих возможностей до последних исправлений, не доказательство нового качественного Profile.

Первый запуск нового norm harness (`/private/tmp/evertree-attribution-norm-live-01/.../attribution-norm-learning.json`) остановился при initial assessment с `unexpected_model`: helper не принимал структурированный model request этой фазы. Во втором запуске норма не появилась: естественный вопрос ошибочно отправлялся только в KnowledgeIntegration вместо выполнения сознанием. Это не проверяло intended task path. Harness исправлен: первые три рассказа идут через реальный KI, вопрос — через production conscious step с обычными semantic tools, анализом, интеграцией и evidence assessment.

Третий norm run обнаружил настоящий дефект production boundary: callback из SDK reader thread терял execution owner/semantic scope, и `graph.search` внутри conscious step отклонялся. Исправление переносит копию invocation context в каждый callback; проверка через реальный CodexProvider и отдельный SDK-style thread воспроизводит прежний отказ и подтверждает исправление, сохраняя запрет чужой записи. Связанный набор дал 64 passed, executor integration — 11 passed. Первые три failures сохранены.

Norm run 04 завершился failure примерно за 222 s: модель добавила в норму `comparison_group`, хотя исходные измерения имеют пустые conditions. Runtime корректно вернул count=0 при несовпадающих условиях; usable norm/Profile не получены. Это ошибка выбора и сохранения критерия, не ошибка подсчёта. Дополнительный audit обнаружил отсутствие `interpret_property`, `select_properties` и explicit point policy в conscious tool surface, хотя Program tools уже предоставляли их. Следующий checkpoint исправляет этот разрыв API и уточняет, что условия измерения нельзя выдумывать ради названия группы сравнения.

Norm run 05 завершился failure примерно за 119 s без сохранённой нормы: KnowledgeIntegration передавал старые source refs вне текущего supplied experience. Guard правильно отклонял такую запись, хотя текущий retained analysis уже содержал нужную ancestry. Следующее узкое исправление объясняет использование допустимой текущей ссылки и делает сообщение об отказе actionable, не расширяя доступ к произвольным источникам. Положительного live результата learned norm/Profile на этом этапе ещё нет.

Norm run 07 на `d0b0…6766` завершился **2 failed, 219.98 s**. Первый case создал ready norm с count=3 и boundaries около 7 и 26/3, используя округлённые quantiles. Затем SDK event для `record_analysis` содержал невалидный source path: trace recorder попытался разрешить его до callback и упал, поэтому assessment/restore не были достигнуты. Исправление сохраняет невалидированное SDK event как opaque JSON с диагностикой и разрешает только валидные зависимости; настоящий callback по-прежнему отклоняет неверный note и допускает исправленный повтор. Новый regression использует настоящий application handler и отдельный SDK-style thread. Во втором case frequency distribution с count=10 была сохранена правильно, но предложенные сознанием середины 7.5/10.5 были ошибочно записаны как bands вместо learned norm. Уточнён контракт: явные cutoffs источника — bands, frequencies — distribution, относительные категории из распределения — qualitative Property со ссылкой на него; аналитическое предложение не превращается в исходное справочное правило. Артефакты сохранены в `/private/tmp/evertree-attribution-norm-live-07`.

Первый case прогона 08 прошёл на неизменном `51f6…6400` и фактической конфигурации `gpt-6-luna/high`: три наблюдения, conscious создание нормы, автоматический assessment, JSON restore, новый reader с `read_property`/`select_properties`/`interpret_property`, независимый review 4/4 и correction 8→9 с reassessment и сохранённой историей. Победитель каждого Profile имеет Strength=0.6; это оценка evidence, не доказанная калибровка. Гипотетические 7 kg дали условный Small по сохранённому default criterion и не добавили наблюдение. Артефакт: `/private/tmp/evertree-attribution-live-08/test_real_model_learns_relativ0/attribution-norm-learning.json`.

Второй case 08 также прошёл: natural acquisition внешней таблицы, conscious создание qualitative Property со ссылкой на сохранённый distribution, count=10 и boundaries 6/9, JSON restore и новый `interpret_property(7 kg)` → Medium. Индивидуальные собаки не созданы, чтение не меняет stores. Артефакт: `/private/tmp/evertree-attribution-live-08/test_real_model_learns_frequen0/attribution-table-norm-learning.json`.

Третий case 08, descriptive selection, прошёл: один typed guide сохранён и прочитан, exact endpoint flags соответствуют источнику, три собаки получили правильные категории, Туман без массы сохранил unknown. Mean=50/3 kg, большая и ближайшая к 25 kg собака — Гром. Все четыре semantic review criteria прошли. Артефакт: `/private/tmp/evertree-attribution-live-08/test_model_learns_attribution_0/attribution-learning.json`. Четвёртый case, посылки со смешанными units и условной категорией 750 g, также прошёл hard assertions и review. Это новые acquisitions после прежних failures, не пересмотр старых артефактов. Итог прогона 08: **4 passed, 7 deselected, 516.39 s**; XML и log — `/private/tmp/evertree-attribution-live-08.xml` и соседний `.log`.

Дополняющий descriptive-final-08 дал **7 passed, 2 deselected, 467.92 s**: отдельные наблюдения, справочник, frequency table, повтор/исправление записи, конфликтующие справочники, интервальная статистика и породная область. Все hard assertions и четыре semantic review criteria каждого case прошли. Для 7 kg общее правило дало Small, Chihuahua rule — Large, применение последнего к Labrador сохранило unknown. Source hash start/end/current равен финальному `51f6…6400`. Артефакты находятся в `/private/tmp/evertree-attribution-descriptive-final-08`, XML и log — в соседних `.xml`/`.log`. Вместе с предыдущим запуском это 9 descriptive и 2 learned norm cases, все на одной версии и `gpt-6-luna/high`.

Пять остальных descriptive live-сценариев на hash `408c1e3891a91a658dc529e03b36b5342a54fbab09d73eea24ed954922bef413` завершились с тремя passes (correction, conflicting guides, breeds) и двумя failures. Interval case правильно сохранил данные, посчитал 7.6 и [6.6,8.6], указал категорию `unknown`, но oracle запрещал даже explicit unknown. Он уточнён: пустой список либо unknown допустимы, выдуманный класс отвергается; сохранённый ответ проходит уточнённые offline hard checks и negative control. Исходный pytest failure сохранён. Дополнительный внешний review старого ответа не запускался; новый полный descriptive run проверяет acquisition, использование и обычный semantic review заново.

В selection case найден реальный дефект приобретения правила: источник говорит «до 10 включительно», а модель сохранила `boundary_inclusive=[false,true]`. Категории 7/15/28 и ближайшая к 25 собака были верны, однако ровно 10 kg ошибочно относились бы к Medium. Прежние hard checks проверяли только внутренние точки и пропустили ошибку. Теперь все inclusive guide fixtures проверяют точные boundaries и flags в сохранённом правиле и runtime report; компонентные negative controls отвергают неверную включительность. Уточнены инструкции приобретения и проверки каждой границы; исправление подтверждено новым live acquisition 08. Отдельное замечание reviewer к фразе «неоценённые по надёжности» не отменяет этого дефекта: unassessed означает отсутствие оценки, а не ненадёжность. Исходный прогон не считается успешным по правильной прозе или после изменения rubric.

Попытка полного descriptive run в `/private/tmp/evertree-attribution-descriptive-live-final` на hash `0f70b0136cd57ea00eaa33a19badf9ba64422c621e6ce9290508403d3e8753da` остановлена после двух успешных cases и failure frequency table. В третьем case приобретение, restore, provenance и runtime верны: count=10, mean=8.1, для 7 kg четыре значения ниже и шесть выше. Проза также верна, но structured comparison fields равны null/null вместо 6/4. Test descriptions двусмысленно говорили «known dogs», хотя вопрос касается внешней frequency population; они уточнены без изменения ожидаемых чисел или assertions. Это failure structured ответа при двусмысленном тестовом контракте, не runtime failure и не pass; reviewer не запускался. Четвёртый acquisition прерван, его private Redis namespace очищен. Все исходные артефакты сохранены; новый suite проверяет эти случаи заново.

Descriptive live 06 на hash `b1b6…5b58` завершился **5 passed, 4 failures, 714.60 s**. Прошли отдельные наблюдения, справочник, frequency table, correction и conflicting guides. Последние четыре остановлены в acquisition первого сообщения, до usage/reviewer. Interval case выполнил семь tools за примерно 13 s, затем 107.851 s не было новых tool events до лимита 120 s; причина паузы не установлена. Breed case не вызвал tools и получил SDK `workspace routing discovery timed out` после 97.378 s. Selection и parcels также не вызвали tools: routing discovery/reconnect завершились timeout. Эти остановки не считаются успешной проверкой, но не доказывают дефект числового runtime или необходимость увеличить лимит для полезной работы. Artifacts `_0…_8` и `timeout-diagnostics.json` сохранены в `/private/tmp/evertree-attribution-descriptive-live-06`; четыре private Redis namespaces проверены пустыми.

В descriptive 07 на `d0b0…6766` interval и breed прошли. Selection выявил новое приобретение без typed numeric reference: справочник сохранён только описанием plain Concept. Вызовы `interpret_property` для числового свойства вернули UNKNOWN, но reader всё равно выдал категории в прозе и structured ответе. Числовые count=3, mean=50/3 и nearest к 25 kg были правильны; это не закрывает отсутствие применимого сохранённого правила. Parcel case прошёл все hard assertions, но reviewer отверг обычные слова «измеренные посылки» и «измерения имеют статус unassessed» как усиление источника. Это привело к уточнению общего rubric ниже и новому acquisition/review 08; исходный pytest failure не переименован в pass. Артефакты и `selection-and-parcel-failure-audit.json` сохранены в `/private/tmp/evertree-attribution-descriptive-live-07`.

Перед новым повтором ordinary и extended reviews используют единый source-meaning criterion: слова «измерение» и unassessed сами по себе не заявляют личную проверку или ненадёжность. Явные неподдержанные утверждения по-прежнему недопустимы. Selection oracle также уточнён: он требует ровно четыре собаки в Dog/subtype domain, не запрещая отдельный Instance приюта. Три component controls проверяют допустимый Shelter и недопустимую лишнюю собаку; весь bridge набор дал 18 passed. Это изменения точности приёмки, без пересмотра исходных failures или повторного review старых ответов.

Финальный portable integration повтор сначала использовал неверный локальный Redis endpoint из окружения запуска и получил connection refused. После загрузки конфигурации реального test Redis полный suite прошёл: 159 tests. Это исправление конфигурации запуска, без изменения production кода; исходный ошибочный запуск сохранён отдельно.

Один native прогон завис на demo task из-за отсутствующего managed Git object при `evaluate_candidate`; attribution в ошибке не участвовала. Диагностика сохранена в `/private/tmp/evertree-native-hang-99566.json`; этот запуск не назван успешным. Полный повтор дал указанные выше 22 passed/4 skipped.

## Итог описательного MVP до текущего этапа

Реализован описательный числовой MVP: агент приобретает отдельные измерения, справочные границы и таблицы частот; новые запросы считают статистику, применяют выбранный справочник и находят ближайший известный объект. Источники, условия, единицы и BeliefData сохраняются. Чтение не обучает модель и не меняет stores; условная метка не выдаётся за уверенность в действительной категории объекта.

Последний offline suite: **634 passed**. Все **156 различных portable integration cases** прошли через полный запуск и целевые повторы; native transport test также прошёл. Для исходных трёх и шести расширенных live-сценариев есть положительные evidence приобретения и использования через настоящий Redis Search, embeddings и отдельный reader после serialized restore. Это результаты нескольких запусков и checkpoints, включая явно отмеченные usage-only повторы; не один чистый suite на последней версии и не измеренные 80% реальных обращений. Ошибки модели, инфраструктуры и проверки сохранены ниже. Финальная проверка отдельных наблюдений включает успешные hard assertions и повтор независимого review того же ответа после уточнения rubric, с отрицательным контролем; первоначальный pytest failure не переименован в pass.

На этом checkpoint ещё отсутствовали canonical qualitative/Profile contracts, наученные версионированные нормы, typed Program readers, точное восстановление и общий выбор по свойствам. Их реализация относится к текущему этапу выше; старые результаты не доказывают новые возможности.

## Что уже работает в исходной ревизии

| Область | Состояние и основание | Практический предел |
| --- | --- | --- |
| Шкалы и чтения | `PropertyDefinition`, `PropertyReading`, numeric/nominal/ordinal/circular в [attribution.py](../../src/evertree/core/attribution.py), строки 19–70 | Контракты описывают основу; `belief_data=None` разрешён, параметры задаются только именами, единица отсутствует в самом чтении. |
| Числовые факты | `HAS_NUMERIC_VALUE` читается с сохранением исходного fact ID; строки 300–310, 360–364 | Единица проверяется точным равенством; преобразования единиц нет. Автоматически найденное числовое свойство не получает unit из факта. |
| Классификация | Читаются `CLASSIFIED_AS` из объявленного набора классов; строки 311–318 | Нет полноценной проверки Criterion и его области применения. Качественная метка не подменяет отсутствующее число. |
| Конкурирующие значения | `bind_scope` и чтение общего `Profile`, включая prior без наблюдений; строки 187–199, 280–298 | Scope и binding создаются вручную через Python. Обычный интерфейс агента этот цикл не открывает. |
| Свойства из отношений | Чтение через общий relation view, без копии исходной связи; строки 319–333 | Требуется заранее объявленный binding. |
| Состояния во времени | Instance → подходящие Facets, интервалы `[from, until)`, сохранение неизвестной применимости; строки 267–298 | Это не готовая реконструкция состояния всего приложения из backup. |
| Алгебра шкал | Числовое и порядковое сравнение, числовая и круговая дистанция; строки 395–413 | Нет полного свойства-ориентированного filter/rank/top-k/nearest. Общий graph query не заменяет работу с Profile и порядковой шкалой. |
| Обнаружение свойств | Факты, scopes, domains и наследование типов; [attribution.py](../../src/evertree/core/attribution.py), строки 136–179; [reading.py](../../src/evertree/core/semantics/reading.py), строки 65–116 | `describe` не запускает Programs и правильно сообщает о параметрах/вычислениях. Карточке не хватает scale/unit/classes для интерпретации значения. |
| Определения в графе | `properties.attribution` валидируется атомарно; [store.py](../../src/evertree/core/graph/store.py), строки 271–299 | Это пока PropertyDefinition, без полного criterion/norm/model lifecycle. |
| Нормализация | Статические bands либо z-score; [attribution.py](../../src/evertree/core/attribution.py), строки 74–93, 415–449 | Границы задаются вручную. Результат — метка или число, а не обученный qualitative Profile. |
| Сохранение | Definitions, bindings и rules входят в snapshot; [persistence.py](../../src/evertree/_application/persistence.py), строки 146–162, 193–195 | Сохранение данных не подключает отсутствующие вычислительный и исторический readers. |
| Общая база обучения и убеждений | [beliefs.py](../../src/evertree/core/beliefs.py), [learning/state.py](../../src/evertree/core/learning/state.py), [learning/updates.py](../../src/evertree/core/learning/updates.py) | Есть shared Profile, источники, переоценка, mean/categorical/linear estimators, учёт повторов и отмена вкладов. Они пока не соединены с обучением норм свойств. |

## Разрывы, обнаруженные в исходной ревизии

### Агент не может построить нужную семантическую структуру

В [WRITE_TOOLS](../../src/evertree/core/semantics/tools.py) есть создание Concept, Prototype, Instance, Facet, Claim и Relation, но нет объявления Property с типом шкалы и источником. [Компилятор](../../src/evertree/core/semantics/compile.py), строки 78–95, определяет kind по действию; обычный update не позволяет превратить Concept в Property. Числовой факт может породить неявное numeric definition, но таким путём нельзя объявить ordered classes, criterion или программу чтения.

Scope, normalization rule и их связи тоже не доступны для создания через production gateway. [CoreOperations](../../src/evertree/core/operations.py), строки 282–304, предоставляет чтения и статическую нормализацию; assessment неизвестного target создаёт binary target, а не categorical scope. Поэтому тест с ручными `register` и `bind_scope` ещё не доказывает работу агента.

### Нет обучения и применения нормы как единой возможности

Отсутствуют population samples с правилами отбора, обученная версия нормы, quantile mapper, минимальная достаточность данных и управляемое обновление границ. Существующий `NormalizationRule` хранит последнее вручную зарегистрированное правило. Нет связи «качественное свойство → числовое свойство → Criterion → конкретная версия нормы» и её происхождения.

Для взаимоисключающих исчерпывающих классов архитектура требует общий Profile. Текущее `normalize` возвращает отдельную метку с `rule.belief_data`. Уверенность в норме не является уверенностью в классификации конкретной собаки: различаются target, входное измерение и условия применения.

### Вычисляемые и исторические чтения не подключены к приложению

`program_reader` и `historical_loader` — рабочие точки расширения, используемые в тестах. Production создаёт AttributionRuntime без них ([persistence.py](../../src/evertree/_application/persistence.py), строка 36). Нет законченного binding на совместимый Program и typed result; объявленное `source="program"` в обычном приложении возвращает unknown.

`reconstruct_property` проверяет точный момент snapshot, но не загружает завершённый backup самостоятельно. Для завершения этого архитектурного пути нужен доступный read-only loader к точному backup. Он входит в последующие этапы; описательный MVP не требует произвольной исторической реконструкции.

### Не завершены применимость и проверка результата

`applies_to` помогает обнаруживать свойства, но не ограничивает сам вызов чтения. Classification проверяет список классов и совпадение conditions, но не полную совместимость Criterion. Нужны явные domain/context, числовая валидность, единицы, форма результата и происхождение вычисления.

Небольшой запуск реальных объектов в памяти подтвердил три дефекта:

- `register_normalization` падает с `KeyError` для свойства, объявленного только в графе: строка 203 обращается к `_properties`, а не к `definitions()`.
- При bands результат имеет `belief_data=None` и пустые `source_facts`, если уверенность вручную не передана.
- `normalize(NaN, ...)` выбирает последний класс вместо отказа: сравнения со всеми границами ложны.

Неполные контракты `PropertyReading` и unit — отдельная проблема: отсутствие эпистемической оценки допустимо представить явно, но нельзя показывать его как установленное знание или выдумывать численную уверенность.

## Минимальный дизайн: три естественных пути приобретения знания

Первый MVP должен работать после обычного сообщения пользователя, без отдельной команды «обучи норму». Агент сохраняет полезные измерения, справочные правила и числовые таблицы через KnowledgeIntegration; следующие запросы сразу используют сохранённые сведения. Обучение в этом объёме означает приобретение и повторное использование источников, а не обязательную оптимизацию параметров модели.

Различаются три пути:

1. **Отдельные наблюдения:** рассказы о разных собаках становятся числовыми фактами этих объектов. Эмпирическая сводка по известным объектам вычисляется при запросе.
2. **Справочное правило:** заданные источником границы сохраняются как критерий. Интерпретация числа отвечает «по этому справочнику», не выдавая правило за выученное на локальных наблюдениях.
3. **Статистический источник:** таблица значений и частот либо интервальная гистограмма сохраняется как одно распределение со своей популяцией и источником. Его строки не превращаются в вымышленных собак.

Эти пути используют один числовой property и один инструмент сводки. Не нужны отдельные learning stores, автоматическое обучение quantile mapper на каждой фразе и предварительная публикация frozen norm для простого среднего.

### Определения и источники остаются в графе

`create_property` объявляет numeric property node с `properties.attribution`: каноническая единица, числовой источник и применимость. Измерения сохраняются обычными `HAS_NUMERIC_VALUE`; факты ссылаются на существующие Instance/Facet, а provenance — на исходные рассказы. Новое сообщение о той же собаке не создаёт нового животного. Повторное сохранение исходного факта не делает его независимым наблюдением.

`create_property_reference` сохраняет source-backed concept с проверяемым `properties.numeric_reference`:

```text
property, domain, unit, conditions
reference_kind = bands | distribution
boundaries[], classes[concept IDs]
boundary_inclusive?[]
samples[{lower, upper, count}]
```

Для `bands` используются возрастающие boundaries и упорядоченные classes; для `distribution` — samples. Необязательный `boundary_inclusive` содержит boolean для каждой границы: true относит равное значение к нижнему band, false — к следующему. По умолчанию все верхние границы включительны: `10, 20` означают `≤10`, `(10,20]`, `>20`. Для `[False, True]` те же границы означают `<10`, `[10,20]`, `>20`; нижняя и верхняя границы интерпретации должны показывать это согласованно.

В distribution `lower == upper` означает точное значение с частотой count, `lower < upper` — интервальный bin. Поля, несовместимые с выбранной формой, отвергаются. Числа конечны, частоты положительны; unit, domain и property согласованы. Первый summary поддерживает только numeric property с `source=numeric`; числовая шкала Program/relation-backed свойства не даёт права читать вместо него произвольные numeric facts.

Reference требует явно сохранённого graph-backed declaration с `scale=numeric` и `source=numeric`. Одного `kind=property`, подразумеваемого типа или случайного numeric fact недостаточно для создания пригодного справочника. Некорректный новый reference либо изменение его зависимости отвергается атомарно.

Conditions сравниваются по точному структурированному значению: JSON arrays совпадают с их сохранённым frozen представлением, порядок keys объекта несущественен, boolean не приравнивается к 0/1. Это не автоматическая интерпретация массива как диапазона. Пустые и зарезервированные имена условий, конфликтующие с аргументами read API, отвергаются при сохранении и чтении.

Это обычные графовые записи с существующими GraphDelta, atomic validation, history, sources и backup. Отдельный изменяемый реестр их копий не нужен. Для correction обновляется соответствующая запись с историей и источниками. Повтор той же таблицы переиспользует запись; если независимость двух источников не установлена, они остаются разными reference records и не складываются.

Данные по породам нельзя автоматически считать измерениями отдельных собак. Средние значения пород без численности — не samples с count=1; такой источник остаётся описательным знанием, пока не задан корректный статистический смысл. Частоты собак и число источников тоже не взаимозаменяемы.

### Один read-only инструмент `summarize_property`

Инструмент получает property, domain и при необходимости число с единицей для интерпретации; явный выбор reference позволяет обратиться к конкретному справочнику или распределению:

```text
summarize_property(domain, property, value?, unit?, reference?, at?, parameters?)
```

Без `at` выбирается последнее сохранённое измерение каждого индивидуального объекта: `time_basis=latest_recorded`. Исторический рассказ или Facet с неизвестной границей могут участвовать именно как сообщённые наблюдения; исходные временные границы сохраняются в результате. Это не сводка текущего состояния популяции. Явный `at` требует применимости состояния в этот момент и исключает неизвестную временную применимость. Обычный `read_property` по умолчанию по-прежнему читает на now.

Режим latest_recorded явно выбирает последнее сохранённое измерение. С явным `at` действует объявленная selection policy свойства: latest, max_support либо unique. При unique несколько применимых кандидатов не превращаются в одно измерение посредством скрытого выбора последнего.

Для recency учитывается последнее содержательное изменение fact: его arguments, relation type или conditions. Исправление числового значения становится последней записью, даже если identity fact создана раньше другого измерения. Редактирование имени/описания либо другой metadata само по себе не делает старое измерение новым. Обычный `read_property` использует тот же порядок при latest и при равном support.

Результат различает:

- эмпирическую сводку по известным подходящим индивидуальным объектам, с числом включённых субъектов, единицей и источниками;
- отдельные применимые справочные правила и внешние распределения;
- условное сравнение заданного числа с явно названной выборкой либо интерпретацию по явно названному правилу;
- отсутствие данных, несовместимые условия, неполноту выборки и невозможность точного расчёта.

Конкретные поля результата:

| Поле | Смысл |
| --- | --- |
| `observations` | Локальная выборка `basis=reported_individuals`: count, mean, median, min/max, source-backed items и отдельная оценка применимости к популяции. |
| `observations.comparison` | Переданное value, `difference_from_mean`, число записанных значений ниже/выше value и число совпадающих либо пересекающих его интервалов. |
| `observations.nearest` | При переданном value и непустой выборке: `distance`, ближайшие `items[{subject,name,value}]` и `items_total`; иначе null. Значения и абсолютная дистанция выражены в unit отчёта. |
| `references` | Только подходящие reference records, каждый с собственными источником и оценкой; distribution содержит `summary`, bands — границы с `boundary_inclusive` и при запросе `interpretation.kind=conditional_rule_result`. |
| `reference_candidates` | Существующие записи этого свойства с другой популяцией (`different_population`) либо несовпадающими условиями (`needs_matching_parameters`). Они обнаружены, но не применены. |
| `excluded` | Исключённые факты с причинами, например неприменимое время или несовместимая единица. |
| `time_basis`, `at`, `conditions`, `unit` | Временной режим, условия и каноническая единица расчёта. `interpretation_status=conditional_on_reported_sources` сохраняет условный смысл результата. |

`observations.items`, `references`, `reference_candidates` и `excluded` возвращают preview максимум из 20 записей с соответствующим `*_total`. Статистика использует всю подходящую выборку, а не только первые 20 items. У bands показываются максимум 20 boundaries и 21 class с `bands_total`; интерпретация использует полное правило. Preview не доказывает отсутствие других записей: конкретный reference можно выбрать по ID/имени, исходные объекты — исследовать через существующие query/walk. Параметр `reference` выбирает внешний источник, но не подмешивает его в локальную выборку.

В `describe` вложенный `properties.numeric_reference` тоже ограничен: `samples`, `boundaries` и `boundary_inclusive` — 20 элементов, `classes` — 21. Только усечённые массивы получают `<field>_total`; `truncated=true` и `details` объясняют, что полный reference доступен через `query` с `fields=["properties"]`. Эта проекция не меняет сохранённый источник и не обрезает PropertyDefinition.

Диапазон выбранного класса возвращается как числовые `lower_bound`/`upper_bound` и boolean `lower_inclusive`/`upper_inclusive`; у отсутствующей бесконечной границы соответствующие поля равны null. Названия полей не должны приписывать всем нижним границам исключительность.

Числовой nearest вычисляется по всем включённым observations, даже за пределами первого preview. Возвращаются все равные минимумы в стабильном порядке subject ID, preview ограничен 20 с полным `items_total`. Анонимные aggregate rows и unknown observations не становятся кандидатами. Для ненулевых расстояний допустима только абсолютная погрешность округления в два ULP для входа и сравниваемых значений; это не процентная близость и не fuzzy membership. Нулевой минимум требует точного совпадения числа. Например, 1.1 kg и 1300 g равноудалены от 1.2 kg, а для 7/15/28 kg ближайшее к 25 kg — 28 kg с distance=3. Результат остаётся условным на сообщённых значениях и не создаёт убеждения о действительном весе.

Для индивидуальной выборки используется не более одного выбранного измерения свойства на объект в объявленном временном режиме. Повторы, парафразы и сто взвешиваний одной собаки не получают вес ста животных. Несовместимые или неоднозначные чтения не усредняются молча; пропущенные объекты и причины должны оставаться понятны. Unknown не считается нулём.

Внешние reference records не подмешиваются в локальную выборку. При нескольких справочниках ответ сохраняет их отдельность; противоречащие bands не объединяются в одно правило. Разные популяции, условия, породы и потенциально пересекающиеся источники не объединяются без явного обоснования. Неизвестная единица не превращается в kg; разрешённое преобразование единиц сохраняет исходный источник.

Для известных единиц поддерживаются только явные символьные aliases: `кг/г/мг` → `kg/g/mg`, `м/см/мм/км` → `m/cm/mm/km`, `с/мс/мкс` → `s/ms/us`, `µs` и `μs` → `us`. Это не parser словесных или составных единиц. Ordinary read и summary используют одинаковое преобразование; исходная запись unit в graph и её provenance сохраняются.

Новый факт автоматически участвует в следующей подходящей сводке. Это вычисление по текущему графу, а не mutation во время чтения: `summarize_property` не пишет facts, targets, assignments, sample buffers или model state. Оно не вызывает LLM и не запускает обучение. Источники и состояние, использованные сохранённым результатом, удерживаются обычным provenance; прежний результат не переопределяется новым наблюдением.

### Описательный результат не подменяет убеждение

Среднее сохранённых чисел — условный факт об этих данных. «По справочнику A значение 7 kg относится к Small» — условное применение правила A. Для этих ответов не требуется придумывать error model бытовому рассказу или превращать арифметику в epistemic Profile.

Результат `summarize_property` — описательная сводка и условная интерпретация, а не новый `PropertyReading` о реальной категории объекта. Число samples, частота, percentile и попадание в band не становятся `Strength`, `Support` или `PriorSupport`. Источники остаются видимы; сохранение утверждения не подтверждает надёжность рассказчика или применимость справочника ко всей популяции.

Исходный `BeliefData` каждого включённого measurement и reference, если он доступен, сохраняется отдельно. Нельзя усреднять Strength или выдавать достоверность отдельного измерения за уверенность в норме. Репрезентативность локальной выборки либо применимость внешней нормы к широкой популяции — отдельный semantic target. Чтение может вернуть его имеющуюся оценку, связанную с конкретными данными, областью и версией; оно не создаёт target или evidence. При отсутствии оценки состояние — unassessed, а не refuted. Default prior не показывается как калиброванная уверенность. Число 7, переданное только для сравнения, не меняет identity этой оценки популяции.

`belief_status=prior_only` означает существующий target без собственного evidence; `assessed` требует `evidence_count > 0`. Пустое или недоступное состояние остаётся unassessed. Проверка не основана только на Support: проверенный, но недискриминирующий источник тоже может иметь Support=0. Сам статус assessed не означает высокую достоверность или независимую калибровку.

Retraction evidence меняет BeliefData, но не удаляет само сообщённое измерение: арифметическая сводка остаётся условной на сохранённых записях. Исправление или удаление numeric fact — отдельная операция. Нельзя автоматически приравнять ослабление belief к уменьшению sample count либо перенести прежнюю оценку репрезентативности на изменённый состав данных.

Для убеждения о том, к какому классу действительно относится конкретный объект, остаётся общий контракт `read_property`/BeliefStore: exclusive/exhaustive alternatives используют Profile, а evidence требует обоснованной оценки и учёта зависимостей. Отсутствие такой оценки ограничивает epistemic claim, но не блокирует честную описательную сводку. Эти два результата нельзя смешивать или показывать условную метку как уверенное знание о мире.

### Частоты, интервалы и маленькие выборки

Для точечных частот среднее вычисляется как `sum(value × count) / sum(count)`. Частоты принадлежат конкретной внешней выборке, а не считаются независимыми подтверждениями её качества. Интервальные bins не определяют точное среднее и точные quantiles внутри bin. Если используется midpoint estimate, результат обязан явно назвать его приближённым и показать допущение; точное среднее из такой таблицы не выдумывается.

Для интервальной таблицы результат обозначает `approximate=true`, `estimate=interval_midpoints` и отдельно возвращает `mean_bounds`/`median_bounds`. Поля mean и median в этом случае — оценки, а не точные значения. `count_below_value` учитывает только строки с upper < value, `count_above_value` — с lower > value; остальные попадают в `count_overlapping_or_equal` и не доказывают ни одного направления.

Три известные собаки позволяют описать этих собак, но не установить норму для всех взрослых собак, породы или ветеринарной практики. Без заданного критерия «ниже среднего» не означает «маленькая собака». Для обобщения на широкую популяцию нужны пригодность выборки, определение целевой популяции и отдельная проверка. Когда понадобится устойчивая наученная норма, можно добавить batch quantiles и immutable norm revision; это следующий шаг, а не обязательная предпосылка бытового использования.

## Контрольные примеры

### 1. Отдельные рассказы: 8, 5 и 10 kg

В трёх сообщениях появляются три разные собаки. KnowledgeIntegration сохраняет их идентичности, принадлежность к Dog, property BodyMass с единицей kg и исходные numeric facts. Между сообщениями нет команды обучения или refresh.

После первого сообщения средняя масса известной собаки — 8 kg. После второго среднее двух — 6.5 kg. После третьего:

```text
count = 3
mean = (8 + 5 + 10) / 3 = 23/3 kg ≈ 7.67 kg
median = 8 kg
range = [5, 10] kg
```

На вопрос о 7 kg агент отвечает: «Это на 2/3 kg ниже средней массы трёх известных мне собак и находится в наблюдённом диапазоне». Число 7 не добавляется в обучающую выборку самим вопросом. Универсальный Small/Medium/Large из этих трёх рассказов не появляется. Если позже сохранено измерение четвёртой собаки, следующая сводка использует уже четыре субъекта.

### 2. Справочник с категориями

Отдельный источник задаёт критерий по массе: Small `≤10 kg`, Medium `(10,20] kg`, Large `>20 kg`. Агент сохраняет bands, domain, классы и grounds одним reference record. Это условные тестовые границы, не ветеринарная рекомендация.

Для 7 kg ожидается «по этому справочнику — Small». Проверяются включительные верхние границы: 10 → Small, 20 → Medium; 28 → Large. Масса остаётся числом, правило — отдельным источником интерпретации. Другой справочник с иными thresholds возвращается отдельно. Ни одна метка не создаёт автоматического Profile или `CLASSIFIED_AS`.

### 3. Статистическая таблица

Внешняя таблица сообщает точечные частоты:

| Масса | Число собак |
| --- | --- |
| 5 kg | 2 |
| 8 kg | 1 |
| 10 kg | 3 |

Ожидаемое среднее этой таблицы — `(5×2 + 8×1 + 10×3) / 6 = 8 kg`, а не среднее трёх строк `23/3`. Локальные собаки из первого примера остаются отдельной выборкой со средним `23/3`. Повторная передача таблицы не делает count равным 12 и не создаёт шесть новых Instances.

Вариант с диапазонами `[4,6]`, `[7,9]`, `[9,11]` и теми же частотами проверяет, что exact mean недоступно без распределения внутри bins; midpoint estimate 8 kg, если он показан, явно приближённый. Строки со средними пород без численности не интерпретируются как эта таблица частот.

## Сценарии MVP по принципу Парето

| ID | Кейс | Приёмка |
| --- | --- | --- |
| ATTR-01 | Свойство приобретается из отдельных естественных сообщений | Агент создаёт/reuses property и субъектов публичными tools; значения с единицей и источниками доступны следующему `read_property` и `summarize_property`. |
| ATTR-02 | Среднее известных объектов и сравнение нового числа | Для 8/5/10 получены count=3, mean=23/3; 7 ниже среднего на 2/3 без вымышленного универсального размера. Нет отдельного train/refresh и нет записи вопроса в samples. |
| ATTR-03 | Справочные качественные понятия | Bands читаются с источником; 7/10/20/28 дают ожидаемые условные labels. Разные справочники и domains не сливаются. |
| ATTR-04 | Внешняя статистическая таблица | Учтены частоты: среднее 8, count=6. Named individuals и aggregate разделены; нет фиктивных объектов или exact mean для интервальных bins. |
| ATTR-05 | Полезный выбор | По выбранному справочнику отфильтровать Large из 7/15/28 kg, затем выбрать ближайшую к 25 kg: 28 kg, distance=3. Объяснение условное и ссылается на rule и исходные readings. |
| ATTR-06 | Категориальные и relation-backed свойства | Существующий Profile сохраняется целиком, independent binary признаки не объединяются; `SurfaceUnder` читает исходную связь без её копии. Это регрессии общей плоскости. |
| ATTR-07 | Повторы, correction и новые наблюдения | Повтор не увеличивает число субъектов или частоты. Correction меняет следующую сводку; прежний сохранённый результат остаётся прежним. Данные по породам не объединяются молча. |
| ATTR-08 | Новая задача и восстановление | После snapshot/restore definitions, numeric facts и reference records доступны штатным чтениям без ручной регистрации. Новый контекст использует сохранённые источники, не исходный текст разговора. |

Это целевая приоритизация, а не доказанные 80% обращений. Пользу и частоту сценариев затем следует измерять на реальных задачах. Неопределённость и несовместимые единицы/domain входят в негативные варианты каждого пути.

## Расширенные сценарии после первой проверки

Эта матрица расширяет исходные три пути, а не измеряет процент покрытия реальных обращений. `pending` означает, что соответствующий новый прогон ещё не завершён; `pass` требует фактического выполнения на указанной версии; `fail` сохраняет обнаруженный отказ до подтверждённого исправления либо успешного повтора. Один успешный повтор не отменяет предыдущую ошибку модели и не оценивает частоту таких ошибок. Component и live результаты различаются: первые проверяют контракт, вторые — самостоятельное приобретение и использование знания моделью с настоящим retrieval.

### Дополнительные live-сценарии

| ID | Сценарий и ожидаемый результат | Статус |
| --- | --- | --- |
| ATTR-X01 | Джек 8 kg, повтор о нём 8000 g, затем исправление до 9 kg; Луна 5 kg. После нового чтения count=2 и mean=7 kg; повтор не создаёт третью собаку. | pass — новый acquisition final-regression-02 на последней версии, hard assertions и все четыре review checks; ранний pass extended-01 сохранён |
| ATTR-X02 | Два справочника: клуб «Берег» с boundaries 6/9 и клуб «Лес» с 10/20. Для 7 kg возвращаются соответственно Medium и Small, с раздельными источниками и без молчаливого выбора победителя. | pass — extended-12, новый acquisition и все четыре semantic review checks |
| ATTR-X03 | Интервальная таблица `[1,3]×1`, `[5,7]×1`, `[9,11]×3`: count=5, midpoint mean=7.6, mean bounds `[6.6,8.6]`; для 6 ниже=1, выше=3, пересечение=1. Нет индивидуальных собак и вымышленного exact mean. | pass — extended-05, hard assertions и все четыре semantic review checks |
| ATTR-X04 | Общий справочник собак с 10/20 и справочник Chihuahua с 2/4. Для 7 kg общий критерий даёт Small, породный — Large. Запрос сохраняет выбранную популяцию; другой справочник виден отдельно и не применяется молча. | pass — extended-15 с новым acquisition, runtime чтением обоих guides и всеми четырьмя review checks; прежние failures 08/13 сохранены |
| ATTR-X05 | Справочник 10/20, собаки 7/15/28 kg и одна без массы. Large — собака 28 kg; ближайшая к 25 kg — та же, distance=3. Count=3, unknown не превращается в 0; модель использует доступные чтения для выбора. | pass — extended-11 с новым acquisition и deterministic nearest; прежние failures сохранены |
| ATTR-X06 | Другая предметная область и смешанные исходные единицы: первая посылка сообщена как 500 g, вторая — 1.5 kg. Запрошенный mean=1 kg; правило Light ≤1 kg условно относит 750 g к Light. Понятия собак не используются, сравниваемое значение не добавляется к двум измерениям. | pass связанного acquisition/use — завершённый acquisition extended-14 и новый reader extended-16 на той же версии; это не полный повтор 14, его ошибка enum сохранена |

Первый расширенный live-прогон завершён за 97.82 s: X01 прошёл, остальные пять остановлены HTTP 429 до вызовов инструментов и не дали semantic evidence. Это не доказательство дефекта attribution в этих пяти сценариях и не их успешная проверка. Артефакты сохранены в `/private/tmp/evertree-attribution-extended-01/test_model_learns_attribution_{0..5}/attribution-learning.json`. Production source hash оставался неизменным на всём прогоне: `220bb666a9b86fffe214f6e3f2724a88ad670b3cf7c320f91a7a8149cf116064`.

В extended-02 X02 действительно сохранил два справочника и прочитал для 7 kg Medium/Small, но test-local oracle завершился `KeyError: 'кг'`: он не распознал единицу в свободном ответе. Это ошибка тестового сопоставления, а не расчёта runtime. Запуск остановлен после неё, semantic review и оставшиеся четыре сценария не выполнялись; итог 67.02 s. Oracle дополнен display-unit alias; production hash не менялся. Артефакт сохранён в `/private/tmp/evertree-attribution-extended-02/test_model_learns_attribution_0/attribution-learning.json`. Этот частичный результат не обозначается полным pass X02.

Extended-03 выявил настоящий отказ приобретения X02 за 57.35 s. Модель объявила популяцию как обычный Concept вместо Prototype и создала свойство для этого Concept; reference был отвергнут по типу domain. После создания Prototype попытка повторно создать property с тем же именем тоже была отвергнута. Правило осталось только текстовым Claim, а свежая модель дала правдоподобный ответ без требуемого чтения bands через `summarize_property`. Строгая проверка закономерно завершилась fail; X03–X06 после остановки не запускались. Артефакт: `/private/tmp/evertree-attribution-extended-03/test_model_learns_attribution_0/attribution-learning.json`; production hash в начале и конце тот же, что в extended-01.

После extended-03 metadata tools явно указывает domain kind=Prototype и numeric property contract. Инструкция KI требует сначала определить популяцию, переиспользовать общий domain/property для разных справочников и исправлять существующее attribution declaration через update вместо создания дубликата. Ошибка domain сообщает ID и фактический kind. Реальная component-проверка прошла путь reject invalid domain → repair property → retry reference с тем же ключом → успешный summary. Отдельно добавлены ограниченные unit aliases и public API regressions для массы, длины и времени. Изменённая production версия требует собственного live-повтора; успех более раннего X01 не выдаётся за повтор на новой версии.

Extended-04 завершился fail за 140.54 s: второй KI packet X02 достиг 120-секундного лимита. Оба справочника уже были сохранены; коллизию имени Concept/reference модель исправила переименованием, хотя выполнила лишнее удаление и повторное создание. Последняя успешная запись была примерно на 38.6 s, затем около 81 s не было новых model/tool events. Проверка использования и rubric не выполнены, поэтому правильный итоговый graph не считается полным pass. Production hash этого прогона: `19dd1d24f4140263b28ba16743e81e0ab4868ac406ca7c160fa781a72f4d5fac`. Следующие X03–X06 запускаются отдельно; повтор X02 не требует новой правки production.

Extended-05: **1 passed, 1 failed, 5 deselected**, 96.99 s. X03 прошёл полностью: арифметика, границы и направления сравнения совпали с ожиданиями, named individuals не создавались, все четыре semantic review checks прошли. Для X04 обе KI acquisitions завершились и сохранили отдельные Dog/Chihuahua references, но fresh reader получил HTTP 429 до первого tool call. X05/X06 после остановки ещё не исполнялись. Артефакты — `/private/tmp/evertree-attribution-extended-05/test_model_learns_attribution_0/attribution-learning.json` для X03 и соседний `_1` для X04. Production hash тот же, что в extended-04.

Extended-06 X05 завершился semantic fail за 124.87 s. Модель правильно сохранила 7/15/28 kg и отдельную собаку с неизвестным весом; runtime верно рассчитал count=3, mean=50/3 и категории. В тексте ответа обеим критериям соответствовал Гром 28 kg, но structured `nearest_choice` указывал ID Весты 15 kg, тогда как `large_choice` — правильный ID Грома. Это реальная ошибка выбора identity моделью, а не ошибка oracle или числовой сводки; правильный текст не заменяет правильный структурированный результат для дальнейшего действия. Hard assertion отклонил результат до запуска rubric. После этого единичного исхода production не меняли; был назначен повтор. X06 после остановки не запускался. Артефакт: `/private/tmp/evertree-attribution-extended-06/test_model_learns_attribution_0/attribution-learning.json`; production hash остался версией extended-04.

Extended-07 X06 завершился настоящим acquisition fail за 81.59 s. Единицы и mean=1 kg корректны, но KI сохранил понятия Light/Heavy и производные классификации двух известных посылок, не создав reusable reference исходного правила. Свежий reader назвал 750 g лёгкой посылкой в тексте, однако runtime вернул пустые references; строгая проверка отклонила результат. Сохранение частных применений не заменяет сохранение правила для следующих объектов. Артефакт: `/private/tmp/evertree-attribution-extended-07/test_model_learns_attribution_0/attribution-learning.json`.

Для повторного использования завершённого acquisition добавлен opt-in `EVERTREE_ATTRIBUTION_LEARNED_ARTIFACT`. Harness проверяет исходный case, содержимое и число packets, завершённость каждого provider invocation, полные snapshots и точное совпадение production hash. Новый artifact хранит путь и SHA256 оригинала; первоначальный failure не заменяется. Проверка без вызова модели приняла завершённое обучение X04 и отвергла timeout acquisition X02. Такой повтор проверяет нового reader на том же сохранённом знании, а не повторное обучение. Успешный прогон дополнительно требует равенства source hash в начале и конце.

Resume extended-08 для X04 завершился fail за 13.19 s. Ответ правильно различал общий и породный критерии, но reader вызвал summary только для общего guide; породный вывод он получил из описания лишнего обычного Concept, а не из второго сохранённого numeric reference. Это не ошибка арифметики или смысла ответа, но требуемый вычислимый путь использования второго guide не подтверждён. Артефакт `/private/tmp/evertree-attribution-extended-08/test_model_learns_attribution_0/attribution-learning.json` ссылается на завершённый acquisition X04 из extended-05 и его SHA256.

Resume extended-09 для X05 повторно выявил ошибочный выбор за 15.77 s: теперь Веста 15 kg была названа ближайшей к 25 kg и в structured ID, и в тексте, хотя Гром 28 kg ближе. Артефакт `/private/tmp/evertree-attribution-extended-09/test_model_learns_attribution_0/attribution-learning.json` ссылается на acquisition extended-06. Оба resume использовали неизменную версию extended-04. По результатам повторяемой ошибки реализован узкий deterministic nearest по уже прочитанным числовым observations, без нового API или store. Для guide retention уточнён общий контракт KI: numeric reference представляет сам источник правила; лишний plain Concept/Claim и классификации текущих объектов не заменяют его. Явные thresholds и frequencies сохраняются независимо от текущих примеров, само правило не даёт права материализовать безусловные `CLASSIFIED_AS`. После этой правки началась новая серия live-проверок с новыми acquisitions; snapshots прежнего production hash не подмешивались.

Extended-10 повторно выявил acquisition fail X06 за 92.54 s уже на новой версии `edfc3645910409868f35df9c8b1aa983734a7e2d4bdaec486f10ebc90a46fdfe`. KI создал Light/Heavy и собственное relation `Delivery weight class` для известных посылок, но не numeric reference. Mean=1 kg и свободный вывод о 750 g правильны, требуемый reusable-rule путь не выполнен. На этом этапе новая инструкция ещё не подтвердила исправление retention этого правила. Артефакт: `/private/tmp/evertree-attribution-extended-10/test_model_learns_attribution_0/attribution-learning.json`.

Extended-11 X05 прошёл полностью за **89.29 s** с новым acquisition на версии `edfc…fdfe`. Runtime nearest для 25 kg вернул Грома 28 kg, distance=3 и его фактический ID; оба structured выбора модели совпали с ним. Три категории правильны, Туман остался unknown, count=3, mean=50/3, все четыре semantic review checks прошли. Артефакт: `/private/tmp/evertree-attribution-extended-11/test_model_learns_attribution_0/attribution-learning.json`. Это подтверждает применение нового числового nearest в этом прогоне; ошибки 06/09 остаются частью результатов.

Extended-12 X02 прошёл полностью за **98.16 s** на той же версии `edfc…fdfe`: новый acquisition сохранил общий domain/property и два отдельных references 6/9 и 10/20. Fresh reader получил через runtime для 7 kg соответственно Medium и Small, не выбрал единственный общий критерий; observations count=0, mean=null. Все четыре semantic review checks прошли. Артефакт: `/private/tmp/evertree-attribution-extended-12/test_model_learns_attribution_0/attribution-learning.json`.

Extended-13 X04 завершился fail пути использования за **42.35 s** на версии `edfc…fdfe`. Новый acquisition сохранил оба references с правильными Dog/Chihuahua domains и без лишних guide containers. Fresh reader сделал два поиска и правильно ответил Small/Large, не распространив породный критерий на Labrador, но ни разу не вызвал `summarize_property`. Hard assertion отклонил отсутствие требуемого вычислимого чтения. Это не ошибка значения категорий или области применимости в ответе: не подтверждён предусмотренный тестом путь применения сохранённых rules через Attribution API. Артефакт: `/private/tmp/evertree-attribution-extended-13/test_model_learns_attribution_0/attribution-learning.json`.

После extended-13 контракт использования объявлен явно в общей production-инструкции `NUMERIC_READ_INSTRUCTIONS`, которую импортируют и live readers. Search/describe находят identities и declarations; перед ответом о сохранённых измерениях, guide либо таблице требуется runtime summary, а для каждого запрошенного guide — его interpretation с reference/value/unit. Неудачное чтение остаётся unknown. Это общий контракт работы агента с плоскостью, а не скрытое требование только теста. В workflow KnowledgeIntegration добавлена проверка сохранённого numeric reference чтением перед завершением: bands/classes/counts должны совпадать с источником с учётом единиц. Правило не заменяется индивидуальной категоризацией, в том числе через custom relation. Эти инструкции реализованы и прошли offline-регрессии; прежние passes X02/X05 относятся к версии `edfc…fdfe`, до этой правки.

Extended-14 X06 завершился fail structured ответа за **65.10 s** на новой неизменной версии `407bc094208e6648595936999b899c2f78c61a6ead8cb9e8f23593d98ff8fc14`. Теперь acquisition сохранил Light/Heavy reference с boundary=1 kg без индивидуальных class assignments или custom relations. Runtime вернул count=2, mean=1 kg и правильную «Лёгкую посылку» для 0.75 kg. Русское объяснение также правильное, но в structured classification модель выбрала `small` вместо требуемого `light`. Предыдущий дефект сохранения правила в этом прогоне не повторился; полный pass не получен из-за неверной метки ответа. Артефакт: `/private/tmp/evertree-attribution-extended-14/test_model_learns_attribution_0/attribution-learning.json`.

Extended-15 X04 прошёл полностью за **66.79 s** на той же версии `407bc…fc14`, с новым acquisition и fresh reader. Оба guides действительно прочитаны через отдельные runtime summaries: для 7 kg Small по общему справочнику 10/20 и Large по Chihuahua 2/4. Породный критерий не применён к Labrador, его результат сохранён как unknown. Hard assertions и все четыре semantic review checks прошли. Артефакт: `/private/tmp/evertree-attribution-extended-15/test_model_learns_attribution_0/attribution-learning.json`.

Usage-only extended-16 X06 прошёл за **13.85 s** на той же версии `407bc…fc14`. Завершённые три acquisition packets и неизменные snapshots взяты из extended-14; новый reader вернул mean=1 kg, count=2 и `light` для 0.75 kg по сохранённому классу «Лёгкая посылка». Все четыре semantic review checks прошли. Артефакт `/private/tmp/evertree-attribution-extended-16/test_model_learns_attribution_0/attribution-learning.json` содержит ссылку на acquisition 14 с SHA256 `4bfaf609630a28ecd1068a1541aa218b50d5f3da76a1ef7439f95afe6db75e30`. Это положительная проверка связанного обучения и нового использования на одной версии, не полный повтор acquisition и не изменение исходного enum failure 14.

Все шесть расширенных сценариев теперь имеют положительные evidence по указанным checkpoints и запускам. Это не один чистый suite на последней версии и не оценка вероятности успеха модели: X03 и X02/X05 прошли на более ранних checkpoints, X01/X04 — на `407bc…fc14`, X06 — через связанный acquisition/read retry этой же версии. Повтор исходных трёх сценариев и correction на последней версии описан отдельно ниже.

Повтор final-regression-01 на `407bc…fc14` остановился на отдельных наблюдениях: новый acquisition и fresh reader прошли все deterministic checks — mean=23/3, count=3, сравнение с 7 и unknown qualitative class. Независимый reviewer получил HTTP 429 до ответа; итог **fail**, 64.89 s, полного semantic pass нет. Это не ошибка приобретения или расчёта, но недостающий review не заменяется предполагаемым успехом. Артефакт: `/private/tmp/evertree-attribution-final-regression-01/test_model_learns_attribution_0/attribution-learning.json`. Оставшиеся сценарии и повтор использования завершённого acquisition проверяются отдельно.

Проверка X06 на отсутствие выдуманных индивидуальных category assignments закреплена в общем live harness и учитывает custom relations, а не только имя `CLASSIFIED_AS`. Повтор проверки сохранённых данных без вызова модели принял правильные artifacts 14/16 и отклонил custom relation из 10. Это регрессия oracle на существующих evidence, не ещё один live pass.

Final-regression-02: **3 passed**, 140.54 s, на неизменной версии `407bc…fc14`. Новые acquisitions и fresh readers подтвердили справочник (7 kg → Medium, observations count=0), frequency table (count=10, weighted mean=8.1 kg; для 7 kg шесть значений выше и четыре ниже) и correction X01 (один Джек 8 kg/8000 g → 9 kg плюс Луна 5 kg, count=2, mean=7 kg). Каждый case прошёл hard assertions и все четыре review criteria. Артефакты: `/private/tmp/evertree-attribution-final-regression-02/test_model_learns_attribution_{0,1,2}/attribution-learning.json`.

Usage-only final-regression-03 на той же версии использовал завершённый acquisition отдельных наблюдений из final-regression-01. Итог **fail**, 13.21 s: hard assertions прошли, три из четырёх rubric criteria прошли. Reviewer отклонил только source_meaning, поскольку объяснение назвало 5/8/10 kg «измерениями», не повторив газетную атрибуцию. При этом сам reviewer подтвердил сохранение газетного источника и unassessed belief; ответ ограничил среднее тремя известными собаками и не утверждал самостоятельной проверки. Этот исход сохранён как отказ judge; одного ручного несогласия с ним было недостаточно для признания pass, поэтому проверка rubric выполнена отдельно ниже. Артефакт: `/private/tmp/evertree-attribution-final-regression-03/test_model_learns_attribution_0/attribution-learning.json`.

Rubric уточнён: общие слова weights/measurements сами по себе не утверждают firsthand verification; явное утверждение «я лично измерил / независимо подтвердил» требует основания в источнике. Выполнены ровно два независимых review вызова без нового reader или KI. Неизменённый ответ final-regression-03 получил **4/4 pass**; отрицательный контроль с добавленным ложным утверждением о личном взвешивании всех трёх собак получил `source_meaning=false`, остальные три criteria прошли. `/private/tmp/evertree-attribution-review-calibration-01/review-calibration.json` сохраняет исходный artifact и digest, production hash `407bc…fc14`, requests/events/results. Так подтверждены hard checks и независимый review исходного ответа после исправления слишком строгого oracle; исторический pytest failure 03 остаётся failure и не считается новым успешным pytest-прогоном. Обязательных незавершённых проверок этого MVP не осталось; результаты девяти уникальных сценариев относятся к явно перечисленным версиям и способам повтора.

### Контракты и adversarial cases

| ID | Проверяемый контракт | Статус |
| --- | --- | --- |
| ATTR-C01 | Конфликтующие bands остаются отдельными; явный `reference` выбирает только нужную запись. | pass — component |
| ATTR-C02 | Выборка по Dog включает известные подтипы; запрос подтипа исключает чужие экземпляры; несовпадающая область reference даёт `different_population`. | pass — component |
| ATTR-C03 | Смешанные единицы и известные символьные aliases массы/длины/времени приводятся к единице свойства в ordinary read и summary. Несовместимые dimensions не включаются как числа; source unit не переписывается. | pass — component |
| ATTR-C04 | Исторические и временно неизвестные Facets: latest_recorded остаётся описанием записей, explicit `at` сохраняет applicability и unknown. | pass — component |
| ATTR-C05 | Дубликаты и correction не увеличивают количество субъектов; explicit `at` соблюдает unique/max_support, no-time — latest_recorded. | pass — component |
| ATTR-C06 | После retraction исходного evidence BeliefData меняется без превращения sample count в Support. Данные остаются сообщёнными наблюдениями; correction меняет соответствующую data revision, чтение не пишет stores. | pass — component для population target; дополнительно smoke retraction fact evidence |
| ATTR-C07 | Условия изолируют выборки и rules; одинаковые структурированные JSON conditions совпадают после сохранения/restore. Коллизии с аргументами API отвергаются как ContractError до сохранения, а не вызывают TypeError при чтении. | pass — component и независимый smoke |
| ATTR-C08 | Пустая выборка, один субъект и равные значения дают определённые count/mean/median/comparison без фиктивной дисперсии или population norm. | pass — component |
| ATTR-C09 | Некорректный reference/update отвергается атомарно: неверные интервалы/частоты, domain, unit, type и отсутствующий числовой контракт свойства не оставляют непригодную запись. | pass — component и независимый smoke |
| ATTR-C10 | Интервальные aggregates сохраняют weighted bounds и число пересечений; исходная таблица, named individuals и разные популяции не складываются. | pass — component и отдельный live пример ATTR-X03 |
| ATTR-C11 | Публичный gateway возвращает `at`, `valid_from`, `valid_until` обычными ISO-строками; повторная сериализация не превращает их в служебные вложенные objects. Public report совпадает с runtime report. | pass — component |
| ATTR-C12 | После атомарного отказа reference из-за Concept domain существующее property исправляется на Prototype scope; повтор reference с тем же operation key создаёт пригодный источник без дубликата property. | pass — component; самостоятельный repair моделью проверяется отдельно |
| ATTR-C13 | Numeric nearest возвращает правильные subject IDs, исключает unknown/aggregate rows, учитывает все observations и ограничивает preview равных минимумов. Decimal ties после преобразования единиц допускают только roundoff; exact match не объединяется с соседним float. | pass — public API component, включая 43 observations и 23 равных минимума |

[Расширенный population-набор](../../tests/component/test_attribution_population.py): **54 passed**. Вместе с связанными attribution tools, unit attribution, facet time и semantic interface проверками: **104 passed**, 0.60 s. Эти результаты подтверждают механические контракты, а не самостоятельный выбор представления моделью в шести новых live-сценариях.

До добавления nearest независимый повтор всех тогдашних 51 population cases через настоящий `operations.execute("graph.summarize_property")` вместо внутреннего helper дал **51 passed**, 0.22 s, без правок файлов. Новые nearest regressions также используют public API. Записи проходят SemanticService; retraction в component-проверке вызывается через BeliefStore API, а не инструментом модели. Этот повтор подтверждает публичную маршрутизацию чтения и не является дополнительным LLM-прогоном.

Первый независимый read-only audit воспроизвёл три причины отказа. `conditions={"value":"resting"}` сохранялись, но соответствующий public read отвергал свой зарезервированный аргумент. `conditions={"subject":"resting"}` при explicit `at` приводили к Python TypeError из-за двойной передачи subject. `conditions={"age_range":[1,5]}` после сохранения переставали совпадать с таким же JSON-параметром: frozen tuple сравнивался с исходным list; summary исключала и наблюдение, и reference. Это exact equality структурированного параметра, не просьба интерпретировать массив как диапазон.

Отдельно reference с `unit=null` удавалось сохранить для `kind=property` без typed attribution declaration; последующий summary не находил допустимое numeric свойство. Исправление атомарно отклоняет такую новую запись до явного объявления контракта, без добавления незаказанной миграционной поддержки. Независимый ручной повтор подтвердил отказы для зарезервированных keys без mutation и Python TypeError, успешное matching arrays/nested maps, различие boolean/number и отклонение reference без declaration. Новые component regressions также прошли. Для условий `relate` разрешены структурированные JSON values; relation arguments сохраняют прежний scalar/array контракт. Отдельная component-проверка выявила и подтвердила исправление повторного кодирования временных полей публичного summary. Исходные отказы учтены; успешный smoke не подменяет live-прогоны матрицы.

## Первоначальный порядок реализации описательного MVP

### Этап 1 Объявления через семантические tools

Добавить `create_property` и `create_property_reference` через существующие compilation, source validation, GraphDelta и историю. Проверять ссылки, units, тип reference, классы, конечность чисел и частоты. Дать KnowledgeIntegration краткое правило различать индивидуальное измерение, правило справочника и aggregate. Сохранять числовые facts вместо прозы, когда это полезно для сравнения и сводки.

### Этап 2 Общая описательная сводка

Подключить `summarize_property` к Core API и semantic read tools. Получать individual readings из общего runtime, считать statistics при запросе и читать external references отдельно. Обработать exact frequency weights, interval limitations, domain/conditions, отсутствие данных и явную интерпретацию по rule. Не добавлять stores, background jobs, refresh или belief adapter для этой операции.

### Этап 3 Проверка приобретения и использования

Провести три контрольных пути выше через реальные semantic writes и чтения; затем через настоящий KnowledgeIntegration. Обучение и использование — разные сообщения/контексты. Проверять фактические записи и источники, арифметику и отсутствие мутаций на read. Отдельно проверить snapshot/restore и повторное использование новой задачей.

### Порядок завершения плоскости после описательного MVP

Этот порядок был следующим после описательного MVP и реализован в текущем этапе выше. Он задаёт зависимости и приёмку; успешные старые numeric live-прогоны не закрывают новые пункты автоматически.

| Порядок | Результат и зависимость | Приёмочный сценарий |
| --- | --- | --- |
| 1. Canonical qualitative readings | Объявления nominal/ordinal properties и source-backed evidence adapter через общий BeliefStore. Условный rule result, degree of membership и epistemic Profile различаются; reads не создают evidence. | Контролируемая оценка источника даёт полный Profile Small/Medium/Large без вымышленного p=1 и без Support=count. Неоценённый или stale вопрос даёт UNKNOWN; повторное чтение не меняет beliefs. |
| 2. Наученная норма | Эмпирические weighted quantiles из сохранённых observations либо одного source distribution; semantic/fit/data revisions и pinned dependencies. Существующий Learning pipeline нужен для supervised labels/outcomes, а не как промежуточный склад измерений. | На 5/8/10 fit сохраняет 7 и 26/3; удержанное значение 7 интерпретируется без нового наблюдения. Correction создаёт новую fit revision, прежний checkpoint сохраняет результат. Породная норма не переносится на всех собак. Это проверка процедуры и источников, не статистическая оценка генерализации по трём собакам. |
| 3. Typed Program readers и точное восстановление | Подключить необходимые typed результаты к общему PropertyReading через существующий Program contract. Восстанавливать definitions, bindings, model versions и источники из настоящего exact backup, без ручной регистрации readers. Зависит от устойчивых деклараций и versioning первых двух этапов. | После backup и нового runtime numeric, qualitative и одно Program-backed свойство дают те же значения, Profile и provenance на заданных world/knowledge times. Недоступная историческая версия возвращает unknown, а не текущую модель. |
| 4. Общий выбор по свойствам | Обобщить уже реализованный numeric nearest до единых filter/rank/nearest поверх PropertyReading с явными правилами для unknown, partial Profile, единиц и ties. До появления нужного масштаба обходиться без computed-property индекса. Зависит от общего read contract; learned norms используются только там, где выбран соответствующий criterion. | Числовой пример 7/15/28 kg с unknown остаётся регрессией: nearest к 25 kg — 28 kg, distance=3. Дополнительно фильтр qualitative Profile использует явно заданный порог, сохраняет недостаточные оценки как unknown и объясняет решение через criterion и evidence. |
| 5. Расширенные оси по потребности | Добавлять composite axes, learned transforms, drift handling и другие возможности только для измеренной задачи, которую предыдущие этапы не решают. Сначала фиксировать требуемое улучшение, sampling semantics и стоимость. | На реальном сценарии новая ось улучшает заранее выбранный результат против простого свойства, сохраняет источники и воспроизводимость; без такого эффекта расширение не включается в runtime. |

Observation/evidence adapter нужен для убеждения о действительной категории, но не становится условием ответа «среднее известных значений — 7.67». Дальнейшие этапы не отменяют доступность простых описательных сводок.

## Финальная проверка end to end

### Детерминированный сквозной тест

Настоящие graph, attribution, beliefs и semantic gateway; публичные write/read tools, а не прямое заполнение внутренних словарей. ScriptedProvider может фиксировать семантические решения, но не подменяет statistics, bands, source selection и mutation checks. Начальное состояние содержит только bootstrap. По шагам сохраняются три разных рассказа, справочное правило и frequency table; новая задача читает их по смыслу. В тесте нет скрытого train/refresh и подготовленного среднего.

Обязательные проверки:

- После каждого рассказа значение доступно; после 8/5/10 mean равен 23/3.
- Число 7 сравнивается с этой выборкой, но запрос не увеличивает count и не устанавливает универсальную категорию.
- Справочник даёт условную метку с указанием источника; другой справочник не перезаписывается и не выбирается молча.
- Включительность каждой boundary сохраняется; для `[10,20]` с `[False,True]` значение 10 относится к Medium, а не Small. Диапазон выбранного класса показывает правильные нижнюю и верхнюю границы.
- Frequency table даёт mean=8 и count=6; interval histogram сохраняет границы точности.
- Локальная выборка, внешние aggregates, породы и повторные источники не объединяются автоматически.
- Чтения не меняют graph, beliefs, learning state или число sources; нет fabricated Profile, confidence или Support=count.
- Исходные BeliefData сохранены; оценка репрезентативности отделена от достоверности измерений. Unassessed не считается опровержением и не блокирует среднее трёх записанных чисел.
- Target только с prior остаётся prior_only; собственное evidence меняет статус на assessed, даже если его различительная масса равна нулю. Ни один статус не устанавливает надёжность автоматически.
- Без `at` исторические наблюдения возвращаются как latest_recorded с границами источника; явный `at` исключает неприменимые и временно неизвестные состояния. Ни один режим не выдает историческую запись за текущее состояние.
- Source!=numeric не подменяется facts; с явным `at` соблюдаются unique/max_support/latest и неизвестное чтение не становится произвольным победителем.
- Missing/NaN/Infinity/несовместимая единица/чужой domain не становятся нормальным измерением.
- Повтор, correction и snapshot/restore сохраняют identities, источники и возможность нового чтения.
- Исторический сохранённый ответ не переопределяется после нового источника; assertions о произвольном historical read требуют отдельного exact-backup теста.

### Настоящий агент и границы инфраструктуры

Live-проверка подаёт рассказы естественным языком, затем справочник, затем таблицу. Готовых property IDs и результатов расчёта нет. В последующей задаче исходный текст не повторяется: модель должна вызвать инструменты сохранённого знания. Правильный свободный ответ без чтения сохранённых данных не доказывает этот путь.

Начать с трёх независимых live прогонов и сохранить все исходы, включая ошибки. Это smoke gate, не статистическое доказательство качества. Перенос на latency или цены должен использовать тот же механизм. Component snapshot roundtrip не подменяет integration тест реальных Program/worker/DBOS и backup/restore; их запуск обязателен при изменении этих границ. Native suites нужны при изменении native boundary.

Проверки новой реализации и их результаты добавляются только после запуска. Описанные критерии являются задачами приёмки, а не утверждением, что они уже пройдены.

## Необязательные расширения после текущего этапа

| Возможность | Когда возвращаться |
| --- | --- |
| `peak_modes`, isotonic/learned_monotonic, membership functions | Когда есть labels/outcomes и задача, которую не решают простые правила. |
| Streaming sketches, EMA, drift detector, InstanceSketch, RecentSamples | После измерения объёма и необходимости динамики. |
| Автоматическое объединение источников и породных strata | После явного контракта независимости, sampling units и overlap. |
| Computed-property indexes и автоматическая материализация | После измеренного выигрыша; typed results и Program readers уже входят в текущую реализацию. |
| Composite axes, PCA/IPCA, автономное открытие осей | После проверки их операционной пользы; для BodyMass не нужны. |
| История между exact backups, causal engine, новый query DSL | Exact saved checkpoints уже читаются; произвольное восстановление отсутствующих промежуточных состояний — отдельная задача. |

Круговая дистанция проверяется регрессией `350° ↔ 10° = 20°`. `InstanceSketch`, `RecentSamples`, альтернативные формы numeric relation и composite axes в архитектуре — варианты расширения, а не основание добавлять параллельные структуры без сценария. Текущий контракт завершает основные операции плоскости; наличие этих необязательных примеров в design document не означает их реализацию.

## Проверки исходной реализации

До доработки естественных описательных путей на исходной реализации выполнены:

- Связанный unit/component набор: 76 passed. Это `test_attribution`, `test_behavioral_semantics`, `test_semantic_interface`, `test_core_operations`, `test_facet_time`, `test_integration_actions`.
- Общий `uv run pytest -q`: 567 passed.
- `uv run pytest tests/integration/test_operations_experiment.py -q -n 0`: 2 passed. Проверяется изоляция семантического состояния при вычислении, включая статическую z-score нормализацию.

Для запуска использован временный UV cache из-за ограниченного доступа к пользовательскому cache. Эти результаты относятся к исходному аудиту и не подтверждают новую реализацию; существующая локальная правка `src/evertree/debug_integration.py` не относится к этому плану.

На момент исходного аудита четыре [unit tests attribution](../../tests/unit/test_attribution.py) проверяли temporal numeric/classification reads, шкалы/z-score, prior Profile и подставленный historical loader; отдельной проверки hard bands не было. [INT-02](../../tests/component/test_behavioral_generalization.py) действительно учит линейную модель и восстанавливает её, но не связывает обучение с attribution. [Live KnowledgeIntegration](../../tests/live/test_knowledge_integration.py) проверяет сохранение смысла и поведение интеграции; он не доказывает обучение qualitative mapper.

**Эти baseline-тесты не доказывают сквозное приобретение и использование новых описательных свойств.** Для новой реализации нужны отдельные результаты по трём путям и условиям приёмки выше.

## Исторические результаты описательного MVP

Добавлены source-backed `create_property` и `create_property_reference`, общий `summarize_property`, подключение к semantic tools и инструкции KnowledgeIntegration. [Числовая сводка](../../src/evertree/core/attribution_population.py) считает известные индивидуальные наблюдения и отдельные внешние distributions, применяет bands с включительными либо исключительными границами, сохраняет sources/BeliefData и ограничивает previews. Новые stores и обязательный train/refresh не добавлены.

[Component population tests](../../tests/component/test_attribution_population.py) проверяют три пути, единицы, повторные наблюдения, correction, временной режим, restore, source/population belief и отсутствие мутаций на чтении. [Component tool tests](../../tests/component/test_attribution_tools.py) проверяют публичные declarations, источники, retries, mixed boundaries и общий read gateway. Scripted/in-process проверки подтверждают механику; самостоятельный выбор представления моделью проверяется отдельно.

Фактические результаты после реализации:

- Последний `uv run pytest -q`: **634 passed**, 2.18 s, после всех production, harness и rubric правок.
- До добавления nearest один полный запуск дал **630 passed, 1 failed**: существующий Writer fixture в `test_integration_actions` завершил TraceStore run с ошибкой `run cannot finish before its events`. Целевой повтор дал **1 passed**, 0.04 s, затем тогдашний полный suite дал **631 passed**, 1.91 s, без изменений кода между этими повторами. Этот временной flake сохранён в отчёте; повторный успех не означает, что причина нестабильности устранена.
- Полный integration suite внутри sandbox: **128 passed, 9 failed, 19 skipped**, 50.46 s. Все девять отказов — `PermissionError` на loopback `127.0.0.1` в `test_codex_executor`, а не провал assertions поведения.
- Повтор всего `test_codex_executor` вне sandbox: **11 passed**, 0.15 s; два из этих cases уже прошли в первом запуске.
- Отдельный запуск `tests/integration/test_redis_search.py` с настроенным окружением: **19 passed**, 1.52 s, настоящий Redis Search и deterministic embeddings, собственные test namespaces. Это ранее пропущенные opt-in cases. В сумме **все 156 различных portable integration cases прошли** через полный запуск и два целевых повтора; незакрытых skip нет. Это не один полный зелёный прогон. Настоящие OpenAI embeddings дополнительно проверяются live-сценариями в их отдельном окружении.
- После последних nearest/prompt исправлений `tests/integration/test_operations_experiment.py`: **3 passed**, 3.27 s; все 156 cases целиком повторно не запускались.
- Native `test_program_llm`: **1 passed**, 0.96 s, вне enclosing sandbox; проверена регрессия transport-scoped tools.
- Ruff lint и проверка formatting: пройдены.
- `uv run python -m evertree.core.programs.layout`: пройдено.

Добавлен [live-тест трёх путей](../../tests/live/test_attribution_learning.py): отдельные рассказы 8/5/10 kg; клубный справочник с границами 6/9 kg; опубликованная таблица десяти собак со взвешенным средним 8.1 kg. Это дополнительные fixtures к числовым примерам плана. Начальный domain пуст; модель сама приобретает знания через настоящий KnowledgeIntegration. После приобретения stores сериализуются и восстанавливаются; отдельный вызов модели отвечает через реальные read tools без прежней истории. Поиск использует настоящий RedisSearchIndex и OpenAI embeddings, включая поиск сохранённого справочника. Независимый semantic review проверяет направление сравнения, границы обобщения и смысл источников.

Для запуска нужны обе opt-in переменные `EVERTREE_CODEX_INTEGRATION=1` и `EVERTREE_EMBEDDINGS_INTEGRATION=1`, настроенный Redis Search и credential для embeddings из репозиторного config/`.env`. Каждый pytest case использует собственный namespace; teardown удаляет только его indexes и keys. `attribution-learning.json` сохраняет source packets, transcripts, фактические calls, snapshots, runtime reports и независимый review, в том числе при неуспехе.

**Исходные три smoke-сценария прошли сквозную live-проверку:** отдельные наблюдения и frequency table — в прогоне 04, справочник — в прогоне 06 после исправления контракта имени. Это три успешных сценария по результатам двух запусков, а не один полный suite с результатом 3 passed. Результаты более поздних расширенных сценариев и версий приведены отдельно в матрице выше; прежний pass не закрывает обнаруженные там failures. Harness проверяет in-process semantic acquisition, настоящий retrieval и reuse после serialized restore. Полный scheduler/DBOS, worker recovery, durable backup и реальный перезапуск приложения остаются за его границами. Существующие integration результаты не превращают этот live harness в проверку всего агента.

Исходы итераций сохранены отдельно:

| Прогон | Фактический результат | Исправление или граница результата |
| --- | --- | --- |
| 02 | Обнаружен пробел в сохранении условий источника. | Исправлено сохранение conditions; этот прогон не подтверждает финальное поведение. |
| 03 | Первый кейс прошёл числовые проверки и дал корректное сравнение, но judge отклонил ответ. EmptyIndex не обеспечил поиск сохранённого справочника по смыслу. | Judge дополнен определениями полей направления сравнения; harness переведён на настоящий Redis Search с embeddings. |
| 04 | С настоящим retrieval: **2 passed, 1 failed**, 171.52 s. Отдельные наблюдения дали mean=23/3, таблица — weighted mean=8.1 и count=10; оба пути прошли hard assertions и semantic review после restore в новом контексте. Справочник не был сохранён: модель дважды предложила имя длиннее трёх слов и прекратила работу после отказов. | Реальный дефект контракта новых tools: ограничение имени 1–3 словами не было объявлено в schema. Оно добавлено, инструкция KI уточняет исправление и повтор отклонённой операции; добавлены две regression-проверки. Правильная метка в свободном ответе не компенсировала отсутствие reference record. |
| 05 | Повтор справочника после исправления успешно сохранил `Club weight guide` с boundaries 6/9. Новый reader получил HTTP 429 до первого tool call; **1 failed**, 17.88 s. | Приобретение знания подтверждено; ошибка инфраструктуры не считается ни semantic pass, ни доказательством дефекта reader. Исход сохранён; повтор выполнен без изменения кода. |
| 06 | Повтор только справочника: **1 passed, 2 deselected**, 49.48 s. Свежая модель прочитала сохранённое правило через `summarize_property`: 7 kg → MediumDog, `(6,9]`; observations count=0, mean=null. Источник сохранён, ответ условный; все четыре проверки semantic review пройдены. | После исправления schema подтверждены приобретение, retrieval и использование справочника. Production code тот же, что в прогоне 05; полного повторного запуска двух уже прошедших сценариев не было. |

Артефакты успешных сценариев и исходного отказа 04 находятся в `/private/tmp/evertree-attribution-live-04`, повтор справочника — в `/private/tmp/evertree-attribution-live-06`; ошибка rate limit сохранена в `/private/tmp/evertree-attribution-live-05`. В каждом case содержится `attribution-learning.json` с исходными сообщениями, фактическими вызовами и результатами. Эти локальные evidence files временные; для долгосрочного сравнения их нужно сохранять вместе с ревизией кода.
