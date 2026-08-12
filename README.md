# Image2 Studio

## 中文说明

Image2 Studio 是一个面向 Codex 的本地图片工作台。它在本机提供统一的图片服务，让 Codex 对话和 HTML 控制台共用同一套图片 API 配置。

### 主要能力

- 在 Codex 对话中生成图片或编辑参考图。
- 使用本地 CLI 和 Codex Skill 连接 Image2 服务。
- 支持文生图、参考图编辑、本地上传和公开图片 URL。
- 支持常用画面比例、预设分辨率和自定义尺寸。
- 支持多个图片 API 配置，API Key 保存到 Windows 系统凭据库。
- HTML 控制台提供配置、生成、历史记录和本地输出管理。

### 项目结构

```text
app.py              FastAPI 服务和图片 API 适配层
image2_cli.py       Codex 与本地服务之间的 CLI
static/             HTML、CSS 和 JavaScript 控制台
skills/             Codex Skill 源文件
test_app.py         后端测试
start_image2.*      Windows 启动脚本
build_image2.ps1    PyInstaller 构建脚本
requirements*.txt   运行和构建依赖
LICENSE             MIT License
```

### 工作方式

```text
Codex 对话 ─┐
            ├─ Image2 CLI ─ 本地 Image2 服务 ─ 用户选择的图片 API
HTML 控制台 ┘
```

图片 API、模型和鉴权方式由使用者在本地控制台中配置。项目不内置用户 API Key、账户额度或订阅权益，也不会自动读取 Codex `auth.json` 中的个人密钥。

### 数据边界

程序运行时会在当前程序目录创建 `outputs`、`image2.sqlite3` 和 `.image2-token`。CLI 使用的 `image2-client.json` 只保存本地连接信息，不保存上游 API Key。API Key 由后端写入 Windows 系统凭据库。

本地服务默认只绑定 `127.0.0.1`，适合单用户本机使用，不应直接暴露到公网。生成图片可能产生第三方服务费用或消耗第三方额度，具体规则由使用者选择的图片 API 决定。

## English

Image2 Studio is a local image workspace designed for Codex. It provides one local image service so Codex conversations and the HTML console can use the same image API configuration.

### Features

- Generate and edit images directly from Codex conversations.
- Connect Codex to the local service through a CLI and Codex Skill.
- Support text-to-image, reference-image editing, local uploads, and public image URLs.
- Support common aspect ratios, preset resolutions, and custom dimensions.
- Manage multiple image API profiles while storing API keys in Windows Credential Manager.
- Use the HTML console for configuration, generation, history, and local output management.

### Architecture

```text
Codex conversation ─┐
                    ├─ Image2 CLI ─ local Image2 service ─ selected image API
HTML console        ┘
```

The user configures the image API, model, and authentication method locally. The project does not include user API keys, account credits, or subscription benefits, and it does not automatically read personal keys from Codex `auth.json`.

### Data boundary

At runtime, the application creates `outputs`, `image2.sqlite3`, and `.image2-token` beside the running application. The CLI `image2-client.json` contains only local connection data. The upstream API key is stored by the backend in Windows Credential Manager.

The service binds to `127.0.0.1` by default and is intended for single-user local use. It should not be exposed publicly. Image generation may incur third-party charges or consume third-party credits according to the selected image API provider.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
