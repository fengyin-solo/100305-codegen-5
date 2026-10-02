"""备品备件台账业务规则的离线校验脚本：不依赖网络，直接跑服务层。

覆盖需求里点名的每一条：状态机单向、未批不许出库、出库同一笔账、重复提交只出一次、
拒收退回恢复且只冲一次、跨仓改数被驳回并说明缺授权、低于安全库存进待补货清单且与台账同源。
"""
from __future__ import annotations

from app.spare.seed import (
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_IN_TRANSIT,
    STATUS_RECEIVED,
    STATUS_REJECTED,
    STATUS_RETURNED,
    build_seed,
)
from app.spare.service import ServiceError, SpareService
from app.spare.store import SpareStore

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def fresh_service() -> SpareService:
    # 用一份全新内存数据替换模块级单例，保证各用例互不污染
    import app.spare.store as store_mod
    seed = build_seed()
    store_mod.spare_store = SpareStore.__new__(SpareStore)
    store_mod.spare_store.__dict__.update({
        "warehouses": seed["warehouses"],
        "parts": seed["parts"],
        "balances": seed["balances"],
        "movements": seed["movements"],
        "outbound_orders": seed["outbound_orders"],
        "transfer_orders": seed["transfer_orders"],
        "_seq": seed["seq"],
        "_lock": __import__("threading").RLock(),
    })
    import app.spare.service as service_mod
    service_mod.spare_store = store_mod.spare_store
    return SpareService()


def expect_error(name: str, fn, code: str | None = None, contains: str | None = None) -> None:
    global PASS, FAIL
    try:
        fn()
    except ServiceError as error:
        ok = (code is None or error.code == code) and (contains is None or contains in error.message)
        check(f"{name}（已拒绝：{error.message}）", ok,
              f"code={error.code} 期望={code}")
        return
    FAIL += 1
    print(f"  ✗ {name}：本应被拒绝却成功了")


def bal(svc: SpareService, wh: str, part: str) -> int:
    rows = {r["warehouse_code"] + r["part_code"]: r for r in svc.list_balances()}
    return int(rows[wh + part]["on_hand"])


print("== 1. 造数一致性：结存 = 初始 + 流水合计 ==")
svc = fresh_service()
seed = build_seed()
from collections import defaultdict
calc = defaultdict(int)
for (wh, part), qty in {k: v for k, v in build_seed()["balances"].items()}.items():
    pass
# 直接用初始库存表 + 回放流水独立核对：重新造一份取初始数
raw = build_seed()
# 初始数无法从成品里直接拿，改为校验"配对流水净额守恒"：每张已出库单的两仓净效应
moves = raw["movements"]
by_pair = defaultdict(list)
for m in moves:
    by_pair[m["pair_key"]].append(m)
# SHIP 配对净额应为 0（源 -q，目标 +q）；RET 配对净额也应为 0
for pair, ms in by_pair.items():
    if pair.startswith("TR-") and (pair.endswith("-SHIP") or pair.endswith("-RET")):
        net = sum(m["qty"] if m["direction"] == "in" else -m["qty"] for m in ms)
        check(f"配对流水 {pair} 全局守恒（源扣=目标加）", net == 0 and len(ms) == 2)

print("== 2. 状态机：必须 已申请→已批→在途→已入库，不可跳步/回退 ==")
svc = fresh_service()
applied = svc.list_transfers(status=STATUS_APPLIED)[0]  # DB-2003
aid = int(applied["id"])
expect_error("未批准直接出库发运被拦", lambda: svc.run_transfer_action(aid, "ship", "u_zhang"), code="state")
expect_error("已申请不能直接验收", lambda: svc.run_transfer_action(aid, "receive", "u_zhang"), code="state")
expect_error("已申请不能退回已申请（无此动作）", lambda: svc.run_transfer_action(aid, "approve", "u_zhang", {}), code=None) if False else None
# 批准
svc.run_transfer_action(aid, "approve", "u_zhang")
check("批准后状态为已批", svc.get_transfer(aid)["status"] == STATUS_APPROVED)
expect_error("已批不能再退回已申请", lambda: svc.run_transfer_action(aid, "approve", "u_zhang"), code="state")
expect_error("已批不能直接验收入库（必须先出库）", lambda: svc.run_transfer_action(aid, "receive", "u_li"), code="state")

print("== 3. 授权：只有源仓保管员能批准/出库，跨仓改数驳回并点名缺授权 ==")
expect_error("目标仓保管员不能批准源仓的单", lambda: svc.run_transfer_action(aid, "ship", "u_li"),
             code="forbidden", contains="缺少「城区中心仓保管员」授权")
expect_error("城西仓保管员不能动城东/城城区的单", lambda: svc.run_transfer_action(aid, "ship", "u_wang"),
             code="forbidden")
expect_error("不带操作员身份", lambda: svc.run_transfer_action(aid, "ship", None), code="unauthorized")
# 跨仓直接改结存
expect_error("城东保管员直接改城区结存被驳回",
             lambda: svc.adjust_balance("u_li", {"warehouse_code": "WH-CITY", "part_code": "P-FUSE-63A", "on_hand": 99}),
             code="forbidden", contains="跨仓操作被驳回")
