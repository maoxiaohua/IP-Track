import { createRouter, createWebHistory } from 'vue-router'
import Home from '@/views/Home.vue'
import Switches from '@/views/Switches.vue'
import SwitchDetail from '@/views/SwitchDetail.vue'
import History from '@/views/History.vue'
import Discovery from '@/views/Discovery.vue'
import IPAM from '@/views/IPAM.vue'
import SubnetDetail from '@/views/SubnetDetail.vue'
import CommandTemplates from '@/views/CommandTemplates.vue'
import Alarms from '@/views/Alarms.vue'
import OpticalModules from '@/views/OpticalModules.vue'

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
      path: '/switches/:id',
      name: 'SwitchDetail',
      component: SwitchDetail,
      meta: { title: 'Switch Detail' }
    },
    {
      path: '/discovery',
      name: 'Discovery',
      component: Discovery,
      meta: { title: 'Batch Discovery' }
    },
    {
      path: '/ipam',
      name: 'IPAM',
      component: IPAM,
      meta: { title: 'IP Address Management' }
    },
    {
      path: '/snmp-config',
      name: 'SNMPConfig',
      component: () => import('@/views/SNMPConfig.vue'),
      meta: { title: 'SNMP Configuration', icon: 'Setting' }
    },
    {
      path: '/command-templates',
      name: 'CommandTemplates',
      component: CommandTemplates,
      meta: { title: 'Command Templates', icon: 'Document' }
    },
    {
      path: '/alarms',
      name: 'Alarms',
      component: Alarms,
      meta: { title: 'Alarms & Alerts', icon: 'Bell' }
    },
    {
      path: '/optical-modules',
      name: 'OpticalModules',
      component: OpticalModules,
      meta: { title: 'Optical Modules', icon: 'Connection' }
    },
    {
      path: '/ipam/subnets/:id',
      name: 'SubnetDetail',
      component: SubnetDetail,
      meta: { title: 'Subnet Detail' }
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
