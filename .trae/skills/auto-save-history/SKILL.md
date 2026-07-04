---
name: "auto-save-history"
description: "Automatically saves conversation history to a configurable file with incremental updates. Invoke at the END of every conversation turn to persist dialogue records."
---

# 对话历史自动保存

在每次对话轮次结束时，将对话历史增量保存到指定文件中，确保对话记录不丢失。

## 触发条件

**必须在以下时机调用此技能**：
- 每次对话轮次完成时（即助手回复完成后）
- 用户明确要求保存对话历史时
- 对话中涉及重要决策或代码变更时

**不需要调用的场景**：
- 对话仍在进行中且用户未发出新消息
- 纯问候或闲聊（判断依据：不涉及任何技术内容或决策）

## 配置

对话历史保存路径和格式通过项目根目录 `.trae/skills/auto-save-history/config.json` 管理。若文件不存在，使用以下默认值：

```json
{
  "save_path": "logs/conversation_history.json",
  "format": "json",
  "encoding": "utf-8",
  "max_file_size_mb": 50,
  "rotate_on_overflow": true
}
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `save_path` | 保存文件路径（相对于项目根目录） | `logs/conversation_history.json` |
| `format` | 存储格式，可选 `json` / `jsonl` | `json` |
| `encoding` | 文件编码 | `utf-8` |
| `max_file_size_mb` | 单文件最大大小（MB），超限则轮转 | 50 |
| `rotate_on_overflow` | 超限时是否轮转（追加 `_1`, `_2` 后缀） | true |

## 保存流程

### 1. 读取配置

```
读取 .trae/skills/auto-save-history/config.json → 无则使用默认值
```

### 2. 构建当前轮次记录

每条对话记录结构：

```json
{
  "id": "唯一标识 (UUID 或 timestamp+序列号)",
  "timestamp": "2026-07-05T11:30:00.000+08:00",
  "session_id": "当前会话ID",
  "role": "user | assistant",
  "content": "对话原文",
  "metadata": {
    "model": "使用的模型名",
    "files_modified": ["涉及的文件路径列表"],
    "tools_used": ["调用的工具名称列表"],
    "task_summary": "本轮完成任务的简要描述"
  }
}
```

### 3. 增量保存机制

**核心原则：只追加新记录，不重写已有数据。**

- **JSON 格式**：读取现有文件 → 解析为数组 → 追加新记录 → 写回文件
- **JSONL 格式**：直接在文件末尾追加一行 JSON 记录（更高效，推荐用于高频场景）

增量判断逻辑：
1. 读取文件中最后一条记录的 `id` 和 `timestamp`
2. 仅写入 `timestamp` 晚于文件中最后记录的新消息
3. 若文件为空或不存在，创建新文件并写入

### 4. 文件安全与完整性

- **原子写入**：先写入临时文件（`.tmp` 后缀），写入成功后 rename 替换原文件
- **大小检查**：写入前检查文件大小，若超过 `max_file_size_mb`：
  - `rotate_on_overflow=true`：将当前文件重命名为 `{name}_1.json`，创建新空文件继续写入
  - `rotate_on_overflow=false`：停止写入并记录警告日志
- **备份**：每次写入前，若原文件存在，复制为 `.bak` 后缀文件

### 5. 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 文件路径不存在 | 自动创建所需目录 |
| 文件权限不足 | 记录错误日志，提示用户执行 `chmod` 或更换路径 |
| JSON 解析失败（文件损坏） | 将损坏文件重命名为 `.corrupted`，创建新文件从头开始 |
| 磁盘空间不足 | 记录错误日志，提示用户清理磁盘或调整 `max_file_size_mb` |
| 写入中断（进程崩溃） | 通过 `.tmp` 原子写入机制保证原文件不被破坏 |

错误提示格式：
```
[AutoSave] 保存失败: <错误描述>
[AutoSave] 建议: <修复建议>
[AutoSave] 文件路径: <当前配置的保存路径>
```

## 实施步骤

每次触发时，助手应执行以下操作：

1. **收集当前轮次数据**：从对话上下文中提取 `role`、`content`、`metadata`
2. **读取配置文件**：检查 `.trae/skills/auto-save-history/config.json`
3. **执行增量保存**：
   - 使用 `Read` 工具读取现有历史文件
   - 解析已有记录，确定最后记录的 `id`/`timestamp`
   - 构建新记录对象
   - 使用原子写入（`Write` 到 `.tmp` → `RunCommand` 执行 `mv`）
4. **验证写入**：读取写入后的文件，确认最后一条记录匹配
5. **处理错误**：若任何步骤失败，按错误处理表输出提示

## 示例输出

成功保存后，助手可简要告知（非必须，避免干扰对话）：

```
[AutoSave] 已保存 2 条记录 → logs/conversation_history.json (共 156 条)
```

或静默完成，不输出任何内容（推荐用于非关键对话）。

## 注意事项

- 对话历史可能包含敏感信息（密码、密钥等），保存时不应做额外过滤，但应确保文件权限为仅当前用户可读写（`600`）
- `metadata.files_modified` 和 `metadata.tools_used` 仅记录助手实际操作的部分，不包含未执行的意图
- 不保存图片、文件等二进制内容的完整数据，仅在 `content` 中记录其引用路径
