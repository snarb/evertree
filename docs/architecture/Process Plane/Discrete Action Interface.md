## Интерфейс дискретных действий

#topic_core

(def_id:: et.DiscreteActionInterface)
> [!definition] **Интерфейс дискретных действий** предоставляет агенту конечный список готовых команд внешней среды через Python-адаптер `ActionAdapter`. ^def-DiscreteActionInterface

Сознание или `exec`-[[Program Layer#Program|`Program`]] выбирает действие. Runtime связывает адаптер с задачей и предоставляет два способа вызова: tools `list_actions()` / `take_action(command)` и Python `ctx.actions.list()` / `ctx.actions.take(command)`. Оба используют один исполнительный путь.

### Контракт адаптера

Экземпляр `ActionAdapter` подключён к одной внешней сессии. Он получает список команд и переводит выбранную команду в вызов API.

(formal_id:: et.DiscreteActionInterface.schema)
```python
class ActionOption:
    command: JSONValue
    description: str | None = None

class ActionAdapter(Protocol):
    async def list_actions(self) -> list[ActionOption]: ...
    async def execute(
        self, command: JSONValue
    ) -> Literal["accepted", "rejected", "unknown"]: ...
```
^spec-DiscreteActionInterface

`command` — сериализуемое значение со всеми параметрами действия. Например, `{"type": "raise", "to": 100}` и `{"type": "raise", "to": 200}` — разные варианты покерной ставки. В Mario команда задаёт кнопки и число кадров. `description` при необходимости поясняет команду одной короткой фразой.

### Цикл работы

1. **Получить варианты.** Адаптер возвращает команды, доступные по текущим сведениям. Список и [[Memory#^def-Observation|`Observation`]] раскрывают только видимую агенту информацию; отдельные чтения могут относиться к разным состояниям.
2. **Выбрать.** Сознание или программа выбирает готовую `command`, при необходимости формируя [[Program Layer#Действия|`ActionCandidate`]], и проводит применимые [[Cognition and Attention#^actions-and-user-response|Verification и CommitmentControl]].
3. **Исполнить.** `take_action(command)` проверяет, что передан выданный вариант без изменения параметров. Runtime проверяет допуск, затем вызывает `adapter.execute(command)`. Если команда зависит от хода или версии состояния, адаптер включает это условие при выдаче и проверяет при исполнении. Без атомарной проверки API возможна гонка с изменением среды.
4. **Учесть результат.** `accepted` подтверждает приём команды, `rejected` — отказ, `unknown` — неизвестный исход после сбоя. Фактические последствия поступают как `Observation`; даже отказ может потратить время или вызвать штраф.

Команду можно намеренно выбирать снова, пока её условия действуют; повторы запросов подчиняются [[Cognition and Attention#^program-restart-continuation|общему учёту операций]]. Неизменный список не нужно запрашивать заново. Адаптер описывает длительность нажатия, течение времени между вызовами и эффекты `wait`/`reset`. Смена сессии делает прежний список недействительным.

Перед повтором при `unknown` исход сверяют с источником либо используют поддерживаемую API идемпотентность. [[Cognition and Attention#^agent-backup|Восстановление MVP]] допускает повтор внешнего действия после сбоя.

### Подключение и исполнение

Для новой среды агент готовит адаптер, проверяет команды, устаревшие условия, отказы и таймауты, затем runtime подключает его к задаче. Цель и ограничения берутся из [[Cognition and Attention#Goal, Task и спецификация задачи|`Task specification`]]. Переиспользуемую стратегию оформляют как `Program`, связанную с процессом через [[Process Ontology and Semantic Interface#PROGRAM_FOR_PROCESS|`PROGRAM_FOR_PROCESS`]]. Связи с [[Program Layer#Действия|`ActionConcept`]] добавляют в граф по необходимости.

Runtime хранит привязку к сессии и фактическому Git commit адаптера. Чтения и действия сохраняются по [[Cognition and Attention#^durable-program-execution|правилам DBOS]]; прямой tool call получает общий `exec`-workflow задачи. API и секреты доступны только за runtime-шлюзом. Replay использует сохранённые результаты; simulation и test выполняются вне live-среды.
