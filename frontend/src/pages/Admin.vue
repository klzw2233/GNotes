<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  listUsers,
  updateUser,
  deleteUser,
  resetPassword,
  type User,
} from '../services/users'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const router = useRouter()

const users = ref<User[]>([])
const loading = ref(false)
const error = ref('')

// 删除确认
const showConfirm = ref(false)
const pendingDeleteId = ref<string | null>(null)

// 重置密码结果
const tempPassword = ref<string | null>(null)

// 行内操作反馈
const actionMsg = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    users.value = await listUsers()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function onToggleDisable(u: User): Promise<void> {
  actionMsg.value = ''
  try {
    const updated = await updateUser(u.id, { is_disabled: !u.is_disabled })
    const i = users.value.findIndex((x) => x.id === u.id)
    if (i >= 0) users.value[i] = updated
  } catch (e) {
    actionMsg.value = (e as Error).message
  }
}

async function onToggleRole(u: User): Promise<void> {
  actionMsg.value = ''
  try {
    const updated = await updateUser(u.id, { role: u.role === 'admin' ? 'user' : 'admin' })
    const i = users.value.findIndex((x) => x.id === u.id)
    if (i >= 0) users.value[i] = updated
  } catch (e) {
    actionMsg.value = (e as Error).message
  }
}

function askDelete(id: string): void {
  pendingDeleteId.value = id
  showConfirm.value = true
}

async function confirmDelete(): Promise<void> {
  if (!pendingDeleteId.value) return
  actionMsg.value = ''
  try {
    await deleteUser(pendingDeleteId.value)
    users.value = users.value.filter((u) => u.id !== pendingDeleteId.value)
  } catch (e) {
    actionMsg.value = (e as Error).message
  } finally {
    showConfirm.value = false
    pendingDeleteId.value = null
  }
}

async function onResetPassword(u: User): Promise<void> {
  actionMsg.value = ''
  try {
    const pw = await resetPassword(u.id)
    tempPassword.value = pw
    actionMsg.value = `已重置 ${u.username} 的密码`
  } catch (e) {
    actionMsg.value = (e as Error).message
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <div class="row" style="margin-bottom: 20px">
      <h1 class="page-title">用户管理</h1>
      <span class="spacer" />
      <button @click="router.push({ name: 'list' })">← 返回笔记</button>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="actionMsg" class="muted">{{ actionMsg }}</p>

    <div v-if="tempPassword" class="banner banner-warn" style="margin-bottom: 16px">
      <div>
        <strong>临时密码（仅显示一次）</strong>
        <code style="font-size: 16px; margin: 0 8px">{{ tempPassword }}</code>
        <span class="muted">请立即安全转交用户，用户登录后应尽快修改。</span>
      </div>
      <button @click="tempPassword = null">知道了</button>
    </div>

    <div class="card" v-if="!loading">
      <table class="user-table" v-if="users.length > 0">
        <thead>
          <tr>
            <th>用户名</th>
            <th>邮箱</th>
            <th>角色</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>最后登录</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.username }}</td>
            <td class="muted">{{ u.email }}</td>
            <td>
              <button class="link-btn" @click="onToggleRole(u)">
                {{ u.role === 'admin' ? '管理员' : '普通' }}
              </button>
            </td>
            <td>
              <span :class="u.is_disabled ? 'warn-text' : 'muted'">
                {{ u.is_disabled ? '已禁用' : '正常' }}
              </span>
            </td>
            <td class="muted">{{ formatDate(u.created_at) }}</td>
            <td class="muted">{{ formatDate(u.last_login_at) }}</td>
            <td class="actions-cell">
              <button @click="onToggleDisable(u)">
                {{ u.is_disabled ? '启用' : '禁用' }}
              </button>
              <button @click="onResetPassword(u)">重置密码</button>
              <button class="danger" @click="askDelete(u.id)">
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted" style="text-align: center; margin: 0">暂无用户</p>
    </div>

    <ConfirmDialog
      v-if="showConfirm"
      title="删除用户"
      message="确定删除该用户？此为软删除，用户数据保留但无法登录，可由数据库恢复。"
      :loading="false"
      @confirm="confirmDelete"
      @cancel="showConfirm = false"
    />
  </div>
</template>
