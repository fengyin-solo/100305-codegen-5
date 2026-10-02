import { defineStore } from 'pinia'

export interface WarehouseKeeper {
  code: string
  name: string
  keeperId: string
  keeperName: string
}

/**
 * 备品备件模块的当前保管员会话。
 * 后端按 X-Operator-Id 判断"是不是本仓保管员"，所以这里切换身份后，所有备件接口都带上。
 */
export const useSpareSession = defineStore('spare-session', {
  state: () => ({
    // 默认用城区中心仓保管员进入，方便直接演示批准/出库；可在右上角切换
    operatorId: 'u_zhang',
    operatorName: '张保管',
    warehouseCode: 'WH-CITY',
    warehouseName: '城区中心仓',
    warehouses: [] as WarehouseKeeper[],
  }),
  getters: {
    isAuthed: (state) => state.operatorId.length > 0,
  },
  actions: {
    setWarehouses(list: WarehouseKeeper[]) {
      this.warehouses = list
    },
    switchTo(keeperId: string) {
      const wh = this.warehouses.find((item) => item.keeperId === keeperId)
      if (!wh) return
      this.operatorId = wh.keeperId
      this.operatorName = wh.keeperName
      this.warehouseCode = wh.code
      this.warehouseName = wh.name
    },
  },
})
