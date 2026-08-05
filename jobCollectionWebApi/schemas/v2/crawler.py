from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BeforeValidator, Field

from .common import V2Model


CrawlerCommand = Literal["start", "pause", "resume", "stop", "retry"]
CrawlerDesiredStatus = Literal["running", "paused", "stopped"]
CrawlerRunStatus = Literal[
    "queued",
    "starting",
    "running",
    "pausing",
    "paused",
    "stopping",
    "stopped",
    "succeeded",
    "failed",
    "stale",
]
CrawlerEventLevel = Literal["debug", "info", "warning", "error"]
StringId = Annotated[str, BeforeValidator(lambda value: str(value))]


class CrawlerTaskCommandRequest(V2Model):
    action: CrawlerCommand


class CrawlerWorkerHeartbeat(V2Model):
    worker_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    hostname: str = Field(min_length=1, max_length=255)
    platform: str = Field(default="unknown", max_length=80)
    max_concurrency: int = Field(default=1, ge=1, le=32)
    active_runs: int = Field(default=0, ge=0, le=32)
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class CrawlerRunClaimRequest(V2Model):
    worker_id: str = Field(min_length=1, max_length=64)
    allowed_spiders: List[str] = Field(default_factory=list, max_length=50)


class CrawlerRunAssignment(V2Model):
    run_id: StringId
    task_id: StringId
    spider_name: str
    spider_args: Dict[str, Any] = Field(default_factory=dict)
    execution_token: str
    desired_status: CrawlerDesiredStatus
    checkpoint: Dict[str, Any] = Field(default_factory=dict)


class CrawlerDesiredStateResponse(V2Model):
    run_id: StringId
    desired_status: CrawlerDesiredStatus
    status: CrawlerRunStatus


class CrawlerRunHeartbeat(V2Model):
    execution_token: str = Field(min_length=1, max_length=64)
    status: CrawlerRunStatus
    pid: Optional[int] = Field(default=None, ge=1)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    checkpoint: Dict[str, Any] = Field(default_factory=dict)


class CrawlerEventInput(V2Model):
    event_type: str = Field(min_length=1, max_length=50)
    level: CrawlerEventLevel = "info"
    message: Optional[str] = Field(default=None, max_length=4000)
    payload: Dict[str, Any] = Field(default_factory=dict)


class CrawlerEventBatch(V2Model):
    execution_token: str = Field(min_length=1, max_length=64)
    events: List[CrawlerEventInput] = Field(default_factory=list, max_length=100)


class CrawlerRunFinishRequest(V2Model):
    execution_token: str = Field(min_length=1, max_length=64)
    status: Literal["stopped", "succeeded", "failed"]
    exit_code: Optional[int] = None
    error_msg: Optional[str] = Field(default=None, max_length=8000)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    checkpoint: Dict[str, Any] = Field(default_factory=dict)


class CrawlerWorkerView(V2Model):
    id: str
    name: str
    hostname: str
    platform: str
    status: str
    online: bool
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    max_concurrency: int
    active_runs: int
    last_heartbeat_at: datetime


class CrawlerRunView(V2Model):
    id: StringId
    task_id: StringId
    worker_id: Optional[str] = None
    spider_name: str
    spider_args: Dict[str, Any] = Field(default_factory=dict)
    desired_status: str
    status: str
    pid: Optional[int] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    checkpoint: Dict[str, Any] = Field(default_factory=dict)
    exit_code: Optional[int] = None
    error_msg: Optional[str] = None
    started_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CrawlerTaskView(V2Model):
    id: StringId
    url: str
    spider_name: str
    spider_args: Dict[str, Any] = Field(default_factory=dict)
    desired_status: str
    status: str
    priority: int
    latest_run_id: Optional[StringId] = None
    last_crawl_time: Optional[datetime] = None
    error_msg: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CrawlerEventView(V2Model):
    id: StringId
    run_id: StringId
    worker_id: Optional[str] = None
    event_type: str
    level: str
    message: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CrawlerOverviewResponse(V2Model):
    workers_online: int = 0
    workers_total: int = 0
    runs_active: int = 0
    runs_failed: int = 0
    tasks_pending: int = 0
    items_scraped: int = 0
    pages_processed: int = 0
    errors: int = 0
    updated_at: datetime


class CrawlerListResponse(V2Model):
    items: List[Any] = Field(default_factory=list)
    total: int = 0


class CrawlerCommandResponse(V2Model):
    task_id: StringId
    run_id: Optional[StringId] = None
    desired_status: str
    status: str
