/** 备品备件接口封装：统一拼地址、带当前保管员身份头、把后端可读错误抛给页面。 */
import { useSpareSession } from '@/stores/spareSession'

const API_BASE = '/api/spare'

export interface SpareResult<T = unknown> {
  ok: boolean
  message?: string
  code?: string
  entry?: T
  total?: number
  items?: T[]
}

async function call<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const session = useSpareSession()
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(session.operatorId ? { 'X-Operator-Id': session.operatorId } : {}),
    },
    ...init,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = (data as SpareResult).message || `接口返回 ${response.status}`
    const error = new Error(message) as Error & { code?: string; status?: number }
    error.code = (data as SpareResult).code
    error.status = response.status
    throw error
  }
  return data as T
}

function query(params: Record<string, string | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.append(key, value)
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export interface MetaResponse {
  warehouses: Array<{ code: string; name: string; keeper_id: string; keeper_name: string }>
  parts: Array<{ code: string; name: string; model: string; unit: string; safety_stock: number; warranty_until: string | null }>
  transfer_statuses: string[]
  next_actions: Record<string, Array<[string, string]>>
}

export const spareApi = {
  meta: () => call<MetaResponse>('/meta'),
  balances: (params: { warehouse?: string; keyword?: string }) =>
    call<{ total: number; items: BalanceRow[] }>(`/balances${query(params)}`),
  restock: (warehouse?: string) =>
    call<{ total: number; items: BalanceRow[] }>(`/restock${query({ warehouse })}`),
  movements: (params: { warehouse?: string; voucher_type?: string }) =>
    call<{ total: number; items: MovementRow[] }>(`/movements${query(params)}`),
  outbound: (warehouse?: string) =>
    call<{ total: number; items: OutboundOrder[] }>(`/outbound${query({ warehouse })}`),
  createOutbound: (body: Record<string, unknown>) =>
    call<SpareResult<OutboundOrder>>('/outbound', { method: 'POST', body: JSON.stringify(body) }),
  transfers: (params: { status?: string; warehouse?: string }) =>
    call<{ total: number; items: TransferOrder[] }>(`/transfers${query(params)}`),
  getTransfer: (id: number) => call<TransferOrder>(`/transfers/${id}`),
  createTransfer: (body: Record<string, unknown>) =>
    call<SpareResult<TransferOrder>>('/transfers', { method: 'POST', body: JSON.stringify(body) }),
  transferAction: (id: number, action: string, values: Record<string, unknown> = {}) =>
    call<SpareResult<TransferOrder>>(`/transfers/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, values }),
    }),
  adjustBalance: (body: Record<string, unknown>) =>
    call<SpareResult<BalanceRow>>('/balances', { method: 'POST', body: JSON.stringify(body) }),
}

export interface BalanceRow {
  warehouse_code: string
  warehouse_name?: string
  part_code: string
  part_name: string
  part_model: string
  unit: string
  safety_stock: number
  warranty_until: string | null
  on_hand: number
  below_safety?: boolean
  gap_to_safety?: number
  near_warranty?: boolean
}

export interface MovementRow {
  id: number
  voucher_type: string
  voucher_no: string
  transfer_id: number | null
  warehouse_code: string
  warehouse_name?: string
  part_name: string
  part_model: string
  unit: string
  qty: number
  direction: 'in' | 'out'
  reason: string
  operator: string
  created_at: string
  pair_key: string
}

export interface OutboundOrder {
  id: number
  voucher_no: string
  warehouse_code: string
  warehouse_name?: string
  part_code: string
  part_name: string
  part_model: string
  unit: string
  qty: number
  reason: string
  operator: string
  status: string
  created_at: string
}

export interface HistoryEntry {
  status: string
  at: string
  operator: string
  note: string
}

export interface TransferOrder {
  id: number
  voucher_no: string
  source_code: string
  target_code: string
  source_name?: string
  target_name?: string
  part_code: string
  part_name: string
  part_model: string
  unit: string
  qty: number
  status: string
  applicant: string
  created_at: string
  approved_at: string | null
  shipped_at: string | null
  received_at: string | null
  rejected_at: string | null
  returned_at: string | null
  reject_reason: string | null
  history: HistoryEntry[]
  posted: boolean
  return_posted: boolean
  actions?: Array<{ key: string; label: string }>
}
