# VideoSender 🎬

随机播放小姐姐视频，用于 XYBotV2

<img src="https://github.com/user-attachments/assets/a2627960-69d8-400d-903c-309dbeadf125" width="400" height="600">
## 一、插件概述

VideoSender 是一个功能强大的插件，它能够从多个视频源中随机获取视频，并将视频数据以 Base64 编码的形式发送给用户。同时，若系统中安装了 ffmpeg，插件还支持从视频中提取缩略图，并在发送视频时附带缩略图，提升用户体验。

## 二、功能特性

- **🎥 多视频源支持：** 可以配置多个视频源，支持随机选择视频源或指定特定视频源获取视频。
- **🖼️ 缩略图提取：** 利用 ffmpeg 从视频中提取缩略图，在发送视频时一并提供，增强展示效果。
- **⚡️ 异步操作：** 采用异步编程模型，使用 asyncio 和 aiohttp 进行异步 HTTP 请求和文件下载，提高性能和响应速度。
- **⚠️ 完善错误处理：** 具备完善的错误处理机制，在获取视频、下载视频、提取缩略图等过程中出现异常时，能给用户明确的错误提示。

## 三、安装与配置

1.  **安装依赖**

    确保你的 Python 环境中已经安装了以下依赖库：

    ```bash
    pip install aiohttp loguru filetype Pillow
    ```

    同时，需要安装 ffmpeg 以支持缩略图提取功能。不同操作系统的安装方法如下：

    -   **Ubuntu/Debian**

        ```bash
        sudo apt-get install ffmpeg
        ```

    -   **CentOS/RHEL**

        ```bash
        sudo yum install ffmpeg
        ```

    -   **macOS（使用 Homebrew）**

        ```bash
        brew install ffmpeg
        ```

2.  **配置文件**

    在 `plugins/VideoSender` 目录下创建 `config.toml` 文件，并进行如下配置：

    ```toml
    [VideoSender]
    enable = true
    commands = ["发送视频", "来个视频", "随机视频", "视频目录"]
    ffmpeg_path = "/usr/bin/ffmpeg"  # ffmpeg 路径，根据实际情况修改
    video_sources = [
        { name = "视频源1", url = "https://example.com/video1.mp4" },
        { name = "视频源2", url = "https://example.com/video2.mp4" },
        # 可以添加更多视频源
    ]
    ```

    配置项说明：

    -   `enable`：是否启用该插件，`true` 为启用，`false` 为禁用。
    -   `commands`：触发插件功能的命令列表，用户输入这些命令时，插件会做出相应处理。
    -   `ffmpeg_path`：ffmpeg 的安装路径，确保路径正确，以便插件能正常调用 ffmpeg 进行缩略图提取。
    -   `video_sources`：视频源列表，每个视频源包含 `name`（视频源名称）和 `url`（视频源的 URL）。

## 四、使用方法

1.  **发送随机视频**

    用户输入 `随机视频` 命令，插件会随机选择一个视频源，获取视频链接，下载视频数据，并尝试提取缩略图，最后将视频和缩略图（如果提取成功）发送给用户。例如：

    ```plaintext
    随机视频
    ```

2.  **查看视频目录**

    用户输入 `视频目录` 命令，插件会列出所有可用的视频源名称，方便用户选择特定的视频源。例如：

    ```plaintext
    视频目录
    ```

    插件会回复：

    ```plaintext
    可用的视频系列：
    - 视频源1
    - 视频源2
    ```

3.  **发送指定视频源的视频**

    用户输入视频源名称作为命令，插件会从该指定的视频源获取视频并发送给用户。例如：

    ```plaintext
    视频源1
    ```

## 五、错误处理

-   **配置文件问题：** 如果 `config.toml` 文件未找到，插件会自动禁用，并记录错误日志。
-   **视频获取失败：** 若未能获取到有效的视频链接或下载视频数据失败，插件会向用户发送相应的错误提示，如 “未能获取到有效的视频，请稍后重试。”
-   **缩略图提取失败：** 如果 ffmpeg 未安装或执行 ffmpeg 命令失败，插件会提示用户无法提取缩略图。
-   **Base64 编码失败：** 在将视频或缩略图数据进行 Base64 编码时，如果出现错误，插件会向用户发送 “视频编码失败，请稍后重试。” 的提示。

## 六、注意事项

-   请确保 `config.toml` 文件中的 `ffmpeg_path` 配置正确，否则无法进行缩略图提取。
-   由于插件依赖于网络请求获取视频数据，网络不稳定可能会导致视频获取或下载失败，建议在网络状况良好的环境下使用。
-   插件在处理视频时会创建临时文件夹 `temp_videos` 来存储临时文件，处理完成后会自动清理该文件夹。如果在处理过程中出现异常，可能会导致临时文件残留，可手动删除该文件夹。

**给个 ⭐ Star 支持吧！** 😊

**开源不易，感谢打赏支持！**

![image](https://github.com/user-attachments/assets/2dde3b46-85a1-4f22-8a54-3928ef59b85f)
