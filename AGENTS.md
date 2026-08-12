# Image2 priority

This workspace's primary image-generation path is the local Image2 service. The user must configure and select an image provider in the local HTML console before a real request.

When the user asks to generate, create, or edit an image, use the installed Image2 CLI at `%CODEX_HOME%\skills\euzhi-image2\Image2CLI.exe --prompt "..."` when it exists. Otherwise use `python image2_cli.py --prompt "..."` from this project through the local service at `http://127.0.0.1:8765`; set `IMAGE2_PYTHON` when Python is installed outside PATH. Do not use the built-in `imagegen` tool, because the result must come from the active configured Image2 provider. After generation, inspect the returned local output URL or file and include the generated image in the conversation using its absolute local path when possible.

For a simulation or safety check, use `--dry-run`. It must stop before the final image provider request and must not consume quota.

Before calling the CLI, optimize the prompt while preserving the user's intent: make the subject, action, composition, viewpoint, visual style/material, lighting, color palette, aspect ratio, and important constraints explicit. Do not invent text, logos, people, or objects the user did not request. For edits, explicitly separate what must be preserved from what should change. Send the optimized prompt to Image2 and briefly tell the user what was clarified.

When the user provides a public reference image URL, add `--image-url "https://..."`; the backend downloads it and sends it to the active provider using its configured image field. When a chat attachment is available as a local path, use `--image-path "C:\\path\\to\\image.png"` instead. The user should not need to fill the web form manually.

If the local service is unavailable, run `start_image2.ps1`, or start it with the Python interpreter configured in `IMAGE2_PYTHON` using `-m uvicorn app:app --host 127.0.0.1 --port 8765`, then retry once. Never put an API key in a command, HTML, or client-side JavaScript. Select or configure a provider at `http://127.0.0.1:8765` before any real request.

For a real image provider request, a service started inside a restricted Codex sandbox may not have outbound network access. In that case, request one host-approved network-enabled execution for the same Uvicorn command, keep it bound to `127.0.0.1`, and retry the CLI once after approval. A Skill or this file cannot grant permission by itself. A `--dry-run` must never request or use external network access.

## Release maintenance

After every change to the backend, frontend, startup scripts, build scripts, documentation, or packaging configuration, rebuild the packaged Image2Studio executable and synchronize the release directory before handing the work back to the user. Validate that the packaged service starts and serves the current UI. Never copy API keys, local tokens, SQLite databases, generated images, or runtime logs into the release package.
