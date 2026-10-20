/** 金额与日期格式化工具：对外展示统一走这里，避免各处舍入规则不一致。 */

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/
const WEEK_LABELS = ['日', '一', '二', '三', '四', '五', '六']

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

/** 今天（浏览器本地时区）的 YYYY-MM-DD。 */
export function todayISO(): string {
  const now = new Date()
  return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`
}

/** 当前月份，YYYY-MM。 */
export function currentMonth(): string {
  return todayISO().slice(0, 7)
}

/** 判断是否为合法的 YYYY-MM。 */
export function isMonth(value: string): boolean {
  return MONTH_RE.test(value)
}

/** 判断是否为合法的 YYYY-MM-DD（含日历有效性校验）。 */
export function isDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false
  return !Number.isNaN(new Date(`${value}T00:00:00`).getTime())
}

/** 元（用户输入，最多两位小数）转分；非法或非正数返回 null。 */
export function yuanToCents(input: string): number | null {
  const text = input.trim()
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return null
  const yuan = Number(text)
  if (!Number.isFinite(yuan)) return null
  const cents = Math.round(yuan * 100)
  return cents > 0 ? cents : null
}

/** 分转元，保留两位小数（用于返回值里的 amount_yuan 等字段）。 */
export function centsToYuan(cents: number): number {
  return Number((cents / 100).toFixed(2))
}

/** 分转 '12.34' 字符串。 */
export function formatCents(cents: number): string {
  return (cents / 100).toFixed(2)
}

/** 元转 '12.34' 字符串。 */
export function formatYuan(yuan: number): string {
  return yuan.toFixed(2)
}

/** 元转带符号金额文案：'¥12.34' / '-¥12.34'。 */
export function formatMoney(yuan: number): string {
  const sign = yuan < 0 ? '-' : ''
  return `${sign}¥${Math.abs(yuan).toFixed(2)}`
}

/** 明细列表里的日期文案：'05-03 周五'。 */
export function formatDateLabel(value: string): string {
  if (!isDate(value)) return value
  const date = new Date(`${value}T00:00:00`)
  return `${value.slice(5)} 周${WEEK_LABELS[date.getDay()]}`
}
