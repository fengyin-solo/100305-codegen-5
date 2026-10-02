"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。"""

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class TransferCreatePayload(BaseModel):
    """申请一张调拨单；调拨单号可由调用方给出，重复提交按原单返回。"""

    调拨单号: str | None = None
    源仓库: str
    目标仓库: str
    备件型号: str
    数量: int = Field(gt=0)
    申请人: str | None = None
    备注: str | None = None


class OperatorPayload(BaseModel):
    """调拨单流转动作：只带操作员与备注，状态往哪走由单据当前状态决定。"""

    operator: str = ""
    remark: str | None = None


class IssueCreatePayload(BaseModel):
    """登记一张出库单（领用出库，与调拨分开记账）。"""

    仓库: str
    备件型号: str
    数量: int = Field(gt=0)
    operator: str = ""
    领用人: str | None = None
    备注: str | None = None


class BalanceAdjustPayload(BaseModel):
    """直接调整某仓某型号的结存：只有本仓保管员能过这关。"""

    仓库: str
    备件型号: str
    调整后结存: int = Field(ge=0)
    安全库存: int | None = Field(default=None, ge=0)
    operator: str = ""
    备注: str | None = None



class SiteEntry(BaseModel):
    """基站明细结构。"""

    field_0: str | None = None  # 基站编号
    field_1: str | None = None  # 基站名称
    field_2: str | None = None  # 基站类型
    field_3: str | None = None  # 所属区县
    field_4: str | None = None  # 经纬度坐标
    field_5: str | None = None  # 铁塔高度
    field_6: str | None = None  # 入网日期
    field_7: str | None = None  # 基站状态

class TowerEntry(BaseModel):
    """铁塔明细结构。"""

    field_0: str | None = None  # 铁塔编号
    field_1: str | None = None  # 铁塔类型
    field_2: str | None = None  # 设计高度
    field_3: str | None = None  # 平台数量
    field_4: str | None = None  # 所属站点
    field_5: str | None = None  # 建成年份
    field_6: str | None = None  # 上次检测
    field_7: str | None = None  # 铁塔状态

class PowerEntry(BaseModel):
    """电源设备明细结构。"""

    field_0: str | None = None  # 设备编号
    field_1: str | None = None  # 设备类型
    field_2: str | None = None  # 额定功率
    field_3: str | None = None  # 所属站点
    field_4: str | None = None  # 投用日期
    field_5: str | None = None  # 上次检修
    field_6: str | None = None  # 下次检修日
    field_7: str | None = None  # 设备状态

class BatteryEntry(BaseModel):
    """蓄电池组明细结构。"""

    field_0: str | None = None  # 电池组编号
    field_1: str | None = None  # 电池类型
    field_2: str | None = None  # 额定容量
    field_3: str | None = None  # 所属站点
    field_4: str | None = None  # 放电时长
    field_5: str | None = None  # 内阻值
    field_6: str | None = None  # 投用日期
    field_7: str | None = None  # 电池状态

class GensetEntry(BaseModel):
    """发电机组明细结构。"""

    field_0: str | None = None  # 机组编号
    field_1: str | None = None  # 机组型号
    field_2: str | None = None  # 额定功率
    field_3: str | None = None  # 所属站点
    field_4: str | None = None  # 上次试机
    field_5: str | None = None  # 油量储备
    field_6: str | None = None  # 启动状态
    field_7: str | None = None  # 机组状态

class RectifierEntry(BaseModel):
    """开关电源明细结构。"""

    field_0: str | None = None  # 电源编号
    field_1: str | None = None  # 额定功率
    field_2: str | None = None  # 所属站点
    field_3: str | None = None  # 整流模块数
    field_4: str | None = None  # 负载率
    field_5: str | None = None  # 输出电压
    field_6: str | None = None  # 模块故障
    field_7: str | None = None  # 电源状态

class AcEntry(BaseModel):
    """空调明细结构。"""

    field_0: str | None = None  # 空调编号
    field_1: str | None = None  # 空调类型
    field_2: str | None = None  # 制冷量
    field_3: str | None = None  # 所属站点
    field_4: str | None = None  # 运行电流
    field_5: str | None = None  # 设定温度
    field_6: str | None = None  # 回风温度
    field_7: str | None = None  # 空调状态

class AntennaEntry(BaseModel):
    """天馈设备明细结构。"""

    field_0: str | None = None  # 天馈编号
    field_1: str | None = None  # 天线类型
    field_2: str | None = None  # 工作频段
    field_3: str | None = None  # 所属站点
    field_4: str | None = None  # 挂高
    field_5: str | None = None  # 方位角
    field_6: str | None = None  # 驻波比
    field_7: str | None = None  # 天馈状态

