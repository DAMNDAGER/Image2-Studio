# Image2 Studio

## 中文说明

Image2 Studio 是一个本地图片生成和编辑工具。它的核心用途是让 Codex 直接调用你配置的图片 API，HTML 页面用于配置 API、手动生成图片和查看本地输出。

### 启动

双击同目录下的 `start_image2.bat`。程序会启动本地服务并打开：

```text
http://127.0.0.1:8765/
```

发行版不需要单独安装 Python。请保留 `Image2Studio\Image2Studio.exe` 旁边的 `_internal` 文件夹，以及发行版根目录的启动脚本。

### 第一次使用

1. 打开“设置”，新建或选择图片 API 配置。
2. 填写 Base URL、模型、文生图路径、编辑路径和鉴权方式。
3. 在 API Key 输入框填写自己的密钥并保存。
4. 点击“测试 /models”确认接口可用，再设为当前配置。
5. 在 Codex 接入面板安装或更新全局 Skill，之后重新打开 Codex 窗口。

配置完成后，可以直接在 Codex 对话中提出“生成图片”或“编辑这张图片”。

### 图片和配置保存位置

运行数据保存在发行版程序目录内：

```text
Image2Studio\outputs\           生成的图片
Image2Studio\image2.sqlite3     配置和历史数据
Image2Studio\.image2-token      本地服务令牌
Image2Studio\image2-client.json CLI 的本地连接信息
```

API Key 不写入 HTML、Skill 或 CLI 参数，由后端保存到 Windows 系统凭据库。

## English

Image2 Studio is a local image generation and editing tool. Its main purpose is to let Codex call the image API configured by the user. The HTML console is provided for API configuration, manual generation, and local output history.

### Start

Double-click `start_image2.bat` in this folder. The application starts the local service and opens:

```text
http://127.0.0.1:8765/
```

The release package does not require a separate Python installation. Keep the `_internal` directory beside `Image2Studio\Image2Studio.exe`, together with the launcher scripts in the release root.

### First use

1. Open Settings and create or select an image API profile.
2. Enter the base URL, model, generation path, edit path, and authentication method.
3. Enter your API key and save the profile.
4. Use “Test /models” to verify the connection, then activate the profile.
5. Open the Codex connection panel, install or update the global Skill, and reopen Codex.

After setup, you can ask Codex to generate an image or edit an attached reference image directly in the conversation.

### Local data

Runtime data is stored beside the application:

```text
Image2Studio\outputs\           generated images
Image2Studio\image2.sqlite3     profiles and history
Image2Studio\.image2-token      local service token
Image2Studio\image2-client.json local CLI connection data
```

The API key is not written to HTML, the Skill, or CLI arguments. The backend stores it in Windows Credential Manager.

Copyright (c) 2026 DAGER · All Rights Reserved
