<script setup lang="ts">
defineProps<{
  title: string
  message: string
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()
</script>

<template>
  <div class="confirm-overlay" @click.self="emit('cancel')">
    <div class="card confirm-box">
      <h3>{{ title }}</h3>
      <p class="muted">{{ message }}</p>
      <div class="confirm-actions">
        <button @click="emit('cancel')" :disabled="loading">取消</button>
        <button class="danger" @click="emit('confirm')" :disabled="loading">
          {{ loading ? '删除中…' : '确认删除' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.confirm-box {
  max-width: 380px;
  width: calc(100% - 32px);
}
.confirm-box h3 {
  margin: 0 0 8px;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
</style>
