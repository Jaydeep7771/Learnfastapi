"""Full async CRUD with pagination, filtering and PATCH semantics."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.dependencies import AdminUser, CurrentUser, PaginationDep, SessionDep
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate, Page
from app.services import items as svc

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create(payload: ItemCreate, session: SessionDep, user: CurrentUser) -> object:
    return await svc.create_item(session, payload, owner_id=user.id)


@router.get("", response_model=Page[ItemRead])
async def list_(
    session: SessionDep,
    user: CurrentUser,
    page: PaginationDep,
    q: Annotated[str | None, Query(max_length=120, description="name contains")] = None,
    min_price: Annotated[int | None, Query(ge=0)] = None,
    mine_only: bool = True,
) -> Page[ItemRead]:
    rows, total = await svc.list_items(
        session,
        limit=page.limit,
        offset=page.offset,
        owner_id=user.id if mine_only else None,
        q=q,
        min_price=min_price,
    )
    return Page[ItemRead](
        items=[ItemRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{item_id}", response_model=ItemRead)
async def read(item_id: int, session: SessionDep, user: CurrentUser) -> object:
    return await svc.get_item(session, item_id)


@router.patch("/{item_id}", response_model=ItemRead)
async def patch(
    item_id: int, payload: ItemUpdate, session: SessionDep, user: CurrentUser
) -> object:
    return await svc.update_item(session, item_id, payload)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(item_id: int, session: SessionDep, user: AdminUser) -> Response:
    """Admin-only, to show the RBAC guard composing with the session dependency."""
    await svc.delete_item(session, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
