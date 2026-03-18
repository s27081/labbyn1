"""Router for Rental Database API CRUD."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import RequestContext
from app.core.exceptions import (
    InsufficientAmountError,
    ObjectNotFoundError,
    ValidationError,
)
from app.database import get_async_db
from app.db.models import Inventory, Rentals
from app.db.schemas import RentalReturn, RentalsCreate, RentalsResponse
from app.utils.redis_service import acquire_lock

router = APIRouter(prefix="/db", tags=["Inventory-Rentals"])


@router.post(
    "/rentals",
    response_model=RentalsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rental(
    rent_data: RentalsCreate,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create new item rent.

    :param rent_data: Rent data
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: New Rental object.
    """
    ctx.require_user()

    async with acquire_lock(f"inventory_lock:{rent_data.item_id}"):
        stmt = (
            select(Inventory)
            .filter(Inventory.id == rent_data.item_id)
            .with_for_update(nowait=True)
        )
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()

        if not item:
            raise ObjectNotFoundError("Item for this rental")

        sum_stmt = select(func.coalesce(func.sum(Rentals.quantity), 0)).filter(
            Rentals.item_id == item.id,
            Rentals.start_date <= rent_data.end_date,
            Rentals.end_date >= rent_data.start_date,
        )
        sum_result = await db.execute(sum_stmt)
        active_rentals_sum = sum_result.scalar()

        in_stock = item.quantity - active_rentals_sum

        if rent_data.quantity > in_stock:
            raise InsufficientAmountError(
                requested=rent_data.quantity, available=in_stock
            )

        try:
            rental = Rentals(
                item_id=rent_data.item_id,
                quantity=rent_data.quantity,
                start_date=rent_data.start_date,
                end_date=rent_data.end_date,
                user_id=ctx.current_user.id,
            )

            db.add(rental)

            if in_stock - rent_data.quantity == 0:
                item.rental_status = True

            await db.commit()
            await db.refresh(rental)
            return rental
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Failed to create rental for '{item.name}'") from e


@router.post("/rentals/{rental_id}/return")
async def return_rental(
    rental_id: int,
    return_data: Optional[RentalReturn] = None,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """End item rental.

    :param rental_id: Rental ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Success message.
    """
    ctx.require_user()

    check_stmt = (
        select(Rentals)
        .join(Inventory, Rentals.item_id == Inventory.id)
        .filter(Rentals.id == rental_id)
        .options(joinedload(Rentals.item))
    )
    rental = (
        await db.execute(ctx.team_filter(check_stmt, Inventory))
    ).scalar_one_or_none()

    if not rental:
        raise ObjectNotFoundError("Rental for this item")

    item = rental.item
    async with acquire_lock(f"inventory_lock:{item.id}"):
        await db.refresh(rental)
        await db.refresh(item)

        qty_to_return = (
            return_data.quantity
            if return_data and return_data.quantity
            else rental.quantity
        )

        if qty_to_return > rental.quantity:
            raise InsufficientAmountError(
                requested=qty_to_return, available=rental.quantity
            )

        try:
            if qty_to_return == rental.quantity:
                rental.end_date = date.today()
                msg = f"Fully returned '{item.name}'"
            else:
                rental.quantity -= qty_to_return
                msg = (f"Partially returned {qty_to_return}x "
                       f"'{item.name}'. Remaining: {rental.quantity}")

            item.rental_status = False
            await db.commit()
            return {"message": msg}
        except Exception as e:
            await db.rollback()
            raise ValidationError(f"Return failed for '{item.name}'") from e


@router.get("/rentals", response_model=List[RentalsResponse])
async def get_rentals(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Get all rentals.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: List of all rentals.
    """
    ctx.require_user()
    stmt = select(Rentals).join(Inventory, Rentals.item_id == Inventory.id)
    stmt = ctx.team_filter(stmt, Inventory)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/rentals/{rental_id}", response_model=RentalsResponse)
async def get_rental_by_id(
    rental_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Get specific rental by ID.

    :param rental_id: Rental ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Rental object.
    """
    ctx.require_user()
    stmt = (
        select(Rentals)
        .join(Inventory, Rentals.item_id == Inventory.id)
        .filter(Rentals.id == rental_id)
    )
    stmt = ctx.team_filter(stmt, Inventory)
    result = await db.execute(stmt)
    rental = result.scalar_one_or_none()

    if not rental:
        raise ObjectNotFoundError("Rental for this item")
    return rental


@router.delete("/rentals/{rental_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rental(
    rental_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete rental history.

    :param rental_id: Rental ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    ctx.require_user()
    stmt = (
        select(Rentals)
        .join(Inventory, Rentals.item_id == Inventory.id)
        .filter(Rentals.id == rental_id)
        .options(joinedload(Rentals.item))
    )
    stmt = ctx.team_filter(stmt, Inventory)
    result = await db.execute(stmt)
    rental = result.scalar_one_or_none()

    if not rental:
        raise ObjectNotFoundError("Rental for this item")

    async with acquire_lock(f"inventory_lock:{rental.item_id}"):
        try:
            item_stmt = select(Inventory).filter(Inventory.id == rental.item_id)
            item_res = await db.execute(item_stmt)
            item = item_res.scalar_one_or_none()

            if item and item.rental_id == rental.id:
                item.rental_status = False
                item.rental_id = None

            await db.delete(rental)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            raise ValidationError(f"Could not delete rental for '{item.name}'") from e
