/**
 * 逐轮 / 会话用量的解析、求和与口径计算。
 *
 * 后端把每轮用量明细随 assistant 消息一起下发（实时事件 `message_completed`
 * 的 `payload.usage`、历史快照的 `usage` 字段），字段是蛇形命名；这里统一收敛
 * 成 SDK 内部的驼峰视图，并给出「缓存命中率 / 未缓存输入」两个派生口径。
 *
 * 口径与 DSH 的「本轮用量」弹层一致：
 * - 总量 = total_tokens（输入 + 输出）
 * - 缓存命中率 = 缓存读取 / 总输入
 * - 未缓存输入 = 总输入 − 缓存读取（Anthropic 的 input_tokens 已排除缓存读取，
 *   相减可能为负，按 0 截断）
 *
 * 缓存字段缺失与 0 是两件事：后端没报缓存时字段不出现，UI 据此隐藏「缓存命中」
 * 行，而不是显示一个假的 0%。
 */

export interface ModelUsage {
  promptTokens: number
  completionTokens: number
  totalTokens: number
  cacheReadTokens?: number
  cacheCreationTokens?: number
  /** 生成这条消息时实际调用的模型名（后端快照，历史消息不受后续配置影响）。 */
  model?: string
  /** 提供方标识，后端按模型 base_url 主机名推导；推导不出时省略。 */
  provider?: string
}

function asCount(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    return undefined
  }
  return Math.round(value)
}

function asText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

/**
 * 把后端下发的原始用量字典解析成 `ModelUsage`。
 *
 * 兼容蛇形（线协议）与驼峰两种拼写：实时事件与历史快照都是蛇形，但宿主实现
 * 可能自行拼装 `metadata.usage`。缺少输入/输出/总量时返回 `null`——宁可不出
 * chip，也不显示一份残缺明细。
 */
export function parseUsage(raw: unknown): ModelUsage | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return null
  }
  const source = raw as Record<string, unknown>
  const prompt = asCount(source.prompt_tokens ?? source.promptTokens)
  const completion = asCount(source.completion_tokens ?? source.completionTokens)
  let total = asCount(source.total_tokens ?? source.totalTokens)
  if (total === undefined && prompt !== undefined && completion !== undefined) {
    total = prompt + completion
  }
  if (prompt === undefined || completion === undefined || total === undefined) {
    return null
  }
  const usage: ModelUsage = {
    promptTokens: prompt,
    completionTokens: completion,
    totalTokens: total,
  }
  const cacheRead = asCount(source.cache_read_tokens ?? source.cacheReadTokens)
  if (cacheRead !== undefined) {
    usage.cacheReadTokens = cacheRead
  }
  const cacheCreation = asCount(
    source.cache_creation_tokens ?? source.cacheCreationTokens,
  )
  if (cacheCreation !== undefined) {
    usage.cacheCreationTokens = cacheCreation
  }
  const model = asText(source.model)
  if (model) {
    usage.model = model
  }
  const provider = asText(source.provider)
  if (provider) {
    usage.provider = provider
  }
  return usage
}

/**
 * 累加多条消息的用量，得到会话级合计。
 *
 * `model`/`provider` 取第一条有值的（会话里的模型可能中途换过，合计行只给
 * 一个代表值）；缓存字段只在任意一条报告过时才出现。
 */
export function sumUsage(
  usages: Iterable<ModelUsage | null | undefined>,
): ModelUsage | null {
  let result: ModelUsage | null = null
  for (const usage of usages) {
    if (!usage) continue
    if (!result) {
      result = { ...usage }
      continue
    }
    result.promptTokens += usage.promptTokens
    result.completionTokens += usage.completionTokens
    result.totalTokens += usage.totalTokens
    if (usage.cacheReadTokens !== undefined) {
      result.cacheReadTokens =
        (result.cacheReadTokens ?? 0) + usage.cacheReadTokens
    }
    if (usage.cacheCreationTokens !== undefined) {
      result.cacheCreationTokens =
        (result.cacheCreationTokens ?? 0) + usage.cacheCreationTokens
    }
  }
  return result
}

/**
 * 缓存命中率（0–100 的整数）。
 *
 * 分母用总输入而不是「缓存读取 + 未缓存输入」：两者在 OpenAI/DeepSeek 口径下
 * 相等，在异常数据下取总输入更不容易出现分母为 0 的抖动。provider 没报缓存
 * 或没有输入 token 时返回 `null`。
 */
export function cacheHitPercent(usage: ModelUsage): number | null {
  if (usage.cacheReadTokens === undefined || usage.promptTokens <= 0) {
    return null
  }
  const ratio = Math.min(1, usage.cacheReadTokens / usage.promptTokens)
  return Math.round(ratio * 100)
}

/** 未缓存输入 token 数；provider 没报缓存时返回 `null`。 */
export function uncachedPromptTokens(usage: ModelUsage): number | null {
  if (usage.cacheReadTokens === undefined) {
    return null
  }
  return Math.max(0, usage.promptTokens - usage.cacheReadTokens)
}
