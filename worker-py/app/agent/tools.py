import datetime
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Mock EHR Database
MOCK_PATIENT_RECORDS = {
    "patient-101": {
        "name": "Sarah Connor",
        "dob": "1985-05-12",
        "primary_physician": "Dr. House",
        "allergies": ["Penicillin"],
        "chronic_conditions": ["Hypertension"],
    },
    "patient-anon": {
        "name": "Anonymous Patient",
        "dob": "Unknown",
        "primary_physician": "On-Call Clinician",
        "allergies": [],
        "chronic_conditions": [],
    },
}

MOCK_DOCTOR_SLOTS = [
    {"slot_id": "slot-01", "doctor": "Dr. Gregory House", "specialty": "Cardiology", "time": "Tomorrow at 10:00 AM"},
    {"slot_id": "slot-02", "doctor": "Dr. Allison Cameron", "specialty": "General Medicine", "time": "Tomorrow at 2:30 PM"},
    {"slot_id": "slot-03", "doctor": "Dr. Eric Foreman", "specialty": "Neurology", "time": "Friday at 11:15 AM"},
]


def lookup_patient_record(patient_id: str) -> Dict[str, Any]:
    """Retrieves patient EHR summary by ID."""
    return MOCK_PATIENT_RECORDS.get(patient_id, MOCK_PATIENT_RECORDS["patient-anon"])


def check_red_flag_symptoms(symptoms_description: str) -> Dict[str, Any]:
    """
    Evaluates clinical urgency against critical red-flag emergency symptoms.
    """
    lower = symptoms_description.lower()
    critical_triggers = [
        "chest pain",
        "pressure in chest",
        "radiating to arm",
        "cannot breathe",
        "shortness of breath",
        "passed out",
        "unconscious",
        "sudden numbness",
        "face drooping",
    ]

    matched = [trigger for trigger in critical_triggers if trigger in lower]
    is_emergency = len(matched) > 0

    return {
        "is_emergency": is_emergency,
        "matched_red_flags": matched,
        "recommended_action": "EMERGENCY_DISPATCH" if is_emergency else "STANDARD_TRIAGE",
    }


def find_available_slots(specialty: Optional[str] = None) -> List[Dict[str, str]]:
    """Returns available clinic booking slots filtered by specialty."""
    if not specialty:
        return MOCK_DOCTOR_SLOTS
    return [
        slot for slot in MOCK_DOCTOR_SLOTS
        if specialty.lower() in slot["specialty"].lower()
    ]


def book_appointment_slot(patient_id: str, slot_id: str) -> Dict[str, Any]:
    """Confirms booking reservation for patient in EHR."""
    logger.info("appointment_booking_completed")
    return {
        "status": "CONFIRMED",
        "confirmation_code": f"CONF-{datetime.datetime.now().strftime('%Y%m%d%H%M')}",
        "patient_id": patient_id,
        "slot_id": slot_id,
    }
