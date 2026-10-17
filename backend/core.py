"""Agent orchestration, model access, project files, and test execution."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path, PureWindowsPath

import httpx

from backend.database import q
from backend.settings import (
    BASE,
    FAST_BUILD,
    IMAGE,
    KEY,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_TIMEOUT_SECONDS,
    MAX_FIX,
    MODEL,
    NEED_OK,
    PROVIDER,
    SANDBOX,
    WS,
)

TERMINAL = {"passed", "failed", "cancelled", "error"}
APPROVALS = {}


def emit(pid, agent, kind, message, data=None):
    q(
        "insert into events(project_id,ts,agent,kind,message,data) values(?,?,?,?,?,?)",
        (pid, time.time(), agent, kind, message, json.dumps(data) if data else None),
    )


def setst(pid, status):
    q("update projects set status=? where id=?", (status, pid))


def llm(system, user):
    if PROVIDER == "anthropic":
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            timeout=LLM_TIMEOUT_SECONDS,
            headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"},
            json={
                "model": MODEL,
                "max_tokens": 8000,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        result = response.json()
        return result["content"][0]["text"], result["usage"]["input_tokens"] + result["usage"]["output_tokens"]

    response = httpx.post(
        f"{BASE}/chat/completions",
        timeout=LLM_TIMEOUT_SECONDS,
        headers={"Authorization": f"Bearer {KEY}"},
        json={
            "model": MODEL,
            "temperature": 0.2,
            **({"max_tokens": LLM_MAX_OUTPUT_TOKENS} if FAST_BUILD else {}),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
    )
    response.raise_for_status()
    result = response.json()
    return result["choices"][0]["message"]["content"], result.get("usage", {}).get("total_tokens", 0)


class Cancelled(Exception):
    pass


def check(pid):
    rows = q("select status from projects where id=?", (pid,))
    if rows and rows[0]["status"] == "cancelled":
        raise Cancelled()


def agent(pid, name, system, user):
    check(pid)
    emit(pid, name, "start", f"{name} started")
    started = time.time()
    text, tokens = llm(system, user)
    q("update projects set tokens=tokens+? where id=?", (tokens, pid))
    emit(pid, name, "done", f"{name} finished in {time.time()-started:.1f}s ({tokens} tokens)", {"tokens": tokens})
    return text


def safe(path):
    path = path.strip().strip("`").replace("\\", "/").lstrip("/")
    windows_path = PureWindowsPath(path)
    if (
        not path
        or windows_path.drive
        or windows_path.is_absolute()
        or ".." in path.split("/")
    ):
        raise ValueError(f"unsafe path: {path}")
    return path


def parse_files(text):
    files = {}
    for match in re.finditer(r"###\s*FILE:\s*(.+?)\n```[\w+-]*\n(.*?)\n```", text, re.S):
        try:
            files[safe(match.group(1))] = match.group(2) + "\n"
        except ValueError:
            continue
    return files


def parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def write_files(pid, files):
    project_root = (WS / pid).resolve()
    for path, content in files.items():
        target = (project_root / safe(path)).resolve()
        if project_root not in target.parents:
            raise ValueError(f"unsafe path: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return list(files)


def list_files(pid):
    directory = WS / pid
    if not directory.exists():
        return []
    return sorted(
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
        and path.name != "conftest.py"
    )


def snapshot(pid, limit=30000):
    content = ""
    for path in list_files(pid):
        content += f"### FILE: {path}\n```\n{(WS / pid / path).read_text(errors='replace')}\n```\n"
    return content[:limit]


def _limits():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 << 20, 50 << 20))


def run_tests(pid):
    directory = (WS / pid).resolve()
    if SANDBOX == "docker":
        command = [
            "docker", "run", "--rm", "--network", "none", "--memory", "512m", "--cpus", "1",
            "--pids-limit", "128", "-v", f"{directory}:/w", "-w", "/w", IMAGE,
            "pytest", "-q", "--tb=short", "-p", "no:cacheprovider",
        ]
        kwargs = {}
    else:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not re.search(r"KEY|TOKEN|SECRET|PASSWORD", key, re.I)
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"]
        kwargs = {"env": environment, "preexec_fn": _limits} if os.name == "posix" else {"env": environment}
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=90, **kwargs)
        return result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    except subprocess.TimeoutExpired:
        return False, "Test run timed out after 90s"
    except Exception as error:
        return False, f"Sandbox error: {error}"


FMT = "Output files ONLY in this exact format, nothing else:\n### FILE: path/to/file.py\n```python\n<full file content>\n```\n"
PLANNER = (
    "You are the Project Manager. Turn the idea into a plan for a small PYTHON project (standard library only, no network, "
    'testable with pytest). Reply with ONLY JSON: {"summary":str,"tasks":[{"title":str,"owner":"engineer|tester|reviewer"}],'
    '"files":[str],"acceptance":[str],"risks":[str],"uncertain":[str]} . Acceptance criteria must be concrete and testable. '
    "List in 'uncertain' any claim or assumption you are not sure about."
)
ENGINEER = (
    "You are a senior Python engineer. Implement the plan. Flat modules at repo root (no src/), Python 3.11, stdlib only. "
    "Include README.md. " + FMT
)
TESTER = (
    "You are a test engineer. Write pytest tests in tests/ that verify EVERY acceptance criterion against the existing code "
    "(import modules from repo root). Test behavior, include edge cases. " + FMT
)
FIXER = (
    "You are the engineer fixing failing tests. Fix the root cause. NEVER delete tests or weaken assertions just to pass; "
    "only change a test if it is objectively wrong, and say why in a comment. Output only the files you change, in full. " + FMT
)
REVIEWER = (
    "You are a strict code reviewer. Given the plan, code and REAL test results, write a markdown review: Verdict "
    "(approve/changes needed), correctness issues, security issues, test-quality gaps, and unverified claims. Be specific; cite files."
)
FAST_ENGINEER = (
    "Build a compact, working MVP of the requested Python project using the standard library only. "
    "Implement only the core requested behavior; omit optional features and lengthy explanations. "
    "Include runnable source, a brief README.md, and tests/test_app.py with 3 focused pytest tests in this "
    "same response. Include every import used by the tests. Tests must check real behavior, not implementation "
    "details. Keep each file concise. Do not omit the test file, write fake test reports, or claim tests passed. "
    "Output every file in the required FILE format. "
    + FMT
)


def quick_plan(idea):
    return {
        "summary": f"Build the requested Python project: {idea.strip()}",
        "tasks": [
            {"title": "Implement the requested features", "owner": "engineer"},
            {"title": "Add behavior-focused automated tests", "owner": "tester"},
            {"title": "Run pytest and repair any failures", "owner": "engineer"},
            {"title": "Review the implementation and test results", "owner": "reviewer"},
        ],
        "files": ["Python source files", "tests/", "README.md"],
        "acceptance": [
            "The requested project behavior is implemented.",
            "Automated tests cover core behavior and relevant edge cases.",
            "The project's pytest suite runs successfully.",
        ],
        "risks": [],
        "uncertain": ["The exact interface and optional features are inferred from the project description."],
    }


def contains_tests(files):
    for path in files:
        normalized = path.replace("\\", "/").casefold()
        name = normalized.rsplit("/", 1)[-1]
        if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
            return True
    return False


def fast_review(passed, output, files):
    return (
        "# Automated review\n\n"
        f"- Verdict: {'ready for review' if passed else 'needs fixes'}\n"
        f"- Pytest result: **{'passed' if passed else 'failed'}**\n"
        f"- Files generated: {', '.join(files)}\n\n"
        "This fast-build report uses the actual pytest result. A separate AI code/security review was skipped "
        "to reduce local-model latency; passing tests do not guarantee the absence of defects.\n\n"
        "## Test output\n\n```text\n"
        f"{output}\n"
        "```\n"
    )


def pipeline(pid):
    try:
        project = q("select * from projects where id=?", (pid,))[0]
        directory = WS / pid
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "conftest.py").write_text("")
        setst(pid, "running")
        if FAST_BUILD:
            emit(pid, "planner", "start", "Creating a quick local plan")
            plan = quick_plan(project["idea"])
            emit(pid, "planner", "done", "Plan ready (no model call)")
        else:
            plan = parse_json(
                agent(
                    pid,
                    "planner",
                    PLANNER,
                    f"Idea: {project['idea']}\nConstraints: {project['constraints'] or 'none'}",
                )
            )
        q("update projects set plan=? where id=?", (json.dumps(plan), pid))
        emit(pid, "planner", "plan", f"Plan ready: {len(plan.get('tasks', []))} tasks, {len(plan.get('acceptance', []))} acceptance criteria")
        if NEED_OK:
            event = threading.Event()
            APPROVALS[pid] = (event, {})
            setst(pid, "awaiting_approval")
            emit(pid, "system", "approval", "Waiting for your approval of the plan")
            event.wait(timeout=3600)
            if not APPROVALS.pop(pid)[1].get("ok"):
                setst(pid, "cancelled")
                emit(pid, "system", "info", "Plan rejected")
                return
            setst(pid, "running")
            emit(pid, "system", "info", "Plan approved")

        context = (
            f"Idea: {project['idea']}\nConstraints: {project['constraints']}\nPlan: {json.dumps(plan)}"
        )
        engineer_prompt = FAST_ENGINEER if FAST_BUILD else ENGINEER
        files = write_files(pid, parse_files(agent(pid, "engineer", engineer_prompt, context)))
        if not files:
            raise ValueError("Engineer produced no files")
        emit(pid, "engineer", "files", f"Wrote {len(files)} files: {', '.join(files)}")
        if FAST_BUILD and contains_tests(files):
            tests = [path for path in files if contains_tests([path])]
            emit(pid, "tester", "start", "Using implementation-generated tests")
            emit(pid, "tester", "done", f"Using tests generated with implementation: {', '.join(tests)}")
        else:
            tests = write_files(
                pid,
                parse_files(agent(pid, "tester", TESTER, context + "\nCODE:\n" + snapshot(pid))),
            )
        if not contains_tests(tests):
            raise ValueError("Tester produced no pytest test files")
        if not (FAST_BUILD and contains_tests(files)):
            emit(pid, "tester", "files", f"Wrote tests: {', '.join(tests)}")

        passed, output = False, ""
        for round_number in range(MAX_FIX + 1):
            check(pid)
            emit(pid, "tester", "start", f"Running pytest in sandbox ({SANDBOX}), round {round_number}")
            passed, output = run_tests(pid)
            emit(
                pid,
                "tester",
                "test",
                "Tests PASSED" if passed else "Tests FAILED",
                {"passed": passed, "output": output, "round": round_number},
            )
            if passed or round_number == MAX_FIX:
                break
            q("update projects set fix_rounds=? where id=?", (round_number + 1, pid))
            fixed = write_files(
                pid,
                parse_files(agent(pid, "engineer", FIXER, f"{context}\nCODE:\n{snapshot(pid)}\nTEST OUTPUT:\n{output}")),
            )
            emit(pid, "engineer", "files", f"Fix round {round_number+1}: changed {', '.join(fixed) or 'nothing'}")

        if FAST_BUILD:
            emit(pid, "reviewer", "start", "Preparing an automated test-result review")
            review = fast_review(passed, output, list_files(pid))
            emit(pid, "reviewer", "done", "Automated review ready (no model call)")
        else:
            review = agent(
                pid, "reviewer", REVIEWER,
                f"{context}\nTESTS PASSED: {passed}\nTEST OUTPUT:\n{output}\nCODE:\n{snapshot(pid)}",
            )
        (directory / "REVIEW.md").write_text(review)
        project = q("select * from projects where id=?", (pid,))[0]
        report = (
            f"# Synapse report: {project['name']}\n\n- Result: **{'PASSED' if passed else 'FAILED'}**\n"
            f"- Fix rounds: {project['fix_rounds']}\n- Tokens used: {project['tokens']}\n"
            f"- Model: {MODEL}\n- Sandbox: {SANDBOX}\n\n## Plan\n{plan.get('summary', '')}\n\n"
            "## Acceptance criteria\n"
            + "\n".join(f"- {criterion}" for criterion in plan.get("acceptance", []))
            + f"\n\n## Final test output\n```\n{output}\n```\n\n## Review\n{review}\n"
        )
        (directory / "REPORT.md").write_text(report)
        setst(pid, "passed" if passed else "failed")
        emit(pid, "system", "status", "Done: tests passed" if passed else "Done: tests still failing")
    except Cancelled:
        emit(pid, "system", "info", "Cancelled")
    except Exception as error:
        setst(pid, "error")
        emit(pid, "system", "error", f"{type(error).__name__}: {error}")
