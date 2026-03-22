"""Router for Metadata Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import RequestContext
from app.core.exceptions import (
    ObjectNotFoundError,
    ValidationError,
)
from app.database import get_async_db
from app.db.models import Machines, Metadata
from app.db.schemas import MetadataCreate, MetadataResponse, MetadataUpdate
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["Machines Metadata"])


@router.post(
    "/metadata",
    response_model=MetadataResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_metadata(
    meta_data: MetadataCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create new metadata.

    :param meta_data: Metadata data
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Metadata object.
    """
    ctx.require_user()
    try:
        obj = Metadata(**meta_data.model_dump())
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj
    except Exception as e:
        await db.rollback()
        raise ValidationError("Failed to create metadata record") from e


@router.get("/metadata", response_model=List[MetadataResponse])
async def get_all_metadata(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch all metadata records.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of Metadata.
    """
    ctx.require_user()
    stmt = select(Metadata).join(Machines)
    result = await db.execute(ctx.team_filter(stmt, Machines))

    return result.scalars().all()


@router.get("/metadata/{meta_id}", response_model=MetadataResponse)
async def get_metadata(
    meta_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch metadata by ID.

    :param meta_id: Metadata ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Metadata object.
    """
    ctx.require_user()
    stmt = select(Metadata).filter(Metadata.id == meta_id).join(Machines)
    obj = (await db.execute(ctx.team_filter(stmt, Machines))).scalar_one_or_none()

    if not obj:
        raise ObjectNotFoundError("Metadata")
    return obj


@router.patch("/metadata/{meta_id}", response_model=MetadataResponse)
async def update_metadata(
    meta_id: int,
    data: MetadataUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update Metadata.

    :param meta_id: Metadata ID
    :param data: Metadata data schema
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Updated Metadata.
    """
    ctx.require_user()
    async with acquire_lock(f"meta_lock:{meta_id}"):
        stmt = (
            select(Metadata)
            .filter(Metadata.id == meta_id)
            .join(Machines)
            .options(selectinload(Metadata.machines))
        )
        obj = (await db.execute(ctx.team_filter(stmt, Machines))).scalar_one_or_none()
        if not obj:
            raise ObjectNotFoundError("Metadata")

        m_name = obj.machines[0].name if obj.machines else f"ID {meta_id}"

        try:
            for k, v in data.model_dump(exclude_unset=True).items():
                setattr(obj, k, v)

            await db.commit()
            return obj
        except Exception as e:
            await db.rollback()
            raise ValidationError(
                f"Failed to update metadata for machine '{m_name}'"
            ) from e


@router.delete("/metadata/{meta_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_metadata(
    meta_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete Metadata.

    :param meta_id: Metadata ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: None.
    """
    ctx.require_user()
    async with acquire_lock(f"meta_lock:{meta_id}"):
        stmt = (
            select(Metadata)
            .filter(Metadata.id == meta_id)
            .join(Machines)
            .options(selectinload(Metadata.machines))
        )

        obj = (await db.execute(ctx.team_filter(stmt, Machines))).scalar_one_or_none()

        if not obj:
            raise ObjectNotFoundError("Metadata")

        m_name = obj.machines[0].name if obj.machines else f"ID {meta_id}"

        try:
            await db.delete(obj)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            await db.rollback()
            raise ValidationError(
                f"Could not delete metadata for machine '{m_name}'"
            ) from e
