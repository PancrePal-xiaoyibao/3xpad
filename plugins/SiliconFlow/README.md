# 硅基流动 API 插件 🚀

## 简介

硅基流动 API 插件为 XYBot 提供了与硅基流动 API 的集成，使您可以直接在微信中使用硅基流动的大语言模型服务。

## 特性

- **简单直接**：直接调用硅基流动 API，无需额外的服务器 ✅
- **丰富的模型支持**：支持硅基流动平台上的各种模型，包括通义千问、GLM等 🤖
- **代理支持**：支持配置 HTTP 代理，解决网络访问问题 🌐
- **多种类型交互**：支持自然语言文本问答、文生图、图片识别

## 安装

1. 将插件文件夹复制到 `plugins` 目录
2. 编辑 `config.toml` 配置文件，设置您的硅基流动 API 密钥
3. 重启 XYBot 或使用管理命令加载插件

## 配置说明

```toml
[SiliconFlow]
enable = true                           # 是否启用此功能
handle_all_messages = false               # 是否处理所有消息（不需要命令前缀）
cleanup_days = 3       # 临时文件清理时间，单位 天


# 文本模型配置
[TextGeneration]
enable = true                           # 是否启用此功能
api-key = ""                            # 硅基流动API密钥，必填
base-url = "https://api.siliconflow.cn/v1"  # 硅基流动API地址
default-model = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"          # 默认使用的模型
commands = ["硅基", "sf", "SiliconFlow"]    # 触发插件的命令
# 高级设置
max_tokens = 4096                       # 最大token数
temperature = 0.7                       # 温度参数
top_p = 0.7                             # Top-p采样
top_k = 50                              # Top-k采样
frequency_penalty = 0.5                 # 频率惩罚


# 图片生成配置
[ImageGeneration]
enable = true                           # 是否启用此功能
api-key = ""                            # 硅基流动API密钥，必填
base-url = "https://api.siliconflow.cn/v1"  # 硅基流动API地址
image-model = "Kwai-Kolors/Kolors"
image-size = "1024x1024"
image-steps = 20
image-guidance-scale = 7.5
image-commands = ["画图", "绘图", "生成图片"]
image-batch-size = 4


# 视觉模型配置
[VisionRecognition]
enable = true                           # 是否启用此功能
api-key = ""                            # 硅基流动API密钥，必填
base-url = "https://api.siliconflow.cn/v1"  # 硅基流动API地址
vision-model = "Qwen/Qwen2.5-VL-72B-Instruct"
auto_analyze_images = true
vision_prompt = "请详细描述这张图片的内容"
```

## 使用方法

1. 在微信中发送以下格式的消息：
   - `硅基 你的问题`
   - `sf 你的问题`
   - `SiliconFlow 你的问题`

2. 也可以在群聊中@机器人，然后使用上述命令

## 注意事项

- 此插件需要有效的硅基流动 API 密钥
- 如果在中国大陆使用，可能需要设置代理

## 故障排除

- 如果请求失败，检查硅基流动 API 密钥是否正确
- 如果响应速度慢，考虑使用代理

## 开发者信息

- 作者：XYBot团队
- 版本：1.3.1
- 许可证：MIT
