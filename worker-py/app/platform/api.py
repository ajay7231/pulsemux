import asyncio
import os
import hmac
import csv
import io
import json
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones
import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
)
from sqlalchemy import select, func, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import *
from .schemas import *
from .security import (
    current_user,
    editor,
    admin,
    check_origin,
    password_hash,
    verify_password,
    set_login,
    encrypt,
    decrypt,
    digest,
    COOKIE,
)
from .service import (
    owned,
    audit,
    public_record,
    validate_config,
    knowledge_snapshot,
    chunk_document,
    TEMPLATES,
    knowledge_hash,
)

from .contracts import (
    SessionPublic,
    UserPublic,
    AgentPublic,
    ConnectionPublic,
    WorkspacePublic,
    DocumentPublic,
)

from .contracts import TemplatePublic, ModelCatalogPublic, OverviewPublic

router = APIRouter(prefix="/api")
from .throttling import throttle


def rows(db, model, workspace, limit=200):
    return db.scalars(
        select(model)
        .where(model.workspace_id == workspace)
        .order_by(model.created_at.desc())
        .limit(limit)
    ).all()


@router.get("/bootstrap")
def bootstrap(db: Session = Depends(get_db)):
    return {
        "setup_required": db.get(Installation, 1) is None,
        "setup_token_required": bool(os.getenv("PLATFORM_SETUP_TOKEN"))
        or os.getenv("PLATFORM_ENV") == "production",
    }


@router.get("/knowledge/config")
def knowledge_config(user=Depends(current_user)):
    from app.rag.integration import enabled

    return {"hybrid_enabled": enabled()}


@router.get("/timezones")
def timezones():
    return sorted(available_timezones())


@router.post("/setup", response_model=SessionPublic)
def setup(
    data: Setup, request: Request, response: Response, db: Session = Depends(get_db)
):
    check_origin(request)
    throttle(request)
    setup_token = os.getenv("PLATFORM_SETUP_TOKEN", "")
    if os.getenv("PLATFORM_ENV") == "production" and not setup_token:
        raise HTTPException(503, "The operator must configure PLATFORM_SETUP_TOKEN")
    if setup_token and not hmac.compare_digest(data.setup_token or "", setup_token):
        raise HTTPException(
            403, "Enter the installation setup token from your server configuration"
        )
    if db.get(Installation, 1):
        raise HTTPException(409, "This installation has already been configured")
    workspace = Workspace(name=data.workspace, timezone=data.timezone)
    db.add(workspace)
    db.flush()
    user = User(
        workspace_id=workspace.id,
        name=data.name,
        email=data.email,
        password_hash=password_hash(data.password),
    )
    db.add(user)
    try:
        db.add(Installation(id=1))
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This installation has already been configured")
    set_login(response, db, user)
    audit(db, user, "workspace.created", workspace.id)
    return {"user": public_record(user), "workspace": public_record(workspace)}


@router.post("/login", response_model=SessionPublic)
def login(
    data: Login, request: Request, response: Response, db: Session = Depends(get_db)
):
    check_origin(request)
    throttle(request, data.email)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    # Always perform password work to reduce account enumeration through timing.
    stored = (
        user.password_hash if user else "pbkdf2$600000$" + "00" * 16 + "$" + "00" * 32
    )
    valid = verify_password(data.password, stored)
    if not user or not valid or not user.active:
        raise HTTPException(401, "Email or password is incorrect")
    set_login(response, db, user)
    audit(db, user, "session.created")
    return {
        "user": public_record(user),
        "workspace": public_record(db.get(Workspace, user.workspace_id)),
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    check_origin(request)
    db.execute(
        delete(LoginSession).where(
            LoginSession.token_hash == digest(request.cookies.get(COOKIE, ""))
        )
    )
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=SessionPublic)
def me(user=Depends(current_user), db: Session = Depends(get_db)):
    return {
        "user": public_record(user),
        "workspace": public_record(db.get(Workspace, user.workspace_id)),
    }


@router.get("/templates", response_model=list[TemplatePublic])
def templates(user=Depends(current_user)):
    return TEMPLATES


