"""Router for Shelf Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import RequestContext
from app.core.exceptions import (
    AccessDeniedError,
    ObjectNotFoundError,
    ValidationError,
)
from app.database import get_async_db
from app.db.models import Rack, Shelf
from app.db.schemas import ShelfCreate, ShelfResponse, ShelfUpdate
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["Shelves"])


@router.get("/rack/{rack_id}/all", response_model=List[ShelfResponse])
async def get_shelves_by_rack(
    rack_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Get all shelves for a specific rack.

    :param rack_id: ID of the rack
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of shelves belonging to the rack.
    """
    ctx.require_user()

    rack_stmt = select(Rack).filter(Rack.id == rack_id)
    rack_stmt = ctx.team_filter(rack_stmt, Rack)
    rack_res = await db.execute(rack_stmt)
    rack = rack_res.scalar_one_or_none()

    if not rack:
        raise ObjectNotFoundError("Rack")

    stmt = (
        select(Shelf)
        .options(joinedload(Shelf.machines))
        .filter(Shelf.rack_id == rack_id)
        .order_by(Shelf.order.desc())
    )

    result = await db.execute(stmt)
    return result.unique().scalars().all()


@router.get("/shelf/{shelf_id}", response_model=ShelfResponse)
async def get_single_shelf(
    shelf_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch specific shelf by ID with its nested machines.

    :param shelf_id: ID of the shelf
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Detailed shelf object.
    """
    ctx.require_user()

    stmt = (
        select(Shelf).options(joinedload(Shelf.machines)).filter(Shelf.id == shelf_id)
    )
    result = await db.execute(stmt)
    shelf = result.unique().scalar_one_or_none()

    if not shelf:
        raise ObjectNotFoundError("Shelf")

    rack_stmt = select(Rack).filter(Rack.id == shelf.rack_id)
    rack_stmt = ctx.team_filter(rack_stmt, Rack)
    rack_res = await db.execute(rack_stmt)

    if not rack_res.scalar_one_or_none():
        raise AccessDeniedError("You do not have permission to view this shelf")

    return shelf


@router.post(
    "/shelf/{rack_id}",
    response_model=ShelfResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_shelf(
    rack_id: int,
    shelf_data: ShelfCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create a new shelf in a specific rack.

    :param rack_id: ID of the parent rack
    :param shelf_data: Data for the new shelf
    :param db: Active database session
    :param ctx: Request context for authorization
    :return: Created shelf object with rack context.
    """
    ctx.require_user()
    async with acquire_lock(f"rack_lock:{rack_id}"):
        rack_stmt = select(Rack).filter(Rack.id == rack_id)
        rack_stmt = ctx.team_filter(rack_stmt, Rack)
        rack_res = await db.execute(rack_stmt)
        rack = rack_res.scalar_one_or_none()

        if not rack:
            raise ObjectNotFoundError("Rack")

        try:
            db_shelf = Shelf(**shelf_data.model_dump(), rack_id=rack_id)
            db.add(db_shelf)
            await db.commit()

            await db.refresh(db_shelf, attribute_names=["rack", "machines"])
            db_shelf.rack_name = rack.name
            return db_shelf
        except Exception as e:
            await db.rollback()
            raise ValidationError(
                f"Failed to create shelf {db_shelf.name} in rack '{rack.name}'"
            ) from e


@router.patch("/shelf/{shelf_id}", response_model=ShelfResponse)
async def update_shelf(
    shelf_id: int,
    shelf_data: ShelfUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update shelf details like name or order.

    :param shelf_id: ID of the shelf to update
    :param shelf_data: Fields to update
    :param db: Active database session
    :param ctx: Request context for permissions
    :return: Updated shelf object.
    """
    ctx.require_user()

    async with acquire_lock(f"shelf_lock:{shelf_id}"):
        stmt = select(Shelf).filter(Shelf.id == shelf_id)
        result = await db.execute(stmt)
        db_shelf = result.scalar_one_or_none()

        if not db_shelf:
            raise HTTPException(status_code=404, detail="Shelf does not exist.")

        rack_stmt = select(Rack).filter(Rack.id == db_shelf.rack_id)
        rack_stmt = ctx.team_filter(rack_stmt, Rack)
        rack_res = await db.execute(rack_stmt)

        if not rack_res.scalar_one_or_none():
            raise AccessDeniedError("You do not have permission to manage this shelf")

        try:
            update_dict = shelf_data.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                setattr(db_shelf, key, value)

            await db.commit()
            await db.refresh(db_shelf, attribute_names=["rack", "machines"])
            return db_shelf
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Failed to update shelf '{db_shelf.name}'") from e


@router.delete("/shelf/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shelf(
    shelf_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete a specific shelf if it is empty.

    :param shelf_id: ID of the shelf to delete
    :param db: Active database session
    :param ctx: Request context for authorization
    :return: No content response.
    """
    ctx.require_user()

    async with acquire_lock(f"shelf_lock:{shelf_id}"):
        stmt = (
            select(Shelf)
            .options(joinedload(Shelf.machines))
            .filter(Shelf.id == shelf_id)
        )
        result = await db.execute(stmt)
        db_shelf = result.unique().scalar_one_or_none()

        if not db_shelf:
            raise ObjectNotFoundError("Shelf")

        rack_stmt = select(Rack).filter(Rack.id == db_shelf.rack_id)
        rack_stmt = ctx.team_filter(rack_stmt, Rack)
        rack_res = await db.execute(rack_stmt)

        if not rack_res.scalar_one_or_none():
            raise AccessDeniedError("You do not have permission to delete this shelf")

        if db_shelf.machines:
            count = len(db_shelf.machines)
            raise ValidationError(
                f"Shelf '{db_shelf.name}' is not empty (contains {count} machines). "
                "Move or delete machines first."
            )
        try:
            shelf_name = db_shelf.name
            await db.delete(db_shelf)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Could not delete shelf '{shelf_name}'") from e
