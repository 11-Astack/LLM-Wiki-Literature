# Windows x64 固定来源重建与候选导出

## 适用对象

- 普通用户使用带运行环境的 Windows ZIP。
- 本配方供审阅源码或重建环境的人使用，需要 PowerShell 7.6.x
  （本机实测 7.6.5）和已有 Python 3.12+ 构建宿主。
- Windows PowerShell 5.1 不支持许可获取脚本所用的 .NET API；本配方不把它列为支持环境。
- 普通 Windows ZIP 的 `start.cmd` 启动无需额外安装 PowerShell 7。
- 目标运行环境始终固定为 CPython 3.13.16 Windows x64，不采用构建宿主的第三方包。
- 不安装 pip、系统软件，不改 PATH、注册表，不读取全局账号缓存。

## 从固定官方文件重建

- 在包根执行。
- 阅读 `components/DEPENDENCIES_LOCK.json`；在用户同意本次下载后执行两条获取命令。
  - `& .\build\acquire_runtime.ps1 -Download`
  - `& .\build\acquire_license_materials.ps1 -Download`
- 网络只获取固定官方归档及对应许可资料；所有来源、尺寸、SHA 先核对。
- 用已有 Python 3.12+ 执行以下离线命令。
  - `python -I -S -B .\build\rebuild_runtime.py --run-id runtime-stage-001 --copy-to-package`
- 源码 ZIP 已附完整许可原文，可保留现有 `licenses`。
- 从没有许可输出的工程输入重建时，再执行两条原文收集命令。
  - `python -I -S -B .\build\prepare_notices.py`
  - `python -I -S -B .\build\complete_notices.py`
- 上述目录或许可输出已存在时拒绝覆盖；请在新的源码副本重建。
- 标准库 ZIP 安全展开到包内 `Lib`，保留来源映射、原 `_pth` 和受控配置说明。
- 再用包内固定运行环境执行。
  - `& .\runtime\python\python.exe -X utf8 -I -S -B .\scripts\check-tests.py`
- 客户端检查、真实作者/检查者和单篇完整流程另按人用手册与 AI 手册执行。

## 明确清单导出

- 本工具只生成 candidate，不上传、不授予 release-ready。
- 源码候选不含运行二进制；Windows 候选按完整 runtime manifest 加入文件。
- 导出前必须有两份手册、初始化说明、合成样例、项目 LICENSE 和全部第三方材料。
- 冻结源码清单。
  - `python -I -S -B .\build\export_release.py plan --kind source --plan-id candidate-source-001`
- 冻结 Windows 清单。
  - `python -I -S -B .\build\export_release.py plan --kind windows-x64 --plan-id candidate-windows-001`
- 把 `build/export-plans` 的具体文件与 SHA 交给审核者检查。
- 通过后按选定计划生成候选 ZIP，例如。
  - `python -I -S -B .\build\export_release.py export --plan .\build\export-plans\candidate-windows-001.json`
- 计划冻结后任何输入变化必须建新计划；不修改旧计划或覆盖旧产物。
- ZIP 使用明确文件清单、固定 ZIP 时间戳、逐文件 SHA，并生成内置清单。
- 导出后重新列出 ZIP 内容、逐字节核对，安全解压到新目录并再次核对。
- 输出位于 `dist/candidates`，核验回执记录在同目录。
- 工程目录、真实运行记录、账号、任务 UUID、个人绝对路径与缓存不进入包。
- 只有官方标准库明确登记的 `runtime/python/Lib/*.pyc` 属于必需运行文件；其他缓存拒绝。

## 发布门槛

- 下载 SHA 核验、许可材料审阅、代码审阅、客户端阅读和完整流程验收分别记录。
- Sigstore 未实际密码学验签时写 `NOT_RUN`。
- 本工具不替审核者决定第三方分发条件，也不代表公共发布授权。
- 产品名称、版本、MIT 和署名已固定；公开发布还需实际包验收与明确目标授权。
- 实际单篇运行使用已核候选解压物。完成后仅允许明确列出的手册验收事实变化。
- 生成本地最终计划时指定原候选和获准变化的文档，例如。
  - `python -I -S -B .\build\export_release.py final-plan --candidate-plan .\build\export-plans\candidate-windows-001.json --plan-id final-windows-001 --document docs/RELEASE_NOTES.md`
- 最终计划拒绝其他文件变化，保留每个获准文档的前后 SHA；任何程序、运行环境、
  合成样例、许可或重建脚本变化须建立新候选并验证相关范围。
- 最终 ZIP 保留正式文件名，状态为本地未发布；应从其新解压物再执行只读核验。
