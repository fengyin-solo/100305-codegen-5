"""备品备件模块的示例数据。

为了保证"结存 = 初始库存 + 流水合计"恒成立，造数时先给初始库存，再用一个小型过账引擎
按事件回放：领用出库、调拨出库（源扣/目标加两条配对流水）、拒收退回（目标退/源收两条
冲销流水）。这样页面上看到的每个结存数字都能在台账流水里对上。
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

# 状态口径（服务层也引用，避免两边各写一份字符串）
STATUS_APPLIED = "已申请"
STATUS_APPROVED = "已批"
STATUS_IN_TRANSIT = "在途"
STATUS_RECEIVED = "已入库"
STATUS_REJECTED = "已拒收"
STATUS_RETURNED = "已退回"

# 一张调拨单只允许沿着这张表往后推；已入库/已退回为终态，已拒收只能退回不能再入库。
TRANSITIONS: dict[str, list[str]] = {
    STATUS_APPLIED: [STATUS_APPROVED],
    STATUS_APPROVED: [STATUS_IN_TRANSIT],
    STATUS_IN_TRANSIT: [STATUS_RECEIVED, STATUS_REJECTED],
    STATUS_REJECTED: [STATUS_RETURNED],
    STATUS_RECEIVED: [],
    STATUS_RETURNED: [],
}


def build_seed() -> dict[str, Any]:
    warehouses: dict[str, dict[str, Any]] = {
        "WH-CITY": {"code": "WH-CITY", "name": "城区中心仓", "keeper_id": "u_zhang", "keeper_name": "张保管"},
        "WH-EAST": {"code": "WH-EAST", "name": "城东片区仓", "keeper_id": "u_li", "keeper_name": "李保管"},
        "WH-WEST": {"code": "WH-WEST", "name": "城西片区仓", "keeper_id": "u_wang", "keeper_name": "王保管"},
    }

    parts = [
        {"code": "P-PSU-48V", "name": "开关电源整流模块", "model": "PSU-4850", "unit": "块", "safety_stock": 4, "warranty_until": "2027-06-30"},
        {"code": "P-BAT-12V", "name": "阀控式铅酸蓄电池", "model": "12V100Ah", "unit": "节", "safety_stock": 12, "warranty_until": "2026-12-31"},
        {"code": "P-FUSE-63A", "name": "直流熔断器", "model": "63A/58V", "unit": "只", "safety_stock": 20, "warranty_until": "2029-01-31"},
        {"code": "P-FAN-120", "name": "机柜散热风机", "model": "FAN-12038", "unit": "台", "safety_stock": 3, "warranty_until": "2028-03-31"},
        {"code": "P-CBL-16", "name": "电力电缆", "model": "ZR-YJV 16mm²", "unit": "米", "safety_stock": 100, "warranty_until": "2030-12-31"},
        {"code": "P-SPD-C", "name": "C级防雷模块", "model": "SPD-C40", "unit": "个", "safety_stock": 6, "warranty_until": "2026-10-31"},
    ]
    part_index = {part["code"]: part for part in parts}

    # 初始库存（任何历史业务发生之前）
    initial: dict[tuple[str, str], int] = {
        ("WH-CITY", "P-PSU-48V"): 18,
        ("WH-CITY", "P-BAT-12V"): 40,
        ("WH-CITY", "P-FUSE-63A"): 60,
        ("WH-CITY", "P-FAN-120"): 9,
        ("WH-CITY", "P-CBL-16"): 320,
        ("WH-CITY", "P-SPD-C"): 27,
        ("WH-EAST", "P-PSU-48V"): 4,
        ("WH-EAST", "P-BAT-12V"): 20,
        ("WH-EAST", "P-FUSE-63A"): 8,
        ("WH-EAST", "P-FAN-120"): 5,
        ("WH-EAST", "P-CBL-16"): 60,
        ("WH-EAST", "P-SPD-C"): 4,
        ("WH-WEST", "P-PSU-48V"): 10,
        ("WH-WEST", "P-BAT-12V"): 6,
        ("WH-WEST", "P-FUSE-63A"): 25,
        ("WH-WEST", "P-FAN-120"): 1,
        # 该型号会作为已退回调拨单的目的仓出现，先建 0 结存行以便回放冲销流水
        ("WH-WEST", "P-CBL-16"): 0,
    }

    balances: dict[tuple[str, str], dict[str, Any]] = {}
    # 记一份"该仓是否真正备这个型号"：初始库存为 0、只是为了承接某张单调拨流水而临时出现、
    # 最终结存又回到 0 的行，不应该出现在台账/待补货里（那是幻影物料行）。
    active_keys: set[tuple[str, str]] = set()
    for (wh_code, part_code), on_hand in initial.items():
        part = part_index[part_code]
        balances[(wh_code, part_code)] = {
            "warehouse_code": wh_code,
            "part_code": part_code,
            "part_name": part["name"],
            "part_model": part["model"],
            "unit": part["unit"],
            "safety_stock": part["safety_stock"],
            "warranty_until": part["warranty_until"],
            "on_hand": on_hand,
        }
        if on_hand > 0:
            active_keys.add((wh_code, part_code))

    movements: list[dict[str, Any]] = []
    outbound_orders: list[dict[str, Any]] = []
    transfer_orders: "OrderedDict[int, dict[str, Any]]" = OrderedDict()
    seq = {"movement": 0, "outbound": 0, "transfer": 2000}

    def _row(wh_code: str, part_code: str) -> dict[str, Any]:
        return balances[(wh_code, part_code)]

    def _add_movement(
        *, voucher_type: str, voucher_no: str, transfer_id: int | None, wh_code: str,
        part_code: str, qty: int, direction: str, reason: str, operator: str, created_at: str, pair_key: str,
    ) -> None:
        part = part_index[part_code]
        seq["movement"] += 1
        movements.append({
            "id": 1000 + seq["movement"],
            "voucher_type": voucher_type,
            "voucher_no": voucher_no,
            "transfer_id": transfer_id,
            "warehouse_code": wh_code,
            "part_code": part_code,
            "part_name": part["name"],
            "part_model": part["model"],
            "unit": part["unit"],
            "qty": qty,
            "direction": direction,  # in / out
            "reason": reason,
            "operator": operator,
            "created_at": created_at,
            # pair_key 相同的两条流水是同一笔账（源扣 + 目标加），审计时可成对核验
            "pair_key": pair_key,
            "posted": True,
        })
        row = _row(wh_code, part_code)
        row["on_hand"] += qty if direction == "in" else -qty

    # —— 历史领用出库（与调拨分开记）——
    history_outbound = [
        ("WH-CITY", "P-FUSE-63A", 6, "城区基站直流回路检修领用", "张保管", "2026-09-12 09:20"),
        ("WH-EAST", "P-PSU-48V", 2, "城东2号站整流模块故障更换", "李保管", "2026-09-20 14:05"),
        ("WH-CITY", "P-SPD-C", 3, "雷雨季后防雷模块抽检更换", "张保管", "2026-09-25 10:40"),
    ]
    for wh_code, part_code, qty, reason, operator, created_at in history_outbound:
        seq["outbound"] += 1
        oid = 100 + seq["outbound"]
        voucher_no = f"LL-{oid:04d}"
        outbound_orders.append({
            "id": oid,
            "voucher_no": voucher_no,
            "warehouse_code": wh_code,
            "warehouse_name": warehouses[wh_code]["name"],
            "part_code": part_code,
            "part_name": part_index[part_code]["name"],
            "part_model": part_index[part_code]["model"],
            "unit": part_index[part_code]["unit"],
            "qty": qty,
            "reason": reason,
            "operator": operator,
            "status": "已出库",
            "created_at": created_at,
        })
        _add_movement(
            voucher_type="领用出库", voucher_no=voucher_no, transfer_id=None, wh_code=wh_code,
            part_code=part_code, qty=qty, direction="out", reason=reason, operator=operator,
            created_at=created_at, pair_key=f"OUT-{voucher_no}",
        )

    def _make_transfer(
        tid: int, source: str, target: str, part_code: str, qty: int, status: str, applicant: str,
        created_at: str, approved_at: str | None, shipped_at: str | None, received_at: str | None,
        rejected_at: str | None, reject_reason: str | None, returned_at: str | None,
    ) -> None:
        """登记一张调拨单，并按其所处状态把该发生的过账回放一遍。"""
        part = part_index[part_code]
        order = {
            "id": tid,
            "voucher_no": f"DB-{tid}",
            "source_code": source,
            "target_code": target,
            "part_code": part_code,
            "part_name": part["name"],
            "part_model": part["model"],
            "unit": part["unit"],
            "qty": qty,
            "status": status,
            "applicant": applicant,
            "created_at": created_at,
            "approved_at": approved_at,
            "shipped_at": shipped_at,
            "received_at": received_at,
            "rejected_at": rejected_at,
            "returned_at": returned_at,
            "reject_reason": reject_reason,
            "history": [
                {"status": STATUS_APPLIED, "at": created_at, "operator": applicant, "note": "提交申请"},
            ],
            # posted：出库过账是否已发生（只允许一次）；return_posted：退回冲销是否已发生（只允许一次）
            "posted": False,
            "return_posted": False,
        }
        transfer_orders[tid] = order

        source_keeper = warehouses[source]["keeper_name"]
        target_keeper = warehouses[target]["keeper_name"]

        if approved_at:
            order["history"].append({"status": STATUS_APPROVED, "at": approved_at, "operator": source_keeper, "note": "源仓保管员批准"})

        # 出库过账：只要状态推进到"在途"及以后，源扣 + 目标加就已作为同一笔账发生
        if shipped_at and status in (STATUS_IN_TRANSIT, STATUS_RECEIVED, STATUS_REJECTED, STATUS_RETURNED):
            pair = f"TR-{tid}-SHIP"
            _add_movement(
                voucher_type="调拨出库", voucher_no=order["voucher_no"], transfer_id=tid, wh_code=source,
                part_code=part_code, qty=qty, direction="out", reason="调拨发运（源仓扣减）",
                operator=source_keeper, created_at=shipped_at, pair_key=pair,
            )
            _add_movement(
                voucher_type="调拨入库", voucher_no=order["voucher_no"], transfer_id=tid, wh_code=target,
                part_code=part_code, qty=qty, direction="in", reason="调拨随货入账（目标仓增加，与源仓同一笔账）",
                operator=source_keeper, created_at=shipped_at, pair_key=pair,
            )
            order["posted"] = True
            order["history"].append({"status": STATUS_IN_TRANSIT, "at": shipped_at, "operator": source_keeper, "note": "出库发运：源仓已扣、目标仓已加"})

        if rejected_at and status in (STATUS_REJECTED, STATUS_RETURNED):
            order["history"].append({"status": STATUS_REJECTED, "at": rejected_at, "operator": target_keeper, "note": f"目的仓拒收：{reject_reason}"})

        # 退回过账：拒收后退回源仓，目标退 + 源收 两条冲销流水，结存恢复到出库前
        if returned_at and status == STATUS_RETURNED:
            pair = f"TR-{tid}-RET"
            _add_movement(
                voucher_type="调拨退回", voucher_no=order["voucher_no"], transfer_id=tid, wh_code=target,
                part_code=part_code, qty=qty, direction="out", reason="拒收退回（目标仓退出此前入账）",
                operator=target_keeper, created_at=returned_at, pair_key=pair,
            )
            _add_movement(
                voucher_type="调拨退回", voucher_no=order["voucher_no"], transfer_id=tid, wh_code=source,
                part_code=part_code, qty=qty, direction="in", reason="拒收退回入源仓（冲销此前出库，恢复到出库前）",
                operator=source_keeper, created_at=returned_at, pair_key=pair,
            )
            order["return_posted"] = True
            order["history"].append({"status": STATUS_RETURNED, "at": returned_at, "operator": source_keeper, "note": "退回入源仓：结存恢复到出库前"})

        if received_at and status == STATUS_RECEIVED:
            order["history"].append({"status": STATUS_RECEIVED, "at": received_at, "operator": target_keeper, "note": "目的仓验收入库"})

    # 1) 已入库（终态）：城区 -> 城西，蓄电池 6
    _make_transfer(2001, "WH-CITY", "WH-WEST", "P-BAT-12V", 6, STATUS_RECEIVED, "王保管",
                   "2026-09-15 08:30", "2026-09-15 09:10", "2026-09-15 15:00", "2026-09-16 10:20", None, None, None)
    # 2) 在途：城区 -> 城西，散热风机 2（已出库，货未到）
    _make_transfer(2002, "WH-CITY", "WH-WEST", "P-FAN-120", 2, STATUS_IN_TRANSIT, "王保管",
                   "2026-09-28 08:10", "2026-09-28 09:00", "2026-09-28 13:30", None, None, None, None)
    # 3) 已申请待批：城区 -> 城东，整流模块 3（城东缺货）
    _make_transfer(2003, "WH-CITY", "WH-EAST", "P-PSU-48V", 3, STATUS_APPLIED, "李保管",
                   "2026-10-01 16:00", None, None, None, None, None, None)
    # 4) 已批待出库：城区 -> 城东，熔断器 12
    _make_transfer(2004, "WH-CITY", "WH-EAST", "P-FUSE-63A", 12, STATUS_APPROVED, "李保管",
                   "2026-10-01 17:00", "2026-10-02 08:20", None, None, None, None, None)
    # 5) 已拒收待退回：城区 -> 城东，防雷模块 4（临近过保，外观破损被拒）
    _make_transfer(2005, "WH-CITY", "WH-EAST", "P-SPD-C", 4, STATUS_REJECTED, "李保管",
                   "2026-09-28 11:00", "2026-09-28 11:30", "2026-09-29 09:00", None,
                   "2026-09-30 10:00", "外观破损、检测不合格，目的仓拒收", None)
    # 6) 已退回（终态）：城区 -> 城西，电力电缆 50 米（拒收后已退回，库存恢复）
    _make_transfer(2006, "WH-CITY", "WH-WEST", "P-CBL-16", 50, STATUS_RETURNED, "王保管",
                   "2026-09-10 08:00", "2026-09-10 08:30", "2026-09-10 14:00", None,
                   "2026-09-11 09:00", "型号与申请不符，目的仓拒收", "2026-09-12 11:00")

    movements.sort(key=lambda row: int(row["id"]))

    # 给结存行打 active 标记：承接过调拨（有在途/已入库存货）或盘点过的行视为在册。
    for key, row in balances.items():
        wh_code, part_code = key
        involved = key in active_keys
        if not involved and int(row["on_hand"]) > 0:
            involved = True
        # 只要当前还有调拨单的货"有效落在"该仓（在途/已入库/已拒收），也算在册
        if not involved:
            for order in transfer_orders.values():
                lands = order["status"] in (STATUS_IN_TRANSIT, STATUS_RECEIVED, STATUS_REJECTED)
                if lands and (order["target_code"], order["part_code"]) == key:
                    involved = True
                    break
        row["active"] = involved

    # 自增号从"已占用最大号"之后继续，避免新单据号/流水号和造数里的号撞车
    seq["movement"] = max(int(m["id"]) for m in movements) - 1000
    seq["outbound"] = max(int(o["id"]) for o in outbound_orders) - 100
    seq["transfer"] = max(int(t) for t in transfer_orders)

    return {
        "warehouses": warehouses,
        "parts": parts,
        "balances": balances,
        "movements": movements,
        "outbound_orders": outbound_orders,
        "transfer_orders": transfer_orders,
        "seq": seq,
    }
