import { createRouter, createWebHistory } from 'vue-router'

const Home = () => import('@/views/Home.vue')
const Switches = () => import('@/views/Switches.vue')
const SwitchDetail = () => import('@/views/SwitchDetail.vue')
const History = () => import('@/views/History.vue')
const Discovery = () => import('@/views/Discovery.vue')
const IPAM = () => import('@/views/IPAM_Simple.vue')
const SubnetDetail = () => import('@/views/SubnetDetail_SolarWinds.vue')
const CommandTemplates = () => import('@/views/CommandTemplates.vue')
const Alarms = () => import('@/views/Alarms.vue')
const OpticalModules = () => import('@/views/OpticalModules.vue')
const SNMPProfiles = () => import('@/views/SNMPProfiles.vue')
const SNMPConfig = () => import('@/views/SNMPConfig.vue')
const Settings = () => import('@/views/Settings.vue')

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior() {
    return { top: 0 }
  },
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
      path: '/snmp-profiles',
      name: 'SNMPProfiles',
      component: SNMPProfiles,
      meta: { title: 'SNMP Profiles', icon: 'Key' }
    },
    {
      path: '/snmp-config',
      name: 'SNMPConfig',
      component: SNMPConfig,
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
      path: '/settings',
      name: 'Settings',
      component: Settings,
      meta: { title: 'Settings', icon: 'Setting' }
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
