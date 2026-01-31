<template>
  <div class="ip-lookup-form">
    <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="handleSubmit">
      <el-form-item prop="ipAddress">
        <el-input
          v-model="form.ipAddress"
          placeholder="Enter IP address (e.g., 192.168.1.100)"
          size="large"
          clearable
          @keyup.enter="handleSubmit"
        >
          <template #prepend>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item>
        <el-button
          type="primary"
          size="large"
          :loading="lookupStore.loading"
          @click="handleSubmit"
          style="width: 100%"
        >
          <el-icon v-if="!lookupStore.loading"><Search /></el-icon>
          {{ lookupStore.loading ? 'Searching...' : 'Lookup IP Address' }}
        </el-button>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="lookupStore.error"
      type="error"
      :title="lookupStore.error"
      :closable="true"
      @close="lookupStore.clearResult"
      show-icon
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useLookupStore } from '@/stores/lookup'

const lookupStore = useLookupStore()
const formRef = ref<FormInstance>()

const form = reactive({
  ipAddress: ''
})

// IP address validation
const validateIP = (rule: any, value: string, callback: any) => {
  if (!value) {
    callback(new Error('Please enter an IP address'))
    return
  }

  // Basic IPv4 validation
  const ipv4Regex = /^(\d{1,3}\.){3}\d{1,3}$/
  if (!ipv4Regex.test(value)) {
    callback(new Error('Please enter a valid IPv4 address'))
    return
  }

  // Check each octet is 0-255
  const octets = value.split('.')
  for (const octet of octets) {
    const num = parseInt(octet, 10)
    if (num < 0 || num > 255) {
      callback(new Error('Each octet must be between 0 and 255'))
      return
    }
  }

  callback()
}

const rules: FormRules = {
  ipAddress: [
    { required: true, message: 'IP address is required', trigger: 'blur' },
    { validator: validateIP, trigger: 'blur' }
  ]
}

const handleSubmit = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (valid) {
      await lookupStore.lookupIP(form.ipAddress)

      if (lookupStore.currentResult?.found) {
        ElMessage.success('Device found successfully!')
      }
    }
  })
}
</script>

<style scoped>
.ip-lookup-form {
  margin-bottom: 20px;
}

.el-alert {
  margin-top: 16px;
}
</style>
