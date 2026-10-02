<template>
  <section class="page" data-module="spare-restock">
    <header class="page-head">
      <div>
        <h2>待补货清单</h2>
        <p class="page-desc">
          本入口不单独维护数量，而是实时读取
          <RouterLink to="/spare/ledger" class="inline-link">备件台账</RouterLink>
          里"结存 &lt; 安全库存"的行——另一个入口看到的就是同一份结存，调拨/领用后这里立即跟着变。
        </p>
      </div>
      <div class="page-actions">
        <KeeperSwitch />
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">待补货物料行</span>
        <strong class="stat-value stat-danger">{{ rows.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">建议补货总量（补到安全线）</span>
        <strong class="stat-value">{{ totalGap }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">涉及仓库</span>
        <strong class="stat-value">{{ warehouseCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">数据来源</span>
        <strong class="stat-value stat-source">/api/spare/restock ⇄ /balances 同源</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>仓库</span>
        <select v-model="warehouse" @change="reload">
          <option value="">全部仓库</option>
          <option v-for="wh in warehouses" :key="wh.code" :value="wh.code">{{ wh.name }}</option>
        </select>
      </label>
      <button class="btn" type="button" @click="reload">刷新（重新读台账）</button>
      <RouterLink class="btn ghost" to="/spare/transfers">去调拨补货 →</RouterLink>
    </form>

    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>仓库</th>
            <th>备件编码</th>
            <th>备件名称</th>
            <th>型号</th>
            <th>当前结存</th>
            <th>安全库存</th>
            <th>缺口</th>
            <th>保修期至</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.warehouse_code + row.part_code" class="row-danger">
            <td>{{ row.warehouse_name }}</td>
            <td>{{ row.part_code }}</td>
            <td>{{ row.part_name }}</td>
            <td>{{ row.part_model }}</td>
            <td><strong>{{ row.on_hand }}</strong> {{ row.unit }}</td>
            <td>{{ row.safety_stock }} {{ row.unit }}</td>
            <td><span class="tag tag-danger">缺 {{ row.gap_to_safety }} {{ row.unit }}</span></td>
            <td>
              {{ row.warranty_until ?? '—' }}
              <span v-if="row.near_warranty" class="tag tag-warn">临期</span>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" class="empty-state">当前没有低于安全库存的备件，台账结存均在安全线以上</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span>共 {{ rows.length }} 行待补货，全部实时派生自结存台账，无独立副本。</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { spareApi, type BalanceRow, type MetaResponse } from '@/api/spare'
import KeeperSwitch from '../spare/components/KeeperSwitch.vue'

const warehouses = ref<MetaResponse['warehouses']>([])
const rows = ref<BalanceRow[]>([])
const warehouse = ref('')

const totalGap = computed(() => rows.value.reduce((sum, row) => sum + (row.gap_to_safety || 0), 0))
const warehouseCount = computed(() => new Set(rows.value.map((row) => row.warehouse_code)).size)

async function reload() {
  const res = await spareApi.restock(warehouse.value || undefined)
  rows.value = res.items
}

onMounted(async () => {
  const meta = await spareApi.meta()
  warehouses.value = meta.warehouses
  await reload()
})
</script>
