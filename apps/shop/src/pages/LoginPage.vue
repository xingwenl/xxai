<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { decodeShopJwt, fetchCaptcha, login } from '../lib/hua8'
import { saveSession } from '../lib/session'

const router = useRouter()

const username = ref('')
const password = ref('')
const code = ref('')
const uuid = ref('')
const captchaImg = ref('')
const captchaEnabled = ref(true)
const error = ref('')
const submitting = ref(false)

async function loadCaptcha() {
  try {
    const captcha = await fetchCaptcha()
    uuid.value = captcha.uuid
    captchaImg.value = captcha.img
    captchaEnabled.value = captcha.captchaEnabled
  } catch {
    captchaEnabled.value = false
  }
}

async function submit() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = '请输入账号和密码'
    return
  }
  if (captchaEnabled.value && !code.value) {
    error.value = '请输入验证码'
    return
  }
  submitting.value = true
  try {
    const result = await login(username.value, password.value, code.value, uuid.value)
    const payload = decodeShopJwt(result.accessToken)
    const userId = String(payload.user_id ?? '')
    if (!userId) throw new Error('登录响应缺少用户信息，请重新登录')
    saveSession({
      shopToken: result.accessToken,
      shopUserId: userId,
      displayName: payload.username ?? '',
      expiresIn: result.expiresIn,
    })
    await router.push('/chat')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '登录失败，请重试'
    code.value = ''
    await loadCaptcha()
  } finally {
    submitting.value = false
  }
}

onMounted(loadCaptcha)
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1>店铺运营智能助手</h1>
      <p class="subtitle">请使用店铺运营平台账号登录，登录后可向智能体查询「我的店铺」等信息</p>
      <form @submit.prevent="submit">
        <label>
          <span>账号</span>
          <input v-model="username" type="text" autocomplete="username" placeholder="请输入账号" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" />
        </label>
        <label v-if="captchaEnabled">
          <span>验证码</span>
          <div class="captcha-row">
            <input v-model="code" type="text" placeholder="请输入验证码" />
            <img
              v-if="captchaImg"
              class="captcha-img"
              alt="验证码"
              :src="`data:image/png;base64,${captchaImg}`"
              @click="loadCaptcha"
            />
          </div>
        </label>
        <p v-if="error" class="error">{{ error }}</p>
        <button type="submit" :disabled="submitting">
          {{ submitting ? '登录中…' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-card {
  width: 380px;
  padding: 32px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
}

h1 {
  margin: 0 0 8px;
  font-size: 22px;
}

.subtitle {
  margin: 0 0 24px;
  font-size: 13px;
  color: #8a919f;
}

label {
  display: block;
  margin-bottom: 16px;
}

label span {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: #4b5563;
}

input {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: 1px solid #d8dce3;
  border-radius: 8px;
  font-size: 14px;
}

.captcha-row {
  display: flex;
  gap: 8px;
}

.captcha-row input {
  flex: 1;
}

.captcha-img {
  height: 40px;
  border: 1px solid #d8dce3;
  border-radius: 8px;
  cursor: pointer;
}

.error {
  color: #e5484d;
  font-size: 13px;
  margin: 0 0 12px;
}

button {
  width: 100%;
  height: 42px;
  border: 0;
  border-radius: 8px;
  background: #0f766e;
  color: #fff;
  font-size: 15px;
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