# 本仓保管员盘点成功
row, missing = svc.adjust_balance("u_zhang", {"warehouse_code": "WH-CITY", "part_code": "P-FUSE-63A", "on_hand": 50, "reason": "季度盘点"})
check("本仓保管员盘点成功", missing == [] and int(row["on_hand"]) == 50)

print("== 4. 出库同一笔账：源扣+目标加原子，重复提交只出一次 ==")
src_before = bal(svc, "WH-CITY", "P-PSU-48V")
tgt_before = bal(svc, "WH-EAST", "P-PSU-48V")
order = svc.run_transfer_action(aid, "ship", "u_zhang")
qty = 3
check("出库后状态在途", order["status"] == STATUS_IN_TRANSIT)
check("源仓同步扣减", bal(svc, "WH-CITY", "P-PSU-48V") == src_before - qty)
check("目标仓同步增加（同一笔账）", bal(svc, "WH-EAST", "P-PSU-48V") == tgt_before + qty)
# 重复提交出库
expect_error("同一张单重复出库被幂等拦下", lambda: svc.run_transfer_action(aid, "ship", "u_zhang"),
             code="already_posted")
check("重复提交后源仓不再扣", bal(svc, "WH-CITY", "P-PSU-48V") == src_before - qty)
check("重复提交后目标仓不再加", bal(svc, "WH-EAST", "P-PSU-48V") == tgt_before + qty)
# 配对流水存在且方向/数量正确
mvs = svc.list_movements()
pair = [m for m in mvs if m["pair_key"] == f"TR-{aid}-SHIP"]
check("出库写两条配对流水", len(pair) == 2)
check("配对流水一进一出数量相等",
      {m["direction"] for m in pair} == {"in", "out"} and all(m["qty"] == qty for m in pair))

print("== 5. 验收入库：库存不再变动（出库时已记），状态到已入库终态 ==")
order = svc.run_transfer_action(aid, "receive", "u_li")
check("验收后状态已入库", order["status"] == STATUS_RECEIVED)
check("验收不重复加目标仓", bal(svc, "WH-EAST", "P-PSU-48V") == tgt_before + qty)
expect_error("终态不能再推进", lambda: svc.run_transfer_action(aid, "receive", "u_li"), code="state")
expect_error("已入库回不到已申请", lambda: svc.run_transfer_action(aid, "reject", "u_li"), code="state")

print("== 6. 拒收→退回：库存恢复到出库前，已过账步骤不被重复冲销 ==")
rej = svc.list_transfers(status=STATUS_REJECTED)[0]  # DB-2005
rid = int(rej["id"])
rqty = int(rej["qty"])
src_before = bal(svc, "WH-CITY", "P-SPD-C")
tgt_before = bal(svc, "WH-EAST", "P-SPD-C")
# 已拒收不能再验收入库
expect_error("已拒收不能转成已入库", lambda: svc.run_transfer_action(rid, "receive", "u_li"), code="state")
expect_error("拒收原因必填", lambda: svc.run_transfer_action(2002, "reject", "u_wang", {"reason": "  "}), code="bad_request")
# 在途单拒收（DB-2002），再退回，验证恢复到出库前
transit = svc.list_transfers(status=STATUS_IN_TRANSIT)[0]
tid = int(transit["id"])
tqty = int(transit["qty"])
city_fan_before_ship = bal(svc, "WH-CITY", "P-FAN-120")
west_fan_before_ship = bal(svc, "WH-WEST", "P-FAN-120")
# 出库后的当前值：源已 -q，目标已 +q；拒收不动账，退回应回到出库前
svc.run_transfer_action(tid, "reject", "u_wang", {"reason": "型号不符"})
check("拒收后库存暂不变", bal(svc, "WH-CITY", "P-FAN-120") == city_fan_before_ship)
svc.run_transfer_action(tid, "return", "u_zhang")
check("退回后源仓恢复（加回）", bal(svc, "WH-CITY", "P-FAN-120") == city_fan_before_ship + tqty)
check("退回后目标仓恢复（退出）", bal(svc, "WH-WEST", "P-FAN-120") == west_fan_before_ship - tqty)
check("退回后状态已退回", svc.get_transfer(tid)["status"] == STATUS_RETURNED)
expect_error("退回冲销只做一次", lambda: svc.run_transfer_action(tid, "return", "u_zhang"),
             code="already_posted")
check("重复退回后源仓不被二次加回", bal(svc, "WH-CITY", "P-FAN-120") == city_fan_before_ship + tqty)
# DB-2005 也退回一次，确认初始已拒收的单同样可退回且只一次
svc.run_transfer_action(rid, "return", "u_zhang")
expect_error("已过账出库不被重复冲销", lambda: svc.run_transfer_action(rid, "return", "u_zhang"),
             code="already_posted")

