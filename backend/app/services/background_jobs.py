"""Run slow post-payment work after the HTTP response, and let the screen follow it.

Approving a payment used to make the browser wait for the whole chain: Zoho invoice,
several Bitrix updates and an email. The money is saved first; the rest runs here and
the staff screen polls `GET /api/staff/jobs/{key}` to show progress and any problem.

Jobs live in this process's memory. A restart drops the status (not the payment), and
the "Create & send invoice" button re-runs anything that did not finish.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_PROBLEM = "problem"  # saved, but one of the follow-up steps failed
STATE_FAILED = "failed"  # the job itself crashed

_KEEP_SECONDS = 30 * 60

# Overridable in tests so a job uses the test database instead of the real one.
session_factory: Callable[[], Any] | None = None


@dataclass
class Job:
    key: str
    label: str
    state: str = STATE_RUNNING
    problems: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "problems": self.problems,
            "seconds": round((self.finished_at or time.time()) - self.started_at, 1),
        }


_jobs: dict[str, Job] = {}
_tasks: set[asyncio.Task] = set()


def get_job(key: str) -> Job | None:
    return _jobs.get(key)


def reset_jobs() -> None:
    _jobs.clear()


def open_session():
    """A new database session for background work (the request's session is closed)."""
    if session_factory is not None:
        return session_factory()
    from app.db.session import SessionLocal

    return SessionLocal()


def _prune() -> None:
    cutoff = time.time() - _KEEP_SECONDS
    for key in [k for k, j in _jobs.items() if j.finished_at and j.finished_at < cutoff]:
        _jobs.pop(key, None)


def spawn(key: str, label: str, runner: Callable[[], Awaitable[list[str] | None]]) -> Job:
    """Start `runner` in the background. It returns a list of problems (or None)."""
    _prune()
    job = Job(key=key, label=label)
    _jobs[key] = job

    async def _run() -> None:
        try:
            problems = await runner()
            job.problems = list(problems or [])
            job.state = STATE_PROBLEM if job.problems else STATE_DONE
        except Exception as exc:  # noqa: BLE001
            logger.exception("Background job crashed | key=%s", key)
            job.problems = [f"{type(exc).__name__}: {exc}"[:300]]
            job.state = STATE_FAILED
        finally:
            job.finished_at = time.time()
            logger.info(
                "Background job finished | key=%s state=%s seconds=%.1f problems=%s",
                key,
                job.state,
                job.finished_at - job.started_at,
                job.problems or "-",
            )

    task = asyncio.get_running_loop().create_task(_run())
    _tasks.add(task)  # keep a reference so the task is not garbage-collected mid-run
    task.add_done_callback(_tasks.discard)
    return job
