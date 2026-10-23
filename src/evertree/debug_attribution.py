"""Debug natural attribution learning and later answers with real models in one process.

Open this file in PyCharm with the project interpreter and choose Debug. Edit OBSERVATIONS
and QUESTION below. Codex sign-in and the same .env settings as debug_integration.py are
required. No graph identities, categories, thresholds or model answers are supplied.

Each observation runs KnowledgeIntegration and EvidenceAssessment. The question then gets
semantic tools to discover or learn a suitable property. Assessment follows those writes;
a fresh read-only invocation answers from the retained graph and BeliefData.

Breakpoints work in AttributionSession.run/question, core/attribution_norms.py prepare_norm
and refresh_norm, core/attribution_evidence.py record/read_norm_property, and the ordinary
integration/assessment Programs. Interactive calls have no model deadline; automated callers
can pass timeout_seconds. Application scheduling, worker transport and restart are outside
this debug harness, as in debug_integration.py.

Artifacts under tmp/debug-attribution/<run>/ include inputs, per-stage graph/belief/attribution
snapshots, final readings, answer, calls, tools and model transcripts, including on failure.
"""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from evertree._application.prompts import NUMERIC_READ_INSTRUCTIONS
from evertree.common.integration_actions import SemanticTools
from evertree.common.logging_setup import configure_logging
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.graph import api as graph
from evertree.core.semantics import api as semantics
from evertree.core.semantics.tools import READ_TOOLS, TOOLS
from evertree.core.values import json_value
from evertree.debug_evidence_assessment import EvidenceSession
from evertree.debug_integration import load_debug_environment
from evertree.processes.learning.evidence_assessment._exec import run as assess
from evertree.processes.semantic_processing.knowledge_integration._exec import run as integrate

