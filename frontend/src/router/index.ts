import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../services/http'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../pages/Login.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      name: 'list',
      component: () => import('../pages/NotesList.vue'),
    },
    {
      path: '/notes/new',
      name: 'new',
      component: () => import('../pages/NoteEditor.vue'),
    },
    {
      path: '/notes/:id',
      name: 'edit',
      component: () => import('../pages/NoteEditor.vue'),
    },
  ],
})

// 全局守卫：无 token 跳 /login（放行 public 路由）
router.beforeEach((to) => {
  const isPublic = to.meta.public === true
  if (!isPublic && !getToken()) {
    return { name: 'login' }
  }
  if (to.name === 'login' && getToken()) {
    return { name: 'list' }
  }
  return true
})

export default router
