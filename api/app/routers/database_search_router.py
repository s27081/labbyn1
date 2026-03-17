"""Router for global search across multiple database tables."""

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestContext
from app.database import get_async_db
from app.db.models import Documentation, Inventory, Machines, Rack, Rooms, Teams, User
from app.db.schemas import GroupedSearchResponse

router = APIRouter(tags=["Search"])


@router.get("/db/search", response_model=GroupedSearchResponse)
async def get_search_data(
    ctx: RequestContext = Depends(RequestContext.create),
    db: AsyncSession = Depends(get_async_db),
):
    """Global search endpoint that aggregates data from multiple tables.

    :param ctx: Request context containing user and team information
    :param db: Current database session
    :return: List of search results with type, label, sublabel, and target URL
    """
    users_stmt = select(User)
    teams_stmt = select(Teams)
    docs_stmt = select(Documentation)

    machines_stmt = ctx.team_filter(select(Machines), Machines)
    racks_stmt = ctx.team_filter(select(Rack), Rack)
    items_stmt = ctx.team_filter(select(Inventory), Inventory)
    rooms_stmt = ctx.team_filter(select(Rooms), Rooms)

    (users_res, teams_res, docs_res, machines_res, racks_res, items_res, rooms_res) = (
        await asyncio.gather(
            db.execute(users_stmt),
            db.execute(teams_stmt),
            db.execute(docs_stmt),
            db.execute(machines_stmt),
            db.execute(racks_stmt),
            db.execute(items_stmt),
            db.execute(rooms_stmt),
        )
    )

    users = users_res.scalars().all()
    teams = teams_res.scalars().all()
    docs = docs_res.scalars().all()
    machines = machines_res.scalars().all()
    racks = racks_res.scalars().all()
    items = items_res.scalars().all()
    rooms = rooms_res.scalars().all()

    return {
        "users": [
            {
                "id": u.id,
                "label": f"{u.name} {u.surname}",
                "sublabel": u.email,
                "target_url": f"/users/{u.id}",
            }
            for u in users
        ],
        "teams": [
            {"id": t.id, "label": t.name, "target_url": f"/teams/{t.id}"} for t in teams
        ],
        "documentation": [
            {
                "id": d.id,
                "label": d.title,
                "sublabel": f"Autor: {d.author}",
                "target_url": f"/documentation/{d.id}",
            }
            for d in docs
        ],
        "machines": [
            {
                "id": m.id,
                "label": m.name,
                "sublabel": f"IP: {m.ip_address or '-'} | SN: {m.serial_number or '-'}",
                "target_url": f"/machines/{m.id}",
            }
            for m in machines
        ],
        "racks": [
            {"id": r.id, "label": r.name, "target_url": f"/racks/{r.id}"} for r in racks
        ],
        "inventory": [
            {"id": i.id, "label": i.name, "target_url": f"/inventory/{i.id}"}
            for i in items
        ],
        "rooms": [
            {"id": rm.id, "label": rm.name, "target_url": f"/rooms/{rm.id}"}
            for rm in rooms
        ],
    }
