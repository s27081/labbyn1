"""Router for Documentation Database API CRUD."""

from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import RequestContext
from app.core.exceptions import ObjectNotFoundError, ValidationError, ConflictError
from app.database import get_async_db
from app.db.models import Documentation, Tags
from app.db.schemas import (
    DocumentationCreate,
    DocumentationResponse,
    DocumentationUpdate,
)
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["Documentation"])


@router.get(
    "/documentation",
    response_model=List[DocumentationResponse],
)
async def get_documentation(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Get all documents from documentation.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of all documents.
    """
    ctx.require_user()
    stmt = select(Documentation).options(joinedload(Documentation.tags))
    result = await db.execute(stmt)
    return result.unique().scalars().all()


@router.post(
    "/documentation",
    response_model=DocumentationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_documentation(
    documentation_data: DocumentationCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create new document.

    :param data: Documentation data
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: New document item.
    """
    ctx.require_user()
    current_author = ctx.current_user.login
    tag_ids = documentation_data.tag_ids or []

    try:
        obj = Documentation(
            **documentation_data.model_dump(exclude={"tag_ids"}), author=current_author
        )

        if tag_ids:
            tag_stmt = select(Tags).where(Tags.id.in_(tag_ids))
            tag_result = await db.execute(tag_stmt)
            obj.tags = list(tag_result.scalars().all())

        db.add(obj)
        await db.flush()
        await db.commit()

        stmt = (
            select(Documentation)
            .options(joinedload(Documentation.tags))
            .where(Documentation.id == obj.id)
        )
        result = await db.execute(stmt)
        return result.unique().scalar_one()

    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            message=f"Document with title '{documentation_data.title}' already exists."
        )
    except Exception as e:
        await db.rollback()
        if isinstance(e, ConflictError):
            raise e
        raise ValidationError(
            f"Could not create document: '{documentation_data.title}'"
        ) from e


@router.get(
    "/documentation/{documentation_id}",
    response_model=DocumentationResponse,
)
async def get_documentation_by_id(
    documentation_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Get specific document from documentation by ID.

    :param documentation_id: Document ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Document object.
    """
    ctx.require_user()
    stmt = (
        select(Documentation)
        .filter(Documentation.id == documentation_id)
        .options(joinedload(Documentation.tags))
    )
    result = await db.execute(stmt)
    document = result.unique().scalar_one_or_none()

    if not document:
        raise ObjectNotFoundError("Document")
    return document


@router.patch(
    "/documentation/{documentation_id}",
    response_model=DocumentationResponse,
)
async def update_documentation(
    documentation_id: int,
    documentation_data: DocumentationUpdate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Update document data.

    :param documentation_id: Document ID
    :param documentation_data: Documentation data schema
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Updated Document.
    """
    ctx.require_user()
    async with acquire_lock(f"documentation_lock:{documentation_id}"):
        stmt = (
            select(Documentation)
            .filter(Documentation.id == documentation_id)
            .options(joinedload(Documentation.tags))
        )
        result = await db.execute(stmt)
        document = result.unique().scalar_one_or_none()

        if not document:
            raise ObjectNotFoundError("Document")

        old_title = document.title

        try:
            update_data = documentation_data.model_dump(exclude_unset=True)

            if "tag_ids" in update_data:
                tag_ids = update_data.pop("tag_ids")
                tag_stmt = select(Tags).where(Tags.id.in_(tag_ids))
                tag_result = await db.execute(tag_stmt)
                document.tags = list(tag_result.scalars().all())

            for k, v in update_data.items():
                if hasattr(document, k):
                    setattr(document, k, v)

            await db.flush()
            await db.commit()

            final_stmt = (
                select(Documentation)
                .options(joinedload(Documentation.tags))
                .where(Documentation.id == documentation_id)
            )
            refresh_res = await db.execute(final_stmt)
            return refresh_res.unique().scalar_one()

        except IntegrityError:
            await db.rollback()
            new_title = documentation_data.title or old_title
            raise ConflictError(
                message=f"Update failed. Document title '{new_title}' is already taken."
            )
        except Exception as e:
            await db.rollback()
            if isinstance(e, ConflictError):
                raise e
            raise ValidationError(f"Failed to update document: '{old_title}'") from e


@router.delete(
    "/documentation/{documentation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    documentation_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete document.

    :param documentation_id: Document ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: 204 No Content as success
    """
    ctx.require_user()
    async with acquire_lock(f"documentation_lock:{documentation_id}"):
        stmt = select(Documentation).filter(Documentation.id == documentation_id)
        result = await db.execute(stmt)
        document = result.scalar_one_or_none()

        if not document:
            raise ObjectNotFoundError("Document")
        try:
            await db.delete(document)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Could not delete document: {document.title}") from e
