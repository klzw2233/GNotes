<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getNote, createNote, updateNote } from '../services/notes'

const router = useRouter()
const route = useRoute()

const noteId = computed(() => (route.params.id as string) || null)
const viewMode = computed(() => route.query.view === '1')
const isNew = computed(() => !noteId.value)

const title = ref('')
const content = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')

async function load(): Promise<void> {
  if (!noteId.value) return
  loading.value = true
  error.value = ''
  try {
    const note = await getNote(noteId.value)
    title.value = note.title
    content.value = note.content
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function onSave(): Promise<void> {
  if (!title.value.trim()) {
    error.value = '标题不能为空'
    return
  }
  saving.value = true
  error.value = ''
  try {
    if (isNew.value) {
      const id = await createNote(title.value, content.value)
      router.replace({ name: 'edit', params: { id } })
    } else if (noteId.value) {
      await updateNote(noteId.value, title.value, content.value)
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="row" style="margin-bottom: 20px">
      <button @click="router.push({ name: 'list' })">← 返回</button>
      <span class="spacer" />
      <span class="muted">{{ isNew ? '新建笔记' : viewMode ? '查看笔记' : '编辑笔记' }}</span>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div class="card" v-if="!loading">
      <div class="field">
        <label for="title">标题</label>
        <input
          id="title"
          v-model="title"
          :readonly="viewMode"
          placeholder="笔记标题"
        />
      </div>
      <div class="field">
        <label for="content">正文</label>
        <textarea
          id="content"
          v-model="content"
          :readonly="viewMode"
          class="editor-content"
          placeholder="在这里写笔记…"
        />
      </div>
      <div class="editor-actions" v-if="!viewMode">
        <button class="primary" @click="onSave" :disabled="saving">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button @click="router.push({ name: 'list' })" :disabled="saving">取消</button>
      </div>
    </div>
  </div>
</template>
