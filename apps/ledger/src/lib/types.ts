/** 记账子应用的核心数据模型与默认分类，字段名与宿主侧契约保持一致，不要随意改动。 */

/** 记录类型：支出 / 收入。 */
export type EntryType = 'expense' | 'income'

/** 一条记账记录；金额一律以「分」存储，避免浮点误差。 */
export interface LedgerEntry {
  id: string
  type: EntryType
  amount_cents: number
  category: string
  note: string
  /** 发生日期，YYYY-MM-DD */
  occurred_on: string
  /** 创建时间，ISO 字符串 */
  created_at: string
}

/** 持久化到宿主的完整数据快照。 */
export interface LedgerData {
  version: 1
  entries: LedgerEntry[]
  categories: { expense: string[]; income: string[] }
  updated_at: string
}

/** 月度汇总（工具返回值与界面共用）。 */
export interface MonthSummary {
  month: string
  expense_yuan: number
  income_yuan: number
  balance_yuan: number
}

/** 带分类拆分的月度汇总。 */
export interface MonthSummaryDetail extends MonthSummary {
  by_category: Array<{ category: string; expense_yuan: number; income_yuan: number; count: number }>
}

/** 列表项：在原始记录上补一个「元」金额，方便界面直接渲染。 */
export interface LedgerEntryView extends LedgerEntry {
  amount_yuan: number
}

/** 内置分类；自定义分类按追加顺序排在后面。 */
export const DEFAULT_CATEGORIES: { expense: string[]; income: string[] } = {
  expense: ['餐饮', '交通', '购物', '居住', '娱乐', '医疗', '学习', '其他'],
  income: ['工资', '奖金', '理财', '其他收入'],
}

/** 生成一份空数据，用作首次启动与重置的初始快照。 */
export function emptyLedgerData(): LedgerData {
  return {
    version: 1,
    entries: [],
    categories: { expense: [...DEFAULT_CATEGORIES.expense], income: [...DEFAULT_CATEGORIES.income] },
    updated_at: new Date().toISOString(),
  }
}
