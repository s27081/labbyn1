"""Dashboard dedidacted endpoints router."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestContext
from app.database import get_async_db
from app.db.schemas import DashboardResponse
from app.utils.dashboard_service import build_dashboard

router = APIRouter()


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    tags=["Dashboard"],
)
async def get_dashboard(
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Create dashboard view for user.

    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Dashboard view
    """
    return await build_dashboard(db, ctx)
