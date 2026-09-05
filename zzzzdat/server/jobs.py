"""Background jobs (extracting, encoding, thumbnails) with polled progress."""
from __future__ import annotations

import threading
import uuid
from typing import Callable


class Job:
    def __init__(self, kind: str, **fields):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.state = "running"
        self.progress = 0.0
        self.error: str | None = None
        self.result = None
        self.fields = fields

    def set_progress(self, done: int, total: int) -> None:
        self.progress = done / max(total, 1)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "state": self.state, "progress": self.progress,
                "error": self.error, "result": self.result, **self.fields}


class Jobs:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Callable[[Job], object], **fields) -> Job:
        """Run `work(job)` on a thread; its return value becomes job.result."""
        job = Job(kind, **fields)
        with self._lock:
            self._jobs[job.id] = job
            # keep the registry small
            if len(self._jobs) > 200:
                for k in list(self._jobs)[:-100]:
                    del self._jobs[k]

        def run():
            try:
                job.result = work(job)
                job.state = "done"
                job.progress = 1.0
            except Exception as ex:  # surfaced to the client
                job.state = "error"
                job.error = f"{type(ex).__name__}: {ex}"

        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
