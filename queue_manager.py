import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import time

class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class DownloadJob:
    job_id: str
    user_id: int
    url: str
    media_type: str
    status: JobStatus
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None

class QueueManager:
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.jobs: Dict[str, DownloadJob] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        
    async def start(self):
        """Start queue processing."""
        self._running = True
        asyncio.create_task(self._process_queue())
    
    async def stop(self):
        """Stop queue processing."""
        self._running = False
        # Cancel all active tasks
        for task in self.active_tasks.values():
            task.cancel()
        await asyncio.gather(*self.active_tasks.values(), return_exceptions=True)
    
    async def add_job(self, user_id: int, url: str, media_type: str = "auto") -> str:
        """Add a new download job to queue."""
        job_id = f"{user_id}_{int(time.time())}_{hash(url) % 10000}"
        
        job = DownloadJob(
            job_id=job_id,
            user_id=user_id,
            url=url,
            media_type=media_type,
            status=JobStatus.PENDING,
            created_at=time.time()
        )
        
        self.jobs[job_id] = job
        await self.queue.put(job_id)
        return job_id
    
    async def _process_queue(self):
        """Process jobs from queue."""
        while self._running:
            if len(self.active_tasks) >= self.max_concurrent:
                await asyncio.sleep(0.1)
                continue
            
            try:
                job_id = await asyncio.wait_for(self.queue.get(), timeout=1)
                if job_id in self.jobs:
                    job = self.jobs[job_id]
                    job.status = JobStatus.PROCESSING
                    job.started_at = time.time()
                    
                    # Create processing task
                    task = asyncio.create_task(self._process_job(job))
                    self.active_tasks[job_id] = task
                    task.add_done_callback(lambda t, jid=job_id: self._task_done(jid, t))
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Queue processing error: {e}")
    
    async def _process_job(self, job: DownloadJob):
        """Process a single job."""
        # Simulate processing - replace with actual download logic
        await asyncio.sleep(2)  # Simulate work
        
        # Update job status
        job.status = JobStatus.COMPLETED
        job.completed_at = time.time()
        job.result_path = f"/tmp/{job.job_id}.mp4"
    
    def _task_done(self, job_id: str, task: asyncio.Task):
        """Handle task completion."""
        self.active_tasks.pop(job_id, None)
        self.queue.task_done()
        
        if task.exception():
            if job_id in self.jobs:
                self.jobs[job_id].status = JobStatus.FAILED
                self.jobs[job_id].error_message = str(task.exception())
    
    def get_job_status(self, job_id: str) -> Optional[DownloadJob]:
        """Get job status by ID."""
        return self.jobs.get(job_id)
    
    def get_user_jobs(self, user_id: int) -> List[DownloadJob]:
        """Get all jobs for a user."""
        return [job for job in self.jobs.values() if job.user_id == user_id]