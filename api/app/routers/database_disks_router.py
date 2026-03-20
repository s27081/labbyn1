"""Router for Disks Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import RequestContext
from app.core.exceptions import AccessDeniedError, ObjectNotFoundError, ValidationError
from app.database import get_async_db
from app.db.models import Disks, Machines
from app.db.schemas import DiskCreate, DiskResponse, DiskUpdate
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["Disks"])


@router.post(
    "/disks/",
    response_model=DiskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_disk(
    disk_data: DiskCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create new Disk.

    :param disk_data: Disk data
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Disk object.
    """
    ctx.require_user()

    if not ctx.is_admin:
        if not getattr(disk_data, "machine_id", None):
            raise AccessDeniedError(
                "Non-admin users must attach disks to a specific machine."
            )

    stmt = select(Machines).where(Machines.id == disk_data.machine_id)
    stmt = ctx.team_filter(stmt, Machines)
    result = await db.execute(stmt)
    machine = result.scalar_one_or_none()

    if not machine:
        raise ObjectNotFoundError("Machine for this disk")

    try:
        obj = Disks(**disk_data.model_dump())
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj
    except Exception as e:
        await db.rollback()
        raise ValidationError(
            f"Failed to add disk '{disk_data.name}' to machine '{machine.name}'"
        ) from e


@router.get("/disks/", response_model=List[DiskResponse])
async def get_disks(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch all Disks.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of all Disks.
    """
    ctx.require_user()
    stmt = select(Disks).join(Machines)
    stmt = ctx.team_filter(stmt, Machines)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/disks/{disk_id}", response_model=DiskResponse)
async def get_disk_by_id(
    disk_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch specific disk by ID.

    :param disk_id: Disk ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Disk object.
    """
    ctx.require_user()
    stmt = select(Disks).join(Machines).filter(Disks.id == disk_id)
    stmt = ctx.team_filter(stmt, Machines)
    result = await db.execute(stmt)
    disk = result.scalar_one_or_none()

    if not disk:
        raise ObjectNotFoundError("Disk")
    return disk


@router.patch("/disks/{disk_id}", response_model=DiskResponse)
async def update_disk(
    disk_id: int,
    disk_data: DiskUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update disk.

    :param disk_id: Disk ID
    :param disk_data: Disk data schema
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Updated disk.
    """
    ctx.require_user()
    async with acquire_lock(f"disk_lock:{disk_id}"):
        stmt = (
            select(Disks)
            .options(selectinload(Disks.machine))
            .join(Machines)
            .filter(Disks.id == disk_id)
        )
        stmt = ctx.team_filter(stmt, Machines)
        result = await db.execute(stmt)
        disk = result.scalar_one_or_none()

        if not disk:
            raise ObjectNotFoundError("Disk")

        try:
            for k, v in disk_data.model_dump(exclude_unset=True).items():
                setattr(disk, k, v)
            await db.commit()
            await db.refresh(disk)
            return disk
        except Exception as e:
            await db.rollback()
            raise ValidationError(
                f"Update failed for disk '{disk.name}' on {disk.machine.name}"
            ) from e


@router.delete(
    "/disks/{disk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_disk(
    disk_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete disk.

    :param disk_id: Disk ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: 204 No Content as success
    """
    ctx.require_user()
    async with acquire_lock(f"disk_lock:{disk_id}"):
        stmt = (
            select(Disks)
            .options(selectinload(Disks.machine))
            .join(Machines)
            .filter(Disks.id == disk_id)
        )
        stmt = ctx.team_filter(stmt, Machines)
        result = await db.execute(stmt)
        disk = result.scalar_one_or_none()

        if not disk:
            raise ObjectNotFoundError("Disk")

        try:
            await db.delete(disk)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            await db.rollback()
            raise ValidationError(
                f"Could not delete disk '{disk.name}' from {disk.machine.name}"
            ) from e
