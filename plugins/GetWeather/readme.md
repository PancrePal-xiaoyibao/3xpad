# 🌤️ 天气查询插件

## 📝 功能说明
本插件提供天气查询功能，支持多种查询格式：
- 天气 城市名
- 天气城市名
- 城市名天气
- 城市名 天气

## 🔑 配置说明

### 1. 获取和风天气 JWT参数
1. 访问[和风天气开发平台](https://dev.qweather.com/docs/configuration/project-and-key/)
2. 注册并创建应用
4. 获取api_host：申请后1-2天会下发，在https://console.qweather.com/setting?lang=zh中，找到API Host
5. https://console.qweather.com/project?lang=zh中创建项目，创建后按照提示https://console.qweather.com/project/2NTGFT493T/credential/new?lang=zh创建凭据；

- 项目页获取 “项目ID“，填充到jwt-sub;
- 项目页点进去项目后，获取“凭据ID”，填充到jwt-kid


### 2. 生成密钥对
```bash
# 生成私钥
openssl genpkey -algorithm ED25519 -out ed25519-private.pem

# 从私钥生成公钥
openssl pkey -pubout -in ed25519-private.pem > ed25519-public.pem

cat ./ed25519-private.pem 把完整内容填写到toml文件中
```

### 3. JWT 生成与缓存机制
JWT token 的生成和缓存机制如下：
- **生成逻辑**：JWT token 使用 `EdDSA` 算法生成，包含以下声明：
  - `iat` (Issued At)：JWT 的发行时间，设置为当前时间减去 30 秒，以应对潜在的时钟偏差。
  - `exp` (Expiration Time)：JWT 的过期时间，默认为当前时间加上 15 分钟（900 秒）。
  - `sub` (Subject)：JWT 的主题，设置为项目 ID。
- **缓存机制**：生成的 JWT token 会被缓存，并在过期前 5 分钟自动刷新。如果缓存的 token 仍然有效且不需要刷新，则直接返回缓存的 token。

### 5. 配置插件

1. 打开 `config.toml` 文件
2. 将私钥内容设置为 `api-key` 的值：
```toml
[GetWeather]
enable = true
api-key = """-----BEGIN PRIVATE KEY-----
****

-----END PRIVATE KEY-----"""
api-host = "https://k**.re.qweatherapi.com"
jwt-kid = "K*******T"  # 从控制台获取的凭据ID
jwt-sub = "2*******T"  # 从控制台获取的项目ID
```

## 🚀 使用方法
1. 在聊天中发送以下任意格式：
   - `天气 北京`
   - `天气北京`
   - `北京天气`
   - `北京 天气`

2. 机器人将返回该城市的天气信息，包括：
   - 实时天气
   - 温度
   - 湿度
   - 风向
   - 风力等级

## ⚠️ 注意事项
1. 确保 API Key 正确配置
2. 城市名称需要准确，建议使用标准城市名
3. 如遇到查询失败，请检查网络连接和 API Key 是否有效

## 🔧 故障排除
1. 如果插件无法响应，请检查：
   - 配置文件是否正确
   - API Key 是否有效
   - 网络连接是否正常

2. 如果返回错误信息，请确认：
   - 城市名称是否正确
   - API 调用次数是否超限
   - 服务器是否正常运行

## 📞 支持与反馈
如有问题或建议，请通过以下方式反馈：
1. 提交 Issue
2. 联系管理员
3. 在交流群中反馈

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
⭐️小胃宝: https://chat.xiaoweibao.com.cn （科普版), https://pro.xiaoweibao.com.cn(专业版-首个社区合作项目）

- 欢迎加入社区贡献项目：
👏 为推广患者个人掌握智能体构建的 小X宝社区“AI探宝计划”(https://wiki.xiao-x-bao.com.cn)
👏 标准的github/gitcode上的代码和项目贡献  我们已经开源了3个项目仓库，包括小胰宝，MinerU-xyb(https://github.com/PancrePal-xiaoyibao/miniapp-uniapp)，以及fastgpt-on-wechat（thttps://github.com/hanfangyuan4396/fastgpt-on-wechat），Gemini-2.0病情demo（https://github.com/PancrePal-xiaoyibao/gemini2.0-xiaoyibao）期待更多开源加入完善社区，提供开源能力；
👏 开放病友共创的第一个标准wiki ： 小X宝社区“胰腺肿瘤并发症病友共创宝典” (https://bfz.xiao-x-bao.com.cn)

## 感谢xxx-bot/xy-bot项目上游 🙏

**给个 ⭐ Star 支持吧！** 😊

**开源不易，感谢打赏支持！**

![image](https://github.com/user-attachments/assets/2dde3b46-85a1-4f22-8a54-3928ef59b85f)

感谢 XYBot 框架提供的支持！
