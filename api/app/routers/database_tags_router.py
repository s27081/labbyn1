"""Router for Tags Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestContext
from app.core.exceptions import (
    ObjectNotFoundError,
    ValidationError,
)
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
        raise ValidationError(f"Invalid entity type: {data.entity_type}")

    async with acquire_lock(f"tag_assign_{data.entity_type}:{data.entity_id}"):
        stmt = select(model).filter(model.id == data.entity_id)
        if data.entity_type.lower() != "documentation":
            stmt = ctx.team_filter(stmt, model)

        result = await db.execute(stmt)
        entity = result.scalar_one_or_none()

        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        tag_stmt = select(Tags).where(Tags.id.in_(data.tag_ids))
        tag_res = await db.execute(tag_stmt)
        tags_to_add = tag_res.scalars().all()

        if not tags_to_add:
            raise ObjectNotFoundError("Tags", name=f"IDs: {data.tag_ids}")

        await db.refresh(entity, ["tags"])
        entity_name = getattr(entity, "name", str(entity.id))
        new_tags_names = []

        changed = False
        for tag in tags_to_add:
            if tag not in entity.tags:
                entity.tags.append(tag)
                new_tags_names.append(tag.name)
                changed = True

        if changed:
            await db.commit()
            return {
                "message": f"Assigned tags [{', '.join(new_tags_names)}] "
                           f"to {data.entity_type} '{entity_name}'"
            }

        return {"message": f"Tags already assigned to '{entity_name}'"}


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
        raise ValidationError(f"Invalid entity type: {data.entity_type}")

    async with acquire_lock(f"tag_assign_{data.entity_type}:{data.entity_id}"):
        stmt = select(model).filter(model.id == data.entity_id)
        if data.entity_type.lower() != "documentation":
            stmt = ctx.team_filter(stmt, model)

        entity = (await db.execute(stmt)).scalar_one_or_none()

        if not entity:
            raise ObjectNotFoundError(data.entity_type.capitalize(), id=data.entity_id)

        if not data.tag_ids:
            raise ValidationError("No tag IDs provided for detachment")

        target_tag_id = data.tag_ids[0]
        tag = (
            await db.execute(select(Tags).filter(Tags.id == target_tag_id))
        ).scalar_one_or_none()

        if not tag:
            raise ObjectNotFoundError("Tag", id=target_tag_id)

        await db.refresh(entity, ["tags"])
        entity_name = getattr(entity, "name", str(entity.id))

        if tag in entity.tags:
            entity.tags.remove(tag)
            await db.commit()
            return {
                "message": f"Tag '{tag.name}' detached from "
                           f"{data.entity_type} '{entity_name}'"
            }

        return {"message": f"Tag '{tag.name}' was not assigned to '{entity_name}'"}


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

    try:
        obj = Tags(**tag_data.model_dump())
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj
    except Exception as e:
        await db.rollback()
        raise ValidationError(f"Failed to create tag '{tag_data.name}'") from e


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
        raise ObjectNotFoundError("Tag")

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
            raise ObjectNotFoundError("Tag")

        try:
            update_data = tag_data.model_dump(exclude_unset=True)
            for k, v in update_data.items():
                setattr(tag, k, v)

            await db.commit()
            await db.refresh(tag)
            return tag
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Failed to update tag '{tag.name}'") from e


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
            raise ObjectNotFoundError("Tag")

        try:
            tag_name = tag.name
            await db.delete(tag)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Could not delete tag '{tag_name}'") from e
