// 书签整理助手 popup：读取全部书签并上报到桌面应用内嵌 API

const API_BASE = 'http://127.0.0.1:8765'

const btn = document.getElementById('collectBtn')
const statusEl = document.getElementById('status')
const resultEl = document.getElementById('result')

function setStatus(text, kind) {
  statusEl.textContent = text
  statusEl.className = `status ${kind || ''}`
  statusEl.classList.remove('hidden')
}

function setBusy(busy) {
  btn.disabled = busy
  btn.textContent = busy ? '整理中…' : '整理书签'
}

async function collect() {
  setBusy(true)
  setStatus('正在读取收藏的书签…', 'info')
  try {
    const tree = await chrome.bookmarks.getTree()
    const payload = []
    // 递归遍历书签树：文件夹节点无 url，仅收集叶子书签并记录所属文件夹路径
    function walk(nodes, path) {
      for (const node of nodes) {
        if (node.url) {
          payload.push({
            id: String(node.id),
            title: node.title || '',
            url: node.url,
            folderPath: path,
          })
        }
        if (node.children) {
          walk(node.children, path ? `${path}/${node.title}` : node.title)
        }
      }
    }
    walk(tree, '')
    setStatus(`已读取 ${payload.length} 个书签，正在上报…`, 'info')

    const resp = await fetch(`${API_BASE}/api/desktop/bookmarks/collect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: 'chrome-extension', bookmarks: payload }),
    })
    if (!resp.ok) {
      let detail = ''
      try {
        detail = (await resp.json()).detail || ''
      } catch {
        // 响应体不是 JSON 时忽略
      }
      throw new Error(detail || `上报失败（HTTP ${resp.status}）`)
    }

    const data = await resp.json()
    document.getElementById('total').textContent = String(data.total)
    document.getElementById('unique').textContent = String(data.unique)
    document.getElementById('groups').textContent = String(data.groups.length)
    resultEl.classList.remove('hidden')
    setStatus('整理完成，请到桌面应用查看', 'success')
  } catch (err) {
    const msg = String((err && err.message) || err)
    const hint = /fetch|network|ERR_|failed to fetch/i.test(msg)
      ? '无法连接桌面应用，请先启动 ai-base 桌面应用后重试'
      : msg
    setStatus(hint, 'error')
  } finally {
    setBusy(false)
  }
}

btn.addEventListener('click', collect)
