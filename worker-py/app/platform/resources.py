"""Workspace-scoped, bounded list APIs with explicit searchable/sortable fields."""

from math import ceil
from typing import Literal, Union
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from .database import get_db
from .security import current_user
from . import models as m
from .contracts import (
    PagePublic,
    AgentPublic,
    ConnectionPublic,
    CollectionPublic,
    ContactPublic,
    NumberPublic,
    CampaignPublic,
    CallPublic,
    TaskPublic,
    UserPublic,
    AuditPublic,
)

router = APIRouter(prefix="/api/resources")
_RESOURCE = {
    "agents": (m.Agent, AgentPublic, ("name", "description", "status")),
    "connections": (
        m.Connection,
        ConnectionPublic,
        ("name", "provider", "test_status"),
    ),
    "collections": (m.Collection, CollectionPublic, ("name", "description")),
    "contacts": (m.Contact, ContactPublic, ("name", "phone", "timezone")),
    "numbers": (m.PhoneNumber, NumberPublic, ("number", "label")),
    "campaigns": (m.Campaign, CampaignPublic, ("name", "status")),
    "calls": (
        m.Call,
        CallPublic,
        ("direction", "status", "to_number", "from_number", "outcome"),
    ),
    "tasks": (m.StaffTask, TaskPublic, ("title", "details", "status")),
    "users": (m.User, UserPublic, ("name", "email", "role")),
    "audit": (m.Audit, AuditPublic, ("action", "target_id")),
}
PublicRecord = Union[
    AgentPublic,
    ConnectionPublic,
    CollectionPublic,
    ContactPublic,
    NumberPublic,
    CampaignPublic,
    CallPublic,
    TaskPublic,
    UserPublic,
    AuditPublic,
]


@router.get("/{resource}", response_model=PagePublic[PublicRecord])
def resource_page(
    resource: str,
    page: int = Query(1, ge=1, le=1000000),
    page_size: int = Query(25, ge=1, le=100),
    q: str = Query("", max_length=200),
    sort: Literal["created_at", "name", "status"] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    if resource not in _RESOURCE:
        raise HTTPException(404, "Unknown resource")
    if resource in {"users", "audit"} and user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    model, dto, searchable = _RESOURCE[resource]
    conditions = [model.workspace_id == user.workspace_id]
    if q.strip():
        value = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(
            or_(
                *(
                    getattr(model, field).ilike(f"%{value}%", escape="\\")
                    for field in searchable
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(model).where(*conditions))
    column = getattr(model, sort, None)
    if column is None:
        raise HTTPException(
            422, "This resource does not support the selected sort field"
        )
    order = column.asc() if direction == "asc" else column.desc()
    records = db.scalars(
        select(model)
        .where(*conditions)
        .order_by(order, model.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [dto.model_validate(record) for record in records]
    if resource == "calls" and items:
        names = dict(
            db.execute(
                select(m.Agent.id, m.Agent.name).where(
                    m.Agent.workspace_id == user.workspace_id,
                    m.Agent.id.in_([item.agent_id for item in items]),
                )
            ).all()
        )
        for item in items:
            item.agent_name = names.get(item.agent_id)
    if resource == "campaigns" and items:
        counts = db.execute(
            select(m.Recipient.campaign_id, m.Recipient.status, func.count())
            .where(
                m.Recipient.workspace_id == user.workspace_id,
                m.Recipient.campaign_id.in_([item.id for item in items]),
            )
            .group_by(m.Recipient.campaign_id, m.Recipient.status)
        ).all()
        by_id = {item.id: item for item in items}
        for campaign_id, status, count in counts:
            item = by_id[campaign_id]
            item.recipient_count += count
            field = {
                "completed": "completed_count",
                "failed": "failed_count",
                "suppressed": "suppressed_count",
            }.get(status)
            if field:
                setattr(item, field, count)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": ceil(total / page_size),
    }