@router.get("/overview", response_model=OverviewPublic)
def overview(user=Depends(current_user), db: Session = Depends(get_db)):
    result = {}
    for name, model in [
        ("agents", Agent),
        ("calls", Call),
        ("campaigns", Campaign),
        ("contacts", Contact),
    ]:
        result[name] = db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.workspace_id == user.workspace_id)
        )
    result["active_calls"] = db.scalar(
        select(func.count())
        .select_from(Call)
        .where(
            Call.workspace_id == user.workspace_id,
            Call.status.in_(["created", "initiated", "ringing", "in-progress"]),
        )
    )
    result["open_tasks"] = db.scalar(
        select(func.count())
        .select_from(StaffTask)
        .where(StaffTask.workspace_id == user.workspace_id, StaffTask.status == "open")
    )
    for name, model in [
        ("connections", Connection),
        ("collections", Collection),
        ("numbers", PhoneNumber),
    ]:
        result[name] = db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.workspace_id == user.workspace_id)
        )
    result["recent_calls"] = [
        public_record(c, ("config", "knowledge", "variables"))
        for c in rows(db, Call, user.workspace_id, 8)
    ]
    call_agent_ids = {call["agent_id"] for call in result["recent_calls"]}
    result["agent_choices"] = [
        {"id": agent.id, "name": agent.name}
        for agent in db.scalars(
            select(Agent).where(
                Agent.workspace_id == user.workspace_id, Agent.id.in_(call_agent_ids)
            )
        )
    ]
    result["recent_activity"] = [
        public_record(a) for a in rows(db, Audit, user.workspace_id, 8)
    ]
    return result


@router.get("/connections")
def connections(user=Depends(current_user), db: Session = Depends(get_db)):
    return [public_record(c) for c in rows(db, Connection, user.workspace_id)]


def credentials_valid(provider, value):
    allowed = {
        "twilio": {"account_sid", "auth_token", "api_key_sid", "api_key_secret"},
        "groq": {"api_key"},
        "deepgram": {"api_key"},
        "openai": {"api_key"},
    }[provider]
    if set(value) - allowed or any(
        not isinstance(v, str) or len(v) > 1000 for v in value.values()
    ):
        raise HTTPException(422, "Invalid credential fields")
    required = {"account_sid", "auth_token"} if provider == "twilio" else {"api_key"}
    if any(not value.get(field, "").strip() for field in required):
        raise HTTPException(422, "Complete all required credential fields")
    if provider == "twilio":
        if not re.fullmatch(r"AC[0-9a-fA-F]{32}", value["account_sid"]):
            raise HTTPException(422, "Invalid Twilio Account SID")
        if bool(value.get("api_key_sid")) != bool(value.get("api_key_secret")):
            raise HTTPException(422, "Provide both API key SID and secret")


@router.post("/connections", response_model=ConnectionPublic)
def create_connection(
    data: ConnectionInput, user=Depends(admin), db: Session = Depends(get_db)
):
    credentials_valid(data.provider, data.credentials)
    item = Connection(
        workspace_id=user.workspace_id,
        name=data.name,
        provider=data.provider,
        encrypted_secret=encrypt(data.credentials),
    )
    db.add(item)
    db.flush()
    audit(db, user, "connection.created", item.id, {"provider": item.provider})
    return public_record(item)


@router.put("/connections/{record_id}", response_model=ConnectionPublic)
def rotate_connection(
    record_id: str,
    data: ConnectionInput,
    user=Depends(admin),
    db: Session = Depends(get_db),
):
    item = owned(db, Connection, record_id, user.workspace_id)
    if item.provider != data.provider:
        raise HTTPException(422, "Create a new connection to change provider")
    credentials_valid(data.provider, data.credentials)
    item.name = data.name
    item.encrypted_secret = encrypt(data.credentials)
    item.revision += 1
    item.test_status = "untested"
    item.active = True
    audit(db, user, "connection.rotated", item.id)
    return public_record(item)


@router.post("/connections/{record_id}/revoke")
def revoke_connection(
    record_id: str, user=Depends(admin), db: Session = Depends(get_db)
):
    item = owned(db, Connection, record_id, user.workspace_id)
    item.active = False
    audit(db, user, "connection.revoked", item.id)
    return {"ok": True}


