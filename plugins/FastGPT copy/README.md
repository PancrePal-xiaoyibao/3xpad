<<<<<<< HEAD
 # FastGPT 微信机器人插件

一个基于 XYBot 框架的插件，用于集成 FastGPT 知识库问答功能，支持文本对话和图片分析。

本项目由小x宝社区(https://github.com/pancrePal-xiaoyibao/pancrePal-xiaoyibao)开发者Sam贡献，目的是服务患者在Fastgpt RAG平台上，借助优秀的多模态模型能力（stepfun- step1o-Vision等）方便的进行病情对话和图像报告分析。


## 开发逻辑

### 1. 消息处理流程

#### 1.1 文本消息处理
- 私聊模式：直接处理用户输入的文本 ##主要用于测试
- 群聊模式：##用于实际环境
  - 检查是否为图片分析命令（如"请分析"、"图片分析"等）
  - 检查是否为普通文本命令（如"xyb 如何处理胆道梗阻？"等）
  - 根据命令类型进行相应处理

#### 1.2 图片消息处理
- 私聊模式：直接处理图片
- 群聊模式：
  - 缓存图片信息
  - 等待用户发送分析命令
  - 分析最近的有效图片

### 2. 图片处理流程
1. 提取图片数据
2. 预处理图片（格式转换、大小调整等）
3. 上传到 S3 存储（如果配置）
4. 生成可访问的 URL
5. 调用 FastGPT API 进行分析

### 3. API 调用流程
1. 构建请求数据
2. 发送 API 请求
3. 处理响应结果
4. 返回分析内容

## 积分系统说明

目前积分检查功能已被注释，默认允许所有请求通过。后续可通过配置启用：

```python
async def _check_point(self, bot: WechatAPIClient, message: dict) -> bool:
    # 暂时关闭积分检查，直接返回 True
    return True
```

完整的积分系统支持：
- 可配置每次请求消耗的积分
- 支持管理员豁免
- 支持白名单用户豁免
- 支持群聊和私聊不同场景

## 配置说明

### 基础配置：复制config.toml.bak为config.toml，参考其说明细节修改。

```toml
[FastGPT]
enable = true                           # 是否启用插件
api-key = "your-api-key"               # FastGPT API 密钥
base-url = "https://api.fastgpt.in/api" # API 基础 URL
app-id = "your-app-id"                 # FastGPT 应用 ID
```

### 命令配置
```toml
commands = ["FastGPT", "知识库"]        # 文本命令列表
image-commands = ["图片分析", "报告分析"] # 图片分析命令列表
command-tip = "请输入问题内容"          # 命令提示
detail = false                         # 是否返回详细响应
```

### 图片处理配置
```toml
storage-type = "s3"                    # 存储类型：s3 或 none
image-tmp-dir = "tmp/fastgpt_images"   # 临时文件目录
max-image-size-bytes = 5242880         # 最大图片大小（5MB）
allowed-formats = ["jpg", "png", "gif"] # 允许的图片格式
```

### S3 存储配置（可选-参照config.toml.bak）
```toml
s3-access-key = "your-access-key"      # S3 访问密钥
s3-secret-key = "your-secret-key"      # S3 密钥
s3-endpoint = "your-endpoint"          # S3 终端节点
s3-bucket = "your-bucket"              # S3 存储桶
s3-secure = true                       # 是否使用 HTTPS
```

### 积分系统配置（当前已注释）
```toml
price = 5                              # 每次请求消耗积分
admin_ignore = true                    # 管理员是否豁免
whitelist_ignore = true                # 白名单是否豁免
```

## 使用示例

### 文本对话
- 私聊：直接发送问题
- 群聊：使用命令前缀，如 "FastGPT 什么是人工智能？"

### 图片分析
- 私聊：直接发送图片
- 群聊：
  1. 发送图片
  2. 发送分析命令（如"请分析"）

## 注意事项

1. 确保 API 密钥和应用 ID 配置正确
2. 如使用 S3 存储，需正确配置相关参数
3. 建议在正式环境中启用积分系统
4. 图片分析功能需要稳定的网络环境

## 开发计划

- [ ] 完善积分系统
- [ ] 添加更多图片处理选项
- [ ] 优化群聊交互体验
- [ ] 添加更多自定义配置选项

## 贡献指南

欢迎提交 Issue 和 Pull Request 来帮助改进这个插件。

## 许可证

MIT License

## 关于小X宝社区和招募
概要介绍


#小胰宝 是一个病友自助开始的项目，23年创立，24年中开源发展，24年底捐献给天工开物基金会，25年升级为社区化，由基金会和社区管理委员会CMC管理，构建纯血版的AI类公益开源项目- #小X宝社区，积极推动跨社区合作，专业推动社区规范管理，目前生态人群180+。社区目的是推动AI技术和RAG应用的普及化，集合力量助力25+癌种患者，并延伸至280+罕见病领域，立足患者公益服务，通过技术+任务，有效减少医患信息差，推动患者/家属规范治疗，减低焦虑。目前已经推出了小胰宝助手，小肺宝助手，小萌宝助手，小粉宝助手，小胃宝，小妍宝，小飞侠助手（首个罕见病领域应用）等项目。

了解社区
- 社区具备公益x开源双重属性,属于AI社区中的创新社区 
- 👀  了解社区, 可以点击 https://hi.xiao-x-bao.com.cn 
- ‼️ 了解更多志愿者的责任，点击 https://faq.xiao-x-bao.com.cn 
- ❤️  考虑好了，click "i am in", 点击加入我们 https://iamin.xiao-x-bao.com.cn
- 😊 社区任务全透明化，不仅开放阅读，也开放了创建，鼓励志愿者加入自己的梦想项目 https://task.xiaoyibao.com.cn 
- 👌 首个贡献：您的辅导员，会和您一起沟通介绍，帮助您在第一周确定首个贡献计划 First Good Issue https://myfirst.xiao-x-bao.com.cn

- 欢迎体验demo:
⭐️ 小胰宝3个版本：https://chat.xiaoyibao.com.cn(科普版), https://pro.xiaoyibao.com.cn(pro版本），以及https://deepseek.xiaoyibao.com.cn
⭐️小肺宝: https://chat.xiaofeibao.com.cn
⭐️小萌宝: https://pro.xiaomengbao.cn/
⭐️小粉宝：https://xfb.xiaoyibao.com.cn (后续会有独立域名）
⭐️小胃宝:   https://chat.xiaoweibao.com.cn （科普版), https://pro.xiaoweibao.com.cn(专业版-首个社区合作项目）

- 欢迎加入社区贡献项目：
👏 为推广患者个人掌握智能体构建的 小X宝社区“AI探宝计划”(https://wiki.xiao-x-bao.com.cn)
👏 标准的github/gitcode上的代码和项目贡献  我们已经开源了3个项目仓库，包括小胰宝，MinerU-xyb(https://github.com/PancrePal-xiaoyibao/miniapp-uniapp)，以及fastgpt-on-wechat（thttps://github.com/hanfangyuan4396/fastgpt-on-wechat），Gemini-2.0病情demo（https://github.com/PancrePal-xiaoyibao/gemini2.0-xiaoyibao）期待更多开源加入完善社区，提供开源能力；
👏 开放病友共创的第一个标准wiki ： 小X宝社区“胰腺肿瘤并发症病友共创宝典” (https://bfz.xiao-x-bao.com.cn)
=======
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
>>>>>>> upstream/main
