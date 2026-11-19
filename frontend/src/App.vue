<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '@/api'

const connected = ref(false)
const backendVersion = ref('')

// ---- 登录状态（v1.2.0） ----
const authChecked = ref(false)
const authEnabled = ref(false)
const authenticated = ref(true)
const password = ref('')
const loginError = ref('')
const loggingIn = ref(false)

async function checkAuth() {
  try {
    const st = await api.authStatus()
    authEnabled.value = st.auth_enabled
    authenticated.value = st.authenticated
  } catch {
    // 后端连不上时不拦登录，让顶栏的"未连接"状态说话
    authEnabled.value = false
    authenticated.value = true
  } finally {
    authChecked.value = true
  }
}

async function doLogin() {
  if (!password.value || loggingIn.value) return
  try {
    loggingIn.value = true
    loginError.value = ''
    await api.login(password.value)
    password.value = ''
    authenticated.value = true
    ElMessage.success('登录成功')
  } catch (e: any) {
    loginError.value =
      e?.response?.status === 429 ? '失败次数过多，请 5 分钟后再试' : '密码不正确'
  } finally {
    loggingIn.value = false
  }
}

async function doLogout() {
  try {
    await api.logout()
  } catch {}
  authenticated.value = false
}

function onAuthRequired() {
  if (authEnabled.value) authenticated.value = false
}

async function probe(retry = 3) {
  for (let i = 0; i < retry; i++) {
    try {
      const h: any = await api.health()
      connected.value = true
      backendVersion.value = h?.version || ''
      return
    } catch {
      await new Promise((r) => setTimeout(r, 1000))
    }
  }
  connected.value = false
}

onMounted(() => {
  checkAuth()
  probe()
  setInterval(probe, 15000)
  window.addEventListener('auth:required', onAuthRequired)
})
onUnmounted(() => {
  window.removeEventListener('auth:required', onAuthRequired)
})
</script>

<template>
  <!-- 登录页：验证开启且未登录时，挡住全部内容 -->
  <div v-if="authChecked && authEnabled && !authenticated" class="login-wrap">
    <div class="login-card">
      <div class="brand" style="justify-content:center;margin-bottom:6px">
        <span style="font-size:22px">◎</span>
        <span>Crypto Sim</span>
      </div>
      <p class="muted" style="text-align:center;margin:0 0 18px">模拟交易系统 · 请登录</p>
      <el-input
        v-model="password"
        type="password"
        placeholder="登录密码"
        size="large"
        show-password
        @keyup.enter="doLogin"
      />
      <p v-if="loginError" class="login-error">{{ loginError }}</p>
      <el-button
        type="primary"
        size="large"
        style="width:100%;margin-top:14px"
        :loading="loggingIn"
        @click="doLogin"
      >
        登录
      </el-button>
      <p class="muted" style="font-size:12px;text-align:center;margin:14px 0 0">
        本系统只做模拟交易，不涉及真实资金。
      </p>
    </div>
  </div>

  <template v-else>
    <div class="topbar">
      <div class="brand">
        <span style="font-size:18px">◎</span>
        <span>Crypto Sim</span>
      </div>
      <nav class="nav">
        <RouterLink to="/dashboard">总览</RouterLink>
        <RouterLink to="/market">行情交易</RouterLink>
        <RouterLink to="/bot">策略中心</RouterLink>
        <RouterLink to="/orders">订单记录</RouterLink>
      </nav>
      <div class="spacer" />
      <div class="status">
        <span class="dot" :class="{ ok: connected }" />
        {{ connected ? `已连接 · v${backendVersion}` : '未连接' }}
      </div>
      <el-button v-if="authEnabled" size="small" plain style="margin-left:10px" @click="doLogout">
        退出登录
      </el-button>
    </div>
    <RouterView />
  </template>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.login-card {
  width: 100%;
  max-width: 340px;
  padding: 28px 24px;
  border-radius: 16px;
  background: var(--panel-bg, rgba(255, 255, 255, 0.04));
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
}
.login-error {
  color: var(--down, #f56c6c);
  font-size: 13px;
  margin: 10px 0 0;
  text-align: center;
}
</style>
