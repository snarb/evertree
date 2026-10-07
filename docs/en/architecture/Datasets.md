---
status: draft
target_version: next
---

## Purpose and Relationship to Memory
#concept #topic_core

(def_id:: entity.Dataset)
> [!definition] **Dataset** — a set of examples or aggregates prepared for a specific training or evaluation task. It defines which experience is used and how to interpret it. ^def-Dataset

Datasets let the agent:

- train a new process model on accumulated experience through [[Learning system#^def-TrainingDataset|TrainingDataset]];
- compare candidates on the same cases through [[Process Plane/Program Evaluation and Testing#EvaluationDataset|EvaluationDataset]] and check for improvement on independent data;
- reuse costly data preparation across multiple runs.

[[Memory#^def-Memory|Memory]] maintains a compact representation of experience for different future tasks: typical cases and their variation, rare groups, exceptions, and frequencies. A dataset selects material from it and prepares it for its purpose. Thus selection and compression mechanisms are shared, and a permanent dataset for every process is not required.

Sources include [[Memory#Observation|the agent's own and others' experience]], including accounts and external data, as well as simulations and generated scenarios. Provenance is preserved: a synthetic example does not become an observation of a real event.

Usually, [[Core data structures#Objects and References|references to memory]] are sufficient; a separate file is needed only when required by its use. A dataset may include experience that has not yet been compressed, or it may be assembled online.

## Versions and Usage Rules
#topic_core

Purpose determines a dataset's format, detail, size, coverage, and budget.

For comparability and reproducibility, the **composition, example contents, and preparation and evaluation rules** are fixed. Results apply to that version; repeating retrieval from changed memory does not reproduce it. Additions and corrections create a new version. Correcting source data may require revisiting previous evaluations and trained models.

**The number of retained examples is not a substitute for experience frequency.** If two clusters cover 98% of observations and six others cover 2%, rare cases may be given more space to improve coverage. The [[Memory#^experience-frequency|original frequencies]] are preserved, as are meaningful nuances and noise in frequent groups.

Evaluation on the original process accounts for selection and weights; cluster frequencies alone do not correct biased selection within clusters. A set of difficult cases answers its own question; it does not automatically measure quality across the entire process. Reusing an example or assigning it more weight does not create independent observations.

### Training and Evaluation Boundaries
#topic_core

Final evaluation data must not be used for candidate pre-fitting, its initial state, input preparation, or memory available to it: generalization built using those data also exposes them to training. Splits account for time and shared source episodes; different fragments or retellings of one case are not independent examples. During [[Process Plane/Program Evaluation and Testing#^evaluation-modes|evaluation of learning ability]], already evaluated outcomes may be used in subsequent steps under predefined rules.

If a model, initial state, or learning algorithm is tuned using a dataset's results, that dataset has already been used for tuning. A final conclusion requires held-out or subsequent cases under the [[Process Plane/Program Evaluation and Testing#^prediction-quality-protocol|quality evaluation protocol]]. After evaluation, the experience may be used for training; renaming or deleting the dataset does not make it independent again for that model.

## Lifecycle
#topic_core

**A dataset is created, updated, and deleted by a separate [[Cognition and Attention#Goal, Task, and Task Specification|Task]].** A collection task may accept new data for an extended period: the agent selects examples from memory manually and/or schedules automatic online selection with a budget and stopping condition. Selection occurs only while this Task is running, according to the [[Cognition and Attention#^sequential-tasks|shared ordering]]; while it waits, the runtime stores incoming data for later processing.

**A dataset is retained while that specific set is needed.** It is usually deleted after a one-time candidate comparison. Memory continues to accumulate and refine its representation of experience; a new slice can be prepared for the next task. Retention beyond that requires a reason: continuing experiments on the same composition, unfinished training, reproducing a significant decision, or preserving rare important data at the required level of detail.

For example, future LLM tuning may require a special format and more examples and detail than ordinary memory compression retains. A Task can protect the required data in advance and accumulate them from memory and/or online. Lost details cannot be recovered from a compressed representation. This scenario is allowed; the specific tuning mechanism is not defined here.

### Deletion

Deleting a dataset removes its retention requirements. Useful experience and data needed by other consumers remain under [[Memory#Retention Obligations|Memory rules]]. Compressing a source memory also does not delete an active case if it still needs that information.

A complete evaluation result that is retained requires its outcomes and trace. If a summary is sufficient, it is created as a new result; the old data are released in accordance with [[Memory#Provenance and Referential Integrity|referential integrity]] and [[Memory#Delete and deleted_protection_period|the general deletion process]].

Deleting data does not undo training already performed; correction of its contributions is governed by the [[Learning system#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|Learning System rules]].
