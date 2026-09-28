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
          <select v-model="account" @change="saveAccount">
            <optgroup label="配载人员">
              <option v-for="name in loaderAccounts" :key="name" :value="name">{{ name }}</option>
            </optgroup>
            <optgroup label="复核人员">
              <option v-for="name in reviewerAccounts" :key="name" :value="name">{{ name }}</option>
            </optgroup>
          </select>
        </label>
        <button v-if="isLoader" class="btn primary" type="button" @click="openCreate">登记配载单</button>
        <button class="btn" type="button" @click="exportRows">导出载重平衡清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reloadAll">
      <label class="filter-item">
        <span>配载单号</span>
        <input v-model="filters.keyword" placeholder="按配载单号检索" />
      </label>
      <label class="filter-item">
        <span>配载状态</span>
        <select v-model="filters.status">
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
          <td v-for="column in columns" :key="column">{{ formatCell(column, row) }}</td>
          <td class="row-actions">
            <template v-if="canLoad(row)">
              <button class="link" type="button" @click="openEdit(row)">修改数据</button>
              <button class="link" type="button" @click="runAction('提交复核', row)">提交复核</button>
            </template>
            <template v-if="canReview(row)">
              <button class="link" type="button" @click="openReview('确认配载', row)">确认配载</button>
              <button class="link" type="button" @click="openReview('退回重算', row)">退回重算</button>
            </template>
            <button
              v-if="(row.复核记录 ?? []).length > 0"
              class="link"
              type="button"
              @click="openHistory(row)"
            >
              复核记录
            </button>
            <span v-if="!hasAnyAction(row)" class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无载重平衡数据，可先登记配载单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条载重平衡记录（与上方汇总同一筛选口径）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 复核人员填写意见：结论归属当前账号，退回时签字同步撤销 -->
    <div v-if="reviewDialog.open" class="modal-mask" @click.self="closeDialogs">
      <form class="modal" @submit.prevent="submitReview">
        <h3>{{ reviewDialog.action }}｜{{ reviewDialog.row?.['配载单号'] }}</h3>
        <p class="modal-tip">复核账号：{{ account }}（结论将归属到该账号）</p>
        <label class="filter-item">
          <span>复核意见<span class="required">*</span></span>
          <textarea v-model="reviewDialog.opinion" rows="4" :placeholder="reviewDialog.action === '退回重算' ? '请说明退回原因，便于配载人员重算' : '请填写确认结论'"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDialogs">取消</button>
          <button class="btn primary" type="submit">确定{{ reviewDialog.action }}</button>
        </div>
      </form>
    </div>

    <!-- 退回重算后的修改入口：提交后对配载人员只读，且碰不到复核结论字段 -->
    <div v-if="editDialog.open" class="modal-mask" @click.self="closeDialogs">
      <form class="modal" @submit.prevent="submitEdit">
        <h3>{{ editDialog.id ? '修改配载数据' : '登记配载单' }}</h3>
        <p class="modal-tip">操作账号：{{ account }}（配载人员）；复核人员、复核意见为只读留痕，不在此维护。</p>
        <label v-for="field in editableFields" :key="field" class="filter-item">
          <span>{{ field }}{{ requiredFields.includes(field) ? '*' : '' }}</span>
          <input v-model="editDialog.form[field]" :placeholder="`请输入${field}`" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDialogs">取消</button>
          <button class="btn primary" type="submit">保存</button>
        </div>
      </form>
    </div>

    <!-- 历史复核结论：同一条配载单每轮只保留一条，不重复 -->
    <div v-if="historyDialog.open" class="modal-mask" @click.self="closeDialogs">
      <div class="modal">
        <h3>复核记录｜{{ historyDialog.row?.['配载单号'] }}</h3>
        <table class="data-table">
          <thead>
            <tr><th>轮次</th><th>复核结论</th><th>复核人员</th><th>复核意见</th><th>复核时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="record in historyDialog.row?.['复核记录'] ?? []" :key="String(record['轮次'])">
              <td>第 {{ record['轮次'] }} 轮</td>
              <td>{{ record['复核结论'] }}</td>
              <td>{{ record['复核人员'] }}</td>
              <td>{{ record['复核意见'] }}</td>
              <td>{{ record['复核时间'] }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="closeDialogs">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & {
  id: number
  status: string
  复核记录?: ReviewRecord[]
}
type ReviewRecord = {
  轮次: number
  复核结论: string
  复核人员: string
  复核意见: string
  复核时间: string
}
type Summary = {
  reviewing: number
  total: number
  returned: number
  confirmed: number
  confirmedWeight: number
  confirmedCenterOfGravity: number
}

const ENDPOINT = '/api/loadsheet'
const ACCOUNT_KEY = 'loadsheet-account'
const columns = ['配载单号', '关联航班', '计算重量', '重心位置', '油量数据', '配载人员', '复核人员', '复核结论', '配载状态']
const statuses = ['待计算', '待复核', '已确认', '已退回']
const loaderAccounts = ['张磊', '李强']
const reviewerAccounts = ['王敏', '赵倩']
const requiredFields = ['配载单号', '关联航班', '计算重量']
const editableFields = ['配载单号', '关联航班', '计算重量', '重心位置', '油量数据']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = reactive<{ keyword: string; status: string }>({ keyword: '', status: '' })
const account = ref(localStorage.getItem(ACCOUNT_KEY) || loaderAccounts[0])

const stats = ref([
  { label: '待复核待办', value: 0 },
  { label: '已确认配载', value: 0 },
  { label: '已确认重量汇总', value: '0 kg' },
  { label: '已确认平均重心', value: '0' },
  { label: '退回重算数', value: 0 },
])

const reviewDialog = reactive<{ open: boolean; action: '确认配载' | '退回重算' | ''; row: Row | null; opinion: string }>({
  open: false,
  action: '',
  row: null,
  opinion: '',
})
const editDialog = reactive<{ open: boolean; id: number | null; form: Record<string, string> }>({
  open: false,
  id: null,
  form: {},
})
const historyDialog = reactive<{ open: boolean; row: Row | null }>({ open: false, row: null })

const isLoader = computed(() => loaderAccounts.includes(account.value))

function saveAccount() {
  localStorage.setItem(ACCOUNT_KEY, account.value)
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
  if (filters.status) params.set('status', filters.status)
  return params.toString()
}

function applySummary(payload: Summary) {
  stats.value = [
    { label: '待复核待办', value: payload.reviewing },
    { label: '已确认配载', value: payload.confirmed },
    { label: '已确认重量汇总', value: `${payload.confirmedWeight} kg` },
    { label: '已确认平均重心', value: String(payload.confirmedCenterOfGravity) },
    { label: '退回重算数', value: payload.returned },
  ]
}

function formatCell(column: string, row: Row): string {
  if (column === '复核结论') {
    return row.status === '已退回' ? `已退回（签字已撤销）${row['复核意见'] ? `：${row['复核意见']}` : ''}` : (String(row[column] ?? '—'))
  }
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function canLoad(row: Row): boolean {
  return loaderAccounts.includes(account.value)
    && row['配载人员'] === account.value
    && (row.status === '待计算' || row.status === '已退回')
}

function canReview(row: Row): boolean {
  return reviewerAccounts.includes(account.value) && row.status === '待复核'
}

function hasAnyAction(row: Row): boolean {
  return canLoad(row) || canReview(row) || ((row.复核记录 ?? []).length > 0)
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  void reloadAll()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function closeDialogs() {
  reviewDialog.open = false
  editDialog.open = false
  historyDialog.open = false
  reviewDialog.row = null
  historyDialog.row = null
}

function openCreate() {
  editDialog.id = null
  editDialog.form = { 配载单号: '', 关联航班: '', 计算重量: '', 重心位置: '', 油量数据: '' }
  editDialog.open = true
}

function openEdit(row: Row) {
  editDialog.id = row.id
  editDialog.form = {
    配载单号: String(row['配载单号'] ?? ''),
    关联航班: String(row['关联航班'] ?? ''),
    计算重量: String(row['计算重量'] ?? ''),
    重心位置: String(row['重心位置'] ?? ''),
    油量数据: String(row['油量数据'] ?? ''),
  }
  editDialog.open = true
}

function openReview(action: '确认配载' | '退回重算', row: Row) {
  reviewDialog.action = action
  reviewDialog.row = row
  reviewDialog.opinion = ''
  reviewDialog.open = true
}

function openHistory(row: Row) {
  historyDialog.row = row
  historyDialog.open = true
}

async function reloadAll() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const [listResponse, summaryResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/summary?${query}`),
    ])
    if (!listResponse.ok) throw new Error('配载单列表读取失败')
    if (!summaryResponse.ok) throw new Error('配载单汇总读取失败')
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    applySummary(await summaryResponse.json())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡列表读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, operator: account.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '载重平衡动作未生效，请稍后重试')
    }
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '载重平衡操作失败'
  }
}

async function submitReview() {
  if (!reviewDialog.row || !reviewDialog.action) return
  if (!reviewDialog.opinion.trim()) {
    errorMessage.value = '复核意见不能为空，结论需要归属到具体复核人员'
    return
  }
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${reviewDialog.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        action: reviewDialog.action,
        operator: account.value,
        opinion: reviewDialog.opinion.trim(),
      }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '复核动作未生效，请稍后重试')
    }
    closeDialogs()
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核操作失败'
  }
}

async function submitEdit() {
  const missing = requiredFields.find((field) => !editDialog.form[field]?.trim())
  if (missing) {
    errorMessage.value = `必填字段「${missing}」不能为空`
    return
  }
  errorMessage.value = ''
  const url = editDialog.id ? `${ENDPOINT}/${editDialog.id}` : ENDPOINT
  const method = editDialog.id ? 'PUT' : 'POST'
  const body: Record<string, unknown> = {
    values: { ...editDialog.form, operator: account.value },
  }
  try {
    const response = await request(url, { method, body: JSON.stringify(body) })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '配载数据未保存，请稍后重试')
    }
    closeDialogs()
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '配载数据保存失败'
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.page-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.account-switch {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.account-switch select {
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.muted-text {
  color: var(--muted);
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  width: 460px;
  max-width: calc(100vw - 32px);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2);
}
.modal h3 {
  margin: 0 0 6px;
  font-size: 15px;
}
.modal-tip {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--muted);
}
.modal textarea,
.modal input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font: inherit;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
.required {
  color: #b42318;
}
</style>
