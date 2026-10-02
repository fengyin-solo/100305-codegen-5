"""备品备件台账接口：结存台账、领用出库、调拨单状态流转、待补货清单。

授权约定：前端在请求头带 ``X-Operator-Id``（当前保管员）。批准/出库/退回等写操作由服务层
校验"只有本仓保管员能动本仓"，跨仓直接改结存会被驳回并在 message 里点名缺哪项授权。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from app.spare.seed import (
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_IN_TRANSIT,
    STATUS_RECEIVED,
    STATUS_REJECTED,
    STATUS_RETURNED,
)
from app.spare.service import ServiceError, spare_service
from app.spare.store import spare_store

router = APIRouter(prefix="/api/spare", tags=["备品备件"])

TRANSFER_STATUSES = [
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_IN_TRANSIT,
    STATUS_RECEIVED,
    STATUS_REJECTED,
    STATUS_RETURNED,
]
# 每个状态允许的下一步动作，前端按此渲染按钮，后端仍会独立校验
NEXT_ACTIONS = {
    STATUS_APPLIED: [("approve", "批准")],
    STATUS_APPROVED: [("ship", "出库发运")],
    STATUS_IN_TRANSIT: [("receive", "验收入库"), ("reject", "拒收")],
    STATUS_REJECTED: [("return", "退回源仓")],
    STATUS_RECEIVED: [],
    STATUS_RETURNED: [],
}


def _fail(error: ServiceError) -> JSONResponse:
    status = {
        "unauthorized": 401,
        "forbidden": 403,
        "not_found": 404,
    }.get(error.code, 400)
    return JSONResponse(status_code=status, content={"ok": False, "message": error.message, "code": error.code})


@router.get("/meta")
def meta() -> dict[str, Any]:
    """仓库档案、备件目录与状态/动作字典：给下拉框和状态按钮用。"""
    return {
        "warehouses": spare_service.list_warehouses(),
        "parts": spare_store.parts,
        "transfer_statuses": TRANSFER_STATUSES,
        "next_actions": NEXT_ACTIONS,
    }


@router.get("/me")
def me(x_operator_id: str | None = Header(default=None)) -> dict[str, Any]:
    """告诉前端当前操作员是谁、管的是哪个仓（没带身份则未登录）。"""
    return spare_service.me(x_operator_id)


@router.get("/balances")
def list_balances(
    warehouse: str | None = Query(default=None, description="按仓库编码过滤"),
    keyword: str | None = Query(default=None, description="按备件编码/名称/型号检索"),
) -> dict[str, Any]:
    """结存台账：每个仓库按备件型号登记的结存，是库存数字的唯一事实来源。"""
    items = spare_service.list_balances(warehouse_code=warehouse, part_keyword=keyword)
    return {"total": len(items), "items": items}


@router.post("/balances")
def adjust_balance(payload: dict[str, Any], x_operator_id: str | None = Header(default=None)) -> Any:
    """登记/盘点某仓某型号结存。跨仓保管员直接改数会被驳回并说明缺哪项授权。"""
    try:
        row, missing = spare_service.adjust_balance(x_operator_id, payload)
    except ServiceError as error:
        return _fail(error)
    if missing:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": f"缺少必填字段：{'、'.join(missing)}", "code": "validation"},
        )
    return {"ok": True, "message": "结存已登记", "entry": row}


@router.get("/restock")
def restock(warehouse: str | None = Query(default=None)) -> dict[str, Any]:
    """待补货清单：结存低于安全库存的行，直接从台账同一份结存派生。"""
    items = spare_service.restock_list(warehouse_code=warehouse)
    return {"total": len(items), "items": items}


@router.get("/movements")
def list_movements(
    warehouse: str | None = Query(default=None),
    voucher_type: str | None = Query(default=None, description="领用出库/调拨出库/调拨入库/调拨退回/盘点调整"),
) -> dict[str, Any]:
    """台账流水：领用出库与调拨分开记，可按单据类型过滤。"""
    items = spare_service.list_movements(warehouse_code=warehouse, voucher_type=voucher_type)
    return {"total": len(items), "items": items}


@router.get("/outbound")
def list_outbound(warehouse: str | None = Query(default=None)) -> dict[str, Any]:
    """领用出库单列表（与调拨单分簿）。"""
    items = spare_service.list_outbound(warehouse_code=warehouse)
    return {"total": len(items), "items": items}


@router.post("/outbound")
def create_outbound(payload: dict[str, Any], x_operator_id: str | None = Header(default=None)) -> Any:
    """领用出库：只有本仓保管员能操作本仓，结存不足当场拦下，不产生半条流水。"""
    try:
        order, missing = spare_service.consume_outbound(x_operator_id, payload)
    except ServiceError as error:
        return _fail(error)
    if missing:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": f"缺少必填字段：{'、'.join(missing)}", "code": "validation"},
        )
    return {"ok": True, "message": f"领用出库 {order['voucher_no']} 已过账", "entry": order}


@router.get("/transfers")
def list_transfers(
    status: str | None = Query(default=None),
    warehouse: str | None = Query(default=None, description="只看与本仓相关（源或目的）的调拨单"),
) -> dict[str, Any]:
    """调拨单列表，可按状态/相关仓库过滤。"""
    items = spare_service.list_transfers(status=status, warehouse_code=warehouse)
    for item in items:
        item["actions"] = [{"key": key, "label": label} for key, label in NEXT_ACTIONS.get(item["status"], [])]
    return {"total": len(items), "items": items}


@router.get("/transfers/{order_id}")
def get_transfer(order_id: int) -> Any:
    order = spare_service.get_transfer(order_id)
    if order is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": f"调拨单 {order_id} 不存在", "code": "not_found"})
    order["actions"] = [{"key": key, "label": label} for key, label in NEXT_ACTIONS.get(order["status"], [])]
    return order


@router.post("/transfers")
def create_transfer(payload: dict[str, Any], x_operator_id: str | None = Header(default=None)) -> Any:
    """新建调拨申请（初始状态：已申请，未批准，库存不动）。"""
    try:
        order, missing = spare_service.create_transfer(x_operator_id, payload)
    except ServiceError as error:
        return _fail(error)
    if missing:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": f"缺少必填字段：{'、'.join(missing)}", "code": "validation"},
        )
    return {"ok": True, "message": f"调拨申请 {order['voucher_no']} 已提交，待源仓保管员批准", "entry": order}


@router.post("/transfers/{order_id}/actions")
def run_transfer_action(
    order_id: int,
    payload: dict[str, Any],
    x_operator_id: str | None = Header(default=None),
) -> Any:
    """推进调拨单：approve 批准 / ship 出库发运 / receive 验收入库 / reject 拒收 / return 退回源仓。

    非法跳转、越权、库存不足、重复出库/重复冲销都会被拦下，并返回可读原因。
    """
    action = str(payload.get("action") or "").strip()
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    if "reason" in payload and "reason" not in values:
        values["reason"] = payload["reason"]
    try:
        order = spare_service.run_transfer_action(order_id, action, x_operator_id, values)
    except ServiceError as error:
        return _fail(error)
    messages = {
        "approve": "已批准，源仓可出库发运",
        "ship": "出库过账完成：源仓已扣、目标仓已加（同一笔账）",
        "receive": "目的仓验收入库完成",
        "reject": "已拒收，等待退回源仓",
        "return": "退回过账完成：两边结存已恢复到出库前",
    }
    return {"ok": True, "message": messages.get(action, "操作已完成"), "entry": order}
