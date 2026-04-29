import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElAlert,
  ElBadge,
  ElButton,
  ElCard,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDivider,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLink,
  ElLoading,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPageHeader,
  ElPagination,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElResult,
  ElRow,
  ElSelect,
  ElSpace,
  ElStatistic,
  ElStep,
  ElSteps,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElText,
  ElTimeline,
  ElTimelineItem,
  ElTooltip,
  ElUpload
} from 'element-plus'
import 'element-plus/dist/index.css'
import './assets/styles/global.css'
import {
  Bell,
  Clock,
  Compass,
  Connection,
  Document,
  Grid,
  Key,
  Search,
  Setting,
  Tools
} from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'

const app = createApp(App)
const pinia = createPinia()
const elementComponents = [
  ElAlert,
  ElBadge,
  ElButton,
  ElCard,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDivider,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLink,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPageHeader,
  ElPagination,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElResult,
  ElRow,
  ElSelect,
  ElSpace,
  ElStatistic,
  ElStep,
  ElSteps,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElText,
  ElTimeline,
  ElTimelineItem,
  ElTooltip,
  ElUpload
]

for (const component of elementComponents) {
  app.component(component.name, component)
}

app.component('Bell', Bell)
app.component('Clock', Clock)
app.component('Compass', Compass)
app.component('Connection', Connection)
app.component('Document', Document)
app.component('Grid', Grid)
app.component('Key', Key)
app.component('Search', Search)
app.component('Setting', Setting)
app.component('Tools', Tools)

app.use(pinia)
app.use(router)
app.use(ElLoading)

app.mount('#app')
