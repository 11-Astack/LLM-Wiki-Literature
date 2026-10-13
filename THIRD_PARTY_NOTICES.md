# 第三方软件与许可声明

LLM-Wiki-Literature 的自有程序、手册、全景图和合成样例采用
[MIT](LICENSE)，署名为 `LLM-Wiki-Literature contributors`。
下列第三方软件保留各自原始许可及版权声明。

## 随包组件

| 组件 | 固定版本 | 用途 | 原始许可材料 |
|---|---|---|---|
| CPython | 3.13.16，Windows x64 | 执行程序与标准库 | [Python LICENSE](licenses/cpython/LICENSE.txt)、[附属软件声明](licenses/cpython/INCORPORATED_SOFTWARE_LICENSES.rst) |
| pypdf | 6.10.0 | PDF 页数、基础信息与文字检查 | [BSD-3-Clause](licenses/pypdf/LICENSE) |
| latex2mathml | 3.81.0 | LaTeX 转 MathML | [MIT](licenses/latex2mathml/LICENSE) |
| pypdfium2 / PDFium | 5.13.0 / 153.0.7999.0 | PDF 文字层与页图 | [全部绑定与构建声明](licenses/THIRD_PARTY_LICENSES.json) |
| Pillow | 12.3.0，cp313 Windows x64 | 读取、生成和处理页图 | [MIT-CMU 及完整附属声明](licenses/pillow/LICENSE) |

版本、官方发行文件 URL、字节数和 SHA-256 见
[固定来源清单](components/DEPENDENCIES_LOCK.json)。
运行文件对应的原归档、成员和受控变换见
[来源映射](components/RUNTIME_SOURCES.json)。

## CPython 及其附属组件

- Python 官方 LICENSE、历史许可和 Windows 附加条件完整保留。
- 本包没有修改解释器源码。
- 官方 `python313.zip` 的标准库成员展开到包内 `Lib`，没有重新编译。
- 包内 `python313._pth` 配置为 `Lib`、`python313.zip`、`.`，不启用 `site`。
- 原配置及变换摘要记录在来源映射中。
- 同版本 Python 官方附属声明保留 OpenSSL、Expat、libffi、zlib、
  libmpdec、mimalloc 及其他标准库归属文本。
- 额外保留精确 [OpenSSL 3.5.9 许可](licenses/cpython/OpenSSL-3.5.9-LICENSE.txt)、
  [HACL MIT 版权头](licenses/cpython/HACL-MIT-header.txt)、
  [libb2 0.98.1 声明](licenses/cpython/libb2-0.98.1-COPYING)、
  [SQLite 3.50.4 声明](licenses/cpython/SQLite-3.50.4-LICENSE.md)及
  [xz 5.2.5 声明](licenses/cpython/xz-5.2.5-COPYING)。
- SQLite 原始说明区分其数据库构建产物与构建辅助脚本。
- xz 原始说明区分 liblzma、命令行工具、脚本及编译工具链代码。
- Tcl/Tk 和 macholib 在官方构建来源清单出现，不代表本 Windows 嵌入包附带它们。

## Microsoft Windows 运行代码

本包的 `vcruntime140.dll` 和 `vcruntime140_1.dll` 均来自官方 CPython
3.13.16 嵌入归档，文件版本为 14.51.36247.0。
Python 的 EXE、DLL 和 PYD 也包含 Microsoft Distributable Code。

使用或再分发这些 Microsoft 代码时，应遵守
[Python LICENSE 中的 Windows 附加条件](licenses/cpython/LICENSE.txt)。
其条件要求保留适用声明，保护 Microsoft 代码的下游条款，不冒称 Microsoft
背书，仅在相应 Microsoft 平台使用，且不纳入恶意、欺骗或违法程序。
这些条件针对 Microsoft 代码；项目自身的 MIT 不替代它们。

## PDFium、Pillow 与 FreeType

- pypdfium2 的 Apache-2.0、BSD-3-Clause、随附文档 CC-BY-4.0 原文完整保留。
- PDFium Windows 构建的 16 份依赖声明随包保留，包括 PDFium、
  pdfium-binaries、FreeType、ICU、AGG、abseil、fast_float、LCMS、
  libjpeg-turbo、OpenJPEG、libpng、libtiff、LLVM libc、simdutf 和 zlib。
- Pillow 的完整原始 LICENSE 包括 12 组编译依赖声明：brotli、FreeType、
  HarfBuzz、LCMS、libavif、libjpeg-turbo、libpng、libwebp、OpenJPEG、
  TIFF、xz 和 zlib-ng。
- 本软件使用 FreeType Project 的代码，归属 FreeType Project 及其作者。
  FreeType 的版权及完整原文保留在 PDFium 和 Pillow 的许可材料中。
  项目地址：[FreeType Project](https://freetype.org/)。
- 本软件含有 Independent JPEG Group 的软件，并保留相关 IJG 声明。
- 本软件使用 XZ Utils 的代码；其原始说明与许可边界保留，项目地址：
  [XZ Utils](https://tukaani.org/xz/)。
- 所有适用的原始版权、免责、归属和分发条件均以所附原文为准。

## 外部应用与核验边界

- Codex 与 Obsidian 由使用者自行安装和使用，本包没有附带其客户端、账号或许可。
- 本包没有 Firecrawl SDK、账号、凭据、OCR 或云上传接口。
- [机器可读许可清单](licenses/THIRD_PARTY_LICENSES.json)记录原文、SHA 和对应组件。
- Python 官方 SPDX 的 `NOASSERTION` 项逐项列出；该值不等于许可已获批准。
- 官方归档 SHA 核验与许可证条件审阅分别进行。
- Sigstore 密码学验签尚未执行，记录为 `NOT_RUN`。
- 本候选的 29 份许可原文、精确归档来源、Windows 附加条款已完成独立审查，
  在该限定范围没有 P0、P1 或 P2 发现。
- 独立审查结论记录于机器可读许可清单；整包实际流程与客户端阅读验收另行记录。
- 该审查不构成整体法律保证，也不授予上传或公开发布权限。
