from typing import Optional, Literal, List, Dict
from pydantic import BaseModel, Field, ConfigDict, field_validator
from zoneinfo import ZoneInfo
import re


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Setup(Strict):
    setup_token: Optional[str] = Field(default=None, max_length=256)
    workspace: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    timezone: str = "Asia/Kolkata"

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email")
        return value.lower().strip()

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("Unknown timezone")
        return value


class Login(Strict):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class UserCreate(Strict):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "operator", "viewer"] = "operator"


class ConnectionInput(Strict):
    name: str = Field(min_length=2, max_length=120)
    provider: Literal["deepgram", "groq", "openai", "twilio", "plivo"]
    credentials: Dict[str, str]


class AgentConfig(Strict):
    template: Literal[
        "reception",
        "appointment_reminder",
        "appointment_booking",
        "procedure_preparation",
        "discharge_followup",
        "preventive_recall",
        "medication_reminder",
        "feedback",
    ] = "reception"
    department: str = Field(default="Reception", max_length=120)
    language: Literal["en"] = "en"
    greeting: str = Field(
        default="Hello, I am your hospital assistant. How can I help you today?",
        min_length=5,
        max_length=600,
    )
    instructions: str = Field(
        default="Be warm and concise. Ask one question at a time. Use approved hospital information. Offer a staff callback when you cannot help.",
        min_length=20,
        max_length=12000,
    )
    tone: Literal["warm", "professional", "calm"] = "warm"
    stt_engine: Literal["deepgram", "groq"] = "deepgram"
    stt_keyterms: List[str] = Field(default_factory=list, max_length=25)
    stt_connection_id: Optional[str] = None
    llm_connection_id: Optional[str] = None
    llm_model: str = Field(default="qwen/qwen3.8-27b", max_length=100)
    tts_engine: Literal["kokoro", "deepgram"] = "kokoro"
    tts_connection_id: Optional[str] = None
    voice_id: str = Field(default="af_bella", max_length=80)
    collection_ids: List[str] = Field(default_factory=list, max_length=20)
    tools: List[
        Literal["request_callback", "record_outcome", "opt_out", "transfer"]
    ] = Field(default_factory=lambda: ["request_callback", "record_outcome", "opt_out"])
    transfer_number: str = Field(default="", max_length=20)
    emergency_instructions: str = Field(
        default="For urgent symptoms, tell the caller to contact their local emergency service immediately and offer to connect hospital staff. Do not claim emergency services have been dispatched.",
        min_length=10,
        max_length=1200,
    )
    max_duration_seconds: int = Field(default=600, ge=60, le=1800)
    silence_timeout_seconds: int = Field(default=60, ge=15, le=180)
    end_pause_ms: int = Field(default=800, ge=400, le=1800)

    @field_validator("stt_keyterms")
    @classmethod
    def recognition_terms(cls, value):
        from app.pipeline.recognition_options import validate_keyterms
        return validate_keyterms(value)

    @field_validator("transfer_number")
    @classmethod
    def phone(cls, value):
        if value and not re.fullmatch(r"\+[1-9]\d{7,14}", value):
            raise ValueError("Use an E.164 phone number")
        return value


class AgentInput(Strict):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    config: AgentConfig = Field(default_factory=AgentConfig)
    revision: Optional[int] = None


class CollectionInput(Strict):
    embedding_connection_id: Optional[str] = None
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)


class DocumentInput(Strict):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=10, max_length=200000)
    expires_at: Optional[float] = None


class PhoneInput(Strict):
    number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    label: str = Field(default="", max_length=120)
    connection_id: str
    agent_id: str


class ContactInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    consent: bool = False
    opted_out: bool = False
    timezone: str = "Asia/Kolkata"
    variables: Dict[str, str] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("Unknown timezone")
        return value


class CampaignInput(Strict):
    name: str = Field(min_length=2, max_length=120)
    agent_id: str
    phone_number_id: str
    contact_ids: List[str] = Field(min_length=1, max_length=1000)
    starts_at: float
    max_attempts: int = Field(default=2, ge=1, le=5)
    retry_minutes: int = Field(default=60, ge=15, le=1440)
    concurrency: int = Field(default=2, ge=1, le=20)
    window_start: int = Field(default=9, ge=0, le=23)
    window_end: int = Field(default=18, ge=1, le=24)


class OutboundInput(Strict):
    agent_id: str
    phone_number_id: str
    contact_id: str


class WorkspaceInput(Strict):
    name: str = Field(min_length=2, max_length=120)
    timezone: str = "Asia/Kolkata"
    retention_days: int = Field(default=90, ge=1, le=3650)