@router.post("/connections/{record_id}/test")
async def test_connection(
    record_id: str, user=Depends(admin), db: Session = Depends(get_db)
):
    item = owned(db, Connection, record_id, user.workspace_id)
    if not item.active:
        raise HTTPException(409, "Connection is revoked")
    credentials = decrypt(item.encrypted_secret)
    urls = {
        "deepgram": "https://api.deepgram.com/v1/projects",
        "groq": "https://api.groq.com/openai/v1/models",
        "openai": "https://api.openai.com/v1/models",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if item.provider == "twilio":
                sid = credentials["account_sid"]
                auth = (
                    credentials.get("api_key_sid") or sid,
                    credentials.get("api_key_secret") or credentials["auth_token"],
                )
                result = await client.get(
                    f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json", auth=auth
                )
            else:
                auth = "Token" if item.provider == "deepgram" else "Bearer"
                result = await client.get(
                    urls[item.provider],
                    headers={"Authorization": f'{auth} {credentials["api_key"]}'},
                )
        item.test_status = "valid" if result.is_success else "failed"
    except httpx.RequestError:
        item.test_status = "unreachable"
    item.tested_at = time.time()
    audit(db, user, "connection.tested", item.id, {"status": item.test_status})
    return {
        "status": item.test_status,
        "message": (
            "Connection verified"
            if item.test_status == "valid"
            else "Connection could not be verified; check credentials, permissions, and network access."
        ),
    }


@router.get("/connections/{record_id}/models", response_model=ModelCatalogPublic)
async def connection_models(
    record_id: str, user=Depends(editor), db: Session = Depends(get_db)
):
    from .model_catalog import list_chat_models

    item = owned(db, Connection, record_id, user.workspace_id)
    if not item.active:
        raise HTTPException(409, "Connection is revoked")
    models = await list_chat_models(
        item.provider, decrypt(item.encrypted_secret).get("api_key", "")
    )
    return {
        "models": [{"id": model, "name": model} for model in models],
        "provider": item.provider,
    }


@router.get("/agents")
def agents(user=Depends(current_user), db: Session = Depends(get_db)):
    return [public_record(a) for a in rows(db, Agent, user.workspace_id)]


@router.post("/agents/{record_id}/validate")
async def validate_agent_setup(
    record_id: str, user=Depends(editor), db: Session = Depends(get_db)
):
    from .model_catalog import list_chat_models

    item = owned(db, Agent, record_id, user.workspace_id)
    config = validate_config(db, user.workspace_id, item.config, True)
    connection = owned(db, Connection, config["llm_connection_id"], user.workspace_id)
    models = await list_chat_models(
        connection.provider, decrypt(connection.encrypted_secret)["api_key"]
    )
    if config["llm_model"] not in models:
        raise HTTPException(
            422,
            "The selected language model is unavailable. Refresh models in Voice & models and choose another.",
        )
    return {"ready": True}


@router.post("/agents", response_model=AgentPublic)
def create_agent(data: AgentInput, user=Depends(editor), db: Session = Depends(get_db)):
    config = validate_config(db, user.workspace_id, data.config.model_dump())
    item = Agent(
        workspace_id=user.workspace_id,
        name=data.name,
        description=data.description,
        config=config,
    )
    db.add(item)
    db.flush()
    audit(db, user, "agent.created", item.id)
    return public_record(item)


@router.get("/agents/{record_id}")
def get_agent(
    record_id: str, user=Depends(current_user), db: Session = Depends(get_db)
):
    item = owned(db, Agent, record_id, user.workspace_id)
    result = public_record(item)
    result["versions"] = [
        public_record(v, ("knowledge",))
        for v in db.scalars(
            select(AgentVersion)
            .where(
                AgentVersion.agent_id == item.id,
                AgentVersion.workspace_id == user.workspace_id,
            )
            .order_by(AgentVersion.number.desc())
        )
    ]
    return result


@router.put("/agents/{record_id}", response_model=AgentPublic)
def update_agent(
    record_id: str,
    data: AgentInput,
    user=Depends(editor),
    db: Session = Depends(get_db),
):
    item = owned(db, Agent, record_id, user.workspace_id)
    if data.revision != item.revision:
        raise HTTPException(
            409, "Agent changed since you opened it. Reload before saving."
        )
    config = validate_config(db, user.workspace_id, data.config.model_dump())
    changed = db.execute(
        update(Agent)
        .where(Agent.id == item.id, Agent.revision == data.revision)
        .values(
            name=data.name,
            description=data.description,
            config=config,
            revision=Agent.revision + 1,
            updated_at=time.time(),
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if not changed:
        raise HTTPException(
            409, "Agent changed since you opened it. Reload before saving."
        )
    db.refresh(item)
    audit(db, user, "agent.updated", item.id, {"revision": item.revision})
    return public_record(item)


@router.post("/agents/{record_id}/publish")
def publish_agent(record_id: str, user=Depends(admin), db: Session = Depends(get_db)):
    item = owned(db, Agent, record_id, user.workspace_id)
    db.refresh(item, with_for_update=True)
    config = validate_config(db, user.workspace_id, item.config, True)
    if item.tested_revision != item.revision:
        raise HTTPException(
            409,
            "Complete a simulator conversation with the current draft before publishing",
        )
    snapshot = knowledge_snapshot(db, user.workspace_id, config["collection_ids"])
    if item.tested_knowledge_hash != knowledge_hash(snapshot):
        raise HTTPException(
            409,
            "Knowledge changed since the last test. Test this draft again before publishing.",
        )
    number = (
        db.scalar(
            select(func.max(AgentVersion.number)).where(
                AgentVersion.agent_id == item.id
            )
        )
        or 0
    ) + 1
    version = AgentVersion(
        workspace_id=user.workspace_id,
        agent_id=item.id,
        number=number,
        config=config,
        knowledge=snapshot,
        published_by=user.id,
    )
    db.add(version)
    db.flush()
    item.published_version_id = version.id
    item.status = "published"
    audit(db, user, "agent.published", item.id, {"version": number})
    return public_record(item)


@router.post("/agents/{record_id}/pause")
def pause_agent(record_id: str, user=Depends(admin), db: Session = Depends(get_db)):
    item = owned(db, Agent, record_id, user.workspace_id)
    item.status = "paused"
    audit(db, user, "agent.paused", item.id)
    return public_record(item)


@router.get("/collections")
def collections(user=Depends(current_user), db: Session = Depends(get_db)):
    return [public_record(c) for c in rows(db, Collection, user.workspace_id)]


@router.post("/collections")
def create_collection(
    data: CollectionInput, user=Depends(editor), db: Session = Depends(get_db)
):
    if data.embedding_connection_id:
        connection = owned(
            db, Connection, data.embedding_connection_id, user.workspace_id
        )
        if connection.provider != "openai" or not connection.active:
            raise HTTPException(422, "Choose an active OpenAI embedding connection")
    item = Collection(workspace_id=user.workspace_id, **data.model_dump())
    db.add(item)
    db.flush()
    audit(db, user, "knowledge.collection_created", item.id)
    return public_record(item)


@router.get("/collections/{record_id}/documents", response_model=list[DocumentPublic])
def documents(
    record_id: str, user=Depends(current_user), db: Session = Depends(get_db)
):
    owned(db, Collection, record_id, user.workspace_id)
    return [
        public_record(d)
        for d in db.scalars(
            select(Document)
            .where(
                Document.workspace_id == user.workspace_id,
                Document.collection_id == record_id,
            )
            .order_by(Document.created_at.desc())
        )
    ]


def save_document(db, user, collection_id, data):
    owned(db, Collection, collection_id, user.workspace_id)
    item = Document(
        workspace_id=user.workspace_id, collection_id=collection_id, **data.model_dump()
    )
    db.add(item)
    db.flush()
    from app.rag.integration import enabled

    if enabled():
        item.ingestion_status = "queued"
    else:
        chunk_document(db, item)
    audit(db, user, "knowledge.document_created", item.id)
    return public_record(item)


@router.post("/collections/{record_id}/documents", response_model=DocumentPublic)
def create_document(
    record_id: str,
    data: DocumentInput,
    user=Depends(editor),
    db: Session = Depends(get_db),
):
    return save_document(db, user, record_id, data)


@router.post("/collections/{record_id}/upload", response_model=DocumentPublic)
async def upload_document(
    record_id: str,
    file: UploadFile = File(...),
    user=Depends(editor),
    db: Session = Depends(get_db),
):
    owned(db, Collection, record_id, user.workspace_id)
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Files must be smaller than 5 MB")
    filename = Path(file.filename or "Document").name
    from app.rag.integration import enabled, source_path

    if enabled():
        if not filename.lower().endswith((".pdf", ".md", ".txt", ".csv")):
            raise HTTPException(422, "Upload PDF, TXT, Markdown, or CSV")
        try:
            data = DocumentInput(
                title=filename[:200],
                content=(
                    "Document queued for layout-aware ingestion."
                    if filename.lower().endswith(".pdf")
                    else content.decode("utf-8-sig")
                ),
            )
        except (ValueError, UnicodeError):
            raise HTTPException(
                422, "Text documents must be UTF-8 and contain 10–200,000 characters"
            )
        item = save_document(db, user, record_id, data)
        doc = db.get(Document, item["id"])
        doc.source_format = ".pdf" if filename.lower().endswith(".pdf") else ".md"
        from .database import database

        target = source_path(database(), doc)
        descriptor = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        db.flush()
        return public_record(doc)
    try:
        if filename.lower().endswith(".pdf"):
            from pypdf import PdfReader

            def extract():
                reader = PdfReader(io.BytesIO(content))
                if len(reader.pages) > 100:
                    raise ValueError("Too many pages")
                return "\n".join(page.extract_text() or "" for page in reader.pages)

            text = await asyncio.to_thread(extract)
        elif filename.lower().endswith((".txt", ".md", ".csv")):
            text = content.decode("utf-8-sig")
        else:
            raise HTTPException(422, "Upload PDF, TXT, Markdown, or CSV")
        data = DocumentInput(title=filename[:200], content=text)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            422,
            "Could not extract readable text (limit: 100 pages / 200,000 characters)",
        )
    return save_document(db, user, record_id, data)


@router.post("/documents/{record_id}/index")
async def index_document(
    record_id: str, user=Depends(editor), db: Session = Depends(get_db)
):
    from app.rag.integration import enabled

    if enabled():
        doc = owned(db, Document, record_id, user.workspace_id)
        db.refresh(doc, with_for_update=True)
        if doc.status == "archived":
            raise HTTPException(409, "Archived documents cannot be indexed")
        if doc.ingestion_status in {"queued", "processing"}:
            return {"indexed_chunks": 0, "status": doc.ingestion_status}
        doc.ingestion_status = "queued"
        doc.ingestion_error = None
        doc.status = "draft"
        doc.reviewed_by = None
        doc.reviewed_at = None
        audit(db, user, "knowledge.index_queued", doc.id)
        return {"indexed_chunks": 0, "status": "queued"}
    from .embeddings import embed

    doc = owned(db, Document, record_id, user.workspace_id)
    if doc.status == "archived":
        raise HTTPException(409, "Archived documents cannot be indexed")
    collection = owned(db, Collection, doc.collection_id, user.workspace_id)
    if not collection.embedding_connection_id:
        raise HTTPException(
            422,
            "This collection uses lexical search. Create a collection with an OpenAI embedding connection to enable semantic indexing.",
        )
    chunks = list(
        db.scalars(
            select(Chunk)
            .where(Chunk.workspace_id == user.workspace_id, Chunk.document_id == doc.id)
            .order_by(Chunk.position)
        )
    )
    vectors = await embed(
        user.workspace_id,
        collection.embedding_connection_id,
        [c.content for c in chunks],
    )
    for chunk, vector in zip(chunks, vectors):
        chunk.embedding = vector
    audit(db, user, "knowledge.indexed", doc.id, {"chunks": len(chunks)})
    return {"indexed_chunks": len(chunks)}


@router.post("/documents/{record_id}/approve", response_model=DocumentPublic)
def approve_document(
    record_id: str, user=Depends(admin), db: Session = Depends(get_db)
):
    item = owned(db, Document, record_id, user.workspace_id)
    db.refresh(item, with_for_update=True)
    if item.status == "archived":
        raise HTTPException(409, "Archived documents cannot be approved")
    if item.ingestion_status not in {"ready", "legacy"}:
        raise HTTPException(
            409, "Wait for ingestion to finish successfully before approving"
        )
    if item.expires_at and item.expires_at <= time.time():
        raise HTTPException(422, "Document is expired")
    item.status = "approved"
    item.reviewed_by = user.id
    item.reviewed_at = time.time()
    audit(db, user, "knowledge.approved", item.id)
    return public_record(item)


@router.post("/documents/{record_id}/archive", response_model=DocumentPublic)
def archive_document(
    record_id: str, user=Depends(admin), db: Session = Depends(get_db)
):
    item = owned(db, Document, record_id, user.workspace_id)
    item.status = "archived"
    audit(db, user, "knowledge.archived", item.id)
    # Existing immutable versions remain auditable. Pause agents using this document.
    for agent in rows(db, Agent, user.workspace_id, 10000):
        if agent.published_version_id:
            version = db.get(AgentVersion, agent.published_version_id)
            if any(c["document_id"] == item.id for c in version.knowledge):
                agent.status = "paused"
    return public_record(item)


@router.get("/contacts")
def contacts(user=Depends(current_user), db: Session = Depends(get_db)):
    return [public_record(c) for c in rows(db, Contact, user.workspace_id, 1000)]


@router.post("/contacts")
def create_contact(
    data: ContactInput, user=Depends(editor), db: Session = Depends(get_db)
):
    if len(json.dumps(data.variables)) > 10000:
        raise HTTPException(422, "Contact variables are too large")
    item = Contact(workspace_id=user.workspace_id, **data.model_dump())
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This phone number is already saved")
    audit(db, user, "contact.created", item.id)
    return public_record(item)


@router.put("/contacts/{record_id}")
def update_contact(
    record_id: str,
    data: ContactInput,
    user=Depends(editor),
    db: Session = Depends(get_db),
):
    item = owned(db, Contact, record_id, user.workspace_id)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    audit(db, user, "contact.updated", item.id)
    return public_record(item)


@router.post("/contacts/import-preview")
async def contact_import_preview(file: UploadFile = File(...), user=Depends(editor)):
    content = await file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, "CSV files must be smaller than 2 MB")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if not {"name", "phone"}.issubset(set(reader.fieldnames or [])):
            raise ValueError("Headers must include name and phone")
        result = []
        errors = []
        for line, row in enumerate(reader, 2):
            if line > 1001:
                raise ValueError("Limit: 1,000 contacts per import")
            try:
                known = {"name", "phone", "consent", "opted_out", "timezone"}
                contact = ContactInput(
                    name=row.get("name", ""),
                    phone=row.get("phone", ""),
                    consent=(row.get("consent") or "").strip().lower()
                    in {"true", "yes", "1"},
                    opted_out=(row.get("opted_out") or "").strip().lower()
                    in {"true", "yes", "1"},
                    timezone=row.get("timezone") or "Asia/Kolkata",
                    variables={
                        k: v for k, v in row.items() if k not in known and k and v
                    },
                )
                result.append(contact.model_dump())
            except Exception:
                errors.append(
                    {
                        "line": line,
                        "message": "Invalid contact name, E.164 phone number, or timezone",
                    }
                )
        return {"contacts": result, "errors": errors}
    except (ValueError, UnicodeError, csv.Error) as exc:
        raise HTTPException(422, str(exc))


@router.post("/contacts/import")
def contact_import(
    data: List[ContactInput], user=Depends(editor), db: Session = Depends(get_db)
):
    if not 1 <= len(data) <= 1000:
        raise HTTPException(422, "Import between 1 and 1,000 contacts")
    imported = 0
    duplicates = 0
    for contact in data:
        if len(json.dumps(contact.variables)) > 10000:
            raise HTTPException(422, "Contact variables are too large")
        existing = db.scalar(
            select(Contact.id).where(
                Contact.workspace_id == user.workspace_id,
                Contact.phone == contact.phone,
            )
        )
        if existing:
            duplicates += 1
            continue
        db.add(Contact(workspace_id=user.workspace_id, **contact.model_dump()))
        db.flush()
        imported += 1
    audit(
        db,
        user,
        "contacts.imported",
        detail={"imported": imported, "duplicates": duplicates},
    )
    return {"imported": imported, "duplicates": duplicates}


@router.get("/numbers")
def numbers(user=Depends(current_user), db: Session = Depends(get_db)):
    return [public_record(n) for n in rows(db, PhoneNumber, user.workspace_id)]


@router.post("/numbers")
def create_number(data: PhoneInput, user=Depends(admin), db: Session = Depends(get_db)):
    connection = owned(db, Connection, data.connection_id, user.workspace_id)
    owned(db, Agent, data.agent_id, user.workspace_id)
    if connection.provider != "twilio" or not connection.active:
        raise HTTPException(422, "Select an active Twilio connection")
    item = PhoneNumber(workspace_id=user.workspace_id, **data.model_dump())
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This number is already assigned")
    audit(db, user, "number.assigned", item.id)
    return public_record(item)


@router.delete("/numbers/{record_id}")
def delete_number(record_id: str, user=Depends(admin), db: Session = Depends(get_db)):
    item = owned(db, PhoneNumber, record_id, user.workspace_id)
    if db.scalar(select(Campaign.id).where(Campaign.phone_number_id == item.id)):
        raise HTTPException(409, "This number is used by a campaign")
    db.delete(item)
    audit(db, user, "number.removed", record_id)
    return {"ok": True}


@router.get("/campaigns")
def campaigns(user=Depends(current_user), db: Session = Depends(get_db)):
    result = []
    for c in rows(db, Campaign, user.workspace_id):
        item = public_record(c)
        item["recipients"] = [
            public_record(r)
            for r in db.scalars(
                select(Recipient).where(
                    Recipient.workspace_id == user.workspace_id,
                    Recipient.campaign_id == c.id,
                )
            )
        ]
        result.append(item)
    return result


@router.post("/campaigns")
def create_campaign(
    data: CampaignInput, user=Depends(editor), db: Session = Depends(get_db)
):
    agent = owned(db, Agent, data.agent_id, user.workspace_id)
    number = owned(db, PhoneNumber, data.phone_number_id, user.workspace_id)
    if agent.status != "published":
        raise HTTPException(422, "Publish the agent first")
    if data.window_start >= data.window_end:
        raise HTTPException(422, "Calling window must end after it starts")
    contact_ids = set(data.contact_ids)
    for contact_id in contact_ids:
        owned(db, Contact, contact_id, user.workspace_id)
    config = data.model_dump(
        exclude={"name", "agent_id", "phone_number_id", "contact_ids", "starts_at"}
    )
    item = Campaign(
        workspace_id=user.workspace_id,
        name=data.name,
        agent_version_id=agent.published_version_id,
        phone_number_id=number.id,
        config=config,
    )
    db.add(item)
    db.flush()
    for contact_id in contact_ids:
        db.add(
            Recipient(
                workspace_id=user.workspace_id,
                campaign_id=item.id,
                contact_id=contact_id,
                next_attempt_at=max(time.time(), data.starts_at),
            )
        )
    audit(db, user, "campaign.created", item.id)
    return public_record(item)


@router.post("/campaigns/{record_id}/{action}")
def campaign_action(
    record_id: str, action: str, user=Depends(editor), db: Session = Depends(get_db)
):
    if action not in {"start", "pause", "cancel"}:
        raise HTTPException(404, "Unknown campaign action")
    item = owned(db, Campaign, record_id, user.workspace_id)
    if item.status in {"cancelled", "completed"}:
        raise HTTPException(409, "This campaign has finished")
    if action == "start":
        from .telephony import public_base

        public_base()
        version = owned(db, AgentVersion, item.agent_version_id, user.workspace_id)
        agent = owned(db, Agent, version.agent_id, user.workspace_id)
        if agent.status != "published":
            raise HTTPException(409, "The campaign agent is paused")
        validate_config(db, user.workspace_id, version.config, True)
    item.status = {"start": "running", "pause": "paused", "cancel": "cancelled"}[action]
    audit(db, user, "campaign." + action, item.id)
    return public_record(item)


@router.get("/calls")
def calls(user=Depends(current_user), db: Session = Depends(get_db)):
    return [
        public_record(c, ("config", "knowledge", "variables"))
        for c in rows(db, Call, user.workspace_id, 200)
    ]


@router.get("/calls/{record_id}")
def call_detail(
    record_id: str, user=Depends(current_user), db: Session = Depends(get_db)
):
    item = owned(db, Call, record_id, user.workspace_id)
    result = public_record(item, ("knowledge",))
    result["events"] = [
        public_record(e)
        for e in db.scalars(
            select(CallEvent)
            .where(
                CallEvent.workspace_id == user.workspace_id,
                CallEvent.call_id == item.id,
            )
            .order_by(CallEvent.created_at)
        )
    ]
    return result


@router.post("/calls/outbound")
async def outbound(
    data: OutboundInput, user=Depends(editor), db: Session = Depends(get_db)
):
    from .telephony import place_outbound

    result = await place_outbound(
        db, user.workspace_id, data.agent_id, data.phone_number_id, data.contact_id
    )
    audit(db, user, "call.requested", result.id)
    return public_record(result, ("config", "knowledge", "variables"))


@router.get("/tasks")
def tasks(user=Depends(current_user), db: Session = Depends(get_db)):
    return [public_record(t) for t in rows(db, StaffTask, user.workspace_id)]


@router.post("/tasks/{record_id}/resolve")
def resolve_task(record_id: str, user=Depends(editor), db: Session = Depends(get_db)):
    item = owned(db, StaffTask, record_id, user.workspace_id)
    item.status = "resolved"
    audit(db, user, "task.resolved", item.id)
    return public_record(item)


@router.get("/audit")
def audits(user=Depends(admin), db: Session = Depends(get_db)):
    return [public_record(a) for a in rows(db, Audit, user.workspace_id, 200)]


@router.get("/users")
def users(user=Depends(admin), db: Session = Depends(get_db)):
    return [public_record(u) for u in rows(db, User, user.workspace_id)]


@router.post("/users", response_model=UserPublic)
def create_user(data: UserCreate, user=Depends(admin), db: Session = Depends(get_db)):
    # Reuse setup email normalization and password constraints.
    from pydantic import ValidationError

    try:
        valid = Setup(
            workspace="unused", name=data.name, email=data.email, password=data.password
        )
    except ValidationError:
        raise HTTPException(422, "Enter a valid name, email, and password")
    item = User(
        workspace_id=user.workspace_id,
        name=data.name,
        email=valid.email,
        role=data.role,
        password_hash=password_hash(data.password),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already exists")
    audit(db, user, "user.created", item.id, {"role": item.role})
    return public_record(item)


@router.put("/workspace", response_model=WorkspacePublic)
def update_workspace(
    data: WorkspaceInput, user=Depends(admin), db: Session = Depends(get_db)
):
    try:
        ZoneInfo(data.timezone)
    except Exception:
        raise HTTPException(422, "Unknown timezone")
    item = db.get(Workspace, user.workspace_id)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    audit(db, user, "workspace.updated", item.id)
    return public_record(item)


@router.post("/users/{record_id}/disable", response_model=UserPublic)
def disable_user(record_id: str, user=Depends(admin), db: Session = Depends(get_db)):
    db.get(Workspace, user.workspace_id, with_for_update=True)
    target = owned(db, User, record_id, user.workspace_id)
    if target.id == user.id:
        raise HTTPException(409, "Ask another administrator to deactivate your account")
    active_admins = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.workspace_id == user.workspace_id,
            User.active.is_(True),
            User.role == "admin",
        )
    )
    if target.active and target.role == "admin" and active_admins <= 1:
        raise HTTPException(409, "The workspace must retain an active administrator")
    target.active = False
    db.execute(delete(LoginSession).where(LoginSession.user_id == target.id))
    audit(db, user, "user.disabled", target.id)
    return target


@router.post("/users/{record_id}/revoke-sessions")
def revoke_user_sessions(
    record_id: str, user=Depends(admin), db: Session = Depends(get_db)
):
    target = owned(db, User, record_id, user.workspace_id)
    db.execute(delete(LoginSession).where(LoginSession.user_id == target.id))
    audit(db, user, "user.sessions_revoked", target.id)
    return {"ok": True}
