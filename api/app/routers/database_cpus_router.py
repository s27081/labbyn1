"""Router for CPUs Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import RequestContext
from app.core.exceptions import AccessDeniedError, ObjectNotFoundError, ValidationError
from app.database import get_async_db
from app.db.models import CPUs, Machines
from app.db.schemas import CPUCreate, CPUResponse, CPUUpdate
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["CPUs"])


@router.post(
    "/cpus",
    response_model=CPUResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cpu(
    cpu_data: CPUCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create new CPU.

    :param cpu_data: CPU data
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: CPU object.
    """
    ctx.require_user()

    if not ctx.is_admin:
        if not getattr(cpu_data, "machine_id", None):
            raise AccessDeniedError(
                "Non-admin users must attach CPUs to a specific machine."
            )

    stmt = select(Machines).where(Machines.id == cpu_data.machine_id)
    stmt = ctx.team_filter(stmt, Machines)
    result = await db.execute(stmt)
    machine = result.scalar_one_or_none()

    if not machine:
        raise ObjectNotFoundError("Machine for this CPU")

    try:
        obj = CPUs(**cpu_data.model_dump())
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj
    except Exception as e:
        await db.rollback()
        raise ValidationError(
            f"Failed to add CPU '{cpu_data.name}' to machine '{machine.name}'"
        ) from e


@router.get("/cpus", response_model=List[CPUResponse])
async def get_cpus(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch all CPUs.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of all CPUs.
    """
    ctx.require_user()

    stmt = select(CPUs).join(Machines)
    stmt = ctx.team_filter(stmt, Machines)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/cpus/{cpu_id}", response_model=CPUResponse)
async def get_cpu_by_id(
    cpu_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch specific CPU by ID.

    :param cpu_id: CPU ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: CPU object.
    """
    ctx.require_user()
    stmt = select(CPUs).join(Machines).filter(CPUs.id == cpu_id)
    stmt = ctx.team_filter(stmt, Machines)
    result = await db.execute(stmt)
    cpu = result.scalar_one_or_none()

    if not cpu:
        raise ObjectNotFoundError("CPU")
    return cpu


@router.patch("/cpus/{cpu_id}", response_model=CPUResponse)
async def update_cpu(
    cpu_id: int,
    cpu_data: CPUUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update CPU.

    :param cpu_id: CPU ID
    :param cpu_data: CPU data schema
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Updated CPU.
    """
    ctx.require_user()

    async with acquire_lock(f"cpu_lock:{cpu_id}"):
        stmt = (
            select(CPUs)
            .options(selectinload(CPUs.machine))
            .join(Machines)
            .filter(CPUs.id == cpu_id)
        )
        stmt = ctx.team_filter(stmt, Machines)
        result = await db.execute(stmt)
        cpu = result.scalar_one_or_none()

        if not cpu:
            raise ObjectNotFoundError("CPU")

        try:
            for k, v in cpu_data.model_dump(exclude_unset=True).items():
                setattr(cpu, k, v)
            await db.commit()
            await db.refresh(cpu)
            return cpu
        except Exception as e:
            await db.rollback()
            raise ValidationError(
                f"Update failed for CPU '{cpu.name}' on machine '{cpu.machine.name}'"
            ) from e


@router.delete(
    "/cpus/{cpu_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_cpu(
    cpu_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete CPU.

    :param cpu_id: CPU ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: 204 No Content as success
    """
    ctx.require_user()

    async with acquire_lock(f"cpu_lock:{cpu_id}"):
        stmt = (
            select(CPUs)
            .options(selectinload(CPUs.machine))
            .join(Machines)
            .filter(CPUs.id == cpu_id)
        )
        stmt = ctx.team_filter(stmt, Machines)
        result = await db.execute(stmt)
        cpu = result.scalar_one_or_none()

        if not cpu:
            raise ObjectNotFoundError("CPU")

        try:
            await db.delete(cpu)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            await db.rollback()
            raise ValidationError(
                f"Could not delete CPU '{cpu.name}' from {cpu.machine.name}"
            ) from e
