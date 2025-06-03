import tomllib
import aiohttp
from loguru import logger

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class Music_puls(PluginBase):
    description = "点歌"
    author = "电脑小白"
    version = "2.0.1"

    def __init__(self):
        super().__init__()

        with open("plugins/Music_puls/config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["Music_puls"]

        self.enable = config["enable"]
        self.command = config["command"]
        self.command_format = config["command-format"]
        self.play_command = config.get("play_command", "播放")
        self.search_results = {}
        self.api_url = config["api_url"]
        # 新增：读取日志配置
        self.log_enabled = config.get("log", {}).get("enabled", True)
        self.log_level = config.get("log", {}).get("level", "DEBUG").upper()
        # 新增：读取功能控制配置
        self.fetch_song_list = config.get("features", {}).get("fetch_song_list", True)
        # 初始化日志级别
        logger.level(self.log_level)
        logger.info(f"插件初始化完成 | 启用状态: {self.enable} | 触发命令: {self.command} | 播放命令: {self.play_command} | API地址: {self.api_url}")

    async def _fetch_song_list(self, song_name: str) -> list:
        """调用API获取歌曲列表."""
        params = {
            "gm": song_name,
        }
        # 新增：日志开关控制
        if self.log_enabled:
            logger.debug(f"开始获取歌曲列表 | 歌曲名: {song_name} | 请求参数: {params}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, params=params) as resp:
                    text = await resp.text()
                    # 新增：记录响应状态和内容长度
                    logger.debug(f"获取歌曲列表响应 | 状态码: {resp.status} | 内容长度: {len(text)}")
                    logger.debug(f"API 响应: {text}")  # 保留原有日志
                    song_list = self._parse_song_list(text)
                    # 新增：记录解析结果
                    logger.debug(f"歌曲列表解析完成 | 有效歌曲数: {len(song_list)}")
                    return song_list
        except aiohttp.ClientError as e:
            # 修改：补充上下文信息
            logger.error(f"获取歌曲列表失败 | 歌曲名: {song_name} | 错误详情: {str(e)}")
            return []

    def _parse_song_list(self, text: str) -> list:
        """解析 TEXT 格式的歌曲列表."""
        song_list = []
        lines = text.splitlines()
        # 新增：记录解析开始
        logger.debug(f"开始解析歌曲列表 | 总行数: {len(lines)}")
        for line in lines:
            parts = line.split(" -- ")
            if len(parts) == 2:
                try:
                    num_title, singer = parts
                    num = num_title.split("、")[0].strip()
                    title = num_title.split("、")[1].strip()
                    song_list.append({"num": num, "title": title, "singer": singer.strip()})
                except Exception as e:
                    # 保留原有日志并补充行内容
                    logger.warning(f"行解析失败 | 行内容: {line} | 错误详情: {str(e)}")
        # 新增：记录解析完成
        logger.debug(f"歌曲列表解析结束 | 有效行数: {len(song_list)}")
        return song_list

    async def _fetch_song_data(self, song_name: str, index: int) -> dict:
        """调用API获取歌曲信息，需要指定歌曲序号."""
        params = {
            "gm": song_name,
            "n": index,
            "type": "json",
        }
        # 新增：记录请求开始
        logger.debug(f"开始获取歌曲详情 | 歌曲名: {song_name} | 序号: {index} | 请求参数: {params}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, params=params) as resp:
                    data = await resp.json()
                    # 新增：记录响应状态和关键数据
                    logger.debug(f"获取歌曲详情响应 | 状态码: {resp.status} | 响应code: {data.get('code')}")
                    if data["code"] == 200:
                        # 新增：记录成功信息
                        logger.debug(f"歌曲详情获取成功 | 标题: {data.get('title')} | 歌手: {data.get('singer')}")
                        return data
                    else:
                        # 修改：补充上下文信息
                        logger.warning(f"歌曲详情获取失败 | 歌曲名: {song_name} | 序号: {index} | API返回: {data}")
                        return None
        except aiohttp.ClientError as e:
            # 修改：补充上下文信息
            logger.error(f"获取歌曲详情失败 | 歌曲名: {song_name} | 序号: {index} | 网络错误: {str(e)}")
            return None
        except Exception as e:
            # 保留原有异常日志并补充上下文
            logger.exception(f"歌曲详情解析失败 | 歌曲名: {song_name} | 序号: {index} | 错误详情: {str(e)}")
            return None

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict) -> bool:
        # 新增：日志开关控制
        if self.log_enabled:
            logger.info(f"收到用户消息 | 发送者: {message['SenderWxid']} | 内容: {message['Content']}")
        if not self.enable:
            if self.log_enabled:
                logger.debug("插件未启用 | 忽略当前消息")
            return True

        content = str(message["Content"]).strip()
        command = content.split(" ")

        if command[0] not in self.command and command[0] != self.play_command:
            # 新增：记录不匹配的命令
            logger.debug(f"命令不匹配 | 当前命令: {command[0]} | 有效命令: {self.command + [self.play_command]}")
            return True

        if command[0] in self.command:  # 处理 "点歌" 命令
            if self.log_enabled:
                logger.info(f"触发点歌命令 | 用户: {message['SenderWxid']} | 原始内容: {content}")
            if len(command) == 1:
                if self.log_enabled:
                    logger.warning(f"点歌命令格式错误 | 用户: {message['SenderWxid']} | 内容: {content}")
                await bot.send_at_message(message["FromWxid"], f"-----Music_puls-----\n❌命令格式错误！{self.command_format}",
                                          [message["SenderWxid"]])
                return False

            song_name = content[len(command[0]):].strip()

            # 新增：根据配置决定是否获取歌曲列表
            if self.fetch_song_list:
                # 原有列表获取逻辑
                song_list = await self._fetch_song_list(song_name)
                if not song_list:
                    if self.log_enabled:
                        logger.warning(f"歌曲搜索无结果 | 搜索词: {song_name}")
                    await bot.send_at_message(message["FromWxid"], f"-----Music_puls-----\n❌未找到相关歌曲！",
                                          [message["SenderWxid"]])
                    return False
                # 构建并发送歌曲列表
                response_text = "🎶----- 找到以下歌曲 -----🎶\n"
                for i, song in enumerate(song_list):
                    response_text += f"{i + 1}. 🎵 {song['title']} - {song['singer']} 🎤\n"
                response_text += "_________________________\n"
                response_text += f"🎵输入 “{self.play_command} + 序号” 播放歌曲🎵"
                self.search_results[message["FromWxid"]] = song_list
                await bot.send_at_message(message["FromWxid"], response_text, [message["SenderWxid"]])
                return False
            else:
                # 新增：直接获取首歌逻辑
                if self.log_enabled:
                    logger.debug(f"直接获取首歌曲详情 | 歌曲名: {song_name}")
                song_data = await self._fetch_song_data(song_name, 1)
                if song_data:
                    # 原有歌曲信息发送逻辑
                    title = song_data["title"]
                    singer = song_data["singer"]
                    url = song_data.get("link", "")
                    music_url = song_data.get("music_url", "").split("?")[0]
                    cover_url = song_data.get("cover", "")
                    lyric = song_data.get("lrc", "")
                    xml = f"""<appmsg appid="wx79f2c4418704b4f8" sdkver="0"><title>{title}</title><des>{singer}</des><action>view</action><type>3</type><showtype>0</showtype><content/><url>{url}</url><dataurl>{music_url}</dataurl><lowurl>{url}</lowurl><lowdataurl>{music_url}</lowdataurl><recorditem/><thumburl>{cover_url}</thumburl><messageaction/><laninfo/><extinfo/><sourceusername/><sourcedisplayname/><songlyric>{lyric}</songlyric><commenturl/><appattach><totallen>0</totallen><attachid/><emoticonmd5/><fileext/><aeskey/></appattach><webviewshared><publisherId/><publisherReqId>0</publisherReqId></webviewshared><weappinfo><pagepath/><username/><appid/><appservicetype>0</appservicetype></weappinfo><websearch/><songalbumurl>{cover_url}</songalbumurl></appmsg><fromusername>{bot.wxid}</fromusername><scene>0</scene><appinfo><version>1</version><appname/></appinfo><commenturl/>"""
                    await bot.send_app_message(message["FromWxid"], xml, 3)
                    return False
                else:
                    if self.log_enabled:
                        logger.error(f"获取歌曲信息失败 | 歌曲名: {song_name}")
                    await bot.send_at_message(message["FromWxid"], f"-----Music_puls-----\n❌获取歌曲信息失败！",
                                          [message["SenderWxid"]])
                    return False

        elif command[0] == self.play_command:  # 处理 "播放" 命令
            # 新增：记录播放命令触发
            logger.info(f"触发播放命令 | 用户: {message['SenderWxid']} | 原始内容: {content}")
            try:
                index = int(command[1].strip())
                # 新增：记录播放序号
                logger.debug(f"尝试播放歌曲 | 用户: {message['SenderWxid']} | 目标序号: {index}")
                if message["FromWxid"] in self.search_results and 1 <= index <= len(
                        self.search_results[message["FromWxid"]]):
                    selected_song = self.search_results[message["FromWxid"]][index - 1]
                    song_data = await self._fetch_song_data(selected_song["title"], index)
                    if song_data:
                        title = song_data["title"]
                        singer = song_data["singer"]
                        url = song_data.get("link", "")
                        music_url = song_data.get("music_url", "").split("?")[0]
                        cover_url = song_data.get("cover", "")
                        lyric = song_data.get("lrc", "")

                        xml = f"""<appmsg appid="wx79f2c4418704b4f8" sdkver="0"><title>{title}</title><des>{singer}</des><action>view</action><type>3</type><showtype>0</showtype><content/><url>{url}</url><dataurl>{music_url}</dataurl><lowurl>{url}</lowurl><lowdataurl>{music_url}</lowdataurl><recorditem/><thumburl>{cover_url}</thumburl><messageaction/><laninfo/><extinfo/><sourceusername/><sourcedisplayname/><songlyric>{lyric}</songlyric><commenturl/><appattach><totallen>0</totallen><attachid/><emoticonmd5/><fileext/><aeskey/></appattach><webviewshared><publisherId/><publisherReqId>0</publisherReqId></webviewshared><weappinfo><pagepath/><username/><appid/><appservicetype>0</appservicetype></weappinfo><websearch/><songalbumurl>{cover_url}</songalbumurl></appmsg><fromusername>{bot.wxid}</fromusername><scene>0</scene><appinfo><version>1</version><appname/></appinfo><commenturl/>"""
                        await bot.send_app_message(message["FromWxid"], xml, 3)
                        return False  # 成功发送歌曲，阻止其他插件
                    else:
                        await bot.send_at_message(message["FromWxid"], f"-----Music_puls-----\n❌获取歌曲信息失败！",
                                                  [message["SenderWxid"]])
                        return False  # 已处理错误消息，阻止其他插件
                else:
                    await bot.send_at_message(message["FromWxid"], f"-----Music_puls-----\n❌无效的歌曲序号！",
                                              [message["SenderWxid"]])
                    return False  # 已处理错误消息，阻止其他插件
            except ValueError:
                # 新增：记录序号格式错误
                logger.warning(f"播放序号格式错误 | 用户: {message['SenderWxid']} | 内容: {content}")
                await bot.send_at_message(message["FromWxid"], f"-----Music_puls-----\n❌请输入有效的歌曲序号！",
                                          [message["SenderWxid"]])
                return False  # 已处理错误消息，阻止其他插件

        return True  # 未匹配任何命令，允许其他插件处理
