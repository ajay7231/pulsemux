import time
import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Float,
    Integer,
    Boolean,
    JSON,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base
from pgvector.sqlalchemy import Vector

Base = declarative_base()


def uid():
    return uuid.uuid4().hex


class Installation(Base):
    __tablename__ = "installation"
    id = Column(Integer, primary_key=True)
    created_at = Column(Float, default=time.time, nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(String(32), primary_key=True, default=uid)
    name = Column(String(120), nullable=False)
    timezone = Column(String(80), default="Asia/Kolkata", nullable=False)
    retention_days = Column(Integer, default=90, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(String(32), primary_key=True, default=uid)
    workspace_id = Column(
        String(32), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    email = Column(String(254), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(20), default="admin", nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(String(32), ForeignKey("users.id"), nullable=False)
    expires_at = Column(Float, nullable=False, index=True)


class Owned:
    id = Column(String(32), primary_key=True, default=uid)
    workspace_id = Column(
        String(32), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    created_at = Column(Float, default=time.time, nullable=False)


class Connection(Owned, Base):
    __tablename__ = "connections"
    name = Column(String(120), nullable=False)
    provider = Column(String(20), nullable=False)
    encrypted_secret = Column(Text, nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    tested_at = Column(Float)
    test_status = Column(String(20), default="untested", nullable=False)


class Collection(Owned, Base):
    __tablename__ = "knowledge_collections"
    name = Column(String(120), nullable=False)
    description = Column(Text, default="", nullable=False)
    embedding_connection_id = Column(String(32), ForeignKey("connections.id"))


class Document(Owned, Base):
    __tablename__ = "knowledge_documents"
    collection_id = Column(
        String(32), ForeignKey("knowledge_collections.id"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), default="draft", nullable=False)
    reviewed_by = Column(String(32), ForeignKey("users.id"))
    reviewed_at = Column(Float)
    expires_at = Column(Float)


class Chunk(Owned, Base):
    __tablename__ = "knowledge_chunks"
    document_id = Column(
        String(32), ForeignKey("knowledge_documents.id"), nullable=False, index=True
    )
    position = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536).with_variant(JSON, "sqlite"))


class Agent(Owned, Base):
    __tablename__ = "agents"
    name = Column(String(120), nullable=False)
    description = Column(Text, default="", nullable=False)
    config = Column(JSON, nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    published_version_id = Column(String(32))
    status = Column(String(20), default="draft", nullable=False)
    updated_at = Column(Float, default=time.time, nullable=False)
    tested_revision = Column(Integer)
    tested_knowledge_hash = Column(String(64))


class AgentVersion(Owned, Base):
    __tablename__ = "agent_versions"
    agent_id = Column(String(32), ForeignKey("agents.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    config = Column(JSON, nullable=False)
    knowledge = Column(JSON, nullable=False)
    published_by = Column(String(32), ForeignKey("users.id"), nullable=False)
    __table_args__ = (UniqueConstraint("agent_id", "number"),)


class PhoneNumber(Owned, Base):
    __tablename__ = "phone_numbers"
    number = Column(String(20), nullable=False, unique=True)
    connection_id = Column(String(32), ForeignKey("connections.id"), nullable=False)
    agent_id = Column(String(32), ForeignKey("agents.id"), nullable=False)
    label = Column(String(120), default="", nullable=False)


class Contact(Owned, Base):
    __tablename__ = "contacts"
    name = Column(String(120), nullable=False)
    phone = Column(String(20), nullable=False)
    consent = Column(Boolean, default=False, nullable=False)
    opted_out = Column(Boolean, default=False, nullable=False)
    timezone = Column(String(80), default="Asia/Kolkata", nullable=False)
    variables = Column(JSON, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("workspace_id", "phone"),)


class Campaign(Owned, Base):
    __tablename__ = "campaigns"
    name = Column(String(120), nullable=False)
    agent_version_id = Column(
        String(32), ForeignKey("agent_versions.id"), nullable=False
    )
    phone_number_id = Column(String(32), ForeignKey("phone_numbers.id"), nullable=False)
    status = Column(String(20), default="draft", nullable=False)
    config = Column(JSON, default=dict, nullable=False)


class Recipient(Owned, Base):
    __tablename__ = "campaign_recipients"
    campaign_id = Column(
        String(32), ForeignKey("campaigns.id"), nullable=False, index=True
    )
    contact_id = Column(String(32), ForeignKey("contacts.id"), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    claimed_at = Column(Float)
    next_attempt_at = Column(Float, default=time.time, nullable=False, index=True)
    last_call_id = Column(String(32))
    __table_args__ = (UniqueConstraint("campaign_id", "contact_id"),)


class Call(Owned, Base):
    __tablename__ = "calls"
    agent_id = Column(String(32), ForeignKey("agents.id"), nullable=False, index=True)
    version_id = Column(String(32), ForeignKey("agent_versions.id"))
    connection_id = Column(String(32), ForeignKey("connections.id"))
    contact_id = Column(String(32), ForeignKey("contacts.id"))
    recipient_id = Column(String(32), ForeignKey("campaign_recipients.id"))
    direction = Column(String(20), nullable=False)
    status = Column(String(30), default="created", nullable=False, index=True)
    to_number = Column(String(20))
    from_number = Column(String(20))
    provider_sid = Column(String(40), unique=True)
    stream_token_hash = Column(String(64))
    stream_claimed = Column(Boolean, default=False, nullable=False)
    config = Column(JSON, nullable=False)
    knowledge = Column(JSON, default=list, nullable=False)
    variables = Column(JSON, default=dict, nullable=False)
    outcome = Column(String(80))
    error = Column(Text)
    ended_at = Column(Float)
    deadline = Column(Float)


class CallEvent(Owned, Base):
    __tablename__ = "call_events"
    call_id = Column(String(32), ForeignKey("calls.id"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)
    payload = Column(JSON, default=dict, nullable=False)


class StaffTask(Owned, Base):
    __tablename__ = "staff_tasks"
    call_id = Column(String(32), ForeignKey("calls.id"))
    title = Column(String(200), nullable=False)
    details = Column(Text, default="", nullable=False)
    status = Column(String(20), default="open", nullable=False)


class Audit(Owned, Base):
    __tablename__ = "audit_events"
    actor_id = Column(String(32), ForeignKey("users.id"))
    action = Column(String(80), nullable=False)
    target_id = Column(String(64))
    detail = Column(JSON, default=dict, nullable=False)
