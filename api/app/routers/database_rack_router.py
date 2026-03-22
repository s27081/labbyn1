"""Router for Rack Database API CRUD."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.auth.dependencies import RequestContext
from app.core.exceptions import (
    AccessDeniedError,
    ObjectNotFoundError,
    ValidationError,
    AppBaseException,
    ConflictError,
)
from app.database import get_async_db
from app.db.models import Machines, Rack, Rooms, Shelf, Tags
from app.db.schemas import (
    RackCreate,
    RackResponse,
    RackUpdate,
    RackWithOrderedMachinesResponse,
)
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/db", tags=["Racks"])


def format_rack_output(rack: Rack):
    """Format rack output to display machine list ordered.

    :param rack: Rack object
    :return: Formatted rack dict
    """
    sorted_shelves = sorted(rack.shelves, key=lambda s: s.order or 0)
    ordered_machines = []

    for shelf in sorted_shelves:
        ordered_machines.append(shelf.machines)

    team_name = rack.team.name if rack.team else "N/A"
    rack_link = f"/racks/{rack.id}"

    return {
        "id": rack.id,
        "name": rack.name,
        "team_id": rack.team_id,
        "layout_id": rack.layout_id,
        "team_name": team_name,
        "room_id": rack.room_id,
        "tags": rack.tags or [],
        "machines": ordered_machines,
        "link": rack_link,
    }


@router.get("/racks", response_model=List[RackResponse])
async def get_racks(
    room_ids: Optional[List[int]] = Query(None),
    team_ids: Optional[List[int]] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Returns ALL racks with their shelves and machines nested inside.

    :param room_ids: Optional list of room IDs to filter by
    :param team_ids: Optional list of team IDs to filter by
    :param ctx: Request context for database and user info
    :return: List of racks with nested structures.
    """
    ctx.require_user()
    stmt = select(Rack)
    stmt = ctx.team_filter(stmt, Rack)

    if room_ids:
        stmt = stmt.where(Rack.room_id.in_(room_ids))
    if team_ids:
        stmt = stmt.where(Rack.team_id.in_(team_ids))

    stmt = stmt.options(
        joinedload(Rack.room),
        joinedload(Rack.team),
        joinedload(Rack.tags),
        joinedload(Rack.shelves).joinedload(Shelf.machines),
    )

    result = await db.execute(stmt)
    racks = result.unique().scalars().all()

    for r in racks:
        r.room_name = r.room.name if r.room else "N/A"
        r.team_name = r.team.name if r.team else "N/A"

    return racks


