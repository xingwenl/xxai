/**
 * 「会话历史记录」展示模块的公共入口。
 *
 * 只导出展示组件与读侧契约类型，不含任何 HTTP 调用、后端路径或鉴权：
 * 数据由宿主实现 `ConversationHistorySource` 注入（见 ADR
 * `docs/adr/0003-conversation-history-read-boundary.md`）。
 *
 * 这里显式 import 既有的单一样式文件：宿主若只挂载 `ConversationHistory`
 * 而不加载 `ChatWidget`，消息气泡、Agent 过程卡片等既有样式仍需存在。
 * 该文件与 `ChatWidget.vue` import 的是同一份，单入口打包会去重成同一个
 * `dist/style.css`，不会新增 CSS 产物。
 */
import '../ui/styles/index.css'

export { default as ConversationList } from './ConversationList.vue'
export { default as ConversationHistory } from './ConversationHistory.vue'

export {
  mapHistoryMessage,
  mapHistoryMessages
} from './map-history'
export type { HistoryMessageLike } from './map-history'

export type {
  ConversationSummaryPayload,
  ConversationPagePayload,
  ConversationLoopStepPayload,
  ConversationLoopRunPayload,
  ConversationMessagePayload,
  ConversationListParams,
  ConversationHistorySource
} from './types'
