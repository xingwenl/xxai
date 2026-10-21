import type {
  AgentSwitchFailureReason,
  AgentSwitchOption,
  AgentSwitchingOptions
} from './types'

/**
 * 智能体切换的纯函数集合。
 *
 * 把「候选列表怎么判有效、endpoint 怎么换 agent、选中项存在哪、失败怎么
 * 分类成用户可读文案」从 `AgentClient` 里拆出来：这些规则都有兜底分支
 * （无 localStorage、非标准 endpoint、宿主抛 AxiosError），单独测试比在
 * 一千多行的客户端里测更可靠。设计依据见
 * `docs/adr/0014-host-provided-agent-switching.md`。
 */

/** 记住「上次选中的 agent」的 localStorage key 前缀。 */
const SELECTED_AGENT_KEY_PREFIX = 'xxai-agent:selected-agent:'

/** 宿主提供的候选列表里，只有同时具备合法 agentId 与 name 的项才可渲染。 */
export function isValidAgentOption(value: unknown): value is AgentSwitchOption {
  if (!value || typeof value !== 'object') return false
  const option = value as Record<string, unknown>
  const agentId = option.agentId
  const hasId =
    (typeof agentId === 'number' && Number.isFinite(agentId)) ||
    (typeof agentId === 'string' && agentId.trim() !== '')
  return hasId && typeof option.name === 'string' && option.name.trim() !== ''
}

/**
 * 归一化候选列表与本地开关。
 *
 * 默认 `enabled: true`：宿主传了列表就默认展示，只有显式 `enabled: false`
 * 才隐藏。后台开关不在这里判断，由客户端在 `session_ready` 后合并。
 */
export function resolveAgentSwitchingOptions(
  raw: AgentSwitchingOptions | undefined
): { agents: AgentSwitchOption[]; enabled: boolean } {
  const agents = Array.isArray(raw?.agents)
    ? raw.agents.filter(isValidAgentOption)
    : []
  return { agents, enabled: raw?.enabled !== false }
}

/** 把 agent id 统一成字符串，便于与 token/WS 路径和 localStorage 比较。 */
export function normalizeAgentId(agentId: number | string): string {
  return String(agentId)
}

/** 在候选列表里按 id 查找（容忍 number/string 混用）。 */
export function findAgentOption(
  agents: AgentSwitchOption[],
  agentId: number | string
): AgentSwitchOption | undefined {
  const target = normalizeAgentId(agentId)
  return agents.find((option) => normalizeAgentId(option.agentId) === target)
}

/**
 * 记住选中项的存储 key：按平台 + 终端用户维度隔离。
 *
 * 不含 agentId —— 这个 key 存的就是「用户选了哪个 agent」。匿名用户回退到
 * `anonymous`，与消息存储的隔离维度保持一致。
 */
export function buildSelectionStorageKey(
  platformId: string,
  userId: string | undefined
): string {
  return `${SELECTED_AGENT_KEY_PREFIX}${platformId}:${userId || 'anonymous'}`
}

/** 读取上次选中的 agent；存储不可用或内容非法时返回 null。 */
export function readSelectedAgent(key: string): string | null {
  try {
    const value = globalThis.localStorage?.getItem(key)
    return typeof value === 'string' && value.trim() ? value : null
  } catch {
    return null
  }
}

/** 记住选中的 agent；写入失败（隐私模式/超容量）时静默降级。 */
export function writeSelectedAgent(key: string, agentId: number | string): void {
  try {
    globalThis.localStorage?.setItem(key, normalizeAgentId(agentId))
  } catch {
    // 记忆是体验增强而非功能前提，存储不可用时忽略。
  }
}

/** 清除选中的 agent（后台关闭切换能力时调用）。 */
export function clearSelectedAgent(key: string): void {
  try {
    globalThis.localStorage?.removeItem(key)
  } catch {
    // 同上：清理失败不影响本次回退。
  }
}

/**
 * 由当前 endpoint 推导目标 agent 的 WS 地址。
 *
 * 网关路径固定为 `/ws/agents/{agentId}`，而 embed token 的 `agent_id` 必须与
 * 路径一致，所以切换 agent 必须同时改路径。宿主自定义 endpoint（例如
 * `VITE_AGENT_WS_URL` 指向一个不含 agent 段的固定网关）无法推导时返回 null，
 * 由调用方拒绝切换而不是把 token 发到错误路径。
 */
export function deriveAgentEndpoint(
  endpoint: string,
  targetAgentId: number | string
): string | null {
  if (typeof endpoint !== 'string' || !endpoint) return null
  const pattern = /\/ws\/agents\/[^/?#]+/
  if (!pattern.test(endpoint)) return null
  return endpoint.replace(pattern, `/ws/agents/${normalizeAgentId(targetAgentId)}`)
}

/**
 * 把换 token 失败归类成用户可理解的 reason。
 *
 * 宿主 `getToken` 通常是 axios 请求，失败原因藏在 `response.status`；SDK 自身
 * 的 `AgentError` 则可能带 `code`。分类只影响文案，不影响「失败即回滚」。
 */
export function classifyTokenFailure(error: unknown): AgentSwitchFailureReason {
  const status = readHttpStatus(error)
  if (status === 401 || status === 403) return 'not_bound'
  if (status === 429) return 'quota'
  const code = readErrorCode(error)
  if (typeof code === 'string' && /unauthori[sz]ed|forbidden|not_bound/i.test(code)) {
    return 'not_bound'
  }
  return 'network'
}

/** 失败文案：明确区分「没权限」与「临时失败」，避免用户反复重试无权限的选项。 */
export function formatAgentSwitchError(
  reason: AgentSwitchFailureReason
): string {
  switch (reason) {
    case 'not_allowed':
      return '当前接入未开启智能体切换'
    case 'not_supported':
      return '当前接入地址不支持切换智能体'
    case 'busy':
      return '正在生成回答，请稍后再切换'
    case 'not_bound':
      return '该智能体未授权给当前接入方'
    case 'quota':
      return '请求过于频繁或额度不足，请稍后再试'
    case 'connection_failed':
      return '已切换智能体，但连接失败，请重试'
    default:
      return '切换智能体失败，请检查网络后重试'
  }
}

function readHttpStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined
  const response = (error as { response?: unknown }).response
  if (!response || typeof response !== 'object') return undefined
  const status = (response as { status?: unknown }).status
  return typeof status === 'number' ? status : undefined
}

function readErrorCode(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined
  const code = (error as { code?: unknown }).code
  return typeof code === 'string' ? code : undefined
}
