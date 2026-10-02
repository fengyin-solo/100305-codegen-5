"""备品备件台账业务规则。

各站自存自管的备件收成一张可调的库存台账：
- 每个仓库按备件型号登记结存与安全库存，出库与调拨分开记账；
- 调拨单按 已申请 → 已批 → 在途 → 已入库 单向推进，没批的不许出库，也回不到已申请；
- 同一张调拨单重复提交只出库一次：源仓扣、目标仓加是同一笔账（同一个流水号）；
- 在途被目的仓拒收要退回源仓，库存回到出库前的数，已过账的那一步不许被重复冲掉；
- 只有本仓保管员能批出库，跨仓直接改数当场驳回并说明缺哪项授权；
- 结存低于安全库存的落到待补货清单，库存台账与待补货两个入口读的是同一份结存。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

# 调拨单状态机：只能往前推，回不到「已申请」；「已退回」是在途被拒收后的终态分支
TRANSFER_FLOW = ["已申请", "已批", "在途", "已入库"]
STATUS_RETURNED = "已退回"

# 台账流水类型：出库与调拨分开记
LEDGER_ISSUE = "出库"
LEDGER_TRANSFER_OUT = "调拨出库"
LEDGER_TRANSFER_IN = "调拨入库"
LEDGER_RETURN_IN = "退回入库"
LEDGER_RETURN_OUT = "退回冲减"
LEDGER_ADJUST = "直接调整"

WAREHOUSES = [
    {"id": "WH-01", "名称": "华东中心仓", "保管员": ["王守仓"]},
    {"id": "WH-02", "名称": "华南站仓", "保管员": ["李看站"]},
    {"id": "WH-03", "名称": "西南站仓", "保管员": ["陈守库"]},
]

PARTS = [
    {"型号": "SP-RRU-01", "名称": "RRU射频模块", "单位": "台"},
    {"型号": "SP-BBU-02", "名称": "基带处理板", "单位": "块"},
    {"型号": "SP-PSU-03", "名称": "电源整流模块", "单位": "个"},
    {"型号": "SP-FAN-04", "名称": "风扇单元", "单位": "个"},
    {"型号": "SP-BAT-05", "名称": "磷酸铁锂电池组", "单位": "组"},
]

# (仓库, 备件型号, 结存, 安全库存)：一边缺货、一边压货的典型分布
BALANCE_SEED = [
    ("WH-01", "SP-RRU-01", 12, 5),
    ("WH-01", "SP-BBU-02", 8, 4),
    ("WH-01", "SP-PSU-03", 20, 8),
    ("WH-01", "SP-FAN-04", 30, 10),
    ("WH-01", "SP-BAT-05", 6, 3),
    ("WH-02", "SP-RRU-01", 2, 4),
    ("WH-02", "SP-BBU-02", 5, 3),
    ("WH-02", "SP-PSU-03", 3, 6),
    ("WH-02", "SP-FAN-04", 12, 8),
    ("WH-02", "SP-BAT-05", 1, 2),
    ("WH-03", "SP-RRU-01", 6, 4),
    ("WH-03", "SP-BBU-02", 2, 3),
    ("WH-03", "SP-PSU-03", 9, 6),
    ("WH-03", "SP-FAN-04", 7, 8),
    ("WH-03", "SP-BAT-05", 4, 2),
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SparepartService:
    """备品备件台账：结存、出库单、调拨单与流水都长在这一份数据上。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._warehouses = {row["id"]: dict(row) for row in WAREHOUSES}
        self._parts = {row["型号"]: dict(row) for row in PARTS}
        self._balances: dict[tuple[str, str], dict[str, Any]] = {}
        for warehouse, sku, quantity, safety in BALANCE_SEED:
            self._balances[(warehouse, sku)] = {
                "仓库": warehouse,
                "备件型号": sku,
                "结存": quantity,
                "安全库存": safety,
            }
        self._transfers: list[dict[str, Any]] = []
        self._issues: list[dict[str, Any]] = []
        self._ledger: list[dict[str, Any]] = []
        self._seq = {"transfer": 0, "issue": 0, "ledger": 0, "journal": 0}
        self._seed_history()

    def _seed_history(self) -> None:
        """用真实流转造一条已入库的历史调拨单，保证结存、流水、单据三者一致。"""
        entry, _ = self.create_transfer({
            "源仓库": "WH-01", "目标仓库": "WH-03", "备件型号": "SP-FAN-04",
            "数量": 5, "申请人": "陈守库",
        })
        if entry is not None:
            self.approve_transfer(entry["id"], "王守仓")
            self.ship_transfer(entry["id"], "王守仓")
            self.receive_transfer(entry["id"], "陈守库")
        # 再留一张待批的申请，页面打开就能看到可执行的审批动作
        self.create_transfer({
            "源仓库": "WH-01", "目标仓库": "WH-02", "备件型号": "SP-RRU-01",
            "数量": 3, "申请人": "李看站",
        })

    # ------------------------------------------------------------------
    # 只读入口：库存台账、待补货清单、流水，读的都是同一份结存
    # ------------------------------------------------------------------
    def list_warehouses(self) -> list[dict[str, Any]]:
        return [
            {"id": row["id"], "名称": row["名称"], "保管员": list(row["保管员"])}
            for row in self._warehouses.values()
        ]

    def list_parts(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._parts.values()]

    def _balance_view(self, balance: dict[str, Any]) -> dict[str, Any]:
        part = self._parts[balance["备件型号"]]
        warehouse = self._warehouses[balance["仓库"]]
        return {
            "仓库": balance["仓库"],
            "仓库名称": warehouse["名称"],
            "备件型号": balance["备件型号"],
            "备件名称": part["名称"],
            "单位": part["单位"],
            "结存": balance["结存"],
            "安全库存": balance["安全库存"],
            "低于安全库存": balance["结存"] < balance["安全库存"],
        }

    def list_balances(
        self,
        *,
        warehouse: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = []
        for (warehouse_id, sku), balance in self._balances.items():
            if warehouse and warehouse_id != warehouse:
                continue
            if keyword:
                part_name = self._parts[sku]["名称"]
                if keyword not in sku and keyword not in part_name:
                    continue
            rows.append(self._balance_view(balance))
        rows.sort(key=lambda row: (row["仓库"], row["备件型号"]))
        return rows

    def list_replenishment(self) -> list[dict[str, Any]]:
        """待补货清单：与库存台账读同一份结存，低于安全库存的落到这里。"""
        items = []
        for view in self.list_balances():
            if view["低于安全库存"]:
                items.append({**view, "建议补货量": view["安全库存"] - view["结存"]})
        return items

    def list_transfers(self, *, status: str | None = None) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._transfers if not status or row["status"] == status]
        rows.sort(key=lambda row: row["id"], reverse=True)
        return rows

    def get_transfer(self, transfer_id: int) -> dict[str, Any] | None:
        transfer = self._find_transfer(transfer_id)
        return dict(transfer) if transfer is not None else None

    def list_issues(self) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._issues]
        rows.sort(key=lambda row: row["id"], reverse=True)
        return rows

    def list_ledger(
        self,
        *,
        warehouse: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            dict(row) for row in self._ledger
            if (not warehouse or row["仓库"] == warehouse) and (not kind or row["类型"] == kind)
        ]
        rows.sort(key=lambda row: row["id"], reverse=True)
        return rows

    # ------------------------------------------------------------------
    # 出库单：领用出库，与调拨分开记账
    # ------------------------------------------------------------------
    def create_issue(
        self,
        values: dict[str, Any],
        *,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            warehouse_id = str(values.get("仓库") or "").strip()
            sku = str(values.get("备件型号") or "").strip()
            qty = int(values.get("数量") or 0)
            if warehouse_id not in self._warehouses:
                return None, f"仓库 {warehouse_id or '空'} 不存在"
            if sku not in self._parts:
                return None, f"备件型号 {sku or '空'} 未登记"
            if qty <= 0:
                return None, "出库数量必须大于 0"
            if error := self._keeper_error(warehouse_id, operator):
                return None, error
            balance = self._balances.get((warehouse_id, sku))
            if balance is None:
                return None, f"{self._warehouses[warehouse_id]['名称']} 没有 {sku} 的结存，不能出库"
            if balance["结存"] < qty:
                return None, f"结存不足：现有 {balance['结存']}，需出库 {qty}"
            self._seq["issue"] += 1
            issue_no = f"CK-{self._seq['issue']:04d}"
            journal = self._next_journal()
            self._post(
                journal=journal, kind=LEDGER_ISSUE, warehouse=warehouse_id, sku=sku,
                delta=-qty, operator=operator, ref=issue_no,
            )
            issue = {
                "id": self._seq["issue"],
                "出库单号": issue_no,
                "仓库": warehouse_id,
                "仓库名称": self._warehouses[warehouse_id]["名称"],
                "备件型号": sku,
                "备件名称": self._parts[sku]["名称"],
                "数量": qty,
                "领用人": str(values.get("领用人") or ""),
                "操作员": operator,
                "时间": _now(),
                "流水号": journal,
                "备注": str(values.get("备注") or ""),
            }
            self._issues.append(issue)
            return dict(issue), f"出库单 {issue_no} 已登记：{issue['仓库名称']} {sku} -{qty}（流水 {journal}）"

    # ------------------------------------------------------------------
    # 调拨单：申请 → 审批 → 出库 → 入库 / 拒收退回
    # ------------------------------------------------------------------
    def create_transfer(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            source = str(values.get("源仓库") or "").strip()
            target = str(values.get("目标仓库") or "").strip()
            sku = str(values.get("备件型号") or "").strip()
            qty = int(values.get("数量") or 0)
            if source not in self._warehouses:
                return None, f"源仓库 {source or '空'} 不存在"
            if target not in self._warehouses:
                return None, f"目标仓库 {target or '空'} 不存在"
            if source == target:
                return None, "源仓库与目标仓库不能是同一个仓"
            if sku not in self._parts:
                return None, f"备件型号 {sku or '空'} 未登记"
            if qty <= 0:
                return None, "调拨数量必须大于 0"
            order_no = str(values.get("调拨单号") or "").strip()
            if order_no:
                for transfer in self._transfers:
                    if transfer["调拨单号"] == order_no:
                        return dict(transfer), (
                            f"调拨单 {order_no} 已存在（当前状态「{transfer['status']}」），重复提交按原单返回"
                        )
            self._seq["transfer"] += 1
            if not order_no:
                order_no = f"DB-{self._seq['transfer']:04d}"
            transfer = {
                "id": self._seq["transfer"],
                "调拨单号": order_no,
                "源仓库": source,
                "源仓库名称": self._warehouses[source]["名称"],
                "目标仓库": target,
                "目标仓库名称": self._warehouses[target]["名称"],
                "备件型号": sku,
                "备件名称": self._parts[sku]["名称"],
                "数量": qty,
                "status": TRANSFER_FLOW[0],
                "申请人": str(values.get("申请人") or ""),
                "申请时间": _now(),
                "审批人": None,
                "审批时间": None,
                "出库人": None,
                "出库时间": None,
                "入库人": None,
                "入库时间": None,
                "退回原因": None,
                "退回时间": None,
                "outbound_posted": False,
                "return_posted": False,
                "outbound_journal": None,
                "return_journal": None,
            }
            self._transfers.append(transfer)
            return dict(transfer), f"调拨单 {order_no} 已申请，待 {transfer['源仓库名称']} 保管员审批"

    def approve_transfer(
        self,
        transfer_id: int,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            transfer = self._find_transfer(transfer_id)
            if transfer is None:
                return None, f"调拨单 {transfer_id} 不存在"
            if transfer["status"] != TRANSFER_FLOW[0]:
                return None, (
                    f"调拨单 {transfer['调拨单号']} 当前状态「{transfer['status']}」，"
                    "只有「已申请」的单据能审批，状态只往前走、回不到已申请"
                )
            if error := self._keeper_error(transfer["源仓库"], operator):
                return None, error
            transfer["status"] = TRANSFER_FLOW[1]
            transfer["审批人"] = operator
            transfer["审批时间"] = _now()
            return dict(transfer), f"调拨单 {transfer['调拨单号']} 已审批通过，可以出库"

    def ship_transfer(
        self,
        transfer_id: int,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """出库过账：源仓扣、目标仓加，同一个流水号，是同一笔账；重复提交只出库一次。"""
        with self._lock:
            transfer = self._find_transfer(transfer_id)
            if transfer is None:
                return None, f"调拨单 {transfer_id} 不存在"
            if transfer["status"] == STATUS_RETURNED:
                return None, f"调拨单 {transfer['调拨单号']} 已退回，不能再出库"
            if transfer["outbound_posted"]:
                return dict(transfer), (
                    f"调拨单 {transfer['调拨单号']} 已出库过账（流水 {transfer['outbound_journal']}），"
                    "重复提交不再扣减"
                )
            if transfer["status"] == TRANSFER_FLOW[0]:
                return None, f"调拨单 {transfer['调拨单号']} 还没审批，没批的调拨单不许出库"
            if transfer["status"] != TRANSFER_FLOW[1]:
                return None, f"调拨单 {transfer['调拨单号']} 当前状态「{transfer['status']}」，不能出库"
            if error := self._keeper_error(transfer["源仓库"], operator):
                return None, error
            source, target, sku, qty = (
                transfer["源仓库"], transfer["目标仓库"], transfer["备件型号"], transfer["数量"],
            )
            balance = self._balances.get((source, sku))
            if balance is None or balance["结存"] < qty:
                have = balance["结存"] if balance else 0
                return None, f"源仓结存不足：{transfer['源仓库名称']} {sku} 现有 {have}，需出库 {qty}"
            journal = self._next_journal()
            self._post(
                journal=journal, kind=LEDGER_TRANSFER_OUT, warehouse=source, sku=sku,
                delta=-qty, operator=operator, ref=transfer["调拨单号"],
            )
            self._post(
                journal=journal, kind=LEDGER_TRANSFER_IN, warehouse=target, sku=sku,
                delta=qty, operator=operator, ref=transfer["调拨单号"],
            )
            transfer["status"] = TRANSFER_FLOW[2]
            transfer["出库人"] = operator
            transfer["出库时间"] = _now()
            transfer["outbound_posted"] = True
            transfer["outbound_journal"] = journal
            return dict(transfer), (
                f"调拨单 {transfer['调拨单号']} 已出库：{transfer['源仓库名称']} -{qty}、"
                f"{transfer['目标仓库名称']} +{qty}，同一笔账 {journal}"
            )

    def receive_transfer(
        self,
        transfer_id: int,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            transfer = self._find_transfer(transfer_id)
            if transfer is None:
                return None, f"调拨单 {transfer_id} 不存在"
            if transfer["status"] != TRANSFER_FLOW[2]:
                return None, (
                    f"调拨单 {transfer['调拨单号']} 当前状态「{transfer['status']}」，"
                    "只有「在途」的单据能确认入库"
                )
            transfer["status"] = TRANSFER_FLOW[3]
            transfer["入库人"] = operator
            transfer["入库时间"] = _now()
            return dict(transfer), (
                f"调拨单 {transfer['调拨单号']} 已确认入库"
                "（结存在出库时已双边过账，本步只推进单据）"
            )

    def reject_transfer(
        self,
        transfer_id: int,
        operator: str,
        *,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """在途拒收退回：把出库那笔账原路冲回，库存回到出库前的数，且只冲一次。"""
        with self._lock:
            transfer = self._find_transfer(transfer_id)
            if transfer is None:
                return None, f"调拨单 {transfer_id} 不存在"
            if transfer["return_posted"]:
                return dict(transfer), (
                    f"调拨单 {transfer['调拨单号']} 的退回已冲销过（流水 {transfer['return_journal']}），"
                    "不许重复冲账"
                )
            if transfer["status"] != TRANSFER_FLOW[2]:
                return None, (
                    f"调拨单 {transfer['调拨单号']} 当前状态「{transfer['status']}」，"
                    "只有「在途」的单据能拒收退回"
                )
            source, target, sku, qty = (
                transfer["源仓库"], transfer["目标仓库"], transfer["备件型号"], transfer["数量"],
            )
            target_balance = self._balances.get((target, sku))
            if target_balance is None or target_balance["结存"] < qty:
                have = target_balance["结存"] if target_balance else 0
                return None, (
                    f"目的仓 {transfer['目标仓库名称']} {sku} 结存仅剩 {have}，"
                    "不足退回数量，无法原路冲回，请先核对账目"
                )
            journal = self._next_journal()
            self._post(
                journal=journal, kind=LEDGER_RETURN_IN, warehouse=source, sku=sku,
                delta=qty, operator=operator, ref=transfer["调拨单号"],
            )
            self._post(
                journal=journal, kind=LEDGER_RETURN_OUT, warehouse=target, sku=sku,
                delta=-qty, operator=operator, ref=transfer["调拨单号"],
            )
            transfer["status"] = STATUS_RETURNED
            transfer["退回原因"] = remark or "目的仓拒收"
            transfer["退回时间"] = _now()
            transfer["return_posted"] = True
            transfer["return_journal"] = journal
            return dict(transfer), (
                f"调拨单 {transfer['调拨单号']} 已退回源仓，库存回到出库前的数（冲销流水 {journal}）"
            )

    # ------------------------------------------------------------------
    # 直接调整结存：只有本仓保管员能过这关，跨仓改数当场驳回
    # ------------------------------------------------------------------
    def adjust_balance(
        self,
        values: dict[str, Any],
        *,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            warehouse_id = str(values.get("仓库") or "").strip()
            sku = str(values.get("备件型号") or "").strip()
            new_quantity = int(values.get("调整后结存") or 0)
            new_safety = values.get("安全库存")
            if warehouse_id not in self._warehouses:
                return None, f"仓库 {warehouse_id or '空'} 不存在"
            if sku not in self._parts:
                return None, f"备件型号 {sku or '空'} 未登记"
            if new_quantity < 0:
                return None, "结存不能调成负数"
            if error := self._keeper_error(warehouse_id, operator):
                return None, error
            balance = self._balances.setdefault(
                (warehouse_id, sku),
                {"仓库": warehouse_id, "备件型号": sku, "结存": 0, "安全库存": 0},
            )
            old_quantity = balance["结存"]
            delta = new_quantity - old_quantity
            if new_safety is not None:
                balance["安全库存"] = max(int(new_safety), 0)
            if delta == 0:
                return self._balance_view(balance), "结存未变化，未记账"
            journal = self._next_journal()
            self._post(
                journal=journal, kind=LEDGER_ADJUST, warehouse=warehouse_id, sku=sku,
                delta=delta, operator=operator, ref="直接调整",
            )
            view = self._balance_view(balance)
            return view, (
                f"{view['仓库名称']} {sku} 结存 {old_quantity} → {new_quantity}（流水 {journal}）"
            )

    # ------------------------------------------------------------------
    # 内部：授权、过账、流水
    # ------------------------------------------------------------------
    def _keeper_error(self, warehouse_id: str, operator: str) -> str | None:
        warehouse = self._warehouses[warehouse_id]
        if operator in warehouse["保管员"]:
            return None
        keepers = "、".join(warehouse["保管员"])
        return (
            f"缺少「{warehouse['名称']}」保管员授权：{operator or '未署名操作员'} "
            f"不在该仓保管员名单（{keepers}）内，已当场驳回"
        )

    def _find_transfer(self, transfer_id: int) -> dict[str, Any] | None:
        for transfer in self._transfers:
            if transfer["id"] == transfer_id:
                return transfer
        return None

    def _next_journal(self) -> str:
        self._seq["journal"] += 1
        return f"J-{self._seq['journal']:05d}"

    def _post(
        self,
        *,
        journal: str,
        kind: str,
        warehouse: str,
        sku: str,
        delta: int,
        operator: str,
        ref: str,
    ) -> int:
        """记一笔流水并同步结存；双边过账时两笔共用同一个流水号。"""
        balance = self._balances.setdefault(
            (warehouse, sku),
            {"仓库": warehouse, "备件型号": sku, "结存": 0, "安全库存": 0},
        )
        after = balance["结存"] + delta
        if after < 0:
            raise ValueError(
                f"{self._warehouses[warehouse]['名称']} {sku} 结存不足："
                f"现有 {balance['结存']}，需要 {-delta}"
            )
        balance["结存"] = after
        self._seq["ledger"] += 1
        self._ledger.append({
            "id": self._seq["ledger"],
            "流水号": journal,
            "类型": kind,
            "仓库": warehouse,
            "仓库名称": self._warehouses[warehouse]["名称"],
            "备件型号": sku,
            "备件名称": self._parts[sku]["名称"],
            "变动": delta,
            "结存": after,
            "关联单号": ref,
            "操作员": operator,
            "时间": _now(),
        })
        return after
