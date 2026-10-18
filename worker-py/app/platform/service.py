import copy
import hashlib
import json
import re
import time
from fastapi import HTTPException
from sqlalchemy import select
from .models import (
    Agent,
    AgentVersion,
    Connection,
    Collection,
    Document,
    Chunk,
    Audit,
    Call,
    CallEvent,
)
from .schemas import AgentConfig
from .security import decrypt

TEMPLATES = [
    {
        "id": "reception",
        "name": "Inbound reception",
        "description": "Answer hospital questions and route callers.",
        "greeting": "Hello, thank you for calling {{hospital_name}}. How can I help you today?",
        "instructions": "Answer questions using approved hospital information. Ask one question at a time. Offer a staff callback when an answer is unavailable.",
    },
    {
        "id": "appointment_reminder",
        "name": "Appointment reminders",
        "description": "Confirm attendance and collect rescheduling requests.",
        "greeting": "Hello, this is {{hospital_name}} calling about an appointment. Am I speaking with {{patient_name}}?",
        "instructions": "Verify you are speaking with the patient before sharing appointment details. Remind them about {{appointment_date}} at {{appointment_time}} with {{doctor_name}}. Ask if they plan to attend. Record confirmation or create a staff callback for cancellation or rescheduling. Do not claim a schedule was changed.",
    },
    {
        "id": "appointment_booking",
        "name": "Booking requests",
        "description": "Collect preferences for the scheduling team.",
        "greeting": "Hello, I can help arrange an appointment request. Which department do you need?",
        "instructions": "Collect the requested department and preferred date. Explain that a staff member will confirm availability. Create a callback request. Never invent available slots or claim a booking is confirmed.",
    },
    {
        "id": "procedure_preparation",
        "name": "Procedure preparation",
        "description": "Read approved preparation instructions.",
        "greeting": "Hello, this is {{hospital_name}} calling with preparation information. Am I speaking with {{patient_name}}?",
        "instructions": "Verify the patient before discussing their procedure. Share only approved preparation instructions from the attached knowledge. Escalate conflicting instructions or medication questions to staff.",
    },
    {
        "id": "discharge_followup",
        "name": "Discharge follow-up",
        "description": "Collect responses and route concerns to a nurse.",
        "greeting": "Hello, this is {{hospital_name}} checking in after your visit. Is this a good time to talk?",
        "instructions": "Use the approved follow-up questionnaire. Collect responses without diagnosing. Offer a nurse callback for concerns. Follow the urgent-symptom escalation instructions.",
    },
    {
        "id": "preventive_recall",
        "name": "Preventive care recall",
        "description": "Offer a staff callback for an eligible service.",
        "greeting": "Hello, this is {{hospital_name}}. May I speak with {{patient_name}}?",
        "instructions": "Verify the patient and explain the approved preventive care invitation. Ask whether they want staff to contact them. Respect refusal and opt-out requests.",
    },
    {
        "id": "medication_reminder",
        "name": "Medication reminders",
        "description": "Remind patients about existing prescribed instructions.",
        "greeting": "Hello, this is {{hospital_name}} with a reminder. Am I speaking with {{patient_name}}?",
        "instructions": "Only repeat existing prescribed instructions supplied by authorized staff. Never change a dose, prescribe, or recommend stopping medication. Route questions or reported adverse effects to staff.",
    },
    {
        "id": "feedback",
        "name": "Patient feedback",
        "description": "Collect feedback and create service-recovery tasks.",
        "greeting": "Hello, this is {{hospital_name}}. Would you like to share feedback about your visit?",
        "instructions": "Ask approved feedback questions one at a time. Record the response. Offer a staff callback for unresolved concerns. Do not discuss private clinical information with other people.",
    },
]
KOKORO = {"af_bella", "af_sky", "am_adam", "am_michael", "bf_emma"}
DEEPGRAM = {
    f"aura-2-{n}-en"
    for n in (
        "thalia",
        "andromeda",
        "helena",
        "apollo",
        "arcas",
        "aries",
        "pandora",
        "draco",
    )
}


def owned(db, model, record_id, workspace_id):
    value = db.get(model, record_id)
    if not value or value.workspace_id != workspace_id:
        raise HTTPException(404, "Record not found")
    return value


def audit(db, user, action, target=None, detail=None):
    db.add(
        Audit(
            workspace_id=user.workspace_id,
            actor_id=user.id,
            action=action,
            target_id=target,
            detail=detail or {},
        )
    )


def public_record(value, exclude=()):
    return {
        c.name: getattr(value, c.name)
        for c in value.__table__.columns
        if c.name
        not in set(exclude)
        | {"encrypted_secret", "password_hash", "stream_token_hash", "ingestion_token"}
    }


