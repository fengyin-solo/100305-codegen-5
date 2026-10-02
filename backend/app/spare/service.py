"""备品备件业务规则：结存台账、领用出库、调拨状态机与授权控制。

关键不变量（全部在 ``spare_store.run`` 同一把锁内维护）：

1. 一张调拨单的出库过账写两条配对流水：源仓方向 out、目标仓方向 in。"源仓扣 + 目标仓加"
   要么都发生、要么都不发生；源仓结存不足整单回滚。
2. 出库只允许发生一次：靠调拨单上的 ``posted`` 标志 + 配对流水 ``pair_key`` 双重幂等。
   同一张单重复提交"出库发运"，第二次直接拦下，不会再扣一次库存。
3. 拒收退回只允许冲销一次：靠 ``return_posted`` 标志。已过账的出库不会被重复冲掉，
   退回后结存恢复到出库前。
4. 状态只能沿 :data:`TRANSITIONS` 往后推，终态或非法跳转一律拒绝（回不到"已申请"）。
5. 批准与出库发运只有源仓保管员能做；跨仓直接改结存当场驳回并点名缺哪项授权。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.spare.seed import (
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_IN_TRANSIT,
    STATUS_RECEIVED,
    STATUS_REJECTED,
    STATUS_RETURNED,
    TRANSITIONS,
)
from app.spare.store import spare_store


class ServiceError(Exception):
    """业务规则被违反；code 便于前端区分"授权不足/状态非法/库存不足"。"""

    def __init__(self, message: str, *, code: str = "bad_request") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class SpareService:
    # ---- 操作员与授权 ---------------------------------------------
    def _operator(self, operator_id: str | None) -> dict[str, Any]:
        operator_id = (operator_id or "").strip()
        if not operator_id:
            raise ServiceError(
                "缺少操作员身份：请在页面右上角选择当前保管员（需要 X-Operator-Id 授权头）",
                code="unauthorized",
            )
        owned = [
            code for code, wh in spare_store.warehouses.items()
            if wh["keeper_id"] == operator_id
        ]
        if not owned:
            names = "、".join(f"{wh['name']}（{wh['keeper_name']}）" for wh in spare_store.warehouses.values())
            raise ServiceError(
                f"操作员「{operator_id}」不是任何仓库的保管员，无权操作备件台账。"
                f"当前在册保管员：{names}",
                code="forbidden",
            )
        wh = spare_store.warehouses[owned[0]]
        return {"id": operator_id, "name": wh["keeper_name"], "warehouse_code": owned[0], "warehouse_name": wh["name"]}

    def _require_keeper_of(self, operator_id: str | None, warehouse_code: str) -> dict[str, Any]:
        """要求操作员是指定仓库的保管员；跨仓操作在这里被驳回并说明缺哪项授权。"""
        operator = self._operator(operator_id)
        wh = spare_store.warehouse(warehouse_code)
        if wh is None:
            raise ServiceError(f"仓库「{warehouse_code}」不存在", code="not_found")
        if operator["warehouse_code"] != warehouse_code:
            raise ServiceError(
                f"跨仓操作被驳回：{operator['name']} 是{operator['warehouse_name']}的保管员，"
                f"缺少「{wh['name']}保管员」授权，不能批准/出库或改动该仓结存。"
                f"如需在两仓之间调拨，请改走调拨单流程。",
                code="forbidden",
            )
        return operator

    # ---- 基础档案 -------------------------------------------------
    def list_warehouses(self) -> list[dict[str, Any]]:
        return [dict(wh) for wh in spare_store.warehouses.values()]

    def me(self, operator_id: str | None) -> dict[str, Any]:
        if not (operator_id or "").strip():
            return {"authenticated": False, "owned_warehouse": None}
        try:
            operator = self._operator(operator_id)
        except ServiceError:
            return {"authenticated": False, "owned_warehouse": None}
        return {"authenticated": True, "owned_warehouse": operator}

    # ---- 结存台账（唯一事实来源）----------------------------------
    def list_balances(self, *, warehouse_code: str | None = None, part_keyword: str | None = None, include_inactive: bool = False) -> list[dict[str, Any]]:
        rows = spare_store.snapshot_balances()
        # 只为承接调拨流水、最终又回到 0 的幻影行默认不进台账/待补货
        if not include_inactive:
            rows = [row for row in rows if row.get("active", True)]
        if warehouse_code:
            rows = [row for row in rows if row["warehouse_code"] == warehouse_code]
        if part_keyword:
            kw = part_keyword.strip()
            rows = [
                row for row in rows
                if kw in str(row["part_code"]) or kw in str(row["part_name"]) or kw in str(row["part_model"])
            ]
        for row in rows:
            row["warehouse_name"] = spare_store.warehouse(row["warehouse_code"])["name"]
            row["below_safety"] = int(row["on_hand"]) < int(row["safety_stock"])
            row["gap_to_safety"] = max(int(row["safety_stock"]) - int(row["on_hand"]), 0)
            row["near_warranty"] = bool(row.get("warranty_until") and row["warranty_until"] <= "2026-12-31")
        rows.sort(key=lambda row: (row["warehouse_code"], row["part_code"]))
        return rows

    def restock_list(self, *, warehouse_code: str | None = None) -> list[dict[str, Any]]:
        """待补货清单：直接从同一份结存派生，另一个入口读到的就是这里同一份数。"""
        rows = [row for row in self.list_balances(warehouse_code=warehouse_code) if row["below_safety"]]
        rows.sort(key=lambda row: (-int(row["gap_to_safety"]), row["warehouse_code"], row["part_code"]))
        return rows

    def list_movements(self, *, warehouse_code: str | None = None, voucher_type: str | None = None) -> list[dict[str, Any]]:
        rows = spare_store.snapshot_movements()
        if warehouse_code:
            rows = [row for row in rows if row["warehouse_code"] == warehouse_code]
        if voucher_type:
            rows = [row for row in rows if row["voucher_type"] == voucher_type]
        for row in rows:
            row["warehouse_name"] = spare_store.warehouse(row["warehouse_code"])["name"]
        rows.sort(key=lambda row: int(row["id"]))
        return rows

    def adjust_balance(self, operator_id: str | None, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记/盘点结存。只允许本仓保管员改本仓；跨仓直接改数在 _require_keeper_of 被驳回。"""
        warehouse_code = str(values.get("warehouse_code") or "").strip()
        part_code = str(values.get("part_code") or "").strip()
        missing = [name for name, val in (("warehouse_code", warehouse_code), ("part_code", part_code)) if not val]
        try:
            on_hand = int(values.get("on_hand"))
        except (TypeError, ValueError):
            missing.append("on_hand(整数)")
            on_hand = -1
        if missing:
            return None, missing

        def _tx() -> dict[str, Any]:
            operator = self._require_keeper_of(operator_id, warehouse_code)
            if spare_store.part(part_code) is None:
                raise ServiceError(f"备件型号「{part_code}」不在备件目录中", code="bad_request")
            if on_hand < 0:
                raise ServiceError("结存数量不能为负", code="bad_request")
            row = spare_store.ensure_balance_row(warehouse_code, part_code)
            row["active"] = True
            before = int(row["on_hand"])
            diff = on_hand - before
            row["on_hand"] = on_hand
            if diff != 0:
                mvid = spare_store.next_id("movement")
                spare_store.movements.append({
                    "id": mvid,
                    "voucher_type": "盘点调整",
                    "voucher_no": f"PD-{mvid}",
                    "transfer_id": None,
                    "warehouse_code": warehouse_code,
                    "part_code": part_code,
                    "part_name": row["part_name"],
                    "part_model": row["part_model"],
                    "unit": row["unit"],
                    "qty": abs(diff),
                    "direction": "in" if diff > 0 else "out",
                    "reason": str(values.get("reason") or f"盘点调整：{before} -> {on_hand}"),
                    "operator": operator["name"],
                    "created_at": now_str(),
                    "pair_key": f"ADJ-{mvid}",
                    "posted": True,
                })
            return dict(row)

        return spare_store.run(_tx), []

    # ---- 领用出库（独立于调拨）------------------------------------
    def consume_outbound(self, operator_id: str | None, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        warehouse_code = str(values.get("warehouse_code") or "").strip()
        part_code = str(values.get("part_code") or "").strip()
        try:
            qty = int(values.get("qty"))
        except (TypeError, ValueError):
            qty = 0
        missing: list[str] = []
        if not warehouse_code:
            missing.append("warehouse_code")
        if not part_code:
            missing.append("part_code")
        if qty <= 0:
            missing.append("qty(正整数)")
        if missing:
            return None, missing

        def _tx() -> dict[str, Any]:
            operator = self._require_keeper_of(operator_id, warehouse_code)
            row = spare_store.balance_row(warehouse_code, part_code)
            if row is None:
                raise ServiceError(f"{warehouse_code} 没有备件「{part_code}」的结存记录", code="not_found")
            if int(row["on_hand"]) < qty:
                raise ServiceError(
                    f"领用出库失败：{spare_store.warehouse(warehouse_code)['name']}的{row['part_name']}"
                    f"结存 {row['on_hand']}{row['unit']}，不足领用 {qty}{row['unit']}",
                    code="insufficient",
                )
            oid = spare_store.next_id("outbound")
            mvid = spare_store.next_id("movement")
            voucher_no = f"LL-{oid:04d}"
            reason = str(values.get("reason") or "日常维修领用")
            order = {
                "id": oid,
                "voucher_no": voucher_no,
                "warehouse_code": warehouse_code,
                "warehouse_name": spare_store.warehouse(warehouse_code)["name"],
                "part_code": part_code,
                "part_name": row["part_name"],
                "part_model": row["part_model"],
                "unit": row["unit"],
                "qty": qty,
                "reason": reason,
                "operator": operator["name"],
                "status": "已出库",
                "created_at": now_str(),
            }
            spare_store.outbound_orders.append(order)
            spare_store.movements.append({
                "id": mvid,
                "voucher_type": "领用出库",
                "voucher_no": voucher_no,
                "transfer_id": None,
                "warehouse_code": warehouse_code,
                "part_code": part_code,
                "part_name": row["part_name"],
                "part_model": row["part_model"],
                "unit": row["unit"],
                "qty": qty,
                "direction": "out",
                "reason": reason,
                "operator": operator["name"],
                "created_at": order["created_at"],
                "pair_key": f"OUT-{voucher_no}",
                "posted": True,
            })
            row["on_hand"] = int(row["on_hand"]) - qty
            return order

        return spare_store.run(_tx), []

    def list_outbound(self, *, warehouse_code: str | None = None) -> list[dict[str, Any]]:
        rows = [dict(order) for order in spare_store.outbound_orders]
        if warehouse_code:
            rows = [row for row in rows if row["warehouse_code"] == warehouse_code]
        for row in rows:
            row.setdefault("warehouse_name", spare_store.warehouse(row["warehouse_code"])["name"])
        rows.sort(key=lambda row: int(row["id"]), reverse=True)
        return rows

    # ---- 调拨单 ----------------------------------------------------
    def list_transfers(
        self,
        *,
        status: str | None = None,
        warehouse_code: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = [dict(order) for order in spare_store.transfer_orders.values()]
        if status:
            rows = [row for row in rows if row["status"] == status]
        if warehouse_code:
            rows = [
                row for row in rows
                if row["source_code"] == warehouse_code or row["target_code"] == warehouse_code
            ]
        for row in rows:
            row["source_name"] = spare_store.warehouse(row["source_code"])["name"]
            row["target_name"] = spare_store.warehouse(row["target_code"])["name"]
        rows.sort(key=lambda row: int(row["id"]), reverse=True)
        return rows

    def get_transfer(self, order_id: int) -> dict[str, Any] | None:
        order = spare_store.find_transfer(order_id)
        if order is None:
            return None
        view = dict(order)
        view["source_name"] = spare_store.warehouse(order["source_code"])["name"]
        view["target_name"] = spare_store.warehouse(order["target_code"])["name"]
        return view

    def create_transfer(self, operator_id: str | None, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        source_code = str(values.get("source_code") or "").strip()
        target_code = str(values.get("target_code") or "").strip()
        part_code = str(values.get("part_code") or "").strip()
        try:
            qty = int(values.get("qty"))
        except (TypeError, ValueError):
            qty = 0
        missing: list[str] = []
        for name, val in (("source_code", source_code), ("target_code", target_code), ("part_code", part_code)):
            if not val:
                missing.append(name)
        if qty <= 0:
            missing.append("qty(正整数)")
        if missing:
            return None, missing

        def _tx() -> dict[str, Any]:
            operator = self._operator(operator_id)
            if source_code == target_code:
                raise ServiceError("源仓库和目标仓库不能相同", code="bad_request")
            if spare_store.warehouse(source_code) is None:
                raise ServiceError(f"源仓库「{source_code}」不存在", code="bad_request")
            if spare_store.warehouse(target_code) is None:
                raise ServiceError(f"目标仓库「{target_code}」不存在", code="bad_request")
            part = spare_store.part(part_code)
            if part is None:
                raise ServiceError(f"备件型号「{part_code}」不在备件目录中", code="bad_request")
            tid = spare_store.next_id("transfer")
            ts = now_str()
            order = {
                "id": tid,
                "voucher_no": f"DB-{tid}",
                "source_code": source_code,
                "target_code": target_code,
                "part_code": part_code,
                "part_name": part["name"],
                "part_model": part["model"],
                "unit": part["unit"],
                "qty": qty,
                "status": STATUS_APPLIED,
                "applicant": operator["name"],
                "created_at": ts,
                "approved_at": None,
                "shipped_at": None,
                "received_at": None,
                "rejected_at": None,
                "returned_at": None,
                "reject_reason": None,
                "history": [
                    {"status": STATUS_APPLIED, "at": ts, "operator": operator["name"], "note": "提交申请，待源仓批准"},
                ],
                "posted": False,
                "return_posted": False,
            }
            spare_store.transfer_orders[tid] = order
            return self.get_transfer(tid)  # type: ignore[return-value]

        return spare_store.run(_tx), []

    def run_transfer_action(
        self,
        order_id: int,
        action: str,
        operator_id: str | None,
        values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = values or {}

        def _tx() -> dict[str, Any]:
            order = spare_store.find_transfer(order_id)
            if order is None:
                raise ServiceError(f"调拨单 {order_id} 不存在或已归档", code="not_found")

            # 幂等闸门优先于状态校验：无论单据停在在途还是已到终态，重复出库/重复退回
            # 都给出"已经过账、库存不变"的明确口径，而不是笼统的状态错误。
            if action == "ship" and order.get("posted"):
                raise ServiceError(
                    f"调拨单 {order['voucher_no']} 已出库过账（状态：{order['status']}），"
                    "同一张单重复提交不会再次出库，源仓与目标仓库存保持不变。",
                    code="already_posted",
                )
            if action == "return" and order.get("return_posted"):
                raise ServiceError(
                    f"调拨单 {order['voucher_no']} 已完成退回过账，库存已恢复到出库前，"
                    "重复退回不会再次冲销。",
                    code="already_posted",
                )

            target_status = self._action_target(action)
            self._ensure_transition(order, target_status)

            if action == "approve":
                return self._do_approve(order, operator_id)
            if action == "ship":
                return self._do_ship(order, operator_id)
            if action == "receive":
                return self._do_receive(order, operator_id)
            if action == "reject":
                return self._do_reject(order, operator_id, str(values.get("reason") or "").strip())
            if action == "return":
                return self._do_return(order, operator_id)
            raise ServiceError(f"动作「{action}」不属于调拨单可执行范围", code="bad_request")

        return spare_store.run(_tx)

    def _action_target(self, action: str) -> str:
        mapping = {
            "approve": STATUS_APPROVED,
            "ship": STATUS_IN_TRANSIT,
            "receive": STATUS_RECEIVED,
            "reject": STATUS_REJECTED,
            "return": STATUS_RETURNED,
        }
        if action not in mapping:
            raise ServiceError(
                f"动作「{action}」不属于调拨单可执行范围；可执行：{'、'.join(mapping)}",
                code="bad_request",
            )
        return mapping[action]

    def _ensure_transition(self, order: dict[str, Any], target_status: str) -> None:
        current = str(order["status"])
        if target_status not in TRANSITIONS.get(current, []):
            if current in (STATUS_RECEIVED, STATUS_RETURNED):
                raise ServiceError(f"调拨单已是终态「{current}」，不能再往前推，也回不到「{STATUS_APPLIED}」", code="state")
            raise ServiceError(
                f"状态不能从「{current}」跳到「{target_status}」；"
                f"当前只允许推进到：{'、'.join(TRANSITIONS.get(current, [])) or '（终态，无后继）'}",
                code="state",
            )

    def _do_approve(self, order: dict[str, Any], operator_id: str | None) -> dict[str, Any]:
        # 没批的不许出库，批准权只在源仓保管员
        operator = self._require_keeper_of(operator_id, order["source_code"])
        ts = now_str()
        order["status"] = STATUS_APPROVED
        order["approved_at"] = ts
        order["history"].append({"status": STATUS_APPROVED, "at": ts, "operator": operator["name"], "note": "源仓保管员批准"})
        return self.get_transfer(int(order["id"]))  # type: ignore[return-value]

    def _do_ship(self, order: dict[str, Any], operator_id: str | None) -> dict[str, Any]:
        # 出库发运同样只有源仓保管员能做
        operator = self._require_keeper_of(operator_id, order["source_code"])

        # 幂等闸门：posted 为 True 说明这张单已经过账出库，重复提交只出库一次。
        if order.get("posted"):
            raise ServiceError(
                f"调拨单 {order['voucher_no']} 已出库过账（状态：{order['status']}），"
                "同一张单重复提交不会再次出库，源仓与目标仓库存保持不变。",
                code="already_posted",
            )

        source_row = spare_store.balance_row(order["source_code"], order["part_code"])
        qty = int(order["qty"])
        if source_row is None or int(source_row["on_hand"]) < qty:
            on_hand = int(source_row["on_hand"]) if source_row else 0
            raise ServiceError(
                f"出库被拦下：{spare_store.warehouse(order['source_code'])['name']}的"
                f"{order['part_name']}结存 {on_hand}{order['unit']}，不足调拨 {qty}{order['unit']}，"
                "源仓与目标仓均未改动",
                code="insufficient",
            )

        target_row = spare_store.ensure_balance_row(order["target_code"], order["part_code"])
        ts = now_str()
        pair = f"TR-{order['id']}-SHIP"

        # —— 同一笔账：源仓 out、目标仓 in 两条配对流水 + 两边结存，全部在本次临界区内完成。
        # 出库即按单据把货记到目标仓（在途由调拨单状态表达，不靠占用源仓库存）；任一步失败整体不生效。
        src_mvid = spare_store.next_id("movement")
        spare_store.movements.append({
            "id": src_mvid,
            "voucher_type": "调拨出库",
            "voucher_no": order["voucher_no"],
            "transfer_id": int(order["id"]),
            "warehouse_code": order["source_code"],
            "part_code": order["part_code"],
            "part_name": order["part_name"],
            "part_model": order["part_model"],
            "unit": order["unit"],
            "qty": qty,
            "direction": "out",
            "reason": "调拨发运（源仓扣减）",
            "operator": operator["name"],
            "created_at": ts,
            "pair_key": pair,
            "posted": True,
        })
        tgt_mvid = spare_store.next_id("movement")
        spare_store.movements.append({
            "id": tgt_mvid,
            "voucher_type": "调拨入库",
            "voucher_no": order["voucher_no"],
            "transfer_id": int(order["id"]),
            "warehouse_code": order["target_code"],
            "part_code": order["part_code"],
            "part_name": order["part_name"],
            "part_model": order["part_model"],
            "unit": order["unit"],
            "qty": qty,
            "direction": "in",
            "reason": "调拨随货入账（目标仓增加，与源仓出库为同一笔账）",
            "operator": operator["name"],
            "created_at": ts,
            "pair_key": pair,
            "posted": True,
        })
        source_row["on_hand"] = int(source_row["on_hand"]) - qty
        target_row["on_hand"] = int(target_row["on_hand"]) + qty

        order["status"] = STATUS_IN_TRANSIT
        order["shipped_at"] = ts
        order["posted"] = True
        order["history"].append({"status": STATUS_IN_TRANSIT, "at": ts, "operator": operator["name"], "note": "出库发运：源仓已扣、目标仓已加，等待目的仓验收"})
        return self.get_transfer(int(order["id"]))  # type: ignore[return-value]

    def _do_receive(self, order: dict[str, Any], operator_id: str | None) -> dict[str, Any]:
        operator = self._require_keeper_of(operator_id, order["target_code"])
        if not order.get("posted"):
            # 理论上状态机已挡住（没到在途），这里再兜底一次
            raise ServiceError("该调拨单尚未出库过账，不能验收入库", code="state")
        ts = now_str()

        # 库存已在出库过账时作为同一笔账落到目标仓，验收只确认"货到齐、账实一致"，不再改动结存。
        order["status"] = STATUS_RECEIVED
        order["received_at"] = ts
        order["history"].append({"status": STATUS_RECEIVED, "at": ts, "operator": operator["name"], "note": "目的仓验收入库：数量无误，账实一致"})
        return self.get_transfer(int(order["id"]))  # type: ignore[return-value]

    def _do_reject(self, order: dict[str, Any], operator_id: str | None, reason: str) -> dict[str, Any]:
        operator = self._require_keeper_of(operator_id, order["target_code"])
        if not reason:
            raise ServiceError("拒收必须填写拒收原因，随单据退回源仓", code="bad_request")
        ts = now_str()
        order["status"] = STATUS_REJECTED
        order["rejected_at"] = ts
        order["reject_reason"] = reason
        order["history"].append({"status": STATUS_REJECTED, "at": ts, "operator": operator["name"], "note": f"目的仓拒收：{reason}"})
        return self.get_transfer(int(order["id"]))  # type: ignore[return-value]

    def _do_return(self, order: dict[str, Any], operator_id: str | None) -> dict[str, Any]:
        # 退回入源仓：源仓保管员确认收货回库
        operator = self._require_keeper_of(operator_id, order["source_code"])

        # 幂等闸门：退回冲销只做一次。已经冲过的出库不许被重复冲掉。
        if order.get("return_posted"):
            raise ServiceError(
                f"调拨单 {order['voucher_no']} 已完成退回过账，库存已恢复到出库前，"
                "重复退回不会再次冲销。",
                code="already_posted",
            )
        if not order.get("posted"):
            raise ServiceError("该调拨单未发生出库，无需退回", code="state")

        ts = now_str()
        qty = int(order["qty"])
        source_row = spare_store.ensure_balance_row(order["source_code"], order["part_code"])
        target_row = spare_store.ensure_balance_row(order["target_code"], order["part_code"])
        pair = f"TR-{order['id']}-RET"

        # 先校验再写流水：目标仓出库后若又发生过领用导致不足，不能扣成负数，拦下并提示先平账。
        # 校验不通过时不追加任何流水、不消耗流水号，整笔退回保持原子。
        if int(target_row["on_hand"]) < qty:
            raise ServiceError(
                f"退回过账被拦下：{spare_store.warehouse(order['target_code'])['name']}的"
                f"{order['part_name']}当前结存 {target_row['on_hand']}{order['unit']}，"
                f"不足退回 {qty}{order['unit']}（出库后该仓可能已有领用），请先盘点平账",
                code="insufficient",
            )

        # 两条配对冲销流水：目标仓退出此前随货入账、源仓收回。两边恢复到出库前的数。
        tgt_mvid = spare_store.next_id("movement")
        spare_store.movements.append({
            "id": tgt_mvid,
            "voucher_type": "调拨退回",
            "voucher_no": order["voucher_no"],
            "transfer_id": int(order["id"]),
            "warehouse_code": order["target_code"],
            "part_code": order["part_code"],
            "part_name": order["part_name"],
            "part_model": order["part_model"],
            "unit": order["unit"],
            "qty": qty,
            "direction": "out",
            "reason": "拒收退回（目标仓退出此前随货入账）",
            "operator": operator["name"],
            "created_at": ts,
            "pair_key": pair,
            "posted": True,
        })
        src_mvid = spare_store.next_id("movement")
        spare_store.movements.append({
            "id": src_mvid,
            "voucher_type": "调拨退回",
            "voucher_no": order["voucher_no"],
            "transfer_id": int(order["id"]),
            "warehouse_code": order["source_code"],
            "part_code": order["part_code"],
            "part_name": order["part_name"],
            "part_model": order["part_model"],
            "unit": order["unit"],
            "qty": qty,
            "direction": "in",
            "reason": "拒收退回入源仓（冲销此前出库，恢复到出库前结存）",
            "operator": operator["name"],
            "created_at": ts,
            "pair_key": pair,
            "posted": True,
        })
        target_row["on_hand"] = int(target_row["on_hand"]) - qty
        source_row["on_hand"] = int(source_row["on_hand"]) + qty

        order["status"] = STATUS_RETURNED
        order["returned_at"] = ts
        order["return_posted"] = True
        order["history"].append({"status": STATUS_RETURNED, "at": ts, "operator": operator["name"], "note": "退回入源仓：已冲销出库，结存恢复到出库前"})
        return self.get_transfer(int(order["id"]))  # type: ignore[return-value]


spare_service = SpareService()
