"""备品备件台账验收测试：状态机、幂等过账、退回冲销、仓间授权与待补货口径。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.sparepart import SparepartService

SOURCE, TARGET = "WH-01", "WH-02"
KEEPER, OTHER_KEEPER, OUTSIDER = "王守仓", "李看站", "值班管理员"
SKU = "SP-PSU-03"


@pytest.fixture()
def service() -> SparepartService:
    return SparepartService()


def balance_of(service: SparepartService, warehouse: str, sku: str) -> int:
    for row in service.list_balances(warehouse=warehouse):
        if row["备件型号"] == sku:
            return int(row["结存"])
    raise AssertionError(f"{warehouse} 没有 {sku} 的结存行")


def make_transfer(service: SparepartService, qty: int = 3) -> dict:
    entry, message = service.create_transfer({
        "源仓库": SOURCE, "目标仓库": TARGET, "备件型号": SKU, "数量": qty, "申请人": "李看站",
    })
    assert entry is not None, message
    return entry


def test_transfer_flow_moves_forward_only(service: SparepartService) -> None:
    entry = make_transfer(service)
    tid = entry["id"]
    assert entry["status"] == "已申请"

    entry, _ = service.approve_transfer(tid, KEEPER)
    assert entry is not None and entry["status"] == "已批"
    entry, _ = service.ship_transfer(tid, KEEPER)
    assert entry is not None and entry["status"] == "在途"
    entry, _ = service.receive_transfer(tid, "李看站")
    assert entry is not None and entry["status"] == "已入库"

    # 已入库后任何动作都不能把单据打回去，更回不到已申请
    for action in (service.approve_transfer, service.ship_transfer):
        entry, _ = action(tid, KEEPER)
        assert service.get_transfer(tid)["status"] == "已入库"
    entry, message = service.reject_transfer(tid, "李看站")
    assert entry is None and "在途" in message
    assert service.get_transfer(tid)["status"] == "已入库"


def test_ship_requires_approval(service: SparepartService) -> None:
    entry = make_transfer(service)
    before_source = balance_of(service, SOURCE, SKU)
    before_target = balance_of(service, TARGET, SKU)

    result, message = service.ship_transfer(entry["id"], KEEPER)
    assert result is None
    assert "没批" in message or "未批" in message or "不许出库" in message
    assert balance_of(service, SOURCE, SKU) == before_source
    assert balance_of(service, TARGET, SKU) == before_target
    assert service.get_transfer(entry["id"])["status"] == "已申请"


def test_approve_requires_source_keeper(service: SparepartService) -> None:
    entry = make_transfer(service)
    tid = entry["id"]

    # 跨仓保管员与无关人员都被当场驳回，并说明缺哪项授权
    for operator in (OUTSIDER, "陈守库"):
        result, message = service.approve_transfer(tid, operator)
        assert result is None
        assert "缺少「华东中心仓」保管员授权" in message
        assert operator in message
        assert service.get_transfer(tid)["status"] == "已申请"

    entry, _ = service.approve_transfer(tid, KEEPER)
    assert entry is not None and entry["status"] == "已批"
    assert entry["审批人"] == KEEPER


def test_ship_is_idempotent_and_posts_both_sides_as_one_journal(service: SparepartService) -> None:
    entry = make_transfer(service, qty=4)
    tid = entry["id"]
    service.approve_transfer(tid, KEEPER)
    before_source = balance_of(service, SOURCE, SKU)
    before_target = balance_of(service, TARGET, SKU)

    shipped, message = service.ship_transfer(tid, KEEPER)
    assert shipped is not None, message
    assert balance_of(service, SOURCE, SKU) == before_source - 4
    assert balance_of(service, TARGET, SKU) == before_target + 4

    # 两边是同一笔账：同一个流水号，一出一进
    entries = [row for row in service.list_ledger() if row["关联单号"] == shipped["调拨单号"]]
    assert len(entries) == 2
    assert {row["类型"] for row in entries} == {"调拨出库", "调拨入库"}
    assert len({row["流水号"] for row in entries}) == 1

    # 重复提交只出库一次，结存不再动
    again, message = service.ship_transfer(tid, KEEPER)
    assert again is not None and "重复" in message
    assert balance_of(service, SOURCE, SKU) == before_source - 4
    assert balance_of(service, TARGET, SKU) == before_target + 4
    entries = [row for row in service.list_ledger() if row["关联单号"] == shipped["调拨单号"]]
    assert len(entries) == 2


def test_reject_return_restores_stock_and_cannot_double_reverse(service: SparepartService) -> None:
    entry = make_transfer(service, qty=5)
    tid = entry["id"]
    service.approve_transfer(tid, KEEPER)
    before_source = balance_of(service, SOURCE, SKU)
    before_target = balance_of(service, TARGET, SKU)
    service.ship_transfer(tid, KEEPER)
    assert balance_of(service, SOURCE, SKU) == before_source - 5

    returned, message = service.reject_transfer(tid, "李看站", remark="包装破损")
    assert returned is not None and returned["status"] == "已退回", message
    assert balance_of(service, SOURCE, SKU) == before_source
    assert balance_of(service, TARGET, SKU) == before_target

    # 已经过账的退回不许被重复冲掉
    again, message = service.reject_transfer(tid, "李看站")
    assert again is not None and "重复" in message
    assert balance_of(service, SOURCE, SKU) == before_source
    assert balance_of(service, TARGET, SKU) == before_target
    entries = [row for row in service.list_ledger() if row["关联单号"] == returned["调拨单号"]]
    assert len(entries) == 4  # 出库两笔 + 退回两笔，没有第三对
    assert len({row["流水号"] for row in entries}) == 2


def test_returned_transfer_cannot_ship_again(service: SparepartService) -> None:
    entry = make_transfer(service)
    tid = entry["id"]
    service.approve_transfer(tid, KEEPER)
    service.ship_transfer(tid, KEEPER)
    service.reject_transfer(tid, "李看站")

    result, message = service.ship_transfer(tid, KEEPER)
    assert result is None and "已退回" in message


def test_ship_blocked_when_source_stock_short(service: SparepartService) -> None:
    have = balance_of(service, SOURCE, SKU)
    entry = make_transfer(service, qty=have + 1)
    tid = entry["id"]
    service.approve_transfer(tid, KEEPER)

    result, message = service.ship_transfer(tid, KEEPER)
    assert result is None and "结存不足" in message
    assert service.get_transfer(tid)["status"] == "已批"
    assert balance_of(service, SOURCE, SKU) == have


def test_direct_adjust_rejected_cross_warehouse(service: SparepartService) -> None:
    before = balance_of(service, TARGET, SKU)

    # 非本仓保管员跨仓改数：当场驳回并说明缺哪项授权
    result, message = service.adjust_balance(
        {"仓库": TARGET, "备件型号": SKU, "调整后结存": 99}, operator=OUTSIDER,
    )
    assert result is None
    assert "缺少「华南站仓」保管员授权" in message
    assert balance_of(service, TARGET, SKU) == before

    # 本仓保管员可以调，且留下流水
    result, message = service.adjust_balance(
        {"仓库": TARGET, "备件型号": SKU, "调整后结存": 9}, operator=OTHER_KEEPER,
    )
    assert result is not None and result["结存"] == 9
    assert balance_of(service, TARGET, SKU) == 9
    entries = [row for row in service.list_ledger(kind="直接调整") if row["仓库"] == TARGET]
    assert entries and entries[0]["操作员"] == OTHER_KEEPER


def test_issue_and_transfer_are_separate_accounts(service: SparepartService) -> None:
    before = balance_of(service, SOURCE, SKU)

    # 非保管员不能开出库单
    result, message = service.create_issue(
        {"仓库": SOURCE, "备件型号": SKU, "数量": 2}, operator=OUTSIDER,
    )
    assert result is None and "保管员授权" in message

    issue, message = service.create_issue(
        {"仓库": SOURCE, "备件型号": SKU, "数量": 2, "领用人": "张维修"}, operator=KEEPER,
    )
    assert issue is not None, message
    assert balance_of(service, SOURCE, SKU) == before - 2
    issue_entries = [row for row in service.list_ledger(kind="出库") if row["关联单号"] == issue["出库单号"]]
    assert len(issue_entries) == 1 and issue_entries[0]["变动"] == -2

    # 出库与调拨分开记：调拨流水不会混进「出库」类型
    entry = make_transfer(service, qty=1)
    service.approve_transfer(entry["id"], KEEPER)
    service.ship_transfer(entry["id"], KEEPER)
    transfer_kinds = {row["类型"] for row in service.list_ledger() if row["关联单号"] == entry["调拨单号"]}
    assert transfer_kinds == {"调拨出库", "调拨入库"}


def test_issue_blocked_when_stock_short(service: SparepartService) -> None:
    have = balance_of(service, SOURCE, SKU)
    result, message = service.create_issue(
        {"仓库": SOURCE, "备件型号": SKU, "数量": have + 1}, operator=KEEPER,
    )
    assert result is None and "结存不足" in message
    assert balance_of(service, SOURCE, SKU) == have


def test_replenishment_reads_the_same_balance(service: SparepartService) -> None:
    items = service.list_replenishment()
    assert items, "种子里应有低于安全库存的条目"
    balances = {
        (row["仓库"], row["备件型号"]): row["结存"] for row in service.list_balances()
    }
    for item in items:
        assert item["结存"] < item["安全库存"]
        # 另一个入口读到的结存必须跟台账是同一份
        assert balances[(item["仓库"], item["备件型号"])] == item["结存"]
        assert item["建议补货量"] == item["安全库存"] - item["结存"]

    # 把低于安全库存的补齐后，待补货清单跟着变
    target = items[0]
    service.adjust_balance(
        {"仓库": target["仓库"], "备件型号": target["备件型号"], "调整后结存": target["安全库存"]},
        operator={"WH-01": "王守仓", "WH-02": "李看站", "WH-03": "陈守库"}[target["仓库"]],
    )
    remaining = {(row["仓库"], row["备件型号"]) for row in service.list_replenishment()}
    assert (target["仓库"], target["备件型号"]) not in remaining


def test_duplicate_order_no_returns_same_transfer(service: SparepartService) -> None:
    first, _ = service.create_transfer({
        "调拨单号": "DB-2026-0001", "源仓库": SOURCE, "目标仓库": TARGET,
        "备件型号": SKU, "数量": 2,
    })
    second, message = service.create_transfer({
        "调拨单号": "DB-2026-0001", "源仓库": SOURCE, "目标仓库": TARGET,
        "备件型号": SKU, "数量": 2,
    })
    assert first is not None and second is not None
    assert second["id"] == first["id"]
    assert "重复提交" in message
    assert len([t for t in service.list_transfers() if t["调拨单号"] == "DB-2026-0001"]) == 1


def test_api_endpoints_share_one_ledger() -> None:
    client = TestClient(app)
    balances = client.get("/api/sparepart/balances").json()
    replenishment = client.get("/api/sparepart/replenishment").json()
    assert balances["total"] > 0 and replenishment["total"] > 0
    by_key = {(row["仓库"], row["备件型号"]): row["结存"] for row in balances["items"]}
    for item in replenishment["items"]:
        assert by_key[(item["仓库"], item["备件型号"])] == item["结存"]

    # 接口层同样拦得住跨仓改数
    denied = client.post("/api/sparepart/balances/adjust", json={
        "仓库": "WH-02", "备件型号": SKU, "调整后结存": 500, "operator": "值班管理员",
    }).json()
    assert denied["ok"] is False
    assert "缺少「华南站仓」保管员授权" in denied["message"]
