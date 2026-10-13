# 使用要求

## 先选对下载包

- 普通用户请选择 **windows-x64 ZIP**：自带 Python 和处理依赖，可按本手册检查后启动。
- **source ZIP** 只包含源码与说明，不带 Python。
  必须先按 ZIP 内的 `build/BUILD_RECIPE.md` 重建运行环境，才能启动。
- 以下环境清单描述 windows-x64 包或已重建环境的源码包。
  两种 ZIP 共用手册，解压源码包本身不代表已经具备运行环境。

## 你需要安装的三项

| 必需项 | 需要什么能力 | 怎样确认 |
|---|---|---|
| Windows 64 位 | 能完整解压、运行包内程序，并写入选定的新库目录 | 由 Codex 检查包与目录；首版只支持 Windows |
| Codex Windows 客户端 | 能读取你授权的文件、运行终端命令、创建两个独立实际任务，并提供受支持的宿主元数据 | 运行 `host-context`，再由 `doctor` 核对当前身份和记录结构 |
| Obsidian 桌面版 | 安装程序版本 1.12.7 或更新，命令行已启用，应用正在运行 | 提供安装目录中 `Obsidian.com` 的绝对路径；运行 `doctor`，保存后再运行 `read-index` |

- 使用你自己的 Codex 账号与可用额度，处理的快慢也取决于所选模型和任务能力。
- 不需要另设 OpenAI API Key，也不需要 Firecrawl 账号。
- 宿主采集只接受当前适配并经过验证的 Codex 记录协议。
  缺少元数据、协议未知或身份不一致时停止；不保证任意客户端版本都能运行。
- 打开 Obsidian → 设置 → 常规 → 命令行界面，开启功能并按软件提示注册。
- Windows 使用安装目录中的 `Obsidian.com`；运行 CLI 时保持 Obsidian 应用打开。
- 没有这个开关或找不到 `.com` 时，检查安装程序版本是否达到 1.12.7。
  由用户自行升级客户端；AI 不自动安装、不改 PATH。
- 这些 Windows 条件依据本轮核对的 [Obsidian 官方 CLI 说明](https://obsidian.md/help/cli)。
- 首次检查必须实际运行，单看已安装图标或 `--help` 不够。

### 尚未安装时的官方入口

- [ChatGPT 官方桌面下载](https://chatgpt.com/download/)：新版桌面应用含 Chat、Work 和 Codex。
  下载后进入 **Codex 视图**，本包要求其中受支持的本地 Codex 任务。
  网页 Chat 和 ChatGPT Classic 不能替代这套本地任务与证据协议。
- [Obsidian 官方下载](https://obsidian.md/download)：自行安装 Windows 桌面版，
  再按上面的版本和命令行要求检查。
- 应用迁移说明见 [OpenAI 官方说明](https://help.openai.com/en/articles/20001276-moving-to-the-new-chatgpt-desktop-app)。
- 已经安装的客户端保持现状，先检查实际能力；AI 不自动安装或修改客户端。

## windows-x64 包内提供的环境

| 组件 | 固定版本 | 用途 |
|---|---|---|
| CPython Windows 嵌入式环境 | 3.13.16 | 运行程序 |
| pypdf | 6.10.0 | 核 PDF 结构与页数 |
| pypdfium2 | 5.13.0 | 提取页文字与渲染页面 |
| Pillow | 12.3.0 | 图像与裁图处理 |
| latex2mathml | 3.81.0 | 检查公式转换能力 |

- 来源和许可材料见 [RUNTIME_SOURCES.json](components/RUNTIME_SOURCES.json)、
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 `licenses/`。
- [RUNTIME_MANIFEST.json](RUNTIME_MANIFEST.json) 用于核对实际运行文件。
- 运行环境当前验收状态见 [RELEASE_NOTES.md](docs/RELEASE_NOTES.md)。
- 文件校验和来源记录不等于已核数字签名；Sigstore 签名核验当前为 `NOT_RUN`。

使用 windows-x64 包时，用户无需单独安装 Python 或逐个运行 `pip install`。
源码包先按 `build/BUILD_RECIPE.md` 重建环境。
程序只使用 `runtime/` 内的环境；缺失、损坏或指纹变化时停止。
不要换用开发者 Python、全局 Python，或让 AI 自动下载补丁来绕过检查。

## PDF 条件

- 本地有效 PDF，未加密，最多 60 页、25 MiB。
- 每页提取后的文字层超过 80 个字符；这只是入口条件，仍需对照页图核对。
- 每页需要有实际可翻译正文；纯图页、扫描页和零翻译片段页面不在首版范围。
- 原文、显示公式、图及完整参考条目能按当前普通页协议可靠重建。
- 特殊作者豁免、跨页参考条目续接、通用 OCR 和特殊页规则登记尚不提供。
- 表单、脚本、嵌入文件、未知主动行为等 PDF 会被拒绝。

60 页是文件上限，不代表 60 页都能在一次预算内完整处理。
第一次可先用包内合成样例，或选一篇短、清楚且你熟悉的文献。

## 新库和时间

- `init` 的目标必须是尚不存在的新目录，其父目录已经存在。
- 分类由你明确确认；软件生成实例标识、阅读库名和必要 JSON。
- 一次只允许一篇活动文献。
- 从 `intake` 起固定 1–60 分钟，用户给定的更早截止优先。
- 这篇的作者、检查和保存应在同一协调者当前轮次完成。
- 新聊天、换轮次或到期不能接续旧稿；首版没有跨会话续作。
- `recover` 仅收尾已经提交的原保存事务，不能继续翻译未完成文献。

## 隐私条件

- PDF、译文、阅读笔记和 Idea 留在你的实例中。
- 实例保存本次任务的 capture、原记录引用和报告。
  Codex 原始宿主日志仍在该用户的 `sessions` 目录，不会自动复制进实例。
- `review-verify` 需要相应原始记录继续可读；只有实例副本不能保证证据可复验。
  这项依赖不要求上传或公开整段聊天。
- 本地保存不等于 AI 完全离线；只有你同意的材料才能交给自己的 Codex 阅读。
- 默认不联网获取文献，不增加外部上传接口，不读取其他库和无关聊天记录。
- 公开软件包与自己的数据目录分开保管；不要把实例或原始宿主日志当软件发布。

完成检查后，按 [USER_GUIDE.md](USER_GUIDE.md) 开始。
