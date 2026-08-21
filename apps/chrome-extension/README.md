# 书签整理助手（Chrome 扩展）

读取 Chrome 浏览器收藏的书签（标题、URL、所属文件夹），一键整理汇总到 ai-base 桌面应用。

## 安装（加载已解压的扩展程序）

1. 启动 ai-base 桌面应用（`cd apps/desktop && poetry run python -m desktop_app`）。
2. 打开 Chrome，访问 `chrome://extensions`。
3. 打开右上角「开发者模式」开关。
4. 点击「加载已解压的扩展程序」，选择本目录 `apps/chrome-extension/`。
5. 在 Chrome 工具栏点击「书签整理助手」图标，点击「整理书签」。
6. 回到桌面应用，在左侧导航打开「书签整理」即可查看分组汇总。

## 工作原理

- 扩展通过 `chrome.bookmarks.getTree()`（`bookmarks` 权限）读取收藏夹全部书签，并记录所属文件夹路径；
- 点击「整理书签」后，将书签列表 POST 到 `http://127.0.0.1:8765/api/desktop/bookmarks/collect`；
- 桌面应用在本地完成过滤（剔除 `chrome://` 等内部页面）、URL 去重、按域名分组并保存快照；
- 宿主「书签整理」页面通过 `GET /api/desktop/bookmarks/summary` 展示最近一次整理结果。

## 说明

- 数据只在本机流转（Chrome → `127.0.0.1:8765`），不上传公网；
- 若桌面应用未启动，扩展会提示「无法连接桌面应用」；
- 书签数据仅含标题、URL 与所属文件夹路径，不包含登录态或 Cookie。
