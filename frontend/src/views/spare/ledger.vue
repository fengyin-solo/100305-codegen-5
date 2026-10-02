<template>
  <section class="page" data-module="spare-ledger">
    <header class="page-head">
      <div>
        <h2>备品备件台账</h2>
        <p class="page-desc">
          每个仓库按备件型号登记结存；领用出库与调拨分开记。结存低于安全库存自动落入
          <RouterLink to="/spare/restock" class="inline-link">待补货清单</RouterLink>，两处读的是同一份账。
        </p>
      </div>
      <div class="page-actions">
        <KeeperSwitch />
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">在册结存行</span>
        <strong class="stat-value">{{ balances.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">低于安全库存</span>
        <strong class="stat-value stat-danger">{{ lowCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">临近过保（≤2026-12-31）</span>
        <strong class="stat-value stat-warn">{{ nearWarrantyCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">当前身份仓</span>
        <strong class="stat-value stat-warehouse">{{ session.warehouseName }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>仓库</span>
        <select v-model="filters.warehouse">
          <option value="">全部仓库</option>
          <option v-for="wh in warehouses" :key="wh.code" :value="wh.code">{{ wh.name }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>备件型号/名称</span>
        <input v-model="filters.keyword" placeholder="按编码/名称/型号检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
      <span class="filter-spacer"></span>
      <button class="btn primary" type="button" @click="openAdjust">登记/盘点结存</button>
      <button class="btn" type="button" @click="openConsume">领用出库</button>
    </form>

    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>仓库</th>
            <th>备件编码</th>
            <th>备件名称</th>
            <th>型号</th>
            <th>结存</th>
            <th>单位</th>
            <th>安全库存</th>
            <th>保修期至</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in balances" :key="row.warehouse_code + row.part_code"
              :class="{ 'row-danger': row.below_safety, 'row-warn': row.near_warranty && !row.below_safety }">
            <td>{{ row.warehouse_name }}</td>
            <td>{{ row.part_code }}</td>
            <td>{{ row.part_name }}</td>
            <td>{{ row.part_model }}</td>
            <td><strong>{{ row.on_hand }}</strong></td>
            <td>{{ row.unit }}</td>
            <td>{{ row.safety_stock }}</td>
            <td>
              {{ row.warranty_until ?? '—' }}
              <span v-if="row.near_warranty" class="tag tag-warn">临期</span>
            </td>
            <td>
              <span v-if="row.below_safety" class="tag tag-danger">待补货 · 缺 {{ row.gap_to_safety }}</span>
              <span v-else class="tag tag-ok">正常</span>
            </td>
          </tr>
          <tr v-if="!balances.length">
            <td colspan="9" class="empty-state">暂无符合条件的结存记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="sub-head">
      <h3>台账流水（领用与调拨分开记）</h3>
      <div class="seg">
        <button
          v-for="opt in movementTypes"
          :key="opt.value"
          type="button"
          :class="['seg-btn', { active: movementType === opt.value }]"
          @click="movementType = opt.value; loadMovements()"
        >{{ opt.label }}</button>
      </div>
    </div>
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>流水号</th>
            <th>单据类型</th>
            <th>单据号</th>
            <th>仓库</th>
            <th>备件</th>
            <th>方向</th>
            <th>数量</th>
            <th>说明</th>
            <th>经手人</th>
            <th>时间</th>
            <th>配对键</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in movements" :key="m.id">
            <td>{{ m.id }}</td>
            <td><span class="tag" :class="voucherTagClass(m.voucher_type)">{{ m.voucher_type }}</span></td>
            <td>{{ m.voucher_no }}</td>
            <td>{{ m.warehouse_name }}</td>
            <td>{{ m.part_name }}（{{ m.part_model }}）</td>
            <td :class="m.direction === 'in' ? 'dir-in' : 'dir-out'">
              {{ m.direction === 'in' ? '入 +' : '出 −' }}
            </td>
            <td>{{ m.qty }}{{ m.unit }}</td>
            <td>{{ m.reason }}</td>
            <td>{{ m.operator }}</td>
            <td>{{ m.created_at }}</td>
            <td class="pair-key">{{ m.pair_key }}</td>
          </tr>
          <tr v-if="!movements.length">
            <td colspan="11" class="empty-state">暂无流水</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 领用出库 -->
    <div v-if="consumeOpen" class="modal-mask" @click.self="consumeOpen = false">
      <div class="modal">
        <h3>领用出库（{{ session.warehouseName }}）</h3>
        <p class="modal-hint">只有本仓保管员能操作本仓；库存不足会被当场拦下。</p>
        <label class="form-item">
          <span>备件</span>
          <select v-model="consumeForm.part_code">
            <option value="" disabled>请选择备件型号</option>
            <option v-for="p in ownParts" :key="p.part_code" :value="p.part_code">
              {{ p.part_name }}（{{ p.part_model }}）· 结存 {{ p.on_hand }}{{ p.unit }}
            </option>
          </select>
        </label>
        <label class="form-item">
          <span>数量</span>
          <input v-model.number="consumeForm.qty" type="number" min="1" />
        </label>
        <label class="form-item">
          <span>领用事由</span>
          <input v-model="consumeForm.reason" placeholder="如：某站故障抢修领用" />
        </label>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="consumeOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitConsume">确认出库</button>
        </div>
      </div>
    </div>

    <!-- 登记/盘点结存 -->
    <div v-if="adjustOpen" class="modal-mask" @click.self="adjustOpen = false">
      <div class="modal">
        <h3>登记/盘点结存（{{ session.warehouseName }}）</h3>
        <p class="modal-hint">直接改数仅限本仓结存；跨仓改数会被当场驳回并说明缺哪项授权。调拨请走调拨单。</p>
        <label class="form-item">
          <span>备件</span>
          <select v-model="adjustForm.part_code">
            <option value="" disabled>请选择备件型号</option>
            <option v-for="p in partCatalog" :key="p.code" :value="p.code">
              {{ p.name }}（{{ p.model }}）
            </option>
          </select>
        </label>
        <label class="form-item">
          <span>盘点后结存</span>
          <input v-model.number="adjustForm.on_hand" type="number" min="0" />
        </label>
        <label class="form-item">
          <span>备注</span>
          <input v-model="adjustForm.reason" placeholder="如：季度盘点 / 新到一批登记" />
        </label>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="adjustOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAdjust">保存结存</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  spareApi,
  type BalanceRow,
  type MetaResponse,
  type MovementRow,
} from '@/api/spare'
import { useSpareSession } from '@/stores/spareSession'
import KeeperSwitch from './components/KeeperSwitch.vue'

const session = useSpareSession()

const warehouses = ref<MetaResponse['warehouses']>([])
const partCatalog = ref<MetaResponse['parts']>([])
const balances = ref<BalanceRow[]>([])
const movements = ref<MovementRow[]>([])
const filters = reactive<{ warehouse: string; keyword: string }>({ warehouse: '', keyword: '' })
const movementType = ref('')
const submitting = ref(false)
const formError = ref('')

const movementTypes = [
  { value: '', label: '全部流水' },
  { value: '领用出库', label: '领用出库' },
  { value: '调拨出库', label: '调拨出库' },
  { value: '调拨入库', label: '调拨入库' },
  { value: '调拨退回', label: '调拨退回' },
  { value: '盘点调整', label: '盘点调整' },
]

const consumeOpen = ref(false)
const adjustOpen = ref(false)
const consumeForm = reactive({ part_code: '', qty: 1, reason: '' })
const adjustForm = reactive({ part_code: '', on_hand: 0, reason: '' })

const lowCount = computed(() => balances.value.filter((row) => row.below_safety).length)
const nearWarrantyCount = computed(() => balances.value.filter((row) => row.near_warranty).length)
const ownParts = computed(() =>
  balances.value.filter((row) => row.warehouse_code === session.warehouseCode),
)

function voucherTagClass(type: string): Record<string, boolean> {
  return {
    'tag-out': type.includes('出库'),
    'tag-in': type.includes('入库'),
    'tag-return': type.includes('退回'),
    'tag-adjust': type.includes('盘点'),
  }
}

function resetFilters() {
  filters.warehouse = ''
  filters.keyword = ''
  void reload()
}

async function reload() {
  const [balanceRes] = await Promise.all([
    spareApi.balances({ warehouse: filters.warehouse, keyword: filters.keyword }),
    loadMovements(),
  ])
  balances.value = balanceRes.items
}

async function loadMovements() {
  const res = await spareApi.movements({
    warehouse: filters.warehouse,
    voucher_type: movementType.value || undefined,
  })
  movements.value = res.items
}

function openConsume() {
  formError.value = ''
  consumeForm.part_code = ''
  consumeForm.qty = 1
  consumeForm.reason = ''
  consumeOpen.value = true
}

function openAdjust() {
  formError.value = ''
  adjustForm.part_code = ''
  adjustForm.on_hand = 0
  adjustForm.reason = ''
  adjustOpen.value = true
}

async function submitConsume() {
  formError.value = ''
  if (!consumeForm.part_code) {
    formError.value = '请选择备件型号'
    return
  }
  if (!consumeForm.qty || consumeForm.qty <= 0) {
    formError.value = '领用数量必须是正整数'
    return
  }
  submitting.value = true
  try {
    const res = await spareApi.createOutbound({
      warehouse_code: session.warehouseCode,
      part_code: consumeForm.part_code,
      qty: consumeForm.qty,
      reason: consumeForm.reason || '日常维修领用',
    })
    window.alert(res.message || '领用出库已过账')
    consumeOpen.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '领用出库失败'
  } finally {
    submitting.value = false
  }
}

async function submitAdjust() {
  formError.value = ''
  if (!adjustForm.part_code) {
    formError.value = '请选择备件型号'
    return
  }
  submitting.value = true
  try {
    const res = await spareApi.adjustBalance({
      warehouse_code: session.warehouseCode,
      part_code: adjustForm.part_code,
      on_hand: adjustForm.on_hand,
      reason: adjustForm.reason,
    })
    window.alert(res.message || '结存已登记')
    adjustOpen.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '结存登记失败'
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  const meta = await spareApi.meta()
  warehouses.value = meta.warehouses
  partCatalog.value = meta.parts
  await reload()
})
</script>
