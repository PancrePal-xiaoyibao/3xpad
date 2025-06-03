# 🔌 跃问 AI 助手 (Yuewen AI Assistant) 插件

## 📝 目录

- [插件介绍](#插件介绍)
- [功能列表](#功能列表)
- [命令列表](#命令列表)
- [配置文件 (`config.toml`)](#配置文件-configtoml)
- [安装与依赖](#安装与依赖)
- [使用方法](#使用方法)

## 🌟 插件介绍

**跃问 AI 助手** 是一款为 XXXBot 设计的插件，集成了阅文集团的跃问大模型（旧版API）和StepFun模应科技的大模型（新版API）功能。它允许用户通过聊天与AI进行智能对话、识别图片内容、切换不同模型和API版本，并进行联网搜索等。

- **作者**: xxxbot团伙
- **版本**: 0.2

## ✨ 功能列表

- **智能对话**: 通过 `yw [你的问题]` 与AI进行流畅的自然语言对话。
- **API版本切换**:
    - `yw切换旧版`: 切换到旧版API (yuewen.cn)。
    - `yw切换新版`: 切换到新版API (stepfun.com)。
- **图片识别**:
    - **单图识别**: 发送 `yw识图 [可选描述]`，然后发送一张图片，AI将分析图片内容。
    - **多图识别**: 发送 `yw识图N [可选描述]` (N为图片数量，如 `yw识图3`)，然后依次发送N张图片，最后发送 `结束` 指令，AI将综合分析这些图片。
- **用户登录**: 使用 `yw登录` 命令启动登录流程，获取个性化服务和更稳定的API访问。
- **模型管理 (仅旧版API)**:
    - `yw切换模型 [编号]`: 切换不同特性的AI模型。
    - `yw打印模型`: 查看当前支持的AI模型列表。
- **联网控制**:
    - `yw联网`: 开启AI的联网搜索能力。
    - `yw不联网`: 关闭AI的联网搜索能力。
- **会话管理**:
    - `yw新建会话`: 清除当前上下文，开始一个全新的对话。
- **内容分享 (仅旧版API)**:
    - `yw分享`: 将最近的对话内容生成一张图片进行分享。
- **帮助信息**:
    - `yw帮助`: 显示插件的可用命令和当前状态。

## 🤖 命令列表

以下是插件支持的主要命令 (默认前缀为 `yw`，可在 `config.toml` 中修改):

-   `yw [问题内容]`: 向AI提问。
-   `yw登录`: 启动登录/重新登录流程——yw手机号码——yw验证码。
-   `yw联网`: 开启联网模式。
-   `yw不联网`: 关闭联网模式。
-   `yw新建会话`: 开始一个新的对话会话，清除之前的上下文。
-   `yw切换旧版`: 切换到旧版API (yuewen.cn)。
-   `yw切换新版`: 切换到新版API (stepfun.com)。
-   `yw识图 [可选描述]`: 准备进行单张图片识别。发送此命令后，下一条消息应为图片。
-   `yw识图N [可选描述]`: 准备进行N张图片识别 (N为数字, 如 `yw识图3`)。之后依次发送N张图片。
-   `yw切换模型 [编号]` (仅旧版API): 切换AI模型。使用 `yw打印模型` 查看可用编号。
-   `yw打印模型` (仅旧版API): 显示所有可用的AI模型及其编号和特性。
-   `yw分享` (仅旧版API): 将最近的对话生成为一张图片，方便分享。
-   `yw帮助`: 显示本帮助信息和命令列表。

## ⚙️ 配置文件 (`plugins/yuewen/config.toml`)

插件的配置存储在 `plugins/yuewen/config.toml` 文件中。如果文件不存在，插件首次加载时会自动创建一个默认配置文件。

```toml
# YueWen AI Assistant Plugin Configuration
[yuewen]
# 是否启用插件 (true/false)
# 修改后需要重启XXXBot或重新加载插件生效
enable = true

# 是否需要登录 (true/false) - 通常由插件自动管理
# 如果为true且未提供有效凭证，插件会在使用时提示登录
need_login = true

# 跃问/StepFun Web ID (登录后自动填充)
# 请勿手动修改，除非你知道你在做什么
oasis_webid = ""

# 跃问/StepFun Token (登录后自动填充)
# 请勿手动修改
oasis_token = ""

# 当前使用的AI模型ID (仅当 api_version = "old" 时有效)
# 默认: 6 (deepseek r1)
# 可用模型 (旧版API):
#   1: {"name": "deepseek r1", "id": 6, "can_network": true}
#   2: {"name": "Step2", "id": 2, "can_network": true}
#   3: {"name": "Step-R mini", "id": 4, "can_network": false}
#   4: {"name": "Step 2-文学大师版", "id": 5, "can_network": false}
current_model_id = 6

# 是否启用联网搜索功能 (true/false)
# 对于不支持联网的模型，此设置无效
network_mode = true

# 插件命令的触发前缀 (例如: "yw 帮助")
# 修改后需要重启XXXBot或重新加载插件生效
trigger_prefix = "yw"

# 使用的API版本 ("old" 代表 yuewen.cn, "new" 代表 stepfun.com)
# 切换API版本后，建议使用 "yw新建会话" 开始新对话
api_version = "old"

[yuewen.image_config]
# 进行图片识别时，若用户未提供描述，则使用此默认提示
imgprompt = "解释下图片内容"

# 触发图片识别的命令关键字 (例如: "识图 这张照片里有什么")
# 结合 trigger_prefix 使用，如 "yw 识图"
trigger = "识图"
```

## 🛠️ 安装与依赖

确保您的 XXXBot 环境已安装 Python。插件依赖以下库：

- `loguru`
- `requests`
- `Pillow`
- `aiohttp`
- `toml`
- `tomli`

这些依赖项已在 `plugins/yuewen/requirements.txt` 文件中列出。您可以通过以下命令安装它们：

```bash
pip install -r plugins/yuewen/requirements.txt
```
或者，如果XXXBot有统一的依赖管理，请遵循其指导。

## 🚀 使用方法

1.  将 `yuewen` 文件夹放置在 XXXBot 的 `plugins` 目录下。
2.  (如果需要) 安装上述依赖。
3.  启动 XXXBot。插件应会自动加载。
4.  如果插件未自动创建 `config.toml`，您可以手动复制上述配置文件内容到 `plugins/yuewen/config.toml`。
5.  首次使用或需要重新登录时，发送 `yw登录` 并按照提示完成登录过程。
6.  通过发送 `yw帮助` 查看所有可用命令并开始使用。

默认情况下，插件是启用的。您可以在 `config.toml` 中设置 `enable = false` 来禁用它。 