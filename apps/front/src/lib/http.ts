import axios, { AxiosError, AxiosHeaders } from 'axios'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'

/**
 * 旁路/可选请求可声明「本次 401 只让该请求失败，不清空登录态」。
 *
 * 调用方用交叉类型扩展 axios 的请求配置（`AxiosRequestConfig & AuthResetOptOut`），
 * 不用 module augmentation 扩 axios：那会引入 any 与未使用的类型参数。
 */
export type AuthResetOptOut = { skipAuthReset?: boolean }

const TOKEN_KEY = 'chat_token'

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '',
  timeout: 10_000,
})

type ApiEnvelope<T> = {
  code: number
  data?: T
  message: string
}


function clearEmptyDataInterceptor(config: any) {
  if (config.clearEmptyData && config.data) {
  
    const data = typeof config.data === 'object' ? config.data : JSON.parse(config.data)
    console.log('data', data)
    // const cleanedData = Object.fromEntries(
    //   Object.entries(data).filter(
    //     ([_, value]) => value !== null && value !== undefined && value !== ''
    //   )
    // )
    // config.data = JSON.stringify(cleanedData)
  }
}

/**
 * 统一处理 401 的登出副作用。
 *
 * 只有「会话级」请求的 401 才清空登录态；声明了 `skipAuthReset` 的旁路请求
 * 只让调用方自己失败，避免一个可选能力（例如悬浮 Agent 桥接换 embed token）
 * 配置不符就把用户踢回登录页。
 */
function resetAuthUnlessAuxiliary(config: unknown) {
  const optOut = (config as AuthResetOptOut | undefined)?.skipAuthReset === true
  if (optOut) return
  useAuthStore.getState().auth.reset()
}

http.interceptors.request.use((config) => {
  const token =
    typeof localStorage !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null
  if (token) {
    const headers = AxiosHeaders.from(config.headers)
    headers.set('Authorization', `Bearer ${token}`)
    config.headers = headers
  }
  clearEmptyDataInterceptor(config)
  return config
})

http.interceptors.response.use(
  (r) => {
    const payload = r.data as ApiEnvelope<unknown> | unknown

    if (payload && typeof payload === 'object' && 'code' in payload) {
      const envelope = payload as ApiEnvelope<unknown>

      if ([0, 200].includes(Number(envelope.code))) {
        return { ...r, data: envelope.data }
      } else if (Number(envelope.code) === 401) {
        resetAuthUnlessAuxiliary(r.config)
      }
      const message =
        typeof envelope.message === 'string'
          ? envelope.message
          : 'Request failed'
      toast.error(message)
      return Promise.reject(new Error(message))
    }
    return r
  },
  (error) => {
    if (error instanceof AxiosError) {
      const status = error.response?.status
      if (status === 401) {
        resetAuthUnlessAuxiliary(error.config)
      }
    }
    return Promise.reject(error)
  }
)
