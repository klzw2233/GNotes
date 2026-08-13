<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listNotes, deleteNote, type NoteListItem } from '../services/notes'
import { getBackupStatus, triggerBackup, type BackupStatus } from '../services/backup'
import { useAuthStore } from '../stores/auth'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const router = useRouter()
const auth = useAuthStore()

const notes = ref<NoteListItem[]>([])
const loading = ref(false)
const error = ref('')
const backup = ref<BackupStatus | null>(null)
const backupBusy = ref(false)
const backupActionMsg = ref('')

// 删除确认
const showConfirm = ref(false)
const pendingDeleteId = ref<string | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await listNotes(1, 100)
    notes.value = data.items
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function askDelete(id: string): void {
  pendingDeleteId.value = id
  showConfirm.value = true
}

async function confirmDelete(): Promise<void> {
  if (!pendingDeleteId.value) return
  try {
    await deleteNote(pendingDeleteId.value)
    notes.value = notes.value.filter((n) => n.id !== pendingDeleteId.value)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    showConfirm.value = false
    pendingDeleteId.value = null
  }
}

async function loadBackup(): Promise<void> {
  if (!auth.isAdmin) return
  try {
    backup.value = await getBackupStatus()
  } catch {
    backup.value = null
  }
}

async function onBackupNow(): Promise<void> {
  backupBusy.value = true
  backupActionMsg.value = ''
  try {
    await triggerBackup()
    backupActionMsg.value = '备份已上传'
  } catch (e) {
    backupActionMsg.value = (e as Error).message || '备份失败'
  } finally {
    backupBusy.value = false
    await loadBackup()
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  void load()
  void loadBackup()
})
</script>

<template>
  <div>
    <div class="row" style="margin-bottom: 20px">
      <h1 class="page-title">我的笔记</h1>
      <span class="spacer" />
      <span class="muted">{{ auth.username || '已登录' }}</span>
      <button @click="auth.logout().then(() => router.push({ name: 'login' }))">登出</button>
      <button class="primary" @click="router.push({ name: 'new' })">新建</button>
    </div>

    <div
      v-if="auth.isAdmin && backup"
      class="banner"
      :class="backup.ok === false || !backup.configured ? 'banner-warn' : 'banner-ok'"
    >
      <div>
        <strong>备份</strong>
        <span class="muted"> — {{ backup.message }}</span>
        <span v-if="backup.finished_at" class="muted">
          （{{ formatDate(backup.finished_at) }}）
        </span>
      </div>
      <div class="row">
        <span v-if="backupActionMsg" class="muted">{{ backupActionMsg }}</span>
        <button :disabled="backupBusy" @click="onBackupNow">
          {{ backupBusy ? '备份中…' : '立即备份' }}
        </button>
      </div>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div class="card" v-if="!loading && notes.length === 0">
      <p class="muted" style="text-align: center; margin: 0">还没有笔记，点击「新建」开始。</p>
    </div>

    <ul class="note-list card" v-if="notes.length > 0">
      <li class="note-item" v-for="note in notes" :key="note.id">
        <div style="flex: 1; min-width: 0">
          <div class="title">{{ note.title }}</div>
          <div class="meta">更新于 {{ formatDate(note.updated_at) }}</div>
        </div>
        <div class="actions">
          <button @click="router.push({ name: 'edit', params: { id: note.id } })">编辑</button>
          <button class="danger" @click="askDelete(note.id)">删除</button>
        </div>
      </li>
    </ul>

    <ConfirmDialog
      v-if="showConfirm"
      title="删除笔记"
      message="确定要删除这篇笔记吗？此操作不可撤销。"
      :loading="false"
      @confirm="confirmDelete"
      @cancel="showConfirm = false"
    />
  </div>
</template>
