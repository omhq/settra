from fastapi import APIRouter

from app.collection_service import (
    create_collection,
    delete_collection,
    get_collection,
    list_collections,
    update_collection,
)
from app.schemas import CollectionCreate, CollectionUpdate

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("")
async def collection_list():
    return await list_collections()


@router.post("", status_code=201)
async def collection_create(data: CollectionCreate):
    return await create_collection(
        name=data.name,
        description=data.description,
        agent_instructions=data.agent_instructions,
        pipe_ids=data.pipe_ids,
    )


@router.get("/{collection_id}")
async def collection_get(collection_id: int):
    return await get_collection(collection_id)


@router.put("/{collection_id}")
async def collection_update(collection_id: int, data: CollectionUpdate):
    return await update_collection(
        collection_id,
        name=data.name,
        description=data.description,
        agent_instructions=data.agent_instructions,
        pipe_ids=data.pipe_ids,
    )


@router.delete("/{collection_id}")
async def collection_delete(collection_id: int):
    return await delete_collection(collection_id)
