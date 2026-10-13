# LLM-Wiki-Literature v0.1.0

以卡帕西（Andrej Karpathy）的 LLM Wiki 知识库思路为启发，
把文献从 PDF 整理为大语言模型便于读取的 Markdown，
再用 Obsidian 阅读和记录，积累可追溯的文献语料，
为科研检索、阅读和后续知识整理提供基础。

Markdown 让材料便于 LLM 读取、检索、引用和核对；来源记录让你能回看原文。
你可以让自己的 Codex 基于这些材料回答问题和核对出处。
整理后的材料仍需要人的判断，不能自动证明科学结论的真实性。

## 首版能做什么

- 一次处理一篇本地普通文字层 PDF。
- 保存可对照阅读的原文、逐页中文全文、摘要与科学说明。
- 保留公式、图、参考条目及其来源对应，便于回看核对。
- 由你的 Codex 逐页处理，再由另一个不同的真实任务独立检查。
- 将通过检查的材料与来源记录保存到本地，在 Obsidian 中阅读。
- 用户笔记和 Idea 由你管理。

## 从 PDF 到阅读库

PDF → 原文与逐页中文 Markdown → 独立检查 → 本地保存 → Obsidian 阅读与记录。

这个版本提供上述单篇文献流程。
跨文献 Wiki 自动编译、知识图谱推理和其他 AI 接入不在首版支持范围。
已有本机合成示范与各项核验范围见[发行核验状态](docs/RELEASE_NOTES.md)。

## 先选对下载包

- 普通用户下载 **windows-x64 ZIP**：自带 Python 与 PDF、图像、公式处理依赖。
- 开发者下载 **source ZIP**：包含源码与说明，不带 Python 运行环境。
  先按 [重建配方](build/BUILD_RECIPE.md) 准备环境，再运行程序。
- 两种 ZIP 共用这份手册；下面的直接启动步骤适用于 windows-x64 包，
  或已经按配方重建环境的源码包。

## 必装程序与实际检查

- Windows 64 位电脑。
- 你自己的 Codex Windows 客户端与可用账号，
  能创建两个不同的真实任务，并提供受支持的宿主记录。
- Obsidian 桌面版，安装程序版本 1.12.7 或更新，
  命令行功能已启用，应用正在运行。
- 一篇你有权处理、并愿意交给自己的 Codex 阅读的本地 PDF。
- Windows 包用 [start.cmd](start.cmd) 调用自己的 bundled Python。

无需另装 Python 或另设 OpenAI API Key。
开始前必须由 Codex 实际检查环境，单看安装图标或命令帮助不够。
宿主适配仍是基于本轮实证记录的实验性适配，不保证任意客户端版本都可运行。
详细要求与检查方法见 [REQUIREMENTS.md](REQUIREMENTS.md)。

## 五步快速开始

1. 完整解压到你能写入的新目录，在 Codex 中打开这个目录。
2. 把下面的提示交给 Codex，先核对环境和准备新库方案。
3. 确认新库位置与分类后，让 Codex 用 `init` 创建你的库。
4. 按返回的路径，在 Obsidian 中打开 `Reading-<软件生成标识>` 阅读库。
5. 明确选定一篇 PDF、分类和最多 60 分钟的预算，再授权连续处理与保存。

> 请先读本目录的 REQUIREMENTS.md、USER_GUIDE.md 和 AI_GUIDE.md。
> 使用 start.cmd 检查要求与当前命令，不处理文献、不联网。
> 请确认我的 Codex 与 Obsidian 是否满足要求，
> 给出一个全新文献库目录和通用分类的建议，等我确认后再初始化。
> JSON、UUID、哈希和任务证据由软件与 AI 处理，不让我手工填写。

终端入口只有一套；在包根的 PowerShell 中可以先查看要求和帮助：

```powershell
& .\start.cmd requirements
& .\start.cmd --help
```

建议在 Codex 终端或 PowerShell 中运行上面的命令。
双击 `start.cmd` 的窗口可能一闪而过；它没有安装向导，也不会自动处理 PDF。

## 手册与全景图

- [给使用者的手册](USER_GUIDE.md)：准备、提示、处理、阅读、笔记和故障。
- [给 Codex 的手册](AI_GUIDE.md)：实际命令、写入边界、逐页协议和证据链。
- [全景路线](docs/PANORAMA.md)：上排看组成，下排从左向右看处理过程。
- [文件导览](docs/FILE_GUIDE.md)：哪些可以改，哪些需要保留。
- [文献来源与 Firecrawl](docs/SOURCES_AND_FIRECRAWL.md)：可选的独立获取步骤，
  未内置为文献获取或 OCR 服务。

![文献处理全景](docs/literature-panorama.png)

## 范围与许可

首版一次处理一篇普通、未加密、有足够文字层的 PDF，最多 60 页、25 MiB。
每篇固定最多 60 分钟。
OCR、扫描页、特殊页、批量、长文跨会话续作、其他 AI、跨平台和自动升级留到后续。
技术检查、独立内容检查、本地保存、可见阅读与你的科学接受分别报告。

项目自有代码、手册、全景图与合成样例采用 [MIT](LICENSE)，
版权署名为 LLM-Wiki-Literature contributors。
第三方组件保留各自原许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 `licenses/`。
