# 文件导览：看哪里、改哪里

## 程序包

| 文件或目录 | 用途 | 普通使用时 |
|---|---|---|
| [README.md](../README.md) | 快速开始与当前范围 | 先读 |
| [REQUIREMENTS.md](../REQUIREMENTS.md) | 必装软件、包内环境与输入条件 | 首次检查前读 |
| [USER_GUIDE.md](../USER_GUIDE.md) | 人用流程与自然语言提示 | 按步骤使用 |
| [AI_GUIDE.md](../AI_GUIDE.md) | Codex 实际命令与证据纪律 | 交给自己的 Codex |
| [AGENTS.md](../AGENTS.md) | 打开本包时的简短 AI 引导 | 先读要求与 AI 手册 |
| [start.cmd](../start.cmd)、[launch.py](../launch.py) | 唯一终端启动链 | 用 start.cmd，不改解释器 |
| `app/` | 导入、逐页、宿主证据、检查、保存和阅读核验 | 文献任务只读 |
| `runtime/` | 随包 Python 与处理依赖 | 不删、不换、不自行 pip 安装 |
| [RUNTIME_MANIFEST.json](../RUNTIME_MANIFEST.json) | 核包内运行文件指纹 | 软件核对；不手改 |
| `examples/` | 虚构合成 PDF 与合成清单 | 可以明确选定练习 |
| `tests/`、`scripts/` | 合成机制测试和维护辅助 | 测试不替代真实处理与阅读 |
| [LICENSE](../LICENSE) | 项目自有内容的 MIT 许可 | 分发前读 |
| [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | 第三方组件声明 | 组件许可单独适用 |
| [RUNTIME_SOURCES.json](../components/RUNTIME_SOURCES.json) | 固定组件的来源与分发依据 | 软件维护时核对 |
| `licenses/`、`components/` | 第三方许可与来源材料 | 按各组件许可保留 |
| [PANORAMA.md](PANORAMA.md) | 上下对应的全景图 | 先理解组成与处理路线 |

程序包不包含你的已初始化实例、真实 PDF、笔记、Idea、原始宿主日志或账号配置。

### app 里几个重要文件

| 文件 | 作用 |
|---|---|
| [cli.py](../app/cli.py) | 连接公开命令与执行顺序 |
| [documents.py](../app/documents.py) | 单篇导入、固定原文、接受页和组装检查稿 |
| [page_protocol.py](../app/page_protocol.py) | 拆分翻译片段，保护公式、图、引用与数字 |
| [host.py](../app/host.py) | 定位当前宿主身份与精确日志，生成上下文和 capture |
| [evidence.py](../app/evidence.py) | 从原始记录重核真实身份、派发和完成证据 |
| [review.py](../app/review.py) | 核独立检查报告与冻结材料、范围和任务一致性 |
| [storage.py](../app/storage.py) | 保存计划、正式登记、不可覆盖输出与已提交恢复 |
| [client.py](../app/client.py) | 检查 Codex/Obsidian 能力与明确阅读库索引 |
| [environment.py](../app/environment.py) | 核随包组件、文件指纹和导入来源 |

这些文件供 AI 调用和维护者排查；普通使用不需要读懂源码，也不能改门槛。

## 自己的实例

实际阅读库名由 `init` 返回，以下用 `Reading-<标识>` 表示。
文献编号和索引版本也由程序生成，不要求人手编号。

| 路径 | 作用 | 是否可直接修改 |
|---|---|---|
| `.system/library.json` | 正式身份、分类、资产和保存状态 | 不可；由程序提交 |
| `.system/category-confirmation.json` | 首次分类确认依据 | 不可手改 |
| `.work/runs/<run>/` | 输入、逐页材料、冻结稿和真实任务证据 | 只按 AI 手册的当前阶段写入 |
| `.transactions/<事务>/` | 保存计划、前像和恢复记录 | 不手改、不整体删除 |
| `Reading-<标识>/Library.md` | 阅读起点说明 | 系统页面，保持原件 |
| `Reading-<标识>/indexes/Library-<版本>.md` | 指定版本的文献索引 | 不直接改；当前版本看 library.overview |
| `Reading-<标识>/papers/<文献编号>.md` | 一篇的阅读入口 | 不直接改 |
| `Reading-<标识>/domains/<分类ID>.md` | 领域分类页 | 不直接改 |
| `Reading-<标识>/assets/<文献编号>/r001/` | 原件、正文、图和来源 | 正式内容不可覆盖 |
| `Reading-<标识>/user/notes/<文献编号>.md` | 你的阅读说明 | 可以自己写，也可明确授权 AI 修改 |
| `Reading-<标识>/user/ideas/` | 你的想法与文件 | 可以自己维护；AI 不自动确认关系 |
| `Reading-<标识>/.obsidian/` | 客户端配置 | 个人显示设置由你决定；别把配置当正式文献状态 |

## 每篇正式资产

- `source.pdf`：原始 PDF。
- `source.md`：逐页整理的原文。
- `translation_zh.md`：逐页接受后组装的中文全文。
- `summary.md`：摘要。
- `science_notes.md`：概念、方法、假设与边界说明。
- `figures/`：对照渲染页裁出的图。
- `provenance.json`：来源、run、检查与身份引用。

普通阅读从文献页跳转即可。
这些资产是不可覆盖的保存结果，首版没有正式正文修订入口。
发现错误时记录文献、页码与问题，保留原件，先让 Codex 只读分析。

## 保管与备份

- 备份整个实例，包含隐藏的 `.system`、`.work`、`.transactions` 和阅读库。
- 实例备份保留阅读与处理资产、本次 capture、原记录引用和报告。
  Codex 原始宿主日志另在该用户的 `sessions`，不会自动包含在这份备份中。
- `review-verify` 依赖相应原始记录继续可读；实例备份不代表跨机器证据能够复验。
  保管证据不要求上传或公开整段聊天。
- `.work` 含正式引用与失败证据，不能当作可随手删除的缓存。
- 源、接受页、冻结检查稿、报告或图的字节变化会使旧证据失效。
- 首版不提供自动迁址或删除器。复制备份到新路径不代表已完成重新绑定。
- 更新软件时先保留自己的实例，不将它打进公共程序包。
