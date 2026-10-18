"""Durable, restart-safe campaign scheduling. No implicit retries of uncertain calls."""

import asyncio
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, delete
from celery import Celery
from .database import database
from .models import (
    Campaign,
    Recipient,
    Contact,
    AgentVersion,
    Agent,
    Call,
    CallEvent,
    StaffTask,
    Workspace,
    LoginSession,
)
from .telephony import (
    place_outbound,
    twilio_credentials,
    twilio_auth,
    finish_recipient,
    TERMINAL,
)
import httpx

celery = Celery("pulsemux", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
celery.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "campaign-dispatch": {"task": "pulsemux.dispatch", "schedule": 15.0},
        "retention": {"task": "pulsemux.retention", "schedule": 3600.0},
    },
)
ACTIVE = {
    "dispatching",
    "queued",
    "initiated",
    "ringing",
    "in-progress",
    "dispatch_unknown",
}


def eligible_hour(contact, config, now):
    hour = datetime.fromtimestamp(now, ZoneInfo(contact.timezone)).hour
    return config["window_start"] <= hour < config["window_end"]


async def dispatch_due():
    now = time.time()
    with database().Session() as db:
        campaign_ids = list(
            db.scalars(select(Campaign.id).where(Campaign.status == "running"))
        )
    for campaign_id in campaign_ids:
        with database().Session() as db:
            # A locked campaign serializes schedulers and enforces its concurrency
            # limit. Conditional recipient claims also protect SQLite local runs.
            campaign = db.scalar(
                select(Campaign)
                .where(Campaign.id == campaign_id)
                .with_for_update(skip_locked=True)
            )
            if not campaign or campaign.status != "running":
                continue
            version = db.get(AgentVersion, campaign.agent_version_id)
            agent = db.get(Agent, version.agent_id)
            if agent.status != "published":
                campaign.status = "paused"
                db.commit()
                continue
            recipients = list(
                db.scalars(
                    select(Recipient).where(Recipient.campaign_id == campaign.id)
                )
            )
            active = sum(r.status == "dispatching" for r in recipients)
            capacity = max(0, campaign.config["concurrency"] - active)
            claimed = []
            for recipient in recipients:
                if not capacity:
                    break
                if recipient.status != "pending" or recipient.next_attempt_at > now:
                    continue
                contact = db.get(Contact, recipient.contact_id)
                if not contact.consent or contact.opted_out:
                    recipient.status = "suppressed"
                    continue
                if not eligible_hour(contact, campaign.config, now):
                    continue
                result = db.execute(
                    update(Recipient)
                    .where(Recipient.id == recipient.id, Recipient.status == "pending")
                    .values(
                        status="dispatching",
                        attempts=Recipient.attempts + 1,
                        claimed_at=now,
                    )
                )
                if result.rowcount:
                    claimed.append(recipient.id)
                    capacity -= 1
            if not any(
                r.status in {"pending", "dispatching", "dispatch_unknown"}
                for r in recipients
            ):
                campaign.status = "completed"
            db.commit()
        for recipient_id in claimed:
            with database().Session() as db:
                recipient = db.get(Recipient, recipient_id)
                campaign = db.get(Campaign, campaign_id)
                # Consent and pause/cancel may have changed since the claim.
                if campaign.status != "running":
                    recipient.status = (
                        "pending" if campaign.status == "paused" else "suppressed"
                    )
                    db.commit()
                    continue
                version = db.get(AgentVersion, campaign.agent_version_id)
                try:
                    await place_outbound(
                        db,
                        campaign.workspace_id,
                        version.agent_id,
                        campaign.phone_number_id,
                        recipient.contact_id,
                        version_id=version.id,
                        recipient_id=recipient.id,
                    )
                except Exception:
                    db.rollback()
                    recipient = db.get(Recipient, recipient_id)
                    recipient.status = "failed"
                    db.add(
                        StaffTask(
                            workspace_id=campaign.workspace_id,
                            title="Campaign call could not be dispatched",
                            details="Review agent, contact, phone number, and provider configuration.",
                        )
                    )
                    db.commit()
    await reconcile_calls()


async def reconcile_calls():
    with database().Session() as db:
        for recipient in db.scalars(
            select(Recipient).where(
                Recipient.status == "dispatching",
                Recipient.claimed_at < time.time() - 120,
            )
        ):
            if not recipient.last_call_id:
                recipient.status = "dispatch_unknown"
                db.add(
                    StaffTask(
                        workspace_id=recipient.workspace_id,
                        title="Review interrupted campaign dispatch",
                        details="Worker stopped during dispatch. Check the provider call log before scheduling another attempt.",
                    )
                )
        call_ids = list(
            db.scalars(
                select(Call.id).where(
                    Call.status.in_(ACTIVE),
                    Call.direction != "simulation",
                    Call.created_at < time.time() - 60,
                )
            )
        )
        db.commit()
    for call_id in call_ids:
        with database().Session() as db:
            call = db.get(Call, call_id)
            if not call.provider_sid:
                if call.status == "dispatching" and call.created_at < time.time() - 120:
                    call.status = "dispatch_unknown"
                    db.add(
                        StaffTask(
                            workspace_id=call.workspace_id,
                            call_id=call.id,
                            title="Verify interrupted call dispatch",
                            details="Check the Twilio call log. Automatic redial is blocked.",
                        )
                    )
                    db.commit()
                continue
            try:
                credentials = twilio_credentials(
                    db, call.connection_id, call.workspace_id
                )
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(
                        f'https://api.twilio.com/2010-04-01/Accounts/{credentials["account_sid"]}/Calls/{call.provider_sid}.json',
                        auth=twilio_auth(credentials),
                    )
                    response.raise_for_status()
                    status = response.json()["status"]
                if status in TERMINAL:
                    call.status = status
                    call.ended_at = call.ended_at or time.time()
                    finish_recipient(db, call, status)
                    db.commit()
            except Exception:
                # No blind redial when credentials/network/callbacks are uncertain.
                continue


def prune_retention():
    with database().Session() as db:
        for workspace in db.scalars(select(Workspace)):
            cutoff = time.time() - workspace.retention_days * 86400
            expired = list(
                db.scalars(
                    select(Call.id).where(
                        Call.workspace_id == workspace.id, Call.ended_at < cutoff
                    )
                )
            )
            if expired:
                db.execute(delete(CallEvent).where(CallEvent.call_id.in_(expired)))
                # Keep aggregate call outcomes, remove conversation-bearing data.
                db.execute(
                    update(Call)
                    .where(Call.id.in_(expired))
                    .values(
                        variables={},
                        knowledge=[],
                        config={},
                        to_number=None,
                        from_number=None,
                        error=None,
                    )
                )
                db.execute(
                    update(StaffTask)
                    .where(StaffTask.call_id.in_(expired))
                    .values(details="[Removed by retention policy]")
                )
        db.execute(delete(LoginSession).where(LoginSession.expires_at < time.time()))
        db.commit()


@celery.task(name="pulsemux.dispatch")
def dispatch_task():
    asyncio.run(dispatch_due())


@celery.task(name="pulsemux.retention")
def retention_task():
    prune_retention()


async def run_local():
    import logging

    logging.basicConfig(level=logging.INFO)
    logging.getLogger(__name__).info(
        "Campaign scheduler polling the configured platform database every 15 seconds"
    )
    # Local development runner; deployments use Celery worker + beat.
    last_retention = 0
    while True:
        try:
            await dispatch_due()
            if time.time() - last_retention > 3600:
                prune_retention()
                last_retention = time.time()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Campaign worker cycle failed")
        await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(run_local())
