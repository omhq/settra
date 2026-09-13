from fastapi import APIRouter

from app.calculation_service import (
    create_calculation,
    delete_calculation,
    get_calculation,
    list_calculations,
    update_calculation,
)
from app.schemas import CalculationCreate, CalculationUpdate

router = APIRouter(prefix="/calculations", tags=["calculations"])


@router.get("")
async def calculation_list():
    return await list_calculations()


@router.post("", status_code=201)
async def calculation_create(data: CalculationCreate):
    return await create_calculation(name=data.name, content=data.content)


@router.get("/{calculation_id}")
async def calculation_get(calculation_id: int):
    return await get_calculation(calculation_id)


@router.put("/{calculation_id}")
async def calculation_update(calculation_id: int, data: CalculationUpdate):
    return await update_calculation(calculation_id, content=data.content)


@router.delete("/{calculation_id}")
async def calculation_delete(calculation_id: int):
    return await delete_calculation(calculation_id)
