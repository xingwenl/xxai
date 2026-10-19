/**
 * SDK 统一错误形状。
 *
 * 改造前同一个失败会产生三种面：`onError` 收到只带 message 的 `Error`
 * （code/retryable 全丢）、`agent.on('error')` 收到裸 payload 对象、`connect()`
 * 的 reject 只带一句 message。调用方无法按码分支，也无法判断能否重试。
 *
 * 现在所有失败都归一成 `AgentError`：它仍是 `Error` 的实例（`instanceof Error`
 * 与 `error.message` 等既有用法不变），额外挂上 `code`/`retryable`/`requestId`/
 * `details` 四个结构化字段。
 */

export interface AgentError extends Error {
  /** 稳定业务错误码，例如 `chat_model_unavailable`、`unsupported_sdk_version`。 */
  code?: string
  /** 是否值得重试。由服务端给出，SDK 不自行推断。 */
  retryable?: boolean
  /** 关联的请求 ID，便于与服务端日志对齐。 */
  requestId?: string
  /** 附加诊断信息（例如 `minimumSdkVersion`、`supportedProtocolVersion`）。 */
  details?: Record<string, unknown>
}

/** 判断任意值是否为 SDK 归一化后的错误。 */
export function isAgentError(value: unknown): value is AgentError {
  return value instanceof Error && value.name === 'AgentError'
}

/**
 * 把服务端 payload 或普通 Error 归一成 `AgentError`。
 *
 * `message` 的取值顺序与改造前保持一致（先 payload.message，再 payload.code，
 * 最后回退文案），因此既有断言 `toContain('HTTP 502')` 之类的用例不受影响。
 */
export function agentError(
  input: unknown,
  fallbackMessage = '请求失败'
): AgentError {
  if (isAgentError(input)) return input

  if (input instanceof Error) {
    const error = input as AgentError
    error.name = 'AgentError'
    return error
  }

  const payload =
    typeof input === 'object' && input !== null
      ? (input as Record<string, unknown>)
      : {}

  const message =
    typeof payload.message === 'string' && payload.message
      ? payload.message
      : typeof payload.code === 'string' && payload.code
        ? payload.code
        : fallbackMessage

  const error = new Error(message) as AgentError
  error.name = 'AgentError'
  if (typeof payload.code === 'string') error.code = payload.code
  if (typeof payload.retryable === 'boolean') error.retryable = payload.retryable
  if (typeof payload.requestId === 'string') error.requestId = payload.requestId
  if (typeof payload.details === 'object' && payload.details !== null) {
    error.details = payload.details as Record<string, unknown>
  }
  return error
}

/** HTTP 状态码回退的可重试判断：5xx 与 429 视为可重试。 */
function retryableFromStatus(status: number): boolean {
  return status >= 500 || status === 429
}

/**
 * 把 REST 失败响应归一成 `AgentError`。
 *
 * 后端统一响应体是 `{ success, message, data, meta, code, error_code }`，其中
 * `code` 是 HTTP 状态码（数字）、`error_code` 才是稳定业务码。因此业务码取
 * `error_code`；为兼容旧响应，若 `code` 是字符串也接受；两者都没有时回落
 * `http_<status>`，保证调用方拿到的 `code` 恒非空。
 */
export async function agentErrorFromResponse(
  response: { status: number; json: () => Promise<unknown> },
  fallbackMessage: string
): Promise<AgentError> {
  let body: Record<string, unknown> = {}
  try {
    const parsed = await response.json()
    if (typeof parsed === 'object' && parsed !== null) {
      body = parsed as Record<string, unknown>
    }
  } catch {
    // 响应体不是 JSON（例如网关直接返回 HTML 错误页）时只用状态码。
  }

  const code =
    typeof body.error_code === 'string' && body.error_code
      ? body.error_code
      : typeof body.code === 'string' && body.code
        ? body.code
        : `http_${response.status}`

  const message =
    typeof body.message === 'string' && body.message
      ? body.message
      : `${fallbackMessage}: ${response.status}`

  const error = agentError({ code, message, retryable: retryableFromStatus(response.status) })
  if (typeof body.details === 'object' && body.details !== null) {
    error.details = body.details as Record<string, unknown>
  }
  return error
}
