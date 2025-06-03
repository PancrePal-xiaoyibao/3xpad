# ChatSummary - XYBotv2 聊天记录总结插件 📝

[![Version](https://img.shields.io/github/v/release/your_username/ChatSummary)](https://github.com/your_username/ChatSummary/releases)
[![Author](https://img.shields.io/badge/Author-%E8%80%81%E5%A4%8F%E7%9A%84%E9%87%91%E5%BA%93-blue)](https://github.com/your_username)
[![License](https://img.shields.io/github/license/your_username/ChatSummary)](LICENSE)

**本插件是 [XYBotv2](https://github.com/HenryXiaoYang/XYBotv2) 的一个插件。**

<img src="https://github.com/user-attachments/assets/a2627960-69d8-400d-903c-309dbeadf125" width="400" height="600">

## 简介

`ChatSummary` 是一款强大的聊天记录总结插件！ 它可以自动分析聊天记录，并生成包含话题、参与者、时间段、过程和评价的总结报告 📊。 插件支持通过 Dify 大模型进行总结，提供更智能、更全面的分析结果 🧠。

## 功能

*   **聊天记录总结：** 自动分析聊天记录，生成总结报告 🧾。
*   **话题提取：** 提取聊天记录中的主要话题 🗣️。
*   **参与者识别：** 识别参与话题讨论的用户 👤。
*   **时间段分析：** 分析话题讨论的时间段 ⏱️。
*   **过程描述：** 简要描述话题讨论的过程 ✍️。
*   **情感评价：** 对话题讨论进行情感评价 🤔。
*   **Dify 集成：** 通过 Dify 大模型进行总结，提供更智能的分析结果 ✨。
*   **灵活的总结方式：**
    *   **默认条数总结：** 只输入 `$总结` 或 `总结` 时，默认总结最近 100 条消息 💬。
    *   **指定条数总结：** 输入 `$总结 200` 或 `总结 200` 时，总结最近 200 条消息 🔢。
    *   **指定时间段总结：** 输入 `$总结 1小时` 或 `总结 1小时` 时，总结最近 1 小时的消息 🕐。
*   **数据库存储：** 将聊天记录存储到 SQLite 数据库中，方便后续分析和查询 💾。
*   **定期清理：** 定期清理数据库中的旧消息，保持数据库的精简 🧹。
*   **独立表格：** 为每个聊天（个人或群组）创建独立的表格，保证数据隔离和查询效率 🗂️。

## 安装

1.  确保你已经安装了 [XYBotv2]([https://github.com/HenryXiaoYang/XYBotV2])。
2.  将插件文件复制到 XYBotv2 的插件目录中 📂。
3.  安装依赖：`pip install loguru aiohttp tomli` (如果需要) 🛠️
4.  配置插件（见配置章节）⚙️。
5.  重启你的 XYBotv2 应用程序 🔄。

## 配置

插件的配置位于 `config.toml` 文件中 📝。以下是配置示例：

```toml
[ChatSummary.Dify]
enable = true              # 是否启用 Dify 集成
api-key = "你的 Dify API 密钥"   # 你的 Dify API 密钥
base-url = "你的 Dify API Base URL"  # 你的 Dify API Base URL
http-proxy = ""               # HTTP 代理服务器地址 (可选)，如 "http://127.0.0.1:7890"

[ChatSummary]
enable = true
commands = ["$总结", "总结"]  # 触发总结的命令
default_num_messages = 100 # 默认总结 100 条消息
summary_wait_time = 60      # 总结等待时间（秒）
```

**给个 ⭐ Star 支持吧！** 😊

**开源不易，感谢打赏支持！**

![image](https://github.com/user-attachments/assets/2dde3b46-85a1-4f22-8a54-3928ef59b85f)
