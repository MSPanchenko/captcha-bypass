"""Task queue and result storage."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Task:
    """Task data structure."""

    id: str
    url: str
    timeout: int
    proxy: dict[str, str] | None  # {"server": "...", "username": "...", "password": "..."}
    # Validation conditions (OR logic - success if any condition matches)
    success_texts: list[str] = field(default_factory=list)
    success_selectors: list[str] = field(default_factory=list)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    cancel_requested: bool = False
    result: dict[str, Any] | None = None


class TaskStorage:
    """In-memory task queue and result storage with FIFO queue."""

    def __init__(self, result_ttl: int, max_queue_size: int = 1000) -> None:
        self.result_ttl = result_ttl
        self.max_queue_size = max_queue_size
        self._tasks: dict[str, Task] = {}
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=max_queue_size)
        self._lock = asyncio.Lock()

    @property
    def queue_size(self) -> int:
        """Current queue size (pending tasks waiting for processing)."""
        return self._queue.qsize()

    def create_task(
        self,
        url: str,
        timeout: int,
        proxy: dict[str, str] | None = None,
        success_texts: list[str] | None = None,
        success_selectors: list[str] | None = None,
    ) -> str:
        """Create a new task and enqueue it for processing.

        Returns the task_id. Raises asyncio.QueueFull if queue is at capacity.

        NOTE: No await between dict write and put_nowait(), so no context switch
        within this method. Unlocked access is safe because other async methods
        only mutate _tasks inside `async with self._lock` blocks.
        WARNING: Not thread-safe. Use only within single asyncio event loop.
        """
        task_id = str(uuid.uuid4())

        task = Task(
            id=task_id,
            url=url,
            timeout=timeout,
            proxy=proxy,
            success_texts=success_texts or [],
            success_selectors=success_selectors or [],
        )

        # Store task first (dict operations are atomic in CPython)
        self._tasks[task_id] = task

        # Try to enqueue - raises QueueFull if at capacity
        try:
            self._queue.put_nowait(task_id)
        except asyncio.QueueFull:
            # Rollback: remove task from storage
            del self._tasks[task_id]
            raise

        logger.info(f"Task {task_id} created and enqueued")
        return task_id

    async def get_next_task(self) -> Task | None:
        """Get the next task from the queue. Blocks until a task is available.

        Returns None if the task was cancelled/deleted while in queue,
        or if a shutdown sentinel (None) was received.
        Workers should continue on None (skip cancelled) or break on shutdown.

        NOTE: task_done() not called - queue.join() is not used.
        Shutdown relies on: (1) sentinel values (None) via send_shutdown_signal(),
        (2) asyncio.wait() with timeout in stop_workers() as safety net,
        (3) _shutdown_event flag for workers to exit gracefully.
        """
        task_id = await self._queue.get()

        # Shutdown sentinel
        if task_id is None:
            return None

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                # Task was deleted (cancelled) while waiting in queue
                logger.debug(f"Task {task_id} was cancelled while in queue")
                return None

            if task.status != "pending":
                # Task status changed (shouldn't happen normally)
                logger.warning(f"Task {task_id} has unexpected status: {task.status}")
                return None

            # Return a copy to avoid data race - worker works with snapshot
            return replace(task)

    async def send_shutdown_signal(self, num_workers: int) -> None:
        """Send shutdown sentinels to stop all workers.

        Uses put_nowait() to avoid blocking if queue is full.
        Workers that don't receive sentinel will be force-cancelled by
        stop_workers() timeout anyway.
        """
        sentinels_sent = 0
        for _ in range(num_workers):
            try:
                self._queue.put_nowait(None)
                sentinels_sent += 1
            except asyncio.QueueFull:
                logger.warning(
                    f"Queue full during shutdown ({sentinels_sent}/{num_workers} "
                    f"sentinels sent). Remaining workers will be force-cancelled."
                )
                break

        if sentinels_sent > 0:
            logger.debug(f"Sent {sentinels_sent}/{num_workers} shutdown sentinels")

    async def get_task(self, task_id: str) -> Task | None:
        """Get task by ID. Returns a copy to avoid data race."""
        async with self._lock:
            task = self._tasks.get(task_id)
            return replace(task) if task else None

    async def set_running(self, task_id: str) -> bool:
        """Set task status to running. Called when worker starts processing.

        Returns True if status was set, False if task was cancelled/deleted.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == "pending":
                task.status = "running"
                task.started_at = time.time()
                logger.debug(f"Task {task_id} now running")
                return True
            # Task was deleted (cancelled) or status changed
            logger.debug(f"Task {task_id} not set to running (cancelled or missing)")
            return False

    async def get_result(self, task_id: str) -> dict[str, Any] | None:
        """Get task result in API format."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                # Task not found - return not_found status
                return {"status": "not_found", "error": None, "data": None}

            if task.status == "pending":
                return {"status": "pending", "error": None, "data": None}

            if task.status == "running":
                return {"status": "running", "error": None, "data": None}

            # Task is completed - check if it was successful or had an error
            if task.result:
                error_info = task.result.get("error")
                if error_info:
                    # Error case - error is an object with code and message
                    return {"status": "error", "error": error_info, "data": None}
                # Success case
                return {"status": "completed", "error": None, "data": task.result.get("data")}

            # Completed but no result (shouldn't happen normally)
            return {"status": "completed", "error": None, "data": None}

    async def complete_task(self, task_id: str, result: dict[str, Any]) -> None:
        """Mark task as completed with result."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "completed"
                task.completed_at = time.time()
                task.result = result
                logger.info(f"Task {task_id} completed")

    async def cancel_task(self, task_id: str) -> tuple[bool, str]:
        """Cancel or delete a task.

        For pending tasks: removes from storage (task will be skipped when dequeued).
        For running tasks: sets cancel_requested flag for worker to check.
        For completed tasks: deletes the result.
        """
        async with self._lock:
            task = self._tasks.get(task_id)

            if task is None:
                return False, "Task not found"

            if task.status == "pending":
                # Task removed from storage but task_id stays in queue until worker
                # dequeues it. This is intentional - get_next_task() returns None for
                # orphaned IDs (worker skips them). IDs are processed in FIFO order
                # with no additional overhead. No need for complex queue cleanup.
                del self._tasks[task_id]
                return True, "Task cancelled (was pending)"

            if task.status == "running":
                task.cancel_requested = True
                return True, "Task marked for cancellation"

            if task.status == "completed":
                del self._tasks[task_id]
                return True, "Result deleted"

            return False, f"Cannot cancel task in status: {task.status}"

    async def is_cancel_requested(self, task_id: str) -> bool:
        """Check if task cancellation was requested."""
        async with self._lock:
            task = self._tasks.get(task_id)
            # If task exists, check its cancel_requested flag
            # If task was deleted (e.g., cancelled pending), return True
            return task.cancel_requested if task else True

    async def cleanup_loop(self) -> None:
        """Background task to cleanup expired results."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def _cleanup_expired(self) -> None:
        """Remove completed tasks older than result_ttl."""
        now = time.time()
        expired_tasks = []

        async with self._lock:
            for task_id, task in self._tasks.items():
                if task.status == "completed" and task.completed_at:
                    if now - task.completed_at > self.result_ttl:
                        expired_tasks.append(task_id)
                # Do NOT delete running or pending tasks:
                # - Running: worker still holds a reference and will call complete_task()
                # - Pending: waiting in queue, will become running soon
                # Both will eventually become completed and get cleaned up by TTL.
                # If worker dies, task stays orphaned but this is better than
                # silently losing results.

            for task_id in expired_tasks:
                del self._tasks[task_id]

        if expired_tasks:
            logger.info(f"Cleaned up {len(expired_tasks)} expired tasks")