OBSERVATIONS = (
    "Собака Джек весит 8 кг.",
    "Сегодня я был у соседки Тани. Её такса весит 5 кг.",
    "Сегодня прочитал в газете о питбуле принцессы Дианы: он весил 10 кг.",
)
QUESTION = (
    "Каков средний вес собак по нашим наблюдениям? Кого из этих собак можно назвать "
    "маленькой, средней и большой по весу относительно остальных? Если собака весит "
    "7 кг, к какой категории она относится по этой же шкале? Последняя собака — "
    "только воображаемый пример, не новое наблюдение. Объясни уверенность и границы сравнения."
)
_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class AttributionSession(EvidenceSession):
    """Keep successive observations, learned criteria and answers inspectable in the IDE."""

    def __init__(
        self,
        output_dir: Path,
        *,
        observations=OBSERVATIONS,
        question=QUESTION,
        timeout_seconds: float | None = None,
    ):
        super().__init__(
            output_dir,
            task="Запомнить то, что пользователь рассказал, для последующих вопросов.",
            timeout_seconds=timeout_seconds,
        )
        self.observations, self.question_text = tuple(observations), question
        self.metadata["task_id"] = "debug-attribution"
        self.metadata["integration_context"]["task"]["id"] = "debug-attribution"
        self.stages = []
        self.preparation = self.answer = None

    def checkpoint(self, name):
        """Save the actual state after a phase, keeping earlier states available on failure."""
        directory = self.output_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        attribution = self.operations.attribution
        properties = []
        for identity, definition in attribution.definitions().items():
            properties.append(
                {
                    "property": json_value(self.graph.get(identity)),
                    "readings": [
                        {
                            "subject": node.id,
                            "name": node.name,
                            "reading": json_value(attribution.read_property(node.id, identity)),
                        }
                        for node in self.graph.nodes(kind="instance")
                        if attribution.applies(node.id, definition)
                    ],
                }
            )
        for filename, value in {
            "graph": self.graph.snapshot(),
            "beliefs": self.operations.beliefs.snapshot(),
            "attribution": attribution.snapshot(),
            "properties": properties,
        }.items():
            (directory / f"{filename}.json").write_text(
                json.dumps(json_value(value), ensure_ascii=False, indent=2), encoding="utf-8"
            )

    async def question(self, refs, *, learn):
        """Ask with shared semantic tools; only the preparation invocation can write."""

        async def read_step(method, payload, *, journal=True):
            return await self.step(method, payload, role="model", journal=journal)

        reader = SimpleNamespace(step=read_step, call=self.call)

        async def search(queries, *, kinds=None, limit=10):
            return await semantics.call_semantic_search(reader, queries, kinds=kinds, limit=limit)

        async def describe(subject):
            return await graph.describe(reader, subject)

        async def read(name, arguments):
            return await graph.read(reader, name, arguments)

        async def write(action, operation_key):
            if not learn:
                raise PermissionError("The answer invocation is read-only")
            return await semantics.write(
                self, action, operation_key=operation_key, experience_refs=refs
            )

        handler = SemanticTools(search=search, describe=describe, write=write, read=read)
        instructions = NUMERIC_READ_INSTRUCTIONS + (
            "\nPrepare an answer to the user's question using retained knowledge. You may "
            "create useful property definitions through the supplied tools. Cite supplied "
            "source refs for writes. Evidence assessment follows this preparation step."
            if learn
            else "\nAnswer the user's question in Russian using retained knowledge only. "
            "Use the assessed Profiles for actual subjects. This invocation cannot write."
        )
        prompt = {"question": self.question_text}
        if learn:
            prompt["source_refs"] = refs
        result = await self.llm(
            {
                "mode": "exec" if learn else "model",
                "instructions": instructions,
                "prompt": json.dumps(prompt, ensure_ascii=False),
                "output_schema": _ANSWER_SCHEMA,
            },
            tools=TOOLS if learn else READ_TOOLS,
            tool_handler=handler.handle,
        )
        return result["parsed"]["answer"]

    async def run(self):
        """Acquire each report, prepare a qualitative question, assess and answer afresh."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            missing = [
                name
                for name in (self.config.redis_url_env, self.config.openai_key_env)
                if not os.environ.get(name)
            ]
            if missing:
                raise RuntimeError("Для поиска задайте в .env или IDE: " + ", ".join(missing))
            for index, content in enumerate(self.observations):
                print(f"\nНаблюдение {index + 1}: {content}", flush=True)
                self.metadata["integration_operation_id"] = f"attribution-observation-{index}"
                refs = self.record_step(index, {"kind": "user", "content": content})
                self.experience_refs.extend(refs)
                stage = {"observation": content}
                self.stages.append(stage)
                stage["integration"] = (await integrate(self, refs))["result"]
                stage["assessment"] = (await assess(self, refs))["result"]
                self.checkpoint(f"observation-{index + 1}")

            print(f"\nВопрос: {self.question_text}", flush=True)
            refs = self.record_step(1, {"kind": "user", "content": self.question_text})
            self.experience_refs.extend(refs)
            self.metadata["integration_operation_id"] = "attribution-question"
            self.metadata["integration_context"]["task"]["specification"] = TaskSpecification(
                self.question_text
            ).to_dict()
            self.preparation = await self.question(self.experience_refs, learn=True)
            await semantics.refresh_property_norms(self)
            stage = {"question": self.question_text}
            self.stages.append(stage)
            stage["assessment"] = (await assess(self, refs))["result"]
            self.checkpoint("learned")
            self.answer = await self.question([], learn=False)
            return self.answer
        finally:
            try:
                self.checkpoint("final")
                for filename, value in {
                    "inputs": {"observations": self.observations, "question": self.question_text},
                    "trace": self.memory.snapshot(),
                    "stages": self.stages,
                    "answer": {"preparation": self.preparation, "answer": self.answer},
                    "calls": self.calls,
                    "tools": self.tool_calls(),
                }.items():
                    (self.output_dir / f"{filename}.json").write_text(
                        json.dumps(json_value(value), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            finally:
                try:
                    await self.index.close()
                finally:
                    await self.provider.close()


def main():
    """Run the editable dog observations and print the answer and artifact directory."""
    configure_logging()
    repository = Path(__file__).resolve().parents[2]
    session = AttributionSession(repository / "tmp" / "debug-attribution" / uuid4().hex[:12])
    load_debug_environment(repository, session.config)
    print(f"Codex: {session.config.remember.model}, {session.config.remember.effort}")
    print(f"Артефакты: {session.output_dir}", flush=True)
    print("\nОтвет:\n" + asyncio.run(session.run()))


if __name__ == "__main__":
    main()