class TransmissionEntry(BaseModel):
    """传输设备明细结构。"""

    field_0: str | None = None  # 设备编号
    field_1: str | None = None  # 传输类型
    field_2: str | None = None  # 带宽容量
    field_3: str | None = None  # 所属站点
    field_4: str | None = None  # 光口状态
    field_5: str | None = None  # 电口状态
    field_6: str | None = None  # 误码率
    field_7: str | None = None  # 设备状态

class FeederEntry(BaseModel):
    """馈线明细结构。"""

    field_0: str | None = None  # 馈线编号
    field_1: str | None = None  # 所属站点
    field_2: str | None = None  # 馈线长度
    field_3: str | None = None  # 接头数量
    field_4: str | None = None  # 防水情况
    field_5: str | None = None  # 接地电阻
    field_6: str | None = None  # 巡检日期
    field_7: str | None = None  # 馈线状态

class LightningprotEntry(BaseModel):
    """防雷装置明细结构。"""

    field_0: str | None = None  # 装置编号
    field_1: str | None = None  # 所属站点
    field_2: str | None = None  # 接地电阻
    field_3: str | None = None  # 防雷模块
    field_4: str | None = None  # 浪涌保护
    field_5: str | None = None  # 上次测试
    field_6: str | None = None  # 测试人员
    field_7: str | None = None  # 装置状态

class FirealarmEntry(BaseModel):
    """消防设施明细结构。"""

    field_0: str | None = None  # 设施编号
    field_1: str | None = None  # 设施类型
    field_2: str | None = None  # 所属站点
    field_3: str | None = None  # 灭火剂量
    field_4: str | None = None  # 上次检查
    field_5: str | None = None  # 有效期至
    field_6: str | None = None  # 检查人员
    field_7: str | None = None  # 设施状态

class DooraccessEntry(BaseModel):
    """门禁记录明细结构。"""

    field_0: str | None = None  # 门禁编号
    field_1: str | None = None  # 所属站点
    field_2: str | None = None  # 开门方式
    field_3: str | None = None  # 进出人员
    field_4: str | None = None  # 进出时间
    field_5: str | None = None  # 授权状态
    field_6: str | None = None  # 异常记录
    field_7: str | None = None  # 门禁状态

class PatrolEntry(BaseModel):
    """巡检任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 巡检站点
    field_2: str | None = None  # 巡检人员
    field_3: str | None = None  # 计划日期
    field_4: str | None = None  # 巡检路线
    field_5: str | None = None  # 发现问题
    field_6: str | None = None  # 处置措施
    field_7: str | None = None  # 任务状态

class FuelEntry(BaseModel):
    """油料记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 所属站点
    field_2: str | None = None  # 油料类型
    field_3: str | None = None  # 调入量
    field_4: str | None = None  # 当前存量
    field_5: str | None = None  # 发电消耗
    field_6: str | None = None  # 油料日期
    field_7: str | None = None  # 油料状态

class RentalEntry(BaseModel):
    """场租合同明细结构。"""

    field_0: str | None = None  # 合同编号
    field_1: str | None = None  # 站点名称
    field_2: str | None = None  # 出租方
    field_3: str | None = None  # 年租金
    field_4: str | None = None  # 签约日期
    field_5: str | None = None  # 到期日期
    field_6: str | None = None  # 续租条款
    field_7: str | None = None  # 合同状态

class ElectricbillEntry(BaseModel):
    """电费记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 所属站点
    field_2: str | None = None  # 电表读数
    field_3: str | None = None  # 用电量
    field_4: str | None = None  # 电费金额
    field_5: str | None = None  # 缴费月份
    field_6: str | None = None  # 缴费状态
    field_7: str | None = None  # 票据编号

class DemolitionEntry(BaseModel):
    """拆站任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 拆除站点
    field_2: str | None = None  # 拆除原因
    field_3: str | None = None  # 拆除范围
    field_4: str | None = None  # 施工队伍
    field_5: str | None = None  # 计划工期
    field_6: str | None = None  # 物资回收
    field_7: str | None = None  # 任务状态

class EmergencyEntry(BaseModel):
    """应急保障明细结构。"""

    field_0: str | None = None  # 保障编号
    field_1: str | None = None  # 保障类型
    field_2: str | None = None  # 保障地点
    field_3: str | None = None  # 通信车编号
    field_4: str | None = None  # 保障人员
    field_5: str | None = None  # 到达时间
    field_6: str | None = None  # 撤离时间
    field_7: str | None = None  # 保障状态

class EnergyeffEntry(BaseModel):
    """节能项目明细结构。"""

    field_0: str | None = None  # 项目编号
    field_1: str | None = None  # 所属站点
    field_2: str | None = None  # 改造内容
    field_3: str | None = None  # 预估节电率
    field_4: str | None = None  # 投资金额
    field_5: str | None = None  # 承包单位
    field_6: str | None = None  # 投资回收期
    field_7: str | None = None  # 项目状态
