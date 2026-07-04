---
name: "verify-frontend-navigation"
description: "Validates all frontend page navigation links and routing paths. Invoke after modifying URLs, route configs, or docker volume mounts, and before deployment."
---

# 前端页面跳转自动化验证

修改前端连接 URL、路由配置或 Docker 挂载后，自动遍历全部页面跳转路径，验证可达性并生成报告。

## 触发条件

**必须调用此技能**：
- 修改了任何前端文件中的 URL / 路径 / `href` / `location.href` / `window.location`
- 修改了 `docker-compose.yml` 中的 frontend / api-gateway volume 挂载或 `--directory` 参数
- 修改了 `nginx` / `http.server` 等静态文件服务配置
- 修改了 SPA 路由配置（hash route / path route）
- 部署前的最终验证
- 用户明确要求验证前端跳转

**可选调用**：
- 修改了后端 API 路径前缀（可能影响前端 API 调用）

## 第一步：建立跳转关系图谱

扫描项目所有前端 HTML 文件，提取跳转目标，构建图谱。

### 扫描范围

| 目录 | 文件 | 说明 |
|------|------|------|
| `app/` | `index.html`, `login.html` | 系统选择页 + 登录页 |
| `station/warehouse-inspection-system/frontend/` | `index.html` | 基站 SPA |
| `drone/drone-db-prototype/frontend/` | `**/*.html` | 无人机前端 |

### 提取规则

使用 Grep 工具搜索以下模式，提取所有跳转目标：

```
# 1. HTML href 属性
href="..."          → 非锚点(#xxx)且非javascript:的链接

# 2. JS 跳转
location.href = '...' | location.href='...'
location.replace('...')
window.location = '...'
window.location.href = '...'

# 3. meta refresh
http-equiv="refresh" content="0;url=..."

# 4. SPA hash 路由
window.location.hash = '...'
location.hash = '...'
```

### 图谱格式

将提取结果存储为跳转图谱（内存中即可，不持久化）：

```json
{
  "pages": [
    {
      "file": "app/index.html",
      "access_urls": [
        "http://localhost:3000/",
        "http://localhost:3000/app/index.html",
        "http://localhost:8080/app/"
      ],
      "outgoing_links": [
        { "target": "station/warehouse-inspection-system/frontend/index.html", "url": "/station/warehouse-inspection-system/frontend/index.html", "source_line": 203, "trigger": "warehouseCard click" },
        { "target": "drone/drone-db-prototype/frontend/src/index.html", "url": "/drone/drone-db-prototype/frontend/src/index.html", "source_line": 202, "trigger": "droneCard click" }
      ]
    }
  ]
}
```

## 第二步：检测变更触发

当以下文件发生变更时，标记需要重新验证：

| 文件 | 变更类型 | 影响范围 |
|------|----------|----------|
| `docker-compose.yml` | volume 挂载 / command / ports | 全部跳转路径 |
| `app/api-gateway/main.py` | 子页面路由 / 静态文件路径 | 8080 端口所有路由 |
| `app/index.html` | href / location.href | 系统选择页跳转 |
| `app/login.html` | href / API URL | 登录流程 |
| `station/.../frontend/index.html` | href / location / hash 路由 | 基站内部 + 外部跳转 |
| `app/root-index.html` | meta refresh | 根路径跳转 |

若用户未明确指定验证范围，则全量验证。

## 第三步：执行跳转测试

对图谱中每条跳转路径，在 **两个端口** 上分别测试：

### 测试端口

| 端口 | 服务 | 说明 |
|------|------|------|
| 3000 | frontend 容器 (`python -m http.server`) | 直接静态文件服务 |
| 8080 | api-gateway (FastAPI 子页面路由) | SPA 路由代理 |

### 测试方法

使用 `curl -s -o /dev/null -w "%{http_code}"` 对每个跳转 URL 发起 HTTP GET：

```bash
# 对于绝对路径跳转
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/station/warehouse-inspection-system/frontend/index.html
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/station/warehouse-inspection-system/frontend/index.html

# 对于 meta refresh 跳转，验证 refresh 目标
curl -s http://localhost:3000/ | grep -o 'url=[^"]*'
# 然后验证 refresh 目标可达
```

### 判定标准

