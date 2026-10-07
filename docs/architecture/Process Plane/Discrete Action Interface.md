## Discrete Action Interface

#topic_core

(def_id:: et.DiscreteActionInterface)
> [!definition] **Discrete Action Interface** provides the agent with a finite list of ready-made commands for an external environment through a Python `ActionAdapter`. ^def-DiscreteActionInterface

Consciousness or an `exec`-[[Program Layer#Program|`Program`]] selects an action. The runtime binds the adapter to a task and provides two invocation methods: tools `list_actions()` / `take_action(command)` and Python `ctx.actions.list()` / `ctx.actions.take(command)`. Both use the same execution path.

### Adapter Contract

An `ActionAdapter` instance is connected to one external session. It receives a list of commands and translates the selected command into an API call.

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

`command` is a serializable value containing all action parameters. For example, `{"type": "raise", "to": 100}` and `{"type": "raise", "to": 200}` are different poker bet options. In Mario, a command specifies buttons and the number of frames. `description` provides a short explanation of a command when needed.

### Operating Cycle

1. **Get options.** The adapter returns commands available from the current information. The list and [[Memory#^def-Observation|`Observation`]] reveal only information visible to the agent; separate reads may correspond to different states.
2. **Choose.** Consciousness or a program selects a ready-made `command`, optionally forming an [[Program Layer#Actions|`ActionCandidate`]], and performs applicable [[Cognition and Attention#^actions-and-user-response|Verification and CommitmentControl]].
3. **Execute.** `take_action(command)` checks that the supplied option was issued and its parameters have not changed. The runtime checks authorization, then calls `adapter.execute(command)`. If a command depends on a turn or state version, the adapter includes that condition when issuing it and checks it during execution. Without an atomic API check, the environment may change concurrently.
4. **Record the result.** `accepted` confirms that the command was accepted, `rejected` indicates refusal, and `unknown` indicates an unknown outcome after a failure. Actual consequences arrive as an `Observation`; even a rejection may consume time or incur a penalty.

A command may be intentionally selected again while its conditions remain valid; repeated requests follow the [[Cognition and Attention#^program-restart-continuation|shared operation accounting]]. An unchanged list does not need to be fetched again. The adapter describes button duration, time passing between calls, and the effects of `wait`/`reset`. A session change invalidates the previous list.

Before retrying after `unknown`, check the outcome with the source or use API idempotency if supported. [[Cognition and Attention#^agent-backup|MVP recovery]] allows an external action to be repeated after a failure.

### Connection and Execution

For a new environment, the agent prepares an adapter and checks its commands, stale conditions, rejections, and timeouts; the runtime then connects it to a task. The goal and constraints come from the [[Cognition and Attention#Goal, Task, and Task Specification|`Task specification`]]. A reusable strategy is implemented as a `Program` linked to its process through [[Process Ontology and Semantic Interface#PROGRAM_FOR_PROCESS|`PROGRAM_FOR_PROCESS`]]. Links to [[Program Layer#Actions|`ActionConcept`]] are added to the graph when needed.

The runtime stores the session binding and the adapter's actual Git commit. Reads and actions are persisted under the [[Cognition and Attention#^durable-program-execution|DBOS rules]]; a direct tool call receives the task's shared `exec` workflow. APIs and secrets are accessible only behind the runtime gateway. Replay uses stored results; simulation and testing run outside the live environment.
