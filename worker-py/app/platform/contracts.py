"""Public response contracts. Explicit fields keep database secrets private."""

from typing import Any, Dict, List, Optional, Literal, Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field
from .schemas import AgentConfig


class PublicModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WorkspacePublic(PublicModel):
    id: str
    name: str
    timezone: str
    retention_days: int
    created_at: float


class UserPublic(PublicModel):
    id: str
    workspace_id: str
    name: str
    email: str
    role: Literal["admin", "operator", "viewer"]
    active: bool
    created_at: float


class SessionPublic(PublicModel):
    user: UserPublic
    workspace: WorkspacePublic


class RecordPublic(PublicModel):
    id: str
    workspace_id: str
    created_at: float


class AgentPublic(RecordPublic):
    name: str
    description: str
    config: AgentConfig
    revision: int
    status: str
    updated_at: float
    published_version_id: Optional[str] = None
    tested_revision: Optional[int] = None
    tested_knowledge_hash: Optional[str] = None


class ConnectionPublic(RecordPublic):
    name: str
    provider: Literal["deepgram", "groq", "openai", "twilio", "plivo"]
    revision: int
    active: bool
    test_status: str
    tested_at: Optional[float] = None


class CollectionPublic(RecordPublic):
    name: str
    description: str
    embedding_connection_id: Optional[str] = None


class DocumentPublic(RecordPublic):
    collection_id: str
    title: str
    content: str
    status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[float] = None
    expires_at: Optional[float] = None
    ingestion_status: str = "legacy"
    ingestion_error: Optional[str] = None


class ContactPublic(RecordPublic):
    name: str
    phone: str
    consent: bool
    opted_out: bool
    timezone: str
    variables: Dict[str, Any]


class NumberPublic(RecordPublic):
    number: str
    connection_id: str
    agent_id: str
    label: str


class CallPublic(RecordPublic):
    agent_id: str
    agent_name: Optional[str] = None
    direction: str
    status: str
    to_number: Optional[str] = None
    from_number: Optional[str] = None
    outcome: Optional[str] = None
    error: Optional[str] = None
    ended_at: Optional[float] = None


class TaskPublic(RecordPublic):
    call_id: Optional[str] = None
    title: str
    details: str
    status: str


class AuditPublic(RecordPublic):
    actor_id: Optional[str] = None
    action: str
    target_id: Optional[str] = None
    detail: Dict[str, Any]


class CampaignPublic(RecordPublic):
    name: str
    agent_version_id: str
    phone_number_id: str
    status: str
    config: Dict[str, Any]
    recipient_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    suppressed_count: int = 0


T = TypeVar("T")


class PagePublic(PublicModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


class TemplatePublic(PublicModel):
    id: str
    name: str
    description: str
    greeting: str
    instructions: str


class ModelChoice(PublicModel):
    id: str
    name: str


class ModelCatalogPublic(PublicModel):
    provider: Literal["groq", "openai"]
    models: List[ModelChoice]


class AgentChoice(PublicModel):
    id: str
    name: str


class OverviewPublic(PublicModel):
    agents: int
    calls: int
    campaigns: int
    contacts: int
    active_calls: int
    open_tasks: int
    connections: int
    collections: int
    numbers: int
    recent_calls: List[CallPublic]
    agent_choices: List[AgentChoice]
    recent_activity: List[AuditPublic]
