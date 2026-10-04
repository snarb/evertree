"""Local command-line transport for EverTree's Python API."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .application import EverTree
from .core.codex_provider import CodexProvider
from .core.graph import json_value
from .core.sandbox import check_sandbox


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="evertree", description="Local EverTree agent")
    root.add_argument(
        "--home", type=Path, default=Path.cwd(), help="Agent directory (default: current directory)"
    )
    root.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    commands = root.add_subparsers(dest="command", required=True)

    def command(name: str, help: str):
        result = commands.add_parser(name, help=help)
        result.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        return result

    command("init", "Initialize the graph, seed Programs and local state")
    command("doctor", "Check Codex authentication/model and native worker containment")
    command("chat", "Start an interactive conversation")
    run = command("run", "Run a request; read stdin when no prompt is supplied")
    run.add_argument("prompt", nargs="?", help="The complete request")
    run.add_argument("--task", help="Continue an existing open Task")
    run.add_argument(
        "--max-minutes", type=float, help="Explicit user hard limit for total active minutes"
    )

    tasks = command("tasks", "Inspect, resume or cancel persisted Tasks")
    task_commands = tasks.add_subparsers(dest="task_command", required=True)
    task_commands.add_parser("list", help="List all Tasks")
    show = task_commands.add_parser("show", help="Show a Task and its budget/progress")
    show.add_argument("task_id")
    resume = task_commands.add_parser("resume", help="Resume a saved Task")
    resume.add_argument("task_id")
    resume.add_argument("text", nargs="?", help="New input or a clarification")
    resume.add_argument("--max-minutes", type=float, help="Explicit replacement hard limit")
    cancel = task_commands.add_parser("cancel", help="Stop an open Task and retain its history")
    cancel.add_argument("task_id")

    graph = command("graph", "Inspect semantic nodes")
    graph.add_argument("query", nargs="?", help="Case-insensitive name fragment")
    graph.add_argument("--id", type=int, dest="node_id")
    graph.add_argument("--kind", help="Node kind filter")
    memory = command("memory", "Retrieve grouped experience with provenance")
    memory.add_argument("query", nargs="?", default="")
    memory.add_argument("--limit", type=_positive, default=10)
    traces = command("traces", "Inspect ProgramRuns and their immutable trace events")
    traces.add_argument("run_id", nargs="?", type=int)
    command("programs", "List installed reusable Programs")
    backup = command("backup", "Create a consistent agent backup")
    backup.add_argument("--list", action="store_true", dest="list_backups")
    restore = command("restore", "Restore a complete agent backup")
    restore.add_argument(
        "backup", nargs="?", help="Backup name/path (default: latest complete backup)"
    )
    return root


def emit(value: Any) -> None:
    print(json.dumps(json_value(value), ensure_ascii=False, indent=2, allow_nan=False), flush=True)


async def approve(request: dict[str, Any]) -> bool:
    """No assumed consent: unattended invocation denies boundary expansion."""
    if not sys.stdin.isatty():
        return False
    print("EverTree requests approval for:", file=sys.stderr)
    print(json.dumps(json_value(request), ensure_ascii=False, indent=2), file=sys.stderr)
    answer = await asyncio.to_thread(input, "Allow this action? Type yes: ")
    return answer.strip().casefold() == "yes"


async def doctor(home: Path) -> tuple[dict[str, Any], int]:
    provider = CodexProvider(state_dir=home / ".state" / "codex-runtime")
    try:
        provider_status = await provider.doctor()
    except (RuntimeError, OSError, ValueError) as error:
        provider_status = {"available": False, "error": str(error)}
    finally:
        await provider.close()
    try:
        sandbox_status = await asyncio.to_thread(check_sandbox, home / ".state" / "doctor")
        required = ("app_container", "read_denied", "write_denied", "scratch_writable")
        sandbox_status = {
            "available": all(sandbox_status.get(name) is True for name in required),
            **sandbox_status,
        }
    except (RuntimeError, OSError, ValueError) as error:
        sandbox_status = {"available": False, "error": str(error)}
    available = bool(
        provider_status.get("available")
        and provider_status.get("native_coding_available")
        and sandbox_status.get("available")
    )
    return {
        "ready": available,
        "provider": provider_status,
        "sandbox": sandbox_status,
    }, 0 if available else 1


async def consume(agent: EverTree, task_id: str, *, as_json: bool) -> tuple[dict[str, Any], int]:
    answer = ""
    async for event in agent.events():
        if event.task_id != task_id:
            continue
        if event.kind == "answer":
            answer = event.data["text"]
            if not as_json:
                try:
                    print(answer, flush=True)
                except (BrokenPipeError, OSError):
                    await agent.acknowledge_delivery(event.data["delivery_id"], delivered=False)
                    raise
            # JSON mode still delivers the actual answer before acknowledging it.
            else:
                print(
                    json.dumps(
                        {"event": "answer", "task_id": task_id, "answer": answer},
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    flush=True,
                )
            await agent.acknowledge_delivery(event.data["delivery_id"])
        elif event.kind in {"task_completed", "task_failed", "task_waiting", "task_cancelled"}:
            result = {
                "task_id": task_id,
                "status": agent.tasks.get(task_id).status,
                "answer": answer,
                **event.data,
            }
            if as_json:
                print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
            else:
                print(f"Task {task_id}: {result['status']}", file=sys.stderr, flush=True)
                if result.get("reason") and result["status"] == "failed":
                    print(result["reason"], file=sys.stderr, flush=True)
            return result, 1 if result["status"] == "failed" else 0
    raise RuntimeError("Agent stopped without a task outcome")


def _limits(minutes: float | None) -> dict[str, float] | None:
    if minutes is None:
        return None
    if not 0 < minutes < float("inf"):
        raise ValueError("An explicit hard limit must be finite and positive")
    return {"active_time_minutes": minutes}


async def _chat(agent: EverTree, *, as_json: bool) -> int:
    if not sys.stdin.isatty():
        raise ValueError("Interactive chat requires a terminal; use 'run' with stdin")
    pending_task: str | None = None
    if not as_json:
        print("EverTree. Enter /quit to exit, /new to start a separate Task.", file=sys.stderr)
    while True:
        try:
            request = await asyncio.to_thread(input, "> ")
        except EOFError:
            return 0
        if request.strip() in {"/quit", "/exit"}:
            return 0
        if request.strip() == "/new":
            pending_task = None
            continue
        if not request.strip():
            continue
        state = await agent.submit(request, task_id=pending_task)
        result, _ = await consume(agent, state.id, as_json=as_json)
        pending_task = state.id if result["status"] == "waiting" else None


async def dispatch(args: argparse.Namespace) -> int:
    home = args.home.expanduser().resolve()
    if args.command == "doctor":
        result, code = await doctor(home)
        emit(result)
        return code
    async with EverTree(home, approval_handler=approve) as agent:
        if args.command == "init":
            emit(
                {
                    "home": str(home),
                    "state": str(agent.state_dir),
                    "programs": len(agent.programs()),
                }
            )
        elif args.command == "run":
            prompt = args.prompt
            if prompt is None:
                if sys.stdin.isatty():
                    raise ValueError("Supply a request or pipe it to stdin")
                prompt = sys.stdin.read()
            if args.task:
                state = await agent.resume(args.task, prompt, hard_limits=_limits(args.max_minutes))
            else:
                state = await agent.submit(
                    prompt, task_id=None, hard_limits=_limits(args.max_minutes)
                )
            _, code = await consume(agent, state.id, as_json=args.json)
            return code
        elif args.command == "chat":
            return await _chat(agent, as_json=args.json)
        elif args.command == "tasks":
            if args.task_command == "list":
                emit([task.to_dict() for task in agent.tasks.all()])
            elif args.task_command == "show":
                emit(agent.tasks.get(args.task_id).to_dict())
            elif args.task_command == "cancel":
                await agent.cancel(args.task_id)
                emit(agent.tasks.get(args.task_id).to_dict())
            elif args.task_command == "resume":
                state = await agent.resume(
                    args.task_id, args.text, hard_limits=_limits(args.max_minutes)
                )
                _, code = await consume(agent, state.id, as_json=args.json)
                return code
        elif args.command == "graph":
            if args.node_id is not None:
                emit(agent.graph.get(args.node_id))
            else:
                nodes = agent.graph.nodes(kind=args.kind) if args.kind else agent.graph.nodes()
                if args.query:
                    nodes = [
                        node for node in nodes if args.query.casefold() in node.name.casefold()
                    ]
                emit(nodes)
        elif args.command == "memory":
            emit(agent.memory.retrieve(args.query, limit=args.limit))
        elif args.command == "traces":
            if args.run_id is None:
                emit(agent.memory.runs)
            else:
                emit(
                    {
                        "run": agent.memory.get_run(args.run_id),
                        "events": [
                            event
                            for event in agent.memory.events
                            if event.program_run == args.run_id
                        ],
                    }
                )
        elif args.command == "programs":
            emit(agent.programs())
        elif args.command == "backup":
            if args.list_backups:
                emit([str(path) for path in agent.backups.list()])
            else:
                path = await agent.backup()
                if path is None:
                    raise RuntimeError("No consistent backup boundary is available")
                emit({"backup": str(path)})
        elif args.command == "restore":
            selected = Path(args.backup) if args.backup else None
            if selected is not None and not selected.is_absolute():
                selected = agent.backups.root / selected
            await agent.restore(selected)
            emit({"restored": str(selected) if selected else "latest", "home": str(home)})
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return asyncio.run(dispatch(args))
    except KeyboardInterrupt:
        print("Interrupted; saved task state remains available.", file=sys.stderr)
        return 130
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        if args.json:
            emit({"error": str(error), "type": type(error).__name__})
        else:
            print(f"EverTree: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
