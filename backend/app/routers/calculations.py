from fastapi import APIRouter

from app.calculation_service import (
    assign_calculation_collection,
    create_calculation,
    delete_calculation,
    get_calculation,
    list_calculations,
    update_calculation,
)
from app.calculations.service import (
    calculation_parameter_options,
    execute_calculation,
    validate_calculation,
)
from app.schemas import (
    CalculationCollectionUpdate,
    CalculationCreate,
    CalculationExecuteRequest,
    CalculationParameterOptionsRequest,
    CalculationUpdate,
    CalculationValidateRequest,
)

router = APIRouter(prefix="/calculations", tags=["calculations"])


@router.get("")
async def calculation_list(collection_id: int | None = None):
    return await list_calculations(collection_id=collection_id)


@router.post("", status_code=201)
async def calculation_create(data: CalculationCreate):
    return await create_calculation(
        collection_id=data.collection_id,
        name=data.name,
        content=data.content,
    )


@router.post("/{calculation_id}/validate")
async def calculation_validate(
    calculation_id: int,
    data: CalculationValidateRequest,
):
    return await validate_calculation(calculation_id, content=data.content)


@router.post("/{calculation_id}/execute")
async def calculation_execute(
    calculation_id: int,
    data: CalculationExecuteRequest,
):
    return await execute_calculation(
        calculation_id,
        content=data.content,
        target_node_id=data.target_node_id,
        parameters=data.parameters,
    )


@router.post("/{calculation_id}/parameters/{parameter_id}/options")
async def calculation_parameter_option_list(
    calculation_id: int,
    parameter_id: str,
    data: CalculationParameterOptionsRequest,
):
    return await calculation_parameter_options(
        calculation_id,
        parameter_id,
        content=data.content,
        search=data.search,
    )


@router.get("/{calculation_id}")
async def calculation_get(calculation_id: int):
    return await get_calculation(calculation_id)


@router.put("/{calculation_id}")
async def calculation_update(calculation_id: int, data: CalculationUpdate):
    return await update_calculation(calculation_id, content=data.content)


@router.put("/{calculation_id}/collection")
async def calculation_collection_update(
    calculation_id: int,
    data: CalculationCollectionUpdate,
):
    return await assign_calculation_collection(
        calculation_id,
        collection_id=data.collection_id,
    )


@router.delete("/{calculation_id}")
async def calculation_delete(calculation_id: int):
    return await delete_calculation(calculation_id)
