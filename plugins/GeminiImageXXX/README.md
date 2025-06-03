# GeminiImageXXX 插件

基于Google Gemini的图像生成插件，专为XXXBot平台开发。

## 功能特点

- **图像生成**：根据文本描述生成高质量图片
- **图像编辑**：基于现有图片进行修改
- **参考图编辑**：上传图片并根据文本指令进行编辑
- **图像融合**：融合两张图片创作新图像
- **图像分析**：识别图片内容，支持追问
- **反向提示词**：从图片反推可能的生成提示词
- **会话模式**：支持连续对话和图片编辑
- **自动翻译**：内置中文提示词翻译功能，提升生成质量

## 安装方法

1. 确保Python版本 >= 3.8
2. 安装依赖：`pip install tomli aiohttp pillow`
3. 将整个`GeminiImageXXX`目录复制到XXXBot的`plugins`目录下
4. 修改`config.toml`文件，填入你的Gemini API密钥
5. 重启XXXBot

## 配置文件说明

配置文件`config.toml`包含以下主要设置：

```toml
[basic]
# 是否启用插件
enable = true
# Gemini API Key
gemini_api_key = "your_api_key_here"
# 使用的模型
model = "gemini-2.0-flash-exp-image-generation"
# 图片保存路径 (相对于插件目录)
save_path = "temp_images"
# 会话过期时间 (秒)
conversation_expire_seconds = 180
# 最大会话消息数
max_conversation_messages = 10

[commands]
# 各功能触发命令配置
generate = ["g生成", "g画图", "g画"]
# ...其他命令配置

[points]
# 积分系统配置
enable_points = false
generate_image_cost = 10
edit_image_cost = 15

[proxy]
# 代理设置
enable_proxy = false
proxy_url = ""
use_proxy_service = true
proxy_service_url = ""

[translate]
# 翻译设置
enable = true
api_base = "https://open.bigmodel.cn/api/paas/v4"
api_key = ""
model = "glm-4-flash"
```

## 使用方法

### 基本命令

- **生成图片**：`g生成 [描述文本]` 或 `g画图 [描述文本]`
- **编辑图片**：`g改图 [编辑指令]` (需先生成或上传图片)
- **参考图编辑**：`g参考图 [编辑指令]` (会提示上传图片)
- **图片融合**：`g融图 [描述文本]` (会提示上传两张图片)
- **图片分析**：`g识图 [可选问题]` (会提示上传图片)
- **反向提示词**：`g反推` (会提示上传图片)
- **追问分析**：`g追问 [问题]` (对上一次识图进行追问)
- **结束会话**：`g结束对话` 或 `g结束`
- **翻译控制**：`g开启翻译`/`g关闭翻译` (控制是否翻译中文提示词)

### 工作流程示例

1. **图片生成**：
   ```
   用户: g生成 一只穿着宇航服的猫咪在太空中
   机器人: [生成的图片]
   ```

2. **编辑已生成的图片**：
   ```
   用户: g改图 给猫咪添加一顶帽子
   机器人: [编辑后的图片]
   ```

3. **使用参考图**：
   ```
   用户: g参考图 将背景改为城市夜景
   机器人: 请发送需要编辑的参考图片
   用户: [上传图片]
   机器人: [编辑后的图片]
   ```

4. **图片融合**：
   ```
   用户: g融图 将这两张图片融合成一张画面
   机器人: 请发送融图的第一张图片
   用户: [上传第一张图片]
   机器人: 成功获取第一张图片，请发送第二张图片
   用户: [上传第二张图片]
   机器人: [融合后的图片]
   ```

5. **图片分析**：
   ```
   用户: g识图 这张图片有什么特点？
   机器人: 请在3分钟内发送需要gemini识别的图片
   用户: [上传图片]
   机器人: [图片分析结果]
   ```

## 注意事项

1. 图片生成和编辑功能需要有效的Google Gemini API密钥
2. 图片编辑需要在会话有效期内（默认3分钟）
3. 会话超时后需要重新开始对话
4. 所有生成的图片会临时保存在插件的`temp_images`目录下
5. 如果需要使用代理，请在配置文件中设置代理信息

## 开发者信息

原插件开发者: Lingyuzhou
XXXBot移植版开发者: [XXXbot]
版本: 1.0.0

## 声明

本插件使用Google Gemini API，使用时请遵守相关服务条款和内容政策。禁止生成违规内容。 
