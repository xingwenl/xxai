import axios, { AxiosError, AxiosHeaders } from 'axios'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'

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

http.interceptors.request.use((config) => {
  const token =
    typeof localStorage !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null
  if (token) {
    const headers = AxiosHeaders.from(config.headers)
    headers.set('Authorization', `Bearer ${token}`)
    config.headers = headers
  }
  clearEmptyDataInterceptor(config)
  console.log('config.clearEmptyData', config)
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
        useAuthStore.getState().auth.reset()
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
        useAuthStore.getState().auth.reset()
      }
    }
    return Promise.reject(error)
  }
)
