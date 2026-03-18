"""Router for Room Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.auth.dependencies import RequestContext
from app.core.exceptions import (
    ObjectNotFoundError,
    ValidationError,
)
from app.database import get_async_db
from app.db.models import Rack, Rooms, Shelf, Tags
from app.db.schemas import (
    RoomDashboardResponse,
    RoomDetailsResponse,
    RoomsCreate,
    RoomsResponse,
    RoomsUpdate,
)
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["Rooms"])


@router.post(
    "/rooms",
    response_model=RoomsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room(
    room_data: RoomsCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create new room.

    :param room_data: Room data
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Room object.
    """
    ctx.require_group_admin()

    target_team_id = room_data.team_id or (
        ctx.team_ids[0] if len(ctx.team_ids) == 1 else None
    )
    if not target_team_id:
        raise ValidationError("Target team ID is required to create a room")

    await ctx.validate_team_access(target_team_id)

    try:
        obj = Rooms(
            name=room_data.name, room_type=room_data.room_type, team_id=target_team_id
        )

        if room_data.tag_ids:
            tag_res = await db.execute(
                select(Tags).where(Tags.id.in_(room_data.tag_ids))
            )
            obj.tags = list(tag_res.scalars().all())

        db.add(obj)
        await db.commit()

        stmt = (
            select(Rooms)
            .where(Rooms.id == obj.id)
            .options(selectinload(Rooms.tags), selectinload(Rooms.team))
        )
        return (await db.execute(stmt)).scalar_one()
    except Exception as e:
        await db.rollback()
        raise ValidationError(f"Failed to create room '{room_data.name}'") from e


@router.get("/rooms", response_model=List[RoomsResponse])
async def get_rooms(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch all rooms.

    :param ctx: Request context for user and team info
    :param db: Active database session
    :return: List of all rooms.
    """
    ctx.require_user()
    stmt = select(Rooms).options(joinedload(Rooms.tags))
    stmt = ctx.team_filter(stmt, Rooms)

    result = await db.execute(stmt)
    return result.unique().scalars().all()


@router.get("/rooms/dashboard", response_model=List[RoomDashboardResponse])
async def get_rooms_dashboard(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch all rooms with rack count and map link for dashboard.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Room object.
    """
    ctx.require_user()
    stmt = select(Rooms).options(
        joinedload(Rooms.racks), joinedload(Rooms.layouts), joinedload(Rooms.team)
    )
    stmt = ctx.team_filter(stmt, Rooms)

    result = await db.execute(stmt)
    rooms = result.unique().scalars().all()

    results = []
    for r in rooms:
        results.append(
            {
                "id": r.id,
                "name": r.name,
                "team_name": r.team.name if r.team else "N/A",
                "rack_count": len(r.racks),
                "map_link": f"/map/room/{r.id}",
            }
        )
    return results


@router.get("/rooms/{room_id}/details", response_model=RoomDetailsResponse)
async def get_room_details(
    room_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch specific room by ID with nested racks, shelves and machines.

    For dashboard details

    :param room_id: Room ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Room object.
    """
    ctx.require_user()
    stmt = (
        select(Rooms)
        .options(
            joinedload(Rooms.tags),
            joinedload(Rooms.layouts),
            joinedload(Rooms.racks).joinedload(Rack.tags),
            joinedload(Rooms.racks).joinedload(Rack.shelves).joinedload(Shelf.machines),
        )
        .filter(Rooms.id == room_id)
    )

    stmt = ctx.team_filter(stmt, Rooms)
    result = await db.execute(stmt)
    room = result.unique().scalar_one_or_none()

    if not room:
        raise HTTPException(status_code=404, detail="Lab not found")

    racks_list = []
    for rack in room.racks:
        machines_in_rack = []
        for shelf in rack.shelves:
            for m in shelf.machines:
                machines_in_rack.append(
                    {
                        "id": str(m.id),
                        "hostname": m.name,
                        "ip_address": m.ip_address,
                        "mac_address": m.mac_address,
                    }
                )

        racks_list.append(
            {
                "id": rack.id,
                "name": rack.name,
                "tags": [
                    {
                        "name": getattr(t, "name", "Unnamed"),
                        "color": getattr(t, "color", "red"),
                    }
                    for t in (rack.tags or [])
                ],
                "machines": machines_in_rack,
            }
        )

    return {
        "id": room.id,
        "name": room.name,
        "tags": [t.name for t in room.tags],
        "map_link": f"/map/room/{room.id}",
        "racks": racks_list,
    }


@router.get("/rooms/{room_id}", response_model=RoomsResponse)
async def get_room_by_id(
    room_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Fetch specific room by ID.

    :param room_id: Room ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Room object.
    """
    ctx.require_user()
    stmt = select(Rooms).filter(Rooms.id == room_id)
    stmt = ctx.team_filter(stmt, Rooms)

    result = await db.execute(stmt)
    room = result.scalar_one_or_none()

    if not room:
        raise ObjectNotFoundError("Room")
    return room


@router.patch("/rooms/{room_id}", response_model=RoomsResponse)
async def update_room(
    room_id: int,
    room_data: RoomsUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update room.

    :param room_id: Room ID
    :param room_data: Room data schema
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Updated Room.
    """
    ctx.require_group_admin()

    async with acquire_lock(f"room_lock:{room_id}"):
        stmt = select(Rooms).filter(Rooms.id == room_id)
        stmt = ctx.team_filter(stmt, Rooms)

        result = await db.execute(stmt)
        room = result.scalar_one_or_none()

        if not room:
            raise ObjectNotFoundError("Room", id=room_id)

        update_data = room_data.model_dump(exclude_unset=True)
        try:
            if "tag_ids" in update_data:
                tag_ids = update_data.pop("tag_ids")
                if tag_ids is not None:
                    tag_stmt = select(Tags).where(Tags.id.in_(tag_ids))
                    tag_res = await db.execute(tag_stmt)
                    room.tags = tag_res.scalars().all()

            if "team_id" in update_data:
                await ctx.validate_team_access(update_data["team_id"])

            for k, v in update_data.items():
                setattr(room, k, v)

            await db.commit()
            await db.refresh(room, attribute_names=["team", "racks"])
            return room
        except Exception as e:
            raise ValidationError(f"Failed to update room '{room.name}'") from e


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete Room.

    :param room_id: Room ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    ctx.require_group_admin()

    async with acquire_lock(f"room_lock:{room_id}"):
        stmt = select(Rooms).filter(Rooms.id == room_id)
        stmt = ctx.team_filter(stmt, Rooms)

        result = await db.execute(stmt)
        room = result.scalar_one_or_none()

        if not room:
            raise ObjectNotFoundError("Room")

        try:
            await db.delete(room)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Could not delete room '{room.name}'") from e
