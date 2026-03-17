"""Router for CPUs Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestContext
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
    if not ctx.is_admin:
        if not getattr(cpu_data, "machine_id", None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Non-admin users must attach CPUs to a specific machine.",
            )

    stmt = select(Machines).where(Machines.id == cpu_data.machine_id)
    stmt = ctx.team_filter(stmt, Machines)
    result = await db.execute(stmt)
    machine = result.scalar_one_or_none()

    if not machine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target machine not found or access denied.",
        )

    obj = CPUs(**cpu_data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="CPU not found"
        )
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
    ctx.require_admin()

    async with acquire_lock(f"cpu_lock:{cpu_id}"):
        stmt = select(CPUs).join(Machines).filter(CPUs.id == cpu_id)
        stmt = ctx.team_filter(stmt, Machines)
        result = await db.execute(stmt)
        cpu = result.scalar_one_or_none()

        if not cpu:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="CPU not found"
            )
        for k, v in cpu_data.model_dump(exclude_unset=True).items():
            setattr(cpu, k, v)
        await db.commit()
        await db.refresh(cpu)
        return cpu


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
    ctx.require_admin()

    async with acquire_lock(f"cpu_lock:{cpu_id}"):
        stmt = select(CPUs).join(Machines).filter(CPUs.id == cpu_id)
        stmt = ctx.team_filter(stmt, Machines)
        result = await db.execute(stmt)
        cpu = result.scalar_one_or_none()

        if not cpu:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="CPU not found"
            )
        await db.delete(cpu)
        await db.commit()
