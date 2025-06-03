# Doubao 插件

## 简介

Doubao 是一个基于字节跳动豆包 AI 的聊天插件，为微信机器人提供智能对话和图片生成能力。无论是私聊还是群聊，Doubao 都能提供灵活的 AI 对话体验。

## 主要功能

- **文本对话**：回答用户的文本问题，提供智能对话服务
- **图片生成**：支持 AI 图片生成，可以显示豆包生成的图片
- **图片网格与序号**：多张图片时自动生成网格图，带有醒目序号，方便用户查看单张高清图片
- **引用回复**：支持通过引用消息进行交互
- **群聊 @ 消息**：支持在群聊中通过 @ 机器人触发对话
- **命令触发**：支持多种前缀命令触发对话
- **用户限制**：提供每日对话次数限制功能
- **管理员权限**：可设置仅管理员使用或所有用户均可使用

## 安装方法

1. 将 Doubao 文件夹放入机器人的 plugins 目录中
2. 修改 `config.toml` 配置文件，设置必要参数
3. 重启机器人或重新加载插件

## 配置说明

配置文件位于 `plugins/Doubao/config.toml`，主要配置项说明：

### 基础配置

```toml
[Doubao]
# 是否启用插件
enable = true

# 豆包API配置
conversation_id = "你的豆包会话ID"  # 必需
cookie = "你的豆包cookie"    # 必需，用于API认证
```

### 命令触发配置

```toml
# 命令触发配置
# 只有以下命令开头的消息才会触发豆包能力
commands = [
    "#豆包",
    "#豆",
    "#doubao",
    "/豆包",
    "/db",
    "/doubao",
    "豆包",
    "doubao",
    "@豆包",
    "@db",
    "@doubao",
    "豆",
    "db"
]
```

### 聊天配置

```toml
# 聊天配置
private_chat = true  # 是否允许私聊
group_chat = true    # 是否允许群聊
admin_only = false   # 是否仅管理员可用
bot_wxid = "你的机器人wxid"  # 修改为实际被@的wxid
daily_limit = 20     # 每人每日对话次数限制

# 会话模式配置
session_timeout = 30  # 会话超时时间（秒），默认30秒
```

### 引用消息功能配置

```toml
# 引用消息功能配置
enable_quote = true   # 是否启用引用消息回复功能，设为false可避免与元宝的引用功能冲突
private_quote = true  # 是否允许在私聊中响应引用消息
group_quote = true    # 是否允许在群聊中响应引用消息
quote_require_at = true  # 群聊中引用消息是否需要同时@机器人才响应
```

### 管理员配置

```toml
# 管理员列表
admin_list = [
    "管理员1的wxid",
    "管理员2的wxid"
]
```

## 使用方法

### 文本对话

1. **私聊模式**：直接发送以配置的命令前缀开头的消息，例如：`#豆包 今天天气怎么样？`
2. **群聊模式**：在群里@机器人并发送消息，或使用命令前缀，例如：`@机器人 今天天气怎么样？`或`#豆包 今天天气怎么样？`

### 引用回复

1. **私聊引用**：引用一条消息并发送您的问题
2. **群聊引用**：在群里引用一条消息并@机器人（如果启用了`quote_require_at`）

### 图片查看

当豆包返回多张图片时，会自动生成图片网格并添加序号。要查看单张高清图片：

1. 发送`查看图片 序号`，例如：`查看图片 1`
2. 机器人会发送对应序号的高清大图

## 常见问题

### 1. 如何获取豆包API所需参数？

1. 使用浏览器访问 https://www.doubao.com 并登录
2. 按F12打开开发者工具，切换到"网络"(Network)标签
3. 刷新页面并发起一次对话
4. 找到名为"completion"的请求，从其中可以找到：
   - URL中的conversation_id和section_id
   - 请求头中的cookie

### 2. 图片不显示或无法获取图片？

- 确保您的豆包账号有权限使用图片生成功能
- 检查cookie是否有效，过期的cookie需要重新获取
- 查看日志中是否有与图片相关的错误信息

### 3. 机器人不响应命令？

- 检查config.toml中的enable是否设为true
- 确认您使用的命令前缀包含在commands列表中
- 检查是否超出了daily_limit设置的每日次数限制
- 查看日志中是否有错误信息

## 目录结构

```
plugins/Doubao/
├── main.py             # 主插件代码
├── config.toml         # 配置文件
├── README.md           # 说明文档
├── cache/              # 图片缓存目录
├── logs/               # 日志目录
└── chat_history.jsonl  # 聊天历史记录
```

## 更新记录

### v1.0.0
- 初始版本，实现基本的豆包对话功能
- 支持文本对话和图片生成
- 添加群聊和私聊支持
- 实现图片网格功能，支持图片序号查看

## 注意事项

- 请妥善保管您的cookie信息，不要泄露给他人
- 图片缓存会自动清理，默认保留最新的25张图片
- 插件仍在开发中，欢迎提供反馈和建议

## 许可证

本插件仅供学习交流使用，请遵守相关法律法规。 

## 联系方式

<div align="center"><table><tbody><tr><td align="center"><b>个人QQ</b><br><img src="https://wmimg.com/i/1119/2025/02/67a96bb8d3ef6.jpg" width="250" alt="作者QQ"><br><b>QQ：154578485</b></td><td align="center"><b>QQ交流群</b><br><img src="https://wmimg.com/i/1119/2025/02/67a96bb8d6457.jpg" width="250" alt="QQ群二维码"><br><small>群内会更新个人练手的python项目</small></td><td align="center"><b>微信赞赏</b><br><img src="https://wmimg.com/i/1119/2024/09/66dd37a5ab6e8.jpg" width="500" alt="微信赞赏码"><br><small>要到饭咧？啊咧？啊咧？不给也没事~ 请随意打赏</small></td><td align="center"><b>支付宝赞赏</b><br><img src="https://wmimg.com/i/1119/2024/09/66dd3d6febd05.jpg" width="300" alt="支付宝赞赏码"><br><small>如果觉得有帮助,来包辣条犒劳一下吧~</small></td></tr></tbody></table></div>

---

### 📚 推荐阅读

-   [wx群聊总结助手：一个基于人工智能的微信群聊消息总结工具，支持多种AI服务，可以自动提取群聊重点内容并生成结构化总结](https://github.com/Vita0519/wechat_summary)
-   [历时两周半开发的一款加载live2模型的浏览器插件](https://www.allfather.top/archives/live2dkan-ban-niang)
-   [PySide6+live2d+小智 开发的 AI 语音助手桌面精灵，支持和小智持续对话、音乐播放、番茄时钟、书签跳转、ocr等功能](https://www.bilibili.com/video/BV1wN9rYFEze/?share_source=copy_web&vd_source=f3d1033524bcd51cf10e8312ef8376ff)
-   [github优秀开源作品集](https://www.allfather.top/mol2d/)

---