| HTTP 状态码 | 判定 | 说明 |
|-------------|------|------|
| 200 | PASS | 页面可正常访问 |
| 301/302 | PASS (需验证目标) | 重定向，需跟随验证最终目标 |
| 404 | FAIL | 页面不存在 |
| 403 | FAIL | 权限不足 |
| 500 | FAIL | 服务端错误 |
| 连接拒绝 | FAIL | 服务未启动或端口错误 |

### SPA 内部路由验证

对于 SPA hash 路由（如 `#dashboard`, `#inventory`），验证策略：
1. 确认宿主页面（index.html）返回 200
2. 确认页面 JS 中存在对应的 hash 路由处理逻辑（Grep 搜索 `hash === 'xxx'` 或 `route.includes('xxx')`）
3. 无需实际浏览器渲染测试

## 第四步：生成验证报告

### 报告格式

```
━━━ 前端跳转验证报告 ━━━
时间: 2026-07-05 12:00:00
触发原因: docker-compose.yml frontend volumes 变更

── 验证摘要 ──
  总跳转数:    12
  通过:        10 (83.3%)
  失败:         2 (16.7%)
  跳过:         0

── 端口 3000 ──
  [PASS] / → /app/index.html (meta refresh)
  [PASS] /app/index.html → 系统选择页
  [PASS] /app/index.html → /station/.../index.html (基站前端)
  [FAIL] /app/index.html → /drone/.../src/index.html → HTTP 404
         ↑ 文件: app/index.html:202 | 原因: drone 前端未部署
  [PASS] /app/login.html → 登录页
  [PASS] /app/login.html → /app/index.html (登录成功跳转)

── 端口 8080 ──
  [PASS] / → 系统选择页
  [PASS] /app/ → 系统选择页
  [PASS] /station/ → 基站前端
  [FAIL] /drone/ → HTTP 404
         ↑ 文件: api-gateway/main.py:319 | 原因: drone 前端未部署
  [PASS] /station/ → /app/index.html (返回系统选择)

── 错误分类 ──
  404 Not Found:   2 例 (原因: drone 前端未部署)
  403 Forbidden:   0 例
  500 Server Error: 0 例
  连接拒绝:        0 例

── 修复建议 ──
  1. [已知-可忽略] drone 前端未部署，404 为预期行为
     影响路径: app/index.html:202, station/index.html:533
     建议: 待无人机团队部署前端后重新验证
```

### 报告存储

报告保存到 `logs/review/` 目录，文件名格式：`前端跳转验证_YYYY-MM-DD.md`

## 第五步：错误定位与修复

对每个失败的跳转，提供精确定位：

1. **定位来源**：哪个 HTML 文件的哪一行发起了跳转
2. **定位目标**：跳转 URL 在哪个服务（3000/8080）上失败
3. **分类原因**：

| 错误类型 | 常见原因 | 修复方式 |
|----------|----------|----------|
| 404 + 目标文件存在 | volume 挂载路径不对 | 检查 docker-compose.yml 挂载 |
| 404 + 目标文件不存在 | 真正的文件缺失 | 部署文件或更新跳转路径 |
| 404 + SPA 路由 | 子页面路由未配置 | 检查 api-gateway/main.py 路由 |
| 403 | 权限问题 | 检查文件权限和 auth 配置 |
| 连接拒绝 | 服务未启动 | `./start.sh status` 检查 |
| 根路径显示目录列表 | 缺少 index.html | 添加 index.html 或 meta refresh |

## 实施流程

助手执行此技能时，按以下步骤操作：

1. **扫描**：用 Grep 搜索所有前端 HTML 文件的跳转目标
2. **构建图谱**：整理出 pages + outgoing_links 结构
3. **确定测试范围**：全量或仅变更影响范围
4. **执行测试**：对每个跳转 URL 用 curl 测试（3000 + 8080 端口）
5. **生成报告**：按格式输出到 logs/review/
6. **修复建议**：对 FAIL 项给出定位和修复方案

## 注意事项

- 无人机前端（`/drone/...`）当前未部署，404 是预期行为，报告中标记为"已知-可忽略"
- SPA 内部 hash 路由不通过 HTTP 请求验证，而是通过源码分析确认路由逻辑存在
- 相对路径跳转需要结合来源页面的 URL 上下文推算最终绝对路径
- `localhost` 仅在本机验证有效，LAN 验证需使用 `hostname -I` 获取 IP 后替换
- API 调用 URL（fetch/XMLHttpRequest）不在此技能范围内，仅验证页面跳转
