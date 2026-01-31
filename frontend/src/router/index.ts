import { createRouter, createWebHistory } from 'vue-router'
import Home from '@/views/Home.vue'
import Switches from '@/views/Switches.vue'
import History from '@/views/History.vue'
import Discovery from '@/views/Discovery.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'Home',
      component: Home,
      meta: { title: 'IP Lookup' }
    },
    {
      path: '/switches',
      name: 'Switches',
      component: Switches,
      meta: { title: 'Switch Management' }
    },
    {
      path: '/discovery',
      name: 'Discovery',
      component: Discovery,
      meta: { title: 'Batch Discovery' }
    },
    {
      path: '/history',
      name: 'History',
      component: History,
      meta: { title: 'Query History' }
    }
  ]
})

router.beforeEach((to, from, next) => {
  document.title = `${to.meta.title} - IP Track System` || 'IP Track System'
  next()
})

export default router
