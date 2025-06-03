# XYBot-FastGPT 插件 🎉

一个基于 XYBot 框架的插件，用于集成 FastGPT 知识库问答功能。

<img src="https://github.com/user-attachments/assets/a2627960-69d8-400d-903c-309dbeadf125" width="400" height="600">

## 简介 📚

本插件允许用户通过微信机器人与 FastGPT 知识库进行交互。用户可以提问，机器人将调用 FastGPT API 获取答案并返回。支持群聊和私聊模式，并可配置积分系统。

**作者：** 老夏的金库 💰
**版本：** 1.0.0

## 更多插件地址
  [NanSsye's XYBotV2 Plugins Collection](https://github.com/NanSsye/XYBotV2-)

## 功能特性 ✨

- **FastGPT 集成：** 无缝对接 FastGPT API，实现知识库问答。
- **多模态支持：** 支持文本、图片和文件链接的混合输入。
- **群聊 & 私聊：** 灵活应用于群聊和私聊场景。
- **命令触发：** 通过预定义命令触发问答功能。
- **积分系统：** 可配置的积分消耗，支持管理员和白名单豁免。
- **详细模式：** 可选返回 FastGPT 详细响应信息。
- **灵活配置：** 通过 TOML 文件进行详细配置。

## 安装 🛠️

1. **前置条件：**
   - 已安装 XYBot 框架。
   - 拥有 FastGPT API 密钥和应用 ID。
2. **复制插件：**
   - 将 `FastGPT.py` 文件复制到 XYBot 的 `plugins` 目录下。
   - 将 `config.toml` 文件复制到 XYBot 的 `plugins/FastGPT` 目录下。
3. **配置插件：**
   - 编辑 `plugins/FastGPT/config.toml` 文件，填入正确的 API 密钥、应用 ID 等信息。

## 配置 ⚙️

以下是 `config.toml` 文件的详细配置说明：

```toml
[FastGPT]
enable = true # 是否启用插件
# FastGPT API配置
api-key = "fastgpt-xxxxxx" # 替换为你的API密钥 🔑
base-url = "https://api.fastgpt.in/api" # FastGPT API基础URL
app-id = "你的应用ID" # 替换为您的FastGPT应用ID 🆔

# 命令配置
commands = ["FastGPT", "fastgpt", "知识库"] # 触发插件的命令 🗣️
command-tip = """-----FastGPT-----
💬知识库问答指令：
@机器人 知识库 你的问题
例如：@机器人 知识库 什么是FastGPT?
"""

# 功能配置
detail = false # 是否返回详细信息 ℹ️
max-tokens = 2000 # 最大Token数
http-proxy = "" # HTTP代理设置，如果需要 🌐

# 积分系统
price = 0 # 每次使用消耗的积分 💰
admin_ignore = true # 管理员是否免费使用 🛡️
whitelist_ignore = true # 白名单用户是否免费使用 ✅
```

## 使用方法 🚀

1. **群聊：** `@机器人 [命令] [问题]`，例如：`@机器人 知识库 什么是FastGPT?`
2. **私聊：** 直接发送问题即可。

## 依赖 📦

* `aiohttp`
* `loguru`
* `toml`
* `WechatAPI` (XYBot 框架)
* `database.XYBotDB` (XYBot 框架)
* `utils.decorators` (XYBot 框架)
* `utils.plugin_base` (XYBot 框架)

## 注意事项 ⚠️

* 请确保 FastGPT API 密钥有效。
* 如果使用代理，请正确配置 `http-proxy`。
* 图片和文件链接需要是可访问的 URL。
* 微信图片目前不支持直接处理，请上传到图床获取 URL。

## 感谢 🙏

**给个 ⭐ Star 支持吧！** 😊

**开源不易，感谢打赏支持！**

![image](https://github.com/user-attachments/assets/2dde3b46-85a1-4f22-8a54-3928ef59b85f)

感谢 XYBot 框架提供的支持！

补充说明：

优化后的逻辑（群聊分支）：
收到群聊文本消息 content。
首先检查 content 是否包含 self.image_commands 中的任何关键词，并且当前S3存储是可用的 (self.storage_type == "s3" and self.s3_config)。
如果是图片分析指令：
查找 self.image_cache 中该群聊 (from_wxid) 的缓存图片。
如果找到有效缓存图片：执行图片分析流程（检查积分、预处理、上传、调用API、回复、扣分、清缓存）。处理完毕后返回 False。
如果未找到有效缓存图片：回复用户“请先发送图片”。处理完毕后返回 False。
如果不是图片分析指令：
再检查消息开头的词 command_word 是否在 self.commands （普通文本命令列表）中。
如果是普通文本命令：按原逻辑处理文本命令（检查格式、获取query、检查积分、调用API、回复、扣分）。处理完毕后返回 False。
如果也不是普通文本命令：日志记录 TRACE 级别信息，然后返回 True，让其他插件处理。