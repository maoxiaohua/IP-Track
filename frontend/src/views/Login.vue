<template>
  <div class="login-page">
    <el-card class="login-card" shadow="always">
      <template #header>
        <div class="login-header">
          <el-icon :size="22"><Key /></el-icon>
          <span>{{ isChangeMode ? '修改密码' : '登录 IP Track' }}</span>
        </div>
      </template>

      <el-alert
        v-if="!isChangeMode"
        class="login-tip"
        type="info"
        :closable="false"
        show-icon
        title="未登录时只能浏览和查询（只读访客）；新增、修改、删除等操作需要登录。"
      />

      <!-- Step 1: sign in -->
      <el-form
        v-if="!isChangeMode"
        ref="loginFormRef"
        :model="loginForm"
        :rules="loginRules"
        label-position="top"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="loginForm.username" autocomplete="username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="loginForm.password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入密码"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          class="login-submit"
          type="primary"
          :loading="submitting"
          :disabled="submitting"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>

      <!-- Step 2: replace a temporary password -->
      <el-form
        v-else
        ref="changeFormRef"
        :model="changeForm"
        :rules="changeRules"
        label-position="top"
        @submit.prevent="handleChangePassword"
      >
        <el-alert
          v-if="mustChange"
          class="login-tip"
          type="warning"
          :closable="false"
          show-icon
          title="当前使用的是临时密码，请先修改后再使用系统。"
        />
        <el-form-item label="当前密码" prop="currentPassword">
          <el-input v-model="changeForm.currentPassword" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="changeForm.newPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input v-model="changeForm.confirmPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <div class="login-actions">
          <el-button :disabled="submitting" @click="handleBack">返回</el-button>
          <el-button type="primary" :loading="submitting" :disabled="submitting" @click="handleChangePassword">
            保存
          </el-button>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Key } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { formatApiDetail } from '@/api/index'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const submitting = ref(false)
const loginFormRef = ref()
const changeFormRef = ref()

const mustChange = ref(false)
const forcedChange = ref(false)
const isChangeMode = computed(() => route.query.change === '1' || forcedChange.value)

const loginForm = reactive({ username: '', password: '' })
const changeForm = reactive({ currentPassword: '', newPassword: '', confirmPassword: '' })

const loginRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const changeRules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '新密码至少 8 位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string, callback: (err?: Error) => void) => {
        if (value !== changeForm.newPassword) {
          callback(new Error('两次输入的新密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

const redirectTarget = () => {
  const redirect = route.query.redirect
  return typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/'
}

const handleLogin = async () => {
  if (submitting.value) return
  const valid = await loginFormRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const user = await authStore.login(loginForm.username.trim(), loginForm.password)
    changeForm.currentPassword = loginForm.password
    loginForm.password = ''
    if (user.must_change_password) {
      mustChange.value = true
      forcedChange.value = true
      ElMessage.warning('这是临时密码，请先设置新密码')
    } else {
      ElMessage.success(`欢迎回来，${user.display_name || user.username}`)
      router.replace(redirectTarget())
    }
  } catch (error: any) {
    const message = formatApiDetail(error.response?.data?.detail) || '登录失败，请检查网络连接'
    ElMessage.error(message)
  } finally {
    submitting.value = false
  }
}

const handleChangePassword = async () => {
  if (submitting.value) return
  const valid = await changeFormRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await authStore.changePassword(changeForm.currentPassword, changeForm.newPassword)
    changeForm.currentPassword = ''
    changeForm.newPassword = ''
    changeForm.confirmPassword = ''
    ElMessage.success('密码已更新')
    router.replace(redirectTarget())
  } catch (error: any) {
    const message = formatApiDetail(error.response?.data?.detail) || '修改密码失败'
    ElMessage.error(message)
  } finally {
    submitting.value = false
  }
}

const handleBack = () => {
  forcedChange.value = false
  mustChange.value = false
  if (route.query.change === '1') {
    router.replace('/')
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 40px;
}

.login-card {
  width: 100%;
  max-width: 420px;
}

.login-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
}

.login-tip {
  margin-bottom: 18px;
}

.login-submit {
  width: 100%;
}

.login-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

@media (max-width: 768px) {
  .login-page {
    padding-top: 12px;
  }
}
</style>
