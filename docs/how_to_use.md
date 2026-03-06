# How to Use

## 1. WebUI 管理面板

```bash
# 启动 WebUI（默认 http://127.0.0.1:8765）
.venv\Scripts\python.exe -m houdini_mcp.webui
```
```
# 开发模式（代码改动自动重载）
.venv\Scripts\python.exe -m houdini_mcp.webui --reload
```
```
# 自定义端口
.venv\Scripts\python.exe -m houdini_mcp.webui --port 9000
```

WebUI 功能：
- 查看所有活跃的 Houdini MCP 会话（端口、PID、状态）
- 配置：人类/Agent 启动 Houdini 时是否自动开启 RPyC
- 安装/卸载启动脚本（非破坏性，不覆盖已有 456.py 内容）
- 查看 Houdini 进程和端口使用情况

## 2. MCP Server（给 Claude Code / Agent 用）

```bash
# 默认端口 18811
.venv\Scripts\python.exe -m houdini_mcp

# 指定端口（多实例时避免冲突）
.venv\Scripts\python.exe -m houdini_mcp --port 18812

# 指定会话 ID
.venv\Scripts\python.exe -m houdini_mcp --port 18812 --session-id my-session
```

### Claude Code 配置

`.claude/settings.local.json`:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "E:/DEV/houdini-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "houdini_mcp"],
      "cwd": "E:/DEV/houdini-mcp"
    }
  }
}
```

多实例配置（指定端口）：

```json
{
  "args": ["-m", "houdini_mcp", "--port", "18812"]
}
```

## 3. 安装启动脚本

两种方式（二选一）：

**方式 A：WebUI 点击 Install 按钮**

**方式 B：MCP 工具调用**
```
install_startup_scripts()          # 所有版本
install_startup_scripts("21.0")    # 指定版本
```

安装后的效果：
- `houdini_mcp_startup.py` 复制到 `~/Documents/houdiniX.Y/scripts/`
- `456.py` 末尾追加一行 hook（不覆盖原有内容）

卸载：
```
uninstall_startup_scripts("21.0")  # 只删 hook 行和 startup 文件，保留 456.py 其他内容
```

## 4. Houdini 手动启动 MCP

默认情况下，人类手动打开 Houdini 不会启动 RPyC。

如需开启：
- WebUI 中把 "Human Launch: Auto-start RPyC" 切为 ON
- 或 MCP 工具：`update_mcp_config(human_auto_start=True)`
- 或直接编辑 `~/houdini_mcp/config.json` 中 `human_launch.auto_start_rpyc: true`

也可以通过环境变量临时控制（启动 Houdini 前设置）：
```bash
set HOUDINI_MCP_ENABLED=1
set HOUDINI_MCP_PORT=18815
houdinifx.exe
```

## 5. Agent 启动 Houdini

```
# 推荐入口（幂等，已运行则直接连接）
ensure_houdini_ready()

# 明确指定版本和模式
start_houdini(version="21.0", mode="gui")

# headless 模式 + 指定端口
start_houdini(mode="hython", port=18815)
```

Agent 启动的 Houdini 会自动：
- 分配空闲端口（18811-18899）
- 设置环境变量 `HOUDINI_MCP_ENABLED=1`
- 注册会话到 `~/houdini_mcp/sessions/`
- 退出时自动清理会话

## 6. 会话管理

```
get_current_session()       # 当前 MCP 的会话信息
list_all_sessions()         # 本机所有会话
cleanup_stale_sessions()    # 清理已死进程的会话
stop_houdini()              # 停止当前会话的 Houdini
```

## 7. 配置管理

```
get_mcp_config()                              # 查看配置
update_mcp_config(human_auto_start=False)      # 关闭人类自动启动
update_mcp_config(port_range_min=19000, port_range_max=19099)  # 改端口范围
```

配置文件位置：`~/houdini_mcp/config.json`
会话目录：`~/houdini_mcp/sessions/`
启动日志：`~/houdini_mcp/houdini_startup.log`
