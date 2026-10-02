<template>
  <section class="page" data-module="spare-transfer">
    <header class="page-head">
      <div>
        <h2>备件调拨单</h2>
        <p class="page-desc">
          调拨单按 <b>已申请 → 已批 → 在途 → 已入库</b> 单向推进；没批不许出库，已入库回不到已申请。
          在途被目的仓拒收则退回源仓，出库时"源仓扣、目标仓加"是同一笔账，重复提交只出库一次。
        </p>
      </div>
      <div class="page-actions">
        <KeeperSwitch />
      </div>
    </header>

    <div class="callout">
      当前以 <b>{{ session.operatorName }}（{{ session.warehouseName }}）</b> 身份操作：
      批准/出库只对<b>源仓是本仓</b>的单生效；验收/拒收只对<b>目的仓是本仓</b>的单生效。
      跨仓动作会被当场驳回并提示缺哪项授权。
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>相关仓库</span>
        <select v-model="filters.warehouse">
          <option value="">全部仓库</option>
          <option v-for="wh in warehouses" :key="wh.code" :value="wh.code">{{ wh.name }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <span class="filter-spacer"></span>
      <label class="check-item">
        <input type="checkbox" v-model="onlyMine" @change="reload" />
        只看与我所在仓相关
      </label>
      <button class="btn primary" type="button" @click="openCreate">新建调拨申请</button>
    </form>

    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>单据号</th>
            <th>源仓库</th>
            <th>目标仓库</th>
            <th>备件</th>
            <th>数量</th>
            <th>状态</th>
            <th>申请人</th>
            <th>关键时间</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="order in filteredOrders" :key="order.id">
            <td>{{ order.voucher_no }}</td>
            <td>{{ order.source_name }}</td>
            <td>{{ order.target_name }}</td>
            <td>{{ order.part_name }}（{{ order.part_model }}）</td>
            <td>{{ order.qty }}{{ order.unit }}</td>
            <td><span class="status-tag" :class="statusClass(order.status)">{{ order.status }}</span></td>
            <td>{{ order.applicant }}</td>
            <td class="time-cell">
              <span v-if="order.shipped_at">出库 {{ order.shipped_at }}</span>
              <span v-else-if="order.approved_at">已批 {{ order.approved_at }}</span>
              <span v-else>申请 {{ order.created_at }}</span>
              <span v-if="order.reject_reason" class="reject-reason">拒收：{{ order.reject_reason }}</span>
            </td>
            <td class="row-actions">
              <button
                v-for="act in order.actions || []"
                :key="act.key"
                type="button"
                class="link"
                @click="onAction(order, act.key)"
              >{{ act.label }}</button>
              <button type="button" class="link link-muted" @click="showTimeline(order)">流转记录</button>
            </td>
          </tr>
          <tr v-if="!filteredOrders.length">
            <td colspan="9" class="empty-state">暂无调拨单</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="errorMessage" class="error-text action-feedback">{{ errorMessage }}</p>
    <p v-if="successMessage" class="success-text action-feedback">{{ successMessage }}</p>

    <!-- 新建调拨申请 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>新建调拨申请</h3>
        <p class="modal-hint">申请提交后状态为"已申请"，库存不动；须经<b>源仓保管员</b>批准后才能出库。</p>
        <label class="form-item">
          <span>源仓库（出货方）</span>
          <select v-model="createForm.source_code">
            <option value="" disabled>选择源仓库</option>
            <option v-for="wh in warehouses" :key="wh.code" :value="wh.code">{{ wh.name }}</option>
          </select>
        </label>
        <label class="form-item">
          <span>目标仓库（收货方）</span>
          <select v-model="createForm.target_code">
            <option value="" disabled>选择目标仓库</option>
            <option v-for="wh in warehouses" :key="wh.code" :value="wh.code">{{ wh.name }}</option>
          </select>
        </label>
        <label class="form-item">
          <span>备件型号</span>
          <select v-model="createForm.part_code">
            <option value="" disabled>选择备件</option>
            <option v-for="p in parts" :key="p.code" :value="p.code">
              {{ p.name }}（{{ p.model }}）· 安全库存 {{ p.safety_stock }}{{ p.unit }}
            </option>
          </select>
        </label>
        <label class="form-item">
          <span>数量</span>
          <input v-model.number="createForm.qty" type="number" min="1" />
        </label>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">提交申请</button>
        </div>
      </div>
    </div>

    <!-- 拒收原因 -->
    <div v-if="rejectTarget" class="modal-mask" @click.self="rejectTarget = null">
      <div class="modal">
        <h3>目的仓拒收 · {{ rejectTarget.voucher_no }}</h3>
        <p class="modal-hint">拒收后单据进入"已拒收"，需再执行"退回源仓"才会把库存恢复到出库前。</p>
        <label class="form-item">
          <span>拒收原因（必填）</span>
          <textarea v-model="rejectReason" rows="3" placeholder="如：外观破损、检测不合格、型号不符"></textarea>
        </label>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="rejectTarget = null">取消</button>
          <button class="btn danger" type="button" :disabled="submitting" @click="confirmReject">确认拒收</button>
        </div>
      </div>
    </div>

    <!-- 流转时间线 -->
    <div v-if="timelineOrder" class="modal-mask" @click.self="timelineOrder = null">
      <div class="modal">
        <h3>流转记录 · {{ timelineOrder.voucher_no }}</h3>
        <ul class="timeline">
          <li v-for="(h, idx) in timelineOrder.history" :key="idx" class="timeline-item">
            <span class="timeline-status" :class="statusClass(h.status)">{{ h.status }}</span>
            <div>
              <div>{{ h.note }}</div>
              <div class="timeline-meta">{{ h.operator }} · {{ h.at }}</div>
            </div>
          </li>
        </ul>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="timelineOrder = null">知道了</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { spareApi, type MetaResponse, type TransferOrder } from '@/api/spare'
import { useSpareSession } from '@/stores/spareSession'
import KeeperSwitch from './components/KeeperSwitch.vue'

const session = useSpareSession()

const warehouses = ref<MetaResponse['warehouses']>([])
const parts = ref<MetaResponse['parts']>([])
const statuses = ref<string[]>([])
const orders = ref<TransferOrder[]>([])
const filters = reactive<{ status: string; warehouse: string }>({ status: '', warehouse: '' })
const onlyMine = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const createOpen = ref(false)
const createForm = reactive({ source_code: '', target_code: '', part_code: '', qty: 1 })
const rejectTarget = ref<TransferOrder | null>(null)
const rejectReason = ref('')
const timelineOrder = ref<TransferOrder | null>(null)
const formError = ref('')
const submitting = ref(false)

const filteredOrders = computed(() => {
  if (!onlyMine.value) return orders.value
  const mine = session.warehouseCode
  return orders.value.filter((o) => o.source_code === mine || o.target_code === mine)
})

function statusClass(status: string): Record<string, boolean> {
  return {
    'st-applied': status === '已申请',
    'st-approved': status === '已批',
    'st-transit': status === '在途',
    'st-received': status === '已入库',
    'st-rejected': status === '已拒收',
    'st-returned': status === '已退回',
  }
}

function flash(ok: boolean, message: string) {
  if (ok) {
    successMessage.value = message
    errorMessage.value = ''
  } else {
    errorMessage.value = message
    successMessage.value = ''
  }
  window.setTimeout(() => {
    errorMessage.value = ''
    successMessage.value = ''
  }, 5000)
}

async function reload() {
  const res = await spareApi.transfers({
    status: filters.status,
    warehouse: filters.warehouse || (onlyMine.value ? session.warehouseCode : undefined),
  })
  orders.value = res.items
}

function openCreate() {
  formError.value = ''
  createForm.source_code = ''
  createForm.target_code = ''
  createForm.part_code = ''
  createForm.qty = 1
  createOpen.value = true
}

async function submitCreate() {
  formError.value = ''
  if (!createForm.source_code || !createForm.target_code) {
    formError.value = '请选择源仓库和目标仓库'
    return
  }
  if (createForm.source_code === createForm.target_code) {
    formError.value = '源仓库和目标仓库不能相同'
    return
  }
  if (!createForm.part_code) {
    formError.value = '请选择备件型号'
    return
  }
  if (!createForm.qty || createForm.qty <= 0) {
    formError.value = '调拨数量必须是正整数'
    return
  }
  submitting.value = true
  try {
    const res = await spareApi.createTransfer({ ...createForm })
    flash(true, res.message || '调拨申请已提交')
    createOpen.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '调拨申请失败'
  } finally {
    submitting.value = false
  }
}

function onAction(order: TransferOrder, action: string) {
  if (action === 'reject') {
    formError.value = ''
    rejectReason.value = order.reject_reason || ''
    rejectTarget.value = order
    return
  }
  const confirmMap: Record<string, string> = {
    approve: `确认以源仓保管员身份批准 ${order.voucher_no}？`,
    ship: `确认出库发运 ${order.qty}${order.unit}？源仓将扣减、目标仓同时增加（同一笔账）。`,
    receive: `确认验收入库 ${order.voucher_no}？数量与质量无误。`,
    return: `确认退回入源仓？目标仓退出、源仓收回，库存恢复到出库前。`,
  }
  if (!window.confirm(confirmMap[action] || '确认执行该动作？')) return
  void doAction(order, action)
}

async function doAction(order: TransferOrder, action: string, values: Record<string, unknown> = {}) {
  try {
    const res = await spareApi.transferAction(order.id, action, values)
    flash(true, res.message || '操作成功')
    await reload()
  } catch (error) {
    flash(false, error instanceof Error ? error.message : '操作未生效')
  }
}

async function confirmReject() {
  if (!rejectTarget.value) return
  if (!rejectReason.value.trim()) {
    formError.value = '拒收原因必填'
    return
  }
  submitting.value = true
  const target = rejectTarget.value
  try {
    await doAction(target, 'reject', { reason: rejectReason.value.trim() })
    rejectTarget.value = null
  } finally {
    submitting.value = false
  }
}

async function showTimeline(order: TransferOrder) {
  timelineOrder.value = await spareApi.getTransfer(order.id)
}

onMounted(async () => {
  const meta = await spareApi.meta()
  warehouses.value = meta.warehouses
  parts.value = meta.parts
  statuses.value = meta.transfer_statuses
  await reload()
})
</script>
