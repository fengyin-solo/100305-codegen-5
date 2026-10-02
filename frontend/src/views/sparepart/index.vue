<template>
  <section class="page" data-module="sparepart">
    <header class="page-head">
      <div>
        <h2>备品备件台账</h2>
        <p class="page-desc">
          各仓按备件型号登记结存，出库与调拨分开记账；调拨单按 已申请 → 已批 → 在途 → 已入库 流转，没批的不许出库。
        </p>
      </div>
      <div class="page-actions">
        <label class="filter-item">
          <span>当前操作员（批出库 / 直接调整需本仓保管员）</span>
          <select v-model="operator">
            <option v-for="name in operatorOptions" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="panel">
      <h3>申请调拨</h3>
      <form class="filter-bar" @submit.prevent="createTransfer">
        <label class="filter-item">
          <span>源仓库</span>
          <select v-model="transferForm.源仓库">
            <option v-for="wh in warehouses" :key="wh.id" :value="wh.id">{{ wh.名称 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>目标仓库</span>
          <select v-model="transferForm.目标仓库">
            <option v-for="wh in warehouses" :key="wh.id" :value="wh.id">{{ wh.名称 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>备件型号</span>
          <select v-model="transferForm.备件型号">
            <option v-for="part in parts" :key="part.型号" :value="part.型号">
              {{ part.型号 }} · {{ part.名称 }}
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>数量</span>
          <input v-model.number="transferForm.数量" type="number" min="1" />
        </label>
        <button class="btn primary" type="submit">提交申请</button>
      </form>
    </section>

    <section class="panel">
      <h3>库存台账</h3>
      <form class="filter-bar" @submit.prevent="reloadBalances">
        <label class="filter-item">
          <span>仓库</span>
          <select v-model="balanceFilter.warehouse">
            <option value="">全部仓库</option>
            <option v-for="wh in warehouses" :key="wh.id" :value="wh.id">{{ wh.名称 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>备件型号 / 名称</span>
          <input v-model="balanceFilter.keyword" placeholder="按型号或名称检索" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetBalanceFilter">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>仓库</th><th>备件型号</th><th>备件名称</th><th>结存</th><th>安全库存</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in balances" :key="`${row.仓库}-${row.备件型号}`">
            <td>{{ row.仓库名称 }}</td>
            <td>{{ row.备件型号 }}</td>
            <td>{{ row.备件名称 }}</td>
            <td>{{ row.结存 }} {{ row.单位 }}</td>
            <td>{{ row.安全库存 }}</td>
            <td :class="{ 'low-stock': row.低于安全库存 }">
              {{ row.低于安全库存 ? '低于安全库存' : '正常' }}
            </td>
          </tr>
          <tr v-if="!balances.length">
            <td colspan="6" class="empty-state">暂无结存记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3>待补货清单（结存低于安全库存，与台账同一份数据）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>仓库</th><th>备件型号</th><th>备件名称</th><th>结存</th><th>安全库存</th><th>建议补货量</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in replenishment" :key="`${row.仓库}-${row.备件型号}`">
            <td>{{ row.仓库名称 }}</td>
            <td>{{ row.备件型号 }}</td>
            <td>{{ row.备件名称 }}</td>
            <td class="low-stock">{{ row.结存 }} {{ row.单位 }}</td>
            <td>{{ row.安全库存 }}</td>
            <td>{{ row.建议补货量 }}</td>
          </tr>
          <tr v-if="!replenishment.length">
            <td colspan="6" class="empty-state">各仓结存均在安全库存以上</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3>调拨单</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>调拨单号</th><th>源仓库</th><th>目标仓库</th><th>备件型号</th><th>数量</th>
            <th>状态</th><th>申请人</th><th>审批人</th><th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in transfers" :key="row.id">
            <td>{{ row.调拨单号 }}</td>
            <td>{{ row.源仓库名称 }}</td>
            <td>{{ row.目标仓库名称 }}</td>
            <td>{{ row.备件型号 }}</td>
            <td>{{ row.数量 }}</td>
            <td>{{ row.status }}</td>
            <td>{{ row.申请人 || '—' }}</td>
            <td>{{ row.审批人 || '—' }}</td>
            <td class="row-actions">
              <button v-if="row.status === '已申请'" class="link" type="button" @click="act(row, 'approve')">审批</button>
              <button v-if="row.status === '已批'" class="link" type="button" @click="act(row, 'ship')">出库</button>
              <template v-if="row.status === '在途'">
                <button class="link" type="button" @click="act(row, 'receive')">确认入库</button>
                <button class="link" type="button" @click="act(row, 'reject')">拒收退回</button>
              </template>
              <span v-if="['已入库', '已退回'].includes(row.status)">—</span>
            </td>
          </tr>
          <tr v-if="!transfers.length">
            <td colspan="9" class="empty-state">暂无调拨单，可先在上方提交申请</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3>出库登记（领用出库，与调拨分开记账）</h3>
      <form class="filter-bar" @submit.prevent="createIssue">
        <label class="filter-item">
          <span>仓库</span>
          <select v-model="issueForm.仓库">
            <option v-for="wh in warehouses" :key="wh.id" :value="wh.id">{{ wh.名称 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>备件型号</span>
          <select v-model="issueForm.备件型号">
            <option v-for="part in parts" :key="part.型号" :value="part.型号">
              {{ part.型号 }} · {{ part.名称 }}
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>数量</span>
          <input v-model.number="issueForm.数量" type="number" min="1" />
        </label>
        <label class="filter-item">
          <span>领用人</span>
          <input v-model="issueForm.领用人" placeholder="谁领的料" />
        </label>
        <button class="btn primary" type="submit">登记出库</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>出库单号</th><th>仓库</th><th>备件型号</th><th>数量</th><th>领用人</th><th>操作员</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in issues" :key="row.id">
            <td>{{ row.出库单号 }}</td>
            <td>{{ row.仓库名称 }}</td>
            <td>{{ row.备件型号 }}</td>
            <td>{{ row.数量 }}</td>
            <td>{{ row.领用人 || '—' }}</td>
            <td>{{ row.操作员 }}</td>
            <td>{{ row.时间 }}</td>
          </tr>
          <tr v-if="!issues.length">
            <td colspan="7" class="empty-state">暂无出库记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3>台账流水（调拨双边过账共用同一个流水号）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>流水号</th><th>类型</th><th>仓库</th><th>备件型号</th><th>变动</th><th>结存</th>
            <th>关联单号</th><th>操作员</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger" :key="row.id">
            <td>{{ row.流水号 }}</td>
            <td>{{ row.类型 }}</td>
            <td>{{ row.仓库名称 }}</td>
            <td>{{ row.备件型号 }}</td>
            <td>{{ row.变动 > 0 ? `+${row.变动}` : row.变动 }}</td>
            <td>{{ row.结存 }}</td>
            <td>{{ row.关联单号 }}</td>
            <td>{{ row.操作员 }}</td>
            <td>{{ row.时间 }}</td>
          </tr>
          <tr v-if="!ledger.length">
            <td colspan="9" class="empty-state">暂无流水</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>库存台账、待补货清单与流水读的是同一份结存</span>
      <span v-if="notice" class="notice-text">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, any>

const ENDPOINT = '/api/sparepart'
const session = useSessionStore()

const warehouses = ref<Row[]>([])
const parts = ref<Row[]>([])
const balances = ref<Row[]>([])
const replenishment = ref<Row[]>([])
const transfers = ref<Row[]>([])
const issues = ref<Row[]>([])
const ledger = ref<Row[]>([])
const operator = ref(session.operator)
const notice = ref('')
const errorMessage = ref('')

const balanceFilter = ref({ warehouse: '', keyword: '' })
const transferForm = ref({ 源仓库: 'WH-01', 目标仓库: 'WH-02', 备件型号: 'SP-RRU-01', 数量: 1 })
const issueForm = ref({ 仓库: 'WH-01', 备件型号: 'SP-RRU-01', 数量: 1, 领用人: '' })

const operatorOptions = computed(() => {
  const names = new Set<string>([session.operator])
  for (const wh of warehouses.value) {
    for (const keeper of wh.保管员 ?? []) names.add(keeper)
  }
  return [...names]
})

const stats = computed(() => [
  { label: '仓库数', value: warehouses.value.length },
  { label: '在册型号', value: parts.value.length },
  { label: '低于安全库存', value: replenishment.value.length },
  { label: '在途调拨', value: transfers.value.filter((row) => row.status === '在途').length },
])

async function call(path: string, init?: RequestInit): Promise<boolean> {
  notice.value = ''
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}${path}`, init)
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      errorMessage.value = payload.message ?? payload.detail ?? '操作未生效'
      return false
    }
    notice.value = payload.message ?? '操作成功'
    return true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
    return false
  }
}

async function createTransfer() {
  const ok = await call('/transfers', {
    method: 'POST',
    body: JSON.stringify({ ...transferForm.value, 申请人: operator.value }),
  })
  if (ok) await reloadAll()
}

async function createIssue() {
  const ok = await call('/issues', {
    method: 'POST',
    body: JSON.stringify({ ...issueForm.value, operator: operator.value }),
  })
  if (ok) await reloadAll()
}

async function act(row: Row, action: string) {
  const ok = await call(`/transfers/${row.id}/${action}`, {
    method: 'POST',
    body: JSON.stringify({ operator: operator.value }),
  })
  if (ok) await reloadAll()
}

async function reloadMeta() {
  const response = await request(`${ENDPOINT}/meta`)
  const payload = await response.json()
  warehouses.value = payload.warehouses ?? []
  parts.value = payload.parts ?? []
}

async function reloadBalances() {
  const query = new URLSearchParams()
  if (balanceFilter.value.warehouse) query.set('warehouse', balanceFilter.value.warehouse)
  if (balanceFilter.value.keyword) query.set('keyword', balanceFilter.value.keyword)
  const response = await request(`${ENDPOINT}/balances?${query}`)
  balances.value = (await response.json()).items ?? []
}

function resetBalanceFilter() {
  balanceFilter.value = { warehouse: '', keyword: '' }
  void reloadBalances()
}

async function reloadAll() {
  await Promise.all([
    reloadBalances(),
    request(`${ENDPOINT}/replenishment`).then(async (r) => { replenishment.value = (await r.json()).items ?? [] }),
    request(`${ENDPOINT}/transfers`).then(async (r) => { transfers.value = (await r.json()).items ?? [] }),
    request(`${ENDPOINT}/issues`).then(async (r) => { issues.value = (await r.json()).items ?? [] }),
    request(`${ENDPOINT}/ledger`).then(async (r) => { ledger.value = (await r.json()).items ?? [] }),
  ])
}

onMounted(async () => {
  await reloadMeta()
  await reloadAll()
})
</script>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 14px;
}
.panel h3 {
  margin: 0 0 10px;
  font-size: 14px;
}
.panel select,
.panel input {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.low-stock {
  color: #b42318;
  font-weight: 600;
}
.notice-text {
  color: #067647;
}
</style>
