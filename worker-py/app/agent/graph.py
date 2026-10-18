import logging
from typing import Annotated, Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field

from app.agent.tools import (
    check_red_flag_symptoms,
    find_available_slots,
    book_appointment_slot,
    lookup_patient_record,
)

logger = logging.getLogger(__name__)


class ClinicalState(TypedDict):
    """Conversation and triage state container for LangGraph."""
    call_id: str
    patient_id: str
    messages: List[Dict[str, str]]
    current_node: str
    symptoms: str
    is_emergency: bool
    recommended_slot: Optional[Dict[str, str]]
    confirmation_code: Optional[str]


def triage_symptoms_node(state: ClinicalState) -> Dict[str, Any]:
    """Node 1: Extract and verify patient reported symptoms."""
    logger.info(f"LangGraph [TRIAGE_SYMPTOMS] Call={state['call_id']}")
    latest_msg = state["messages"][-1]["content"] if state["messages"] else ""
    symptoms = state.get("symptoms", "") + " " + latest_msg

    return {
        "current_node": "TRIAGE_SYMPTOMS",
        "symptoms": symptoms.strip(),
    }


def red_flag_check_node(state: ClinicalState) -> Dict[str, Any]:
    """Node 2: Evaluate clinical urgency against red-flag criteria."""
    logger.info(f"LangGraph [RED_FLAG_CHECK] Call={state['call_id']}")
    eval_result = check_red_flag_symptoms(state.get("symptoms", ""))

    return {
        "current_node": "RED_FLAG_CHECK",
        "is_emergency": eval_result["is_emergency"],
    }


def routing_decision(state: ClinicalState) -> str:
    """Conditional Edge: Route to Emergency Escalation or Slot Booking."""
    if state.get("is_emergency", False):
        return "emergency_escalation"
    return "book_slot"


def emergency_escalation_node(state: ClinicalState) -> Dict[str, Any]:
    """Emergency Escalation Branch: Immediate transfer warning."""
    logger.warning(f"LangGraph [EMERGENCY_ESCALATION] Call={state['call_id']}")
    msg = (
        "Your symptoms indicate potential cardiovascular distress. "
        "Please remain calm while I immediately connect you to emergency medical services."
    )
    return {
        "current_node": "EMERGENCY_ESCALATION",
        "messages": state["messages"] + [{"role": "assistant", "content": msg}],
    }


def book_slot_node(state: ClinicalState) -> Dict[str, Any]:
    """Node 3: Query EHR and offer an appointment slot."""
    logger.info(f"LangGraph [BOOKING_SLOT] Call={state['call_id']}")
    slots = find_available_slots("General Medicine")
    chosen = slots[0] if slots else None

    msg = (
        f"Thank you for sharing your symptoms. I have an available slot with {chosen['doctor']} "
        f"at {chosen['time']}. Would you like me to book this for you?"
        if chosen else
        "I am checking with our scheduling coordinator to find the next available doctor."
    )

    return {
        "current_node": "BOOKING_SLOT",
        "recommended_slot": chosen,
        "messages": state["messages"] + [{"role": "assistant", "content": msg}],
    }


def confirm_booking_node(state: ClinicalState) -> Dict[str, Any]:
    """Node 4: Confirm appointment reservation in EHR."""
    logger.info(f"LangGraph [CONFIRMATION] Call={state['call_id']}")
    slot = state.get("recommended_slot")
    slot_id = slot["slot_id"] if slot else "slot-01"

    booking = book_appointment_slot(state["patient_id"], slot_id)
    msg = f"Your appointment has been confirmed. Your confirmation code is {booking['confirmation_code']}."

    return {
        "current_node": "CONFIRMATION",
        "confirmation_code": booking["confirmation_code"],
        "messages": state["messages"] + [{"role": "assistant", "content": msg}],
    }


