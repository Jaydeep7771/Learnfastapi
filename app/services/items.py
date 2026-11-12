"""Item persistence. Routers stay thin: validate -> call service -> serialize."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.problems import AppError
from app.models import Item
from app.schemas.item import ItemCreate, ItemUpdate


def _filtered(owner_id: int | None, q: str | None, min_price: int | None) -> Select[tuple[Item]]:
    stmt = select(Item)
    if owner_id is not None:
        stmt = stmt.where(Item.owner_id == owner_id)
    if q:
        stmt = stmt.where(Item.name.ilike(f"%{q}%"))
    if min_price is not None:
        stmt = stmt.where(Item.price_cents >= min_price)
    return stmt


async def create_item(session: AsyncSession, payload: ItemCreate, owner_id: int) -> Item:
    item = Item(**payload.model_dump(), owner_id=owner_id)
    session.add(item)
    await session.flush()  # assigns PK without ending the transaction
    await session.refresh(item)
    return item


async def list_items(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    owner_id: int | None = None,
    q: str | None = None,
    min_price: int | None = None,
) -> tuple[list[Item], int]:
    stmt = _filtered(owner_id, q, min_price)
    total = await session.scalar(
        select(func.count()).select_from(stmt.subquery())
    )
    rows = await session.scalars(
        stmt.order_by(Item.id.desc()).limit(limit).offset(offset)
    )
    return list(rows), int(total or 0)


async def get_item(session: AsyncSession, item_id: int) -> Item:
    item = await session.get(Item, item_id)
    if item is None:
        raise AppError(
            f"Item {item_id} does not exist",
            status_code=404,
            title="Item not found",
            type_="https://example.com/problems/item-not-found",
        )
    return item


async def update_item(session: AsyncSession, item_id: int, payload: ItemUpdate) -> Item:
    item = await get_item(session, item_id)
    # exclude_unset => a PATCH body of {"price_cents": 0} touches ONLY the price.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await session.flush()
    await session.refresh(item)
    return item


async def delete_item(session: AsyncSession, item_id: int) -> None:
    item = await get_item(session, item_id)
    await session.delete(item)
    await session.flush()
