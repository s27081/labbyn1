"""Router for Tags Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestContext
from app.database import get_async_db
from app.db.models import Documentation, Machines, Rack, Rooms, Tags
from app.db.schemas import TagsAssignment, TagsCreate, TagsResponse, TagsUpdate
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["Tags"])

ENTITY_MAP = {
    "machine": Machines,
    "rack": Rack,
    "room": Rooms,
    "documentation": Documentation,
}


@router.get(
    "/tags",
    response_model=List[TagsResponse],
)
async def get_tags(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Get all tags.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of all tags.
    """
    ctx.require_user()
    stmt = select(Tags)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/tags/assign", status_code=status.HTTP_200_OK)
async def assign_tag(
    data: TagsAssignment,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Assign tag to object.

    Can be used for machine, rack, room and documentation objects

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of all tags.
    """
    ctx.require_user()

    model = ENTITY_MAP.get(data.entity_type.lower())
    if not model:
        raise HTTPException(status_code=400, detail="Invalid entity type")

    async with acquire_lock(f"tag_assign_{data.entity_type}:{data.entity_id}"):
        stmt = select(model).filter(model.id == data.entity_id)

        if data.entity_type.lower() == "documentation":
            result = await db.execute(stmt)
        else:
            stmt = ctx.team_filter(stmt, model)
            result = await db.execute(stmt)

        entity = result.scalar_one_or_none()

        if not entity:
            raise HTTPException(
                status_code=404, detail=f"{data.entity_type} not found or access denied"
            )

        tag_stmt = select(Tags).filter(Tags.id == data.tag_id)
        tag_res = await db.execute(tag_stmt)
        tag = tag_res.scalar_one_or_none()

        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        await db.run_sync(lambda _: entity.tags)

        if tag not in entity.tags:
            entity.tags.append(tag)
            await db.commit()

        return {"message": f"Tag {tag.name} assigned to {data.entity_type}"}


@router.post("/tags/detach", status_code=status.HTTP_200_OK)
async def detach_tag(
    data: TagsAssignment,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Detach tag from object.

    Can be used for machine, rack, room and documentation objects

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of all tags.
    """
    ctx.require_user()

    model = ENTITY_MAP.get(data.entity_type.lower())
    if not model:
        raise HTTPException(status_code=400, detail="Invalid entity type")

    async with acquire_lock(f"tag_assign_{data.entity_type}:{data.entity_id}"):
        stmt = select(model).filter(model.id == data.entity_id)
        result = await db.execute(stmt)
        entity = result.scalar_one_or_none()

        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        tag_stmt = select(Tags).filter(Tags.id == data.tag_id)
        tag_res = await db.execute(tag_stmt)
        tag = tag_res.scalar_one_or_none()

        if tag:
            await db.run_sync(lambda _: entity.tags)
            if tag in entity.tags:
                entity.tags.remove(tag)
                await db.commit()

        return {
            "message": f"Tag {tag.name if tag else 'Unknown'} "
                       f"detached from {data.entity_type}"
        }


@router.post(
    "/tags",
    response_model=TagsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tag(
    tag_data: TagsCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create new tag.

    :param data: Tag data
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: New tag item.
    """
    ctx.require_group_admin()
    obj = Tags(**tag_data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)

    return obj


@router.get(
    "/tags/{tag_id}",
    response_model=TagsResponse,
)
async def get_tag_by_id(
    tag_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Get specific tag by ID.

    :param tag_id: Tag ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Tag object.
    """
    ctx.require_user()
    stmt = select(Tags).filter(Tags.id == tag_id)
    result = await db.execute(stmt)
    tag = result.scalar_one_or_none()

    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
        )
    return tag


@router.patch(
    "/tags/{tag_id}",
    response_model=TagsResponse,
)
async def update_tag(
    tag_id: int,
    tag_data: TagsUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update tag data.

    :param tag_id: Tag ID
    :param tag_data: Tag data schema
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Updated tag.
    """
    ctx.require_group_admin()
    async with acquire_lock(f"tag_lock:{tag_id}"):
        stmt = select(Tags).filter(Tags.id == tag_id)
        result = await db.execute(stmt)
        tag = result.scalar_one_or_none()

        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
            )

        update_data = tag_data.model_dump(exclude_unset=True)
        for k, v in update_data.items():
            setattr(tag, k, v)

        await db.commit()
        await db.refresh(tag)
        return tag


@router.delete(
    "/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete tag.

    :param tag_id: Tag ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: None.
    """
    ctx.require_group_admin()
    async with acquire_lock(f"tag_lock:{tag_id}"):
        stmt = select(Tags).filter(Tags.id == tag_id)
        result = await db.execute(stmt)
        tag = result.scalar_one_or_none()

        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
            )

        await db.delete(tag)
        await db.commit()