def validate_config(db, workspace_id, config, require_connections=False):
    config = AgentConfig.model_validate(config).model_dump()
    expected_voice = DEEPGRAM if config["tts_engine"] == "deepgram" else KOKORO
    if config["voice_id"] not in expected_voice:
        raise HTTPException(422, "Voice does not match the TTS provider")
    for field, providers, required in (
        ("stt_connection_id", {config["stt_engine"]}, True),
        ("llm_connection_id", {"groq", "openai"}, True),
        ("tts_connection_id", {"deepgram"}, config["tts_engine"] == "deepgram"),
    ):
        connection_id = config[field]
        if not connection_id:
            if required and require_connections:
                raise HTTPException(
                    422,
                    "Choose a saved "
                    + {
                        "stt_connection_id": "speech recognition",
                        "llm_connection_id": "language model",
                        "tts_connection_id": "voice synthesis",
                    }[field]
                    + " connection in Voice & models",
                )
            continue
        connection = owned(db, Connection, connection_id, workspace_id)
        if not connection.active or connection.provider not in providers:
            raise HTTPException(
                422,
                "The selected connection has the wrong provider or has been revoked",
            )
        if field == "llm_connection_id" and config["llm_model"]:
            from .model_catalog import supported_chat_model

            if not supported_chat_model(connection.provider, config["llm_model"]):
                raise HTTPException(
                    422,
                    "Choose a supported language model for the selected connection in Voice & models",
                )
    if require_connections and not config["llm_model"]:
        raise HTTPException(422, "Choose a language model in Voice & models")
    for collection_id in config["collection_ids"]:
        owned(db, Collection, collection_id, workspace_id)
    if "transfer" in config["tools"] and not config["transfer_number"]:
        raise HTTPException(422, "A staff transfer number is required")
    return config


def knowledge_snapshot(db, workspace_id, collection_ids):
    if not collection_ids:
        return []
    docs = db.scalars(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.collection_id.in_(collection_ids),
            Document.status == "approved",
            Document.ingestion_status.in_(["ready", "legacy"]),
        )
    ).all()
    result, size = [], 0
    for doc in docs:
        if doc.expires_at and doc.expires_at <= time.time():
            continue
        for chunk in db.scalars(
            select(Chunk)
            .where(Chunk.workspace_id == workspace_id, Chunk.document_id == doc.id)
            .order_by(Chunk.position)
        ):
            size += len(chunk.content)
            if size > 500000:
                raise HTTPException(
                    422,
                    "Attached knowledge exceeds 500,000 characters; split this agent by department",
                )
            result.append(
                {
                    "id": chunk.id,
                    "document_id": doc.id,
                    "title": doc.title,
                    "content": chunk.content,
                    "rag_point_id": (chunk.rag_metadata or {}).get("point_id"),
                    "headings": (chunk.rag_metadata or {}).get("headings", []),
                    "page_numbers": (chunk.rag_metadata or {}).get("page_numbers", []),
                    "expires_at": doc.expires_at,
                    "embedding": (
                        [float(v) for v in chunk.embedding]
                        if chunk.embedding is not None
                        else None
                    ),
                    "embedding_connection_id": db.get(
                        Collection, doc.collection_id
                    ).embedding_connection_id,
                }
            )
    return result


def knowledge_hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def validate_snapshot(db, workspace_id, snapshot):
    for document_id in {chunk["document_id"] for chunk in snapshot}:
        doc = owned(db, Document, document_id, workspace_id)
        if (
            doc.status != "approved"
            or doc.ingestion_status not in {"ready", "legacy"}
            or (doc.expires_at and doc.expires_at <= time.time())
        ):
            raise HTTPException(
                409,
                "Published knowledge was archived or expired. Review and republish this agent.",
            )


def retrieve(snapshot, query, limit=4):
    terms = set(re.findall(r"\w{3,}", query.lower())) - {
        "the",
        "and",
        "you",
        "can",
        "what",
        "have",
        "that",
        "with",
        "please",
        "for",
        "this",
        "are",
    }
    scored = []
    for chunk in snapshot:
        if chunk.get("expires_at") and chunk["expires_at"] <= time.time():
            continue
        words = set(
            re.findall(r"\w{3,}", (chunk["title"] + " " + chunk["content"]).lower())
        )
        score = len(terms & words)
        if score:
            scored.append((score, chunk))
    return [
        item
        for _, item in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
    ]


def chunk_document(db, document):
    for position, start in enumerate(range(0, len(document.content), 1000)):
        db.add(
            Chunk(
                workspace_id=document.workspace_id,
                document_id=document.id,
                position=position,
                content=document.content[max(0, start - 150) : start + 1000],
            )
        )


def runtime_bundle(db, user, agent_id, draft=False):
    agent = owned(db, Agent, agent_id, user.workspace_id)
    if draft:
        config = validate_config(
            db, user.workspace_id, copy.deepcopy(agent.config), True
        )
        return (
            agent,
            None,
            config,
            knowledge_snapshot(db, user.workspace_id, config["collection_ids"]),
        )
    if agent.status != "published" or not agent.published_version_id:
        raise HTTPException(409, "Publish the agent before using it")
    version = owned(db, AgentVersion, agent.published_version_id, user.workspace_id)
    validate_config(db, user.workspace_id, version.config, True)
    validate_snapshot(db, user.workspace_id, version.knowledge)
    return (
        agent,
        version,
        copy.deepcopy(version.config),
        copy.deepcopy(version.knowledge),
    )


def resolve_keys(db, workspace_id, config):
    keys = {}
    for channel, field in [
        ("stt", "stt_connection_id"),
        ("llm", "llm_connection_id"),
        ("tts", "tts_connection_id"),
    ]:
        if config.get(field):
            connection = owned(db, Connection, config[field], workspace_id)
            if not connection.active:
                raise HTTPException(409, "Provider connection was revoked")
            credentials = decrypt(connection.encrypted_secret)
            keys[channel] = credentials["api_key"]
            keys[channel + "_provider"] = connection.provider
    return keys


def event(db, call, kind, payload):
    db.add(
        CallEvent(
            workspace_id=call.workspace_id, call_id=call.id, kind=kind, payload=payload
        )
    )
