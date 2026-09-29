<template>
  <section class="page" data-module="loadsheet">
    <header class="page-head">
      <div>
        <h2>载重平衡管理</h2>
        <p class="page-desc">维护配载单，围绕配载单号、关联航班、计算重量、重心位置做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <label class="account-switch">
          当前账号
          <select v-model="selectedAccount">
            <option v-for="account in accounts" :key="account.operator" :value="account.operator">
              {{ account.operator }}（{{ account.role }}）
            </option>
          </select>
        </label>
        <button class="btn primary" type="button" :disabled="selectedRole !== '配载人员'" @click="openCreate">登记配载单</button>
        <button class="btn" type="button" @click="exportRows">导出载重平衡清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.key" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>配载单号</span>
        <input v-model="keyword" placeholder="按配载单号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="runningAction === `${row.id}:${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted-text">无权限或只读</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无载重平衡数据，可先登记配载单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条载重平衡记录（与当前筛选汇总口径一致）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, unknown>

interface Summary {
  待复核配载: number
  配载单总数: number
  退回重算数: number
  已确认配载数: number
  已确认计算重量: number
  已确认重心配载数: number
}

const ENDPOINT = '/api/loadsheet'
const columns = [
  '配载单号',
  '关联航班',
  '计算重量',
  '重心位置',
  '油量数据',
  '配载人员',
  '复核人员',
  '复核意见',
  '复核结论',
  '结论复核人员',
  '复核签字',
  '配载权限',
  '配载状态',
]
const statuses = ['待计算', '待复核', '已确认', '已退回']
const accounts = [
  { operator: '配载员甲', role: '配载人员' },
  { operator: '配载员乙', role: '配载人员' },
  { operator: '复核员甲', role: '复核人员' },
]

const emptySummary: Summary = {
  待复核配载: 0,
  配载单总数: 0,
  退回重算数: 0,
  已确认配载数: 0,
  已确认计算重量: 0,
  已确认重心配载数: 0,
}

const rows = ref<Row[]>([])
const total = ref(0)
const summary = ref<Summary>({ ...emptySummary })
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const selectedAccount = ref(accounts[0].operator)
const runningAction = ref('')

const selectedRole = computed(() => accounts.find((account) => account.operator === selectedAccount.value)?.role ?? '')
const statCards = computed(() => [
  { key: 'pending', label: '待复核配载', value: summary.value.待复核配载 },
  { key: 'total', label: '配载单总数', value: summary.value.配载单总数 },
  { key: 'returned', label: '退回重算数', value: summary.value.退回重算数 },
  { key: 'confirmed', label: '已确认配载数', value: summary.value.已确认配载数 },
  { key: 'weight', label: '已确认计算重量', value: summary.value.已确认计算重量 },
  { key: 'center', label: '已确认重心数', value: summary.value.已确认重心配载数 },
])

function displayValue(row: Row, column: string) {
  if (column === '配载权限') {
    return row.status === '待计算' ? '可编辑' : '只读'
  }
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function availableActions(row: Row): string[] {
  const status = String(row.status ?? '')
  if (selectedRole.value === '配载人员') {
    return status === '待计算' ? ['提交复核'] : []
  }
  if (selectedRole.value === '复核人员') {
    return status === '待复核' ? ['确认配载', '退回重算'] : []
  }
  return []
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '配载单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  let opinion = ''
  if (selectedRole.value === '复核人员') {
    const defaultOpinion = action === '确认配载' ? '重量、重心与油量复核无误' : ''
    const input = window.prompt(action === '退回重算' ? '请填写退回复核意见' : '请确认复核意见', defaultOpinion)
    if (input === null) {
      return
    }
    opinion = input.trim()
    if (action === '退回重算' && !opinion) {
      errorMessage.value = '退回重算必须填写复核意见'
      return
    }
  }

  const values: Record<string, string> = {
    action,
    operator: selectedAccount.value,
    role: selectedRole.value,
  }
  if (opinion) {
    values.复核意见 = opinion
  }

  runningAction.value = `${row.id}:${action}`
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || payload?.detail || '载重平衡动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡操作失败'
  } finally {
    runningAction.value = ''
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) {
    query.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }

  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('配载单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    summary.value = { ...emptySummary, ...(payload.summary ?? {}) }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡列表读取失败'
  }
}

onMounted(reload)
</script>