class ClinicalTriageGraph:
    """
    State machine controller encapsulating clinical triage workflow.
    Provides execution step method and streaming token simulation.
    """

    def __init__(self, redis_url: Optional[str] = None, groq_api_key: Optional[str] = None):
        import os
        self.redis_url = redis_url
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
        logger.info(
            f"Initialized ClinicalTriageGraph (Redis: {'configured' if redis_url else 'in-memory'}, "
            f"Groq: {'Active (' + self.groq_model + ')' if self.groq_api_key else 'Offline/Rule-based'})"
        )

    async def step(self, state: ClinicalState) -> ClinicalState:
        """Executes the state transition cycle based on current state."""
        current = state.get("current_node", "INIT")
        user_msg = state["messages"][-1]["content"] if state["messages"] else ""

        if self.groq_api_key:
            # Groq-powered clinical reasoning
            return await self._step_groq(state, user_msg)

        # Fallback rule-based state machine
        if current in ("INIT", "CONFIRMATION"):
            out = triage_symptoms_node(state)
            state.update(out)
            out = red_flag_check_node(state)
            state.update(out)

            next_route = routing_decision(state)
            if next_route == "emergency_escalation":
                out = emergency_escalation_node(state)
            else:
                out = book_slot_node(state)
            state.update(out)
            return state

        elif current == "BOOKING_SLOT":
            out = confirm_booking_node(state)
            state.update(out)
            return state

        return state

    async def _step_groq(self, state: ClinicalState, user_msg: str) -> ClinicalState:
        """Runs clinical reasoning using ultra-fast Groq LPU inference."""
        import httpx
        import json

        # 1. Quick red-flag check
        eval_result = check_red_flag_symptoms(user_msg)
        is_emergency = eval_result["is_emergency"]

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }

        system_prompt = (
            "You are PulseMux, an ultra-low latency clinical triage voice assistant. "
            "Your output will be spoken aloud to a patient via TTS. "
            "CRITICAL INSTRUCTIONS: "
            "1. If patient shows RED FLAGS (chest pain, stroke symptoms, acute shortness of breath, severe bleeding): "
            "   Command them immediately and calmly to call emergency services (911/112), sit down, and do not drive. "
            "2. If symptoms are non-emergency: "
            "   Acknowledge their condition empathetically, offer concise care guidance, and offer to schedule an appointment. "
            "3. Keep your spoken response strictly to 1 to 2 clear sentences. Never use Markdown bullet points or asterisks."
        )

        messages = [{"role": "system", "content": system_prompt}]
        for m in state.get("messages", [])[-4:]:
            messages.append({"role": m["role"], "content": m["content"]})

        payload = {
            "model": self.groq_model,
            "messages": messages,
            "max_tokens": 120,
            "temperature": 0.2,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if r.status_code == 200:
                    assistant_text = r.json()["choices"][0]["message"]["content"].strip()
                else:
                    logger.error("provider_failure provider=groq operation=llm status=%s", r.status_code)
                    assistant_text = "I have noted your symptoms. Let me connect you with our clinical care team."
        except Exception as e:
            logger.error("provider_failure provider=groq operation=llm")
            assistant_text = "I have noted your symptoms. Let me connect you with our clinical care team."

        node_name = "EMERGENCY_ESCALATION" if is_emergency else "TRIAGE_SYMPTOMS"
        state["current_node"] = node_name
        state["is_emergency"] = is_emergency
        state["symptoms"] = (state.get("symptoms", "") + " " + user_msg).strip()
        state["messages"].append({"role": "assistant", "content": assistant_text})
        return state

    async def stream_tokens(self, text: str):
        """Streams text word-by-word with realistic token arrival cadence."""
        import asyncio
        words = text.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.03)

    async def stream_groq(self, messages: list):
        """Streams raw token chunks in real-time straight from Groq SSE."""
        import httpx
        import json
        if not self.groq_api_key:
            return

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.groq_model,
            "messages": messages,
            "stream": True,
            "max_tokens": 150,
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream(
                "POST", "https://api.groq.com/openai/v1/chat/completions",
                headers=headers, json=payload,
            ) as response:
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue
