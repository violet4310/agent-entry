# Agent Entry

一个以 **skill 为入口、附带独立运行代码**的 agent 工作流原型。你从一个入口提出需求，由宿主 agent 定位合适的目录，再选择三种模式之一。暂用名 Agent Entry，MIT 许可。

| 模式 | 当前对话负责 | 执行 agent 负责 |
| --- | --- | --- |
| `delegate` 主管派工 | 需求、派工、审查和整合 | 调查、实施、测试并报告结果 |
| `retrieve` 检索回注 | 判断、讨论和实施 | 找到相关文件和行范围；程序校验并读取原文 |
| `relay` 持续转发 | 定位、维护会话映射和传递消息 | 在同一个执行会话持续处理用户请求 |

目标是减少手动选择启动目录、重复搜索和主对话中的无关上下文。**它不承诺解决所有卡顿，不会自动修复客户端、网络或内存问题。** 转发增加一层调用，可能增加等待；执行者自己的会话历史仍会增长。

## 当前实现

- 三种模式都由同一个 skill 调用，同一套代码也能独立作为 CLI 使用。
- 执行后端先支持 **Codex CLI**；其他宿主 agent 可以调用 skill 附带的脚本，但其他执行后端尚未实现。
- 目录发现有深度、候选数和遍历条目上限，不扫描文件内容。**语义定位由宿主 agent 完成**，独立 CLI 不会自动理解自然语言选择目录。
- 保存本地会话 ID 与 Codex thread ID 的明确映射；后续使用同一个 ID 续接，不选择“最近会话”。
- 检索结果从本地源文件读取，检查目录边界、行号、行数和字节预算，附源文件 SHA-256。
- 最终回复、事件流和诊断分开保存；`send --raw` 只输出原始最终回复的 UTF-8 字节。
- 默认 read-only；需要修改的派工/转发显式传 `--allow-writes`。单个状态目录同时只运行一个 worker。
- 超时/中断终止本地 worker 进程组，记录失败；不自动重试可能已写入的任务。
- 每轮记录时间、最终回复字节数和事件字节数，便于随后实测开销；没有宣称性能提升百分比。

## 环境

首版支持 macOS/Linux、Python 3.9+，运行代码无第三方 Python 依赖。Codex 需已安装并通过其官方方式登录。程序使用现有 CLI 认证，不复制或读取登录凭据，不要求另填 API key。

19 项离线测试和 skill 格式校验已通过。2026-11-09 使用 `codex-cli 0.167.0-alpha.3.2`、现有 ChatGPT 登录和临时目录，跑通了三种模式的四个真实只读回合。本机测试通过 `--enable respect_system_proxy` 沿用系统代理。详情见 [验证记录](docs/validation.md)。

## 作为 skill 使用

完整 skill 位于 [`skills/agent-entry`](skills/agent-entry/SKILL.md)，其中包含运行代码；复制这个文件夹即可，不依赖本仓库其他目录。

```sh
python3 tools/install_skill.py
```

默认复制到 `~/.codex/skills/agent-entry`；也可通过 `--destination` 选择宿主支持的 skill 目录。目标已存在时拒绝覆盖。安装后启动新的宿主会话以发现 skill：

```text
使用 $agent-entry，先找到这个需求应该在哪个项目目录处理。
这次用检索回注模式，找到必要原文后由当前对话继续判断。
```

其他两种示例：

```text
使用 $agent-entry，把这个边界明确的修复委派出去；完成后你检查结果。

使用 $agent-entry 的持续转发模式，后续消息交给同一个执行会话，最终回复不要改写。
```

Skill 可指导宿主按模式工作，但不能接管宿主的消息管线。**经过宿主模型生成的回复不能严格保证逐字相同**；要求原样时使用下面的 raw CLI 或终端 chat。当前也不会自动把客户端界面切换到执行聊天。

## 独立运行

在仓库目录运行以下命令。`--state-dir` 和 `--codex-bin` 是全局参数，放在子命令前。请固定一个状态目录，后续即使换了 cwd 也继续使用同一路径。

```sh
python3 cli.py --help
python3 cli.py capabilities
python3 cli.py discover --root /path/to/projects --depth 2 --limit 40
```

发现结果是目录候选，不是相关性排名。由人或宿主选定目录后运行：

```sh
python3 cli.py --state-dir /path/to/entry-state retrieve --cwd /path/to/project --message '定位登录超时的相关实现，返回必要原文位置'
python3 cli.py --state-dir /path/to/entry-state delegate --cwd /path/to/project --message '修复已定位的登录超时问题并运行相关测试' --allow-writes
python3 cli.py --state-dir /path/to/entry-state relay --cwd /path/to/project --message '先解释这个模块的结构，不要修改'
```

创建命令输出 JSON，包括 `session_id`。用该 **本地会话 ID** 继续：

```sh
python3 cli.py --state-dir /path/to/entry-state send SESSION_ID --message '请继续解释刷新流程' --raw
python3 cli.py --state-dir /path/to/entry-state chat SESSION_ID
python3 cli.py --state-dir /path/to/entry-state show SESSION_ID
python3 cli.py --state-dir /path/to/entry-state sessions
```

`chat` 仅用于 relay，每行一个用户回合，支持 `/status`、`/quit`；界面提示在 stderr，最终回复在 stdout。多行或含敏感内容的请求使用 `--message-file request.txt`，或不传消息参数而从 stdin 读取。`--message` 内容可能出现在系统进程列表中。

`--model`、`--effort` 在创建时可显式设置，并在后续回合沿用。省略时使用执行者的 Codex 配置，**不会自动获知宿主当前模型**。只读策略和工作目录也保持不变；新任务或不同写入策略请创建新会话。

失败时返回非零退出码，错误保留在 JSON/诊断里。raw 模式失败时 stdout 为空，错误写入 stderr。部分回复不会被包装成成功。崩溃后遗留 `running` 记录时，可运行：

```sh
python3 cli.py --state-dir /path/to/entry-state recover SESSION_ID
```

这只恢复记录，不恢复进程、不重新执行，也不能证明后端已停止。先检查文件和执行状态，再决定是否 `send`。

## 边界

- 首版采用 `codex exec`，不支持交互审批面板、原生富媒体、回合内插话和流式界面。需要新的审批时可能失败，不能靠隐藏错误或绕过审批继续。
- 默认原 CLI 配置和宿主的授权不能混为一谈。嵌套 CLI 不自动继承宿主全部访问限制；在受限制的宿主内，需确认同等边界可执行，否则使用原生工具。
- cwd 不是安全沙箱；“检索只返回该目录内的文件”也不意味着 worker 只能读取该目录。执行权限由 CLI/操作系统控制。
- 默认不创建 worktree、不合并、不并行写入。派工成功只表示执行回合完成，不能代替宿主验收 diff 和测试。
- `.agent-entry` 保存请求、最终回复、事件和诊断；默认不纳入 Git。状态根和回合目录以当前用户私有权限创建。自行选择的状态路径也应排除出版本控制。
- 不自动重试失败操作，不跨不同状态目录规避单 worker 限制。worker 环境标记阻止通过本工具递归派工。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
```

测试使用本地模拟 Codex，不消耗模型额度；覆盖三模式、多轮续接、原样回复、源码校验、越界引用、失败与超时、进程组退出、并发锁、崩溃记录恢复，以及复制 skill 后独立运行。真实调用测试应使用专用临时项目和已有授权，不要把用户项目当成实验样本。

可选的真实调用检查（使用现有登录和模型额度，首个失败即停止）：

```sh
python3 tools/smoke_codex.py --timeout 45
```

它预定四个只读回合：创建转发、续接上下文、检索源文、委派读取；测试文件全部在新建临时目录。

可选的技能格式检查需要开发依赖 PyYAML；运行代码不需要它。若安装环境自带 skill-creator，可用其 `scripts/quick_validate.py` 验证 `skills/agent-entry`。

接口与后续扩展见 [`docs/architecture.md`](docs/architecture.md)。欢迎通过小范围适配器和真实兼容测试贡献其他 agent 支持。

## 依据

实现基于官方 [非交互运行](https://learn.chatgpt.com/docs/non-interactive-mode)、[CLI 参数](https://learn.chatgpt.com/docs/cli/reference) 与 [skill 定制](https://learn.chatgpt.com/docs/customization/overview) 文档。后续的交互审批/流式后端可参考 [Codex App Server](https://learn.chatgpt.com/docs/app-server)。
