"""备品备件台账的内存数据仓库。

和其它业务模块用的通用 ``app.store`` 不同，备件这一摊要做"同一笔账"的原子过账与
幂等控制，所以单独放一个带锁的仓库：所有结存变更都在 :meth:`SpareStore.run` 的临界区里
完成，避免"源仓已扣、目标仓没加"或重复冲销。

真实项目里这里会换成数据库事务（一个事务里写两条配对流水 + 更新两行结存）；当前实现用
一把进程内可重入锁表达同样的边界。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, TypeVar

from app.spare.seed import build_seed

T = TypeVar("T")


class SpareStore:
    def __init__(self) -> None:
        seed = build_seed()
        # 仓库档案：code -> 档案（含保管员）
        self.warehouses: dict[str, dict[str, Any]] = seed["warehouses"]
        # 备件型号目录
        self.parts: list[dict[str, Any]] = seed["parts"]
        # 结存：(仓库编码, 备件编码) -> 结存行
        self.balances: dict[tuple[str, str], dict[str, Any]] = seed["balances"]
        # 台账流水（领用出库与调拨出/入库都在这里，按发生顺序追加）
        self.movements: list[dict[str, Any]] = seed["movements"]
        # 领用出库单（和调拨分开记）
        self.outbound_orders: list[dict[str, Any]] = seed["outbound_orders"]
        # 调拨单
        self.transfer_orders: OrderedDict[int, dict[str, Any]] = seed["transfer_orders"]
        self._seq: dict[str, int] = seed["seq"]
        # 过账串行化：保证一张单的两条配对流水同时可见
        self._lock = threading.RLock()

    # ---- 基础工具 -------------------------------------------------
    def run(self, fn: Callable[[], T]) -> T:
        """在同一把锁里执行一段读写，保证"扣源仓 + 加目标仓"是一笔账。"""
        with self._lock:
            return fn()

    def next_id(self, kind: str) -> int:
        """生成领用出库单/调拨单/流水的自增号，调用方需已持有锁。"""
        self._seq[kind] = self._seq.get(kind, 0) + 1
        return self._seq[kind]

    def warehouse(self, code: str) -> dict[str, Any] | None:
        return self.warehouses.get(code)

    def part(self, code: str) -> dict[str, Any] | None:
        for part in self.parts:
            if part["code"] == code:
                return part
        return None

    def balance_row(self, warehouse_code: str, part_code: str) -> dict[str, Any] | None:
        return self.balances.get((warehouse_code, part_code))

    def ensure_balance_row(self, warehouse_code: str, part_code: str) -> dict[str, Any]:
        key = (warehouse_code, part_code)
        row = self.balances.get(key)
        if row is None:
            part = self.part(part_code)
            row = {
                "warehouse_code": warehouse_code,
                "part_code": part_code,
                "part_name": part["name"] if part else part_code,
                "part_model": part["model"] if part else "",
                "unit": part["unit"] if part else "",
                "safety_stock": part["safety_stock"] if part else 0,
                "warranty_until": part.get("warranty_until"),
                "on_hand": 0,
                # 运行期经调拨落到新仓的行，一旦发生就视为在册（不再是幻影行）
                "active": True,
            }
            self.balances[key] = row
        return row

    def find_transfer(self, order_id: int) -> dict[str, Any] | None:
        return self.transfer_orders.get(order_id)

    def find_outbound(self, order_id: int) -> dict[str, Any] | None:
        for order in self.outbound_orders:
            if int(order.get("id", 0)) == order_id:
                return order
        return None

    def snapshot_balances(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.balances.values()]

    def snapshot_movements(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.movements]


spare_store = SpareStore()
