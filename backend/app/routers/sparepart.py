"""备品备件台账接口：库存结存、出库登记、调拨流转、拒收退回与待补货清单。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BalanceAdjustPayload,
    IssueCreatePayload,
    OperatorPayload,
    PageResult,
    TransferCreatePayload,
)
from app.services.sparepart import SparepartService

router = APIRouter(prefix="/api/sparepart", tags=["备品备件"])

service = SparepartService()

STATUSES = ["已申请", "已批", "在途", "已入库", "已退回"]


def _paginate(rows: list[dict], page: int, size: int) -> PageResult[dict]:
    start = max(page - 1, 0) * size
    return PageResult(items=rows[start:start + size], total=len(rows), page=page, size=size)


@router.get("/meta")
def meta() -> dict[str, object]:
    """页面引导数据：仓库（含保管员名单）与备件型号，一次取齐。"""
    return {"warehouses": service.list_warehouses(), "parts": service.list_parts()}


@router.get("/balances", response_model=PageResult[dict])
def list_balances(
    warehouse: str | None = Query(default=None, description="按仓库编号过滤"),
    keyword: str | None = Query(default=None, description="按备件型号或名称检索"),
    page: int = 1,
    size: int = 200,
) -> PageResult[dict]:
    """库存台账：每个仓库按备件型号登记的结存与安全库存。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    return _paginate(service.list_balances(warehouse=warehouse, keyword=keyword), page, size)


@router.get("/replenishment")
def list_replenishment() -> dict[str, object]:
    """待补货清单：结存低于安全库存的条目；与库存台账读的是同一份结存。"""
    items = service.list_replenishment()
    return {"total": len(items), "items": items}


@router.get("/ledger", response_model=PageResult[dict])
def list_ledger(
    warehouse: str | None = Query(default=None, description="按仓库编号过滤"),
    kind: str | None = Query(default=None, description="出库、调拨出库、调拨入库、退回入库、退回冲减、直接调整"),
    page: int = 1,
    size: int = 100,
) -> PageResult[dict]:
    """台账流水：出库与调拨分开记，调拨双边过账共用同一个流水号。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    return _paginate(service.list_ledger(warehouse=warehouse, kind=kind), page, size)


@router.get("/issues", response_model=PageResult[dict])
def list_issues(page: int = 1, size: int = 100) -> PageResult[dict]:
    """出库单列表：领用出库，与调拨分开记账。"""
    return _paginate(service.list_issues(), page, size)


@router.post("/issues", response_model=ActionResult)
def create_issue(payload: IssueCreatePayload) -> ActionResult:
    """登记出库单：只有本仓保管员能出库，结存不足会被拦下。"""
    entry, message = service.create_issue(payload.model_dump(), operator=payload.operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/transfers", response_model=PageResult[dict])
def list_transfers(
    status: str | None = Query(default=None, description="已申请、已批、在途、已入库、已退回"),
    page: int = 1,
    size: int = 100,
) -> PageResult[dict]:
    """调拨单列表：按状态过滤，看单据推到哪一步。"""
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态「{status}」不在允许的状态序列里")
    return _paginate(service.list_transfers(status=status), page, size)


@router.post("/transfers", response_model=ActionResult)
def create_transfer(payload: TransferCreatePayload) -> ActionResult:
    """申请调拨单：自带单号时重复提交按原单返回，不会开出第二张。"""
    entry, message = service.create_transfer(payload.model_dump())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/transfers/{transfer_id}", response_model=dict)
def get_transfer(transfer_id: int) -> dict:
    """读取单条调拨单；不存在时给出可读的错误说明。"""
    entry = service.get_transfer(transfer_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"调拨单 {transfer_id} 不存在")
    return entry


@router.post("/transfers/{transfer_id}/approve", response_model=ActionResult)
def approve_transfer(transfer_id: int, payload: OperatorPayload) -> ActionResult:
    """审批：已申请 → 已批；只有源仓保管员能批，状态回不到已申请。"""
    entry, message = service.approve_transfer(transfer_id, payload.operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/transfers/{transfer_id}/ship", response_model=ActionResult)
def ship_transfer(transfer_id: int, payload: OperatorPayload) -> ActionResult:
    """出库：已批 → 在途；源仓扣、目标仓加是同一笔账，重复提交只出库一次。"""
    entry, message = service.ship_transfer(transfer_id, payload.operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/transfers/{transfer_id}/receive", response_model=ActionResult)
def receive_transfer(transfer_id: int, payload: OperatorPayload) -> ActionResult:
    """入库：在途 → 已入库；结存在出库时已双边过账，本步只推进单据。"""
    entry, message = service.receive_transfer(transfer_id, payload.operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/transfers/{transfer_id}/reject", response_model=ActionResult)
def reject_transfer(transfer_id: int, payload: OperatorPayload) -> ActionResult:
    """拒收退回：在途 → 已退回；库存回到出库前的数，已冲销过的不许重复冲账。"""
    entry, message = service.reject_transfer(transfer_id, payload.operator, remark=payload.remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/balances/adjust", response_model=ActionResult)
def adjust_balance(payload: BalanceAdjustPayload) -> ActionResult:
    """直接调整结存：跨仓改数当场驳回，并说明缺哪项授权。"""
    entry, message = service.adjust_balance(payload.model_dump(), operator=payload.operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