@router.get("/racks-list")
async def get_racks_list(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Returns a simple list of rack names and IDs for dropdowns.

    :param db: Active database session
    :param ctx: Request context
    :return: List of dictionaries with id and name.
    """
    ctx.require_user()
    stmt = select(Rack.id, Rack.name)
    stmt = ctx.team_filter(stmt, Rack)

    result = await db.execute(stmt)
    racks = result.all()

    return [{"id": r.id, "name": r.name} for r in racks]


@router.get("/racks/{rack_id}", response_model=RackResponse)
async def get_rack_detail(
    rack_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch specific rack by ID with its nested shelves and machines.

    :param rack_id: ID of the rack
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Detailed rack object.
    """
    ctx.require_user()
    stmt = select(Rack).where(Rack.id == rack_id)
    stmt = ctx.team_filter(stmt, Rack).options(
        joinedload(Rack.room),
        joinedload(Rack.team),
        joinedload(Rack.shelves).joinedload(Shelf.machines),
    )

    result = await db.execute(stmt)
    rack = result.unique().scalar_one_or_none()

    if not rack:
        raise ObjectNotFoundError("Rack")

    rack.room_name = rack.room.name if rack.room else "N/A"
    rack.team_name = rack.team.name if rack.team else "N/A"

    return rack


@router.post(
    "/racks",
    response_model=RackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rack(
    rack: RackCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create a new rack with team and room validation.

    :param rack: Rack creation data
    :param db: Active database session
    :param ctx: Request context for user authorization
    :return: Created rack object with names.
    """
    ctx.require_user()

    target_team_id = rack.team_id or (
        ctx.team_ids[0] if len(ctx.team_ids) == 1 else None
    )
    if not target_team_id:
        raise ValidationError("Target team ID is required")

    await ctx.validate_team_access(target_team_id)

    room = (
        await db.execute(select(Rooms).where(Rooms.id == rack.room_id))
    ).scalar_one_or_none()

    if not room:
        raise ObjectNotFoundError("Room")

    if room.team_id != target_team_id and not ctx.is_admin:
        raise AccessDeniedError(f"Room '{room.name}' belongs to another team")

    try:
        db_rack = Rack(
            name=rack.name,
            room_id=rack.room_id,
            layout_id=rack.layout_id,
            team_id=target_team_id,
        )

        if rack.tag_ids:
            tag_res = await db.execute(select(Tags).where(Tags.id.in_(rack.tag_ids)))
            db_rack.tags = list(tag_res.scalars().all())

        db.add(db_rack)
        await db.commit()

    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            message=f"Rack with name '{rack.name}' already exists in this room/team."
        )
    except Exception as e:
        await db.rollback()
        if isinstance(e, AppBaseException):
            raise e
        raise e

    stmt = (
        select(Rack)
        .where(Rack.id == db_rack.id)
        .options(
            selectinload(Rack.room),
            selectinload(Rack.team),
            selectinload(Rack.tags),
            selectinload(Rack.shelves),
        )
    )
    result = await db.execute(stmt)
    db_rack = result.unique().scalar_one()

    db_rack.room_name = db_rack.room.name if db_rack.room else "N/A"
    db_rack.team_name = db_rack.team.name if db_rack.team else "N/A"

    return db_rack


@router.patch("/racks/{rack_id}", response_model=RackResponse)
async def update_rack(
    rack_id: int,
    rack_data: RackUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update an existing rack including team or room changes.

    :param rack_id: ID of the rack to update
    :param rack_data: Data fields to update
    :param db: Active database session
    :param ctx: Request context for permissions
    :return: Updated rack object.
    """
    ctx.require_user()

    stmt = select(Rack).where(Rack.id == rack_id)
    stmt = ctx.team_filter(stmt, Rack)
    result = await db.execute(stmt)
    db_rack = result.scalar_one_or_none()

    if not db_rack:
        raise ObjectNotFoundError("Rack")

    update_dict = rack_data.model_dump(exclude_unset=True)

    # TO DO: Handle ordering of machines
    update_dict.pop("machines", None)
    try:
        if "tag_ids" in update_dict:
            tag_ids = update_dict.pop("tag_ids")
            if tag_ids is not None:
                tag_stmt = select(Tags).where(Tags.id.in_(tag_ids))
                tag_res = await db.execute(tag_stmt)
                db_rack.tags = tag_res.scalars().all()

        if "team_id" in update_dict:
            await ctx.validate_team_access(update_dict["team_id"])

        if "room_id" in update_dict:
            new_room_id = update_dict["room_id"]
            room_stmt = select(Rooms).where(Rooms.id == new_room_id)
            room_res = await db.execute(room_stmt)
            room = room_res.scalar_one_or_none()
            if not room:
                raise ObjectNotFoundError("New room")

            if not ctx.is_admin and room.team_id not in ctx.team_ids:
                raise AccessDeniedError(f"Room '{room.name}' is owned by another team")

        for key, value in update_dict.items():
            setattr(db_rack, key, value)

        final_stmt = (
            select(Rack)
            .where(Rack.id == rack_id)
            .options(
                selectinload(Rack.room),
                selectinload(Rack.team),
                selectinload(Rack.tags),
                selectinload(Rack.shelves).selectinload(Shelf.machines),
            )
        )
        result = await db.execute(final_stmt)
        db_rack = result.unique().scalar_one()

        db_rack.room_name = db_rack.room.name if db_rack.room else "N/A"
        db_rack.team_name = db_rack.team.name if db_rack.team else "N/A"

        return db_rack
    except Exception as e:
        await db.rollback()
        if isinstance(e, (ObjectNotFoundError, AccessDeniedError)):
            raise e
        raise ValidationError(f"Failed to update rack '{db_rack.name}'") from e


@router.delete("/racks/{rack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rack(
    rack_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete a specific rack from the database.

    :param rack_id: ID of the rack to delete
    :param db: Active database session
    :param ctx: Request context for team-based access control
    :return: No content response.
    """
    ctx.require_user()

    stmt = select(Rack).where(Rack.id == rack_id).options(joinedload(Rack.shelves))
    stmt = ctx.team_filter(stmt, Rack)
    result = await db.execute(stmt)
    db_rack = result.unique().scalar_one_or_none()

    if not db_rack:
        raise ObjectNotFoundError("Rack")
    try:
        virtual_room = (
            await db.execute(
                select(Rooms).where(
                    Rooms.team_id == db_rack.team_id, Rooms.room_type == "virtual"
                )
            )
        ).scalar_one_or_none()

        if not virtual_room:
            team_name = db_rack.team.name if db_rack.team else "N/A"
            raise ValidationError(f"Virtual lab not found for team '{team_name}'")

        shelf_ids = [shelf.id for shelf in db_rack.shelves]

        if shelf_ids:
            m_stmt = select(Machines).where(Machines.shelf_id.in_(shelf_ids))
            m_res = await db.execute(m_stmt)
            machines_to_move = m_res.scalars().all()

            for machine in machines_to_move:
                machine.shelf_id = None
                machine.localization_id = virtual_room.id

        await db.delete(db_rack)
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        await db.rollback()
        if isinstance(e, ValidationError):
            raise e
        raise ValidationError(f"Could not delete rack '{db_rack.name}'") from e


@router.get(
    "/racks/rack_info/{rack_id}",
    response_model=RackWithOrderedMachinesResponse,
)
async def get_rack_info_by_id(
    rack_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch detailed information about a specific rack by ID.

    Includes ordered machine list.

    :param rack_id: Rack ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Rack object.
    """
    ctx.require_user()
    stmt = (
        select(Rack)
        .where(Rack.id == rack_id)
        .options(
            joinedload(Rack.team),
            joinedload(Rack.tags),
            joinedload(Rack.shelves).joinedload(Shelf.machines),
        )
    )

    result = await db.execute(stmt)
    rack = result.unique().scalar_one_or_none()

    if not rack:
        raise ObjectNotFoundError("Rack")

    return format_rack_output(rack)
