# Image2 Studio：Codex 本地生图与图片 API 工作台

> 让 Codex 直接调用你配置的图片中转站或 OpenAI-compatible 图片 API，支持文生图、参考图编辑和本地历史管理。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Latest Release](https://img.shields.io/github/v/release/DAMNDAGER/Image2-Studio?display_name=tag)](https://github.com/DAMNDAGER/Image2-Studio/releases/latest)

[English](#english) | [中文](#中文)

徽章说明：`MIT` 表示项目许可证；`Latest Release` 链接到最新的 GitHub Release 下载页面。

## 中文

Image2 Studio 是一个面向 **Codex 生图** 的本地图片工作台。它把 Codex 对话、本地 CLI 和图片中转站连接起来，让你可以直接在 Codex 中使用自己配置的图片 API 完成文生图和参考图编辑。

项目适合使用图片中转站、OpenAI-compatible 图片接口，或需要在本地统一管理多个图片模型的用户。它不提供图片额度，也不绑定任何单一服务商，只负责本地配置、请求转发、结果保存和 Codex 接入。

**搜索关键词：** Codex 生图、Codex 图片生成、图片 API、中转站生图、OpenAI 图片 API、文生图、参考图编辑、AI 绘图、本地图片工作流。

HTML 控制台用于配置图片 API、手动生成、查看历史和管理输出；Codex 接入则用于在对话中直接发起图片生成或编辑请求。

### 下载

Windows 独立版请前往 [GitHub Releases](https://github.com/DAMNDAGER/Image2-Studio/releases/latest) 下载。发行包内含运行所需环境，无需预先安装 Python。

### 主要功能

- 在 Codex 对话中通过本地 Image2 CLI 生成图片或编辑参考图。
- 支持文生图、本地参考图、公开图片 URL 和多张参考图。
- 支持多个图片 API 配置，并选择当前使用的配置。
- 支持常用画面比例、预设分辨率与自定义宽高。
- 提供本地 HTML 控制台，用于配置、手动生成、历史记录和输出管理。
- 支持 `--dry-run` 模拟请求，在最终图片 API 调用前停止且不消耗额度。

### 适合什么场景

- **在 Codex 中直接生图**：在对话里提出生成或编辑需求，由本地 Image2 CLI 调用当前图片 API。
- **接入图片中转站**：自定义基础地址、模型、生成路径、编辑路径和鉴权方式，兼容常见 OpenAI-compatible 接口。
- **统一管理多个图片 API**：保存多个配置并快速切换当前 Provider，不必反复修改调用方式。
- **保留本地结果**：图片保存到本地 outputs 目录，便于查看、下载和后续整理。

### 项目边界

Image2 Studio 是 Codex 的图片 API 适配层和本地工作台，不是图片模型服务商，也不会提供 API Key、账户额度或订阅权益。图片生成费用和可用能力由你配置的中转站或上游图片 API 决定。

### 工作方式

```text
                    ┌────────────────────┐
Codex 对话 ────────►│ Image2 Skill / CLI │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
HTML 控制台 ───────►│ 本地 Image2 服务   │──────► 用户选择的图片 API
                    └────────────────────┘
```

### 快速开始

1. 从 [GitHub Releases](https://github.com/DAMNDAGER/Image2-Studio/releases/latest) 下载并解压 Windows 发行包。
2. 双击 `start_image2.bat`。
3. 浏览器会打开本地控制台；如未自动打开，访问 `http://127.0.0.1:8765`。
4. 在“API 设置”中创建配置，填写图片 API 的基础地址、模型、路径和 API Key，并设为当前配置。
5. 在“Codex 接入”中安装或更新全局 Image2 Skill。
6. 重新打开 Codex 窗口或开始新任务，然后在对话中提出图片生成或编辑需求。

全局 Skill 安装位置：

```text
%CODEX_HOME%\skills\image2
```

### 项目结构

```text
app.py              FastAPI 服务与图片 API 适配层
image2_cli.py       Codex 与本地服务之间的 CLI
static/             本地 HTML、CSS 和 JavaScript 控制台
skills/image2/      Codex Skill 源文件
test_app.py         后端测试
start_image2.*      Windows 启动脚本
build_image2.ps1    Windows 发行包构建脚本
requirements*.txt   运行与构建依赖
LICENSE             MIT License
```

### 安全和数据边界

- 项目不包含 API Key、账户额度或订阅权益，也不会读取 Codex `auth.json` 中的个人密钥。
- API Key 仅通过本地控制台输入，由后端保存到 Windows Credential Manager；不会返回给前端。
- 本地服务默认监听 `127.0.0.1`，仅适合单用户本机使用，不建议暴露到公网。
- 运行时会在程序目录创建 `outputs`、`image2.sqlite3` 和 `.image2-token`。
- `image2-client.json` 只保存本地服务连接信息，不保存上游图片 API 的 Key。
- 图片生成费用和额度由所选择的图片 API 决定。

### 兼容性

- 面向 OpenAI-compatible 图片 API。
- 不绑定任何单一服务商。
- 可由用户配置模型、基础地址、生成路径、编辑路径、鉴权方式和图片字段名。
- 当前发行包面向 Windows x64。

### 开发说明

运行测试：

```powershell
python -m unittest -v
```

构建 Windows 发行包：

```powershell
.\build_image2.ps1
```

开发环境依赖位于 `requirements.txt`；打包依赖位于 `requirements-build.txt`。

## English

Badge meanings: `MIT` identifies the project license; `Latest Release` links to the latest GitHub Release download page.

Image2 Studio is a local image workspace for Codex. It connects Codex conversations, a local CLI, and user-configured image APIs so text-to-image generation and reference-image editing can use one local workflow.

The HTML console is used to configure image APIs, run requests manually, review history, and manage outputs. Codex integration lets a conversation initiate image generation or editing through the local service.

### Download

Download the Windows standalone package from [GitHub Releases](https://github.com/DAMNDAGER/Image2-Studio/releases/latest). The release package includes its required runtime and does not require a pre-installed Python environment.

### Features

- Generate images or edit reference images from Codex conversations through the local Image2 CLI.
- Support text-to-image, local reference images, public image URLs, and multiple reference images.
- Manage multiple image API profiles and select the active profile.
- Support common aspect ratios, preset resolutions, and custom dimensions.
- Provide a local HTML console for configuration, manual requests, history, and output management.
- Support `--dry-run` validation that stops before the final image API request and does not consume quota.

### Why Image2 Studio

- **One Codex image workflow**: use image generation and editing from Codex conversations while retaining a local console for configuration and manual work.
- **One place for image API profiles**: keep models, base URLs, paths, and authentication settings in local profiles and switch between them.
- **Local history and outputs**: keep generation records and output files under local control.

### Architecture

```text
                    ┌────────────────────┐
Codex conversation ►│ Image2 Skill / CLI │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
HTML console ──────►│ Local Image2 service│──────► Selected image API
                    └────────────────────┘
```

### Quick Start

1. Download and extract the Windows package from [GitHub Releases](https://github.com/DAMNDAGER/Image2-Studio/releases/latest).
2. Run `start_image2.bat`.
3. The local console opens in a browser. If it does not open automatically, visit `http://127.0.0.1:8765`.
4. In **API Settings**, create a profile, enter the image API base URL, model, paths, and API key, then make it active.
5. In **Codex Connection**, install or update the global Image2 Skill.
6. Restart Codex or start a new task, then request image generation or editing in the conversation.

The global Skill is installed at:

```text
%CODEX_HOME%\skills\image2
```

### Project Structure

```text
app.py              FastAPI service and image API adapter
image2_cli.py       CLI between Codex and the local service
static/             Local HTML, CSS, and JavaScript console
skills/image2/      Codex Skill source files
test_app.py         Backend tests
start_image2.*      Windows startup scripts
build_image2.ps1    Windows release build script
requirements*.txt   Runtime and build dependencies
LICENSE             MIT License
```

### Security and Data Handling

- The project does not include API keys, account credits, or subscription benefits, and it does not read personal keys from Codex `auth.json`.
- API keys are entered through the local console and stored by the backend in Windows Credential Manager; they are never returned to the frontend.
- The service listens on `127.0.0.1` by default. It is intended for single-user local use and should not be exposed publicly.
- Runtime data includes `outputs`, `image2.sqlite3`, and `.image2-token` in the application directory.
- `image2-client.json` stores local service connection information only. It does not contain the upstream image API key.
- Image-generation costs and quotas are determined by the selected image API.

### Compatibility

- Designed for OpenAI-compatible image APIs.
- Not tied to a single provider.
- Users can configure the model, base URL, generation path, edit path, authentication type, and image field name.
- Current release packages target Windows x64.

### Development

Run tests:

```powershell
python -m unittest -v
```

Build the Windows release package:

```powershell
.\build_image2.ps1
```

Runtime dependencies are listed in `requirements.txt`; build dependencies are listed in `requirements-build.txt`.

## License

This project is licensed under the [MIT License](LICENSE).
