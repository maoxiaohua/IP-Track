import { createRouter, createWebHistory } from 'vue-router'

const Home = () => import('@/views/Home.vue')
const Switches = () => import('@/views/Switches.vue')
const SwitchDetail = () => import('@/views/SwitchDetail.vue')
const Topology = () => import('@/views/Topology.vue')
const History = () => import('@/views/History.vue')
const Discovery = () => import('@/views/Discovery.vue')
const IPAM = () => import('@/views/IPAM_Simple.vue')
const SubnetDetail = () => import('@/views/SubnetDetail_SolarWinds.vue')
const CommandTemplates = () => import('@/views/CommandTemplates.vue')
const Alarms = () => import('@/views/Alarms.vue')
const OpticalModules = () => import('@/views/OpticalModules.vue')
const OSTypeIPList = () => import('@/views/OSTypeIPList.vue')
const SNMPProfiles = () => import('@/views/SNMPProfiles.vue')
const SNMPConfig = () => import('@/views/SNMPConfig.vue')
const Settings = () => import('@/views/Settings.vue')
const BMCReset = () => import('@/views/BMCReset.vue')
const SubnetProbe = () => import('@/views/SubnetProbe.vue')
const VisioViewer = () => import('@/views/VisioViewer.vue')
const Login = () => import('@/views/Login.vue')

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
      path: '/topology',
      name: 'Topology',
      component: Topology,
      meta: { title: 'Network Topology', icon: 'Share' }
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
      path: '/ipam/os-type',
      name: 'OSTypeIPList',
      component: OSTypeIPList,
      meta: { title: 'OS 设备清单' }
    },
    {
      path: '/history',
      name: 'History',
      component: History,
      meta: { title: 'Query History' }
    },
    {
      path: '/bmc-reset',
      name: 'BMCReset',
      component: BMCReset,
      meta: { title: 'BMC Reset', icon: 'Cpu' }
    },
    {
      path: '/subnet-probe',
      name: 'SubnetProbe',
      component: SubnetProbe,
      meta: { title: '子网存活快速探测', icon: 'Search' }
    },
    {
      path: '/visio',
      name: 'VisioViewer',
      component: VisioViewer,
      meta: { title: 'Visio 图纸查看', icon: 'Document' }
    },
    {
      // Login (and temporary-password change). Browsing stays open to guests.
      path: '/login',
      name: 'Login',
      component: Login,
      meta: { title: '登录' }
    }
  ]
})

router.beforeEach((to, _from, next) => {
  void _from
  document.title = `${to.meta.title} - IP Track System` || 'IP Track System'
  next()
})

export default router