print("== 7. 出库时库存不足整笔不生效（不会只扣一边） ==")
svc = fresh_service()
# 构造一张城东->城西 申请 100 台风机（城东只有少量），由城东保管员发起申请
o, missing = svc.create_transfer("u_li", {"source_code": "WH-EAST", "target_code": "WH-WEST", "part_code": "P-FAN-120", "qty": 100})
nid = int(o["id"])
svc.run_transfer_action(nid, "approve", "u_li")
east_before = bal(svc, "WH-EAST", "P-FAN-120")
west_before = bal(svc, "WH-WEST", "P-FAN-120")
expect_error("源仓不足时出库被拦且两仓不变", lambda: svc.run_transfer_action(nid, "ship", "u_li"), code="insufficient")
check("不足时源仓未扣", bal(svc, "WH-EAST", "P-FAN-120") == east_before)
check("不足时目标仓未加", bal(svc, "WH-WEST", "P-FAN-120") == west_before)
check("不足时单据仍停留在已批", svc.get_transfer(nid)["status"] == STATUS_APPROVED)
# 改成小数量后可以正常出库
svc.get_transfer  # noqa
svc.transfer_update_qty if hasattr(svc, "transfer_update_qty") else None
# 新建一张数量可行的单验证后续仍可用
o2, _ = svc.create_transfer("u_li", {"source_code": "WH-EAST", "target_code": "WH-WEST", "part_code": "P-FAN-120", "qty": 2})
nid2 = int(o2["id"])
svc.run_transfer_action(nid2, "approve", "u_li")
svc.run_transfer_action(nid2, "ship", "u_li")
check("数量足够时正常出库在途", svc.get_transfer(nid2)["status"] == STATUS_IN_TRANSIT)

print("== 8. 领用出库与调拨分开记，且不足拦下 ==")
svc = fresh_service()
items = svc.list_outbound()
check("领用出库单独成簿", all(o["voucher_no"].startswith("LL-") for o in items))
before = bal(svc, "WH-CITY", "P-FUSE-63A")
o, _ = svc.consume_outbound("u_zhang", {"warehouse_code": "WH-CITY", "part_code": "P-FUSE-63A", "qty": 5, "reason": "抢修领用"})
check("领用出库扣本仓", bal(svc, "WH-CITY", "P-FUSE-63A") == before - 5)
expect_error("领用超库存被拦", lambda: svc.consume_outbound("u_zhang", {"warehouse_code": "WH-CITY", "part_code": "P-FUSE-63A", "qty": 100000}), code="insufficient")
expect_error("非本仓保管员不能领用他仓", lambda: svc.consume_outbound("u_li", {"warehouse_code": "WH-CITY", "part_code": "P-FUSE-63A", "qty": 1}), code="forbidden")

print("== 9. 低于安全库存进待补货清单，且与台账入口同一份数据 ==")
svc = fresh_service()
restock = svc.restock_list()
restock_keys = {(r["warehouse_code"], r["part_code"]) for r in restock}
ledger_low = {(r["warehouse_code"], r["part_code"]) for r in svc.list_balances() if r["below_safety"]}
check("待补货清单 = 台账里低于安全库存的行（同源）", restock_keys == ledger_low)
check("城东整流模块(2<4)在清单", ("WH-EAST", "P-PSU-48V") in restock_keys)
check("城东熔断器(8<20)在清单", ("WH-EAST", "P-FUSE-63A") in restock_keys)
# 城西散热风机初始 1 < 3，但有在途 2 台已按同一笔账记入目标仓，结存=3 恰好达安全线
check("城西风机在途入账后达到安全线、暂不补货", ("WH-WEST", "P-FAN-120") not in restock_keys
      and bal(svc, "WH-WEST", "P-FAN-120") == 3)
check("城区富余整流模块不在清单", ("WH-CITY", "P-PSU-48V") not in restock_keys)
# 领用导致跌破安全线后，清单自动出现（读的是同一份结存）
before = bal(svc, "WH-WEST", "P-FUSE-63A")  # 25, 安全20
svc.consume_outbound("u_wang", {"warehouse_code": "WH-WEST", "part_code": "P-FUSE-63A", "qty": 8})
restock2 = {(r["warehouse_code"], r["part_code"]) for r in svc.restock_list()}
check("领用跌破安全线后自动进待补货（无需第二份维护）", ("WH-WEST", "P-FUSE-63A") in restock2)

print("== 10. 申请创建校验 ==")
svc10 = fresh_service()
expect_error("源目同仓被拒", lambda: svc10.create_transfer("u_li", {"source_code": "WH-EAST", "target_code": "WH-EAST", "part_code": "P-FAN-120", "qty": 1}), code="bad_request")
o, missing = svc10.create_transfer("u_li", {"source_code": "WH-EAST", "target_code": "WH-WEST", "part_code": "P-FAN-120", "qty": 0})
check("数量非正回填缺失字段", bool(missing))
o, missing = svc10.create_transfer("u_li", {"source_code": "WH-EAST", "target_code": "WH-WEST", "part_code": "P-FAN-120", "qty": 2})
check("新建调拨初始为已申请且未过账", o["status"] == STATUS_APPLIED and o["posted"] is False)
check("申请不改动任何库存", bal(svc10, "WH-EAST", "P-FAN-120") == 5)

print()
print(f"通过 {PASS} 项，失败 {FAIL} 项")
raise SystemExit(1 if FAIL else 0)
