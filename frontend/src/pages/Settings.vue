<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { changePassword } from '../services/auth'

const router = useRouter()

const oldPassword = ref('')
const newPassword = ref('')
const confirm = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')

async function onSubmit(): Promise<void> {
  error.value = ''
  success.value = ''
  if (newPassword.value.length < 6) {
    error.value = '新密码至少 6 位'
    return
  }
  if (newPassword.value !== confirm.value) {
    error.value = '两次新密码不一致'
    return
  }
  loading.value = true
  try {
    await changePassword(oldPassword.value, newPassword.value)
    success.value = '密码已修改，已自动续登'
    oldPassword.value = ''
    newPassword.value = ''
    confirm.value = ''
  } catch (e) {
    error.value = (e as Error).message || '修改失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div class="row" style="margin-bottom: 20px">
      <h1 class="page-title">设置</h1>
      <span class="spacer" />
      <button @click="router.push({ name: 'list' })">← 返回</button>
    </div>

    <div class="card" style="max-width: 420px">
      <h2 style="margin-top: 0">修改密码</h2>
      <form @submit.prevent="onSubmit">
        <div class="field">
          <label for="old">旧密码</label>
          <input id="old" v-model="oldPassword" type="password" autocomplete="current-password" required />
        </div>
        <div class="field">
          <label for="new">新密码（至少 6 位）</label>
          <input id="new" v-model="newPassword" type="password" autocomplete="new-password" required />
        </div>
        <div class="field">
          <label for="confirm">确认新密码</label>
          <input id="confirm" v-model="confirm" type="password" autocomplete="new-password" required />
        </div>
        <button class="primary" type="submit" :disabled="loading">
          {{ loading ? '保存中…' : '保存' }}
        </button>
        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="success" class="muted" style="color: var(--success, #16a34a)">{{ success }}</p>
      </form>
    </div>
  </div>
</template>
