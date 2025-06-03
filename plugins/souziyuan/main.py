import tomllib
import urllib.parse
import requests
import logging
from datetime import datetime
import time
import os

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase

logger = logging.getLogger(__name__)

class ResourceSearch(PluginBase):
    description = "资源搜索插件"
    author = "鸿菇网络"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        try:
            # 加载配置
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.toml")
            with open(config_path, "rb") as f:
                plugin_config = tomllib.load(f)
            
            config = plugin_config["ResourceSearch"]
            
            self.enable = config["enable"]
            self.api_url = config["api_url"]
            self.timeout = config["timeout"]
            self.search_keywords = config["search_keywords"]
            self.max_results = config["max_results"]
            
            logger.info("[ResourceSearch] 插件初始化完成")
            
        except Exception as e:
            logger.error(f"[ResourceSearch] 加载配置文件失败: {e}")
            raise e

    def get_help(self) -> str:
        """返回插件帮助信息"""
        help_text = "资源搜索插件使用说明:\n\n"
        help_text += "1. 支持的命令格式：\n"
        help_text += "- 搜 [关键词]\n"
        help_text += "- 搜剧 [关键词]\n"
        help_text += "- 全网搜 [关键词]\n"
        help_text += "- 搜资源 [关键词]\n\n"
        help_text += "2. 搜索结果包含：\n"
        help_text += "- 资源名称\n"
        help_text += "- 更新时间\n"
        help_text += "- 下载链接\n"
        help_text += "- 资源分类\n\n"
        help_text += "3. 使用示例：\n"
        help_text += "搜 三体\n"
        help_text += "搜剧 你好李焕英\n"
        help_text += "全网搜 流浪地球\n\n"
        help_text += "💡 提示：点击链接即可下载资源"
        return help_text

    def get_status(self) -> str:
        """返回插件状态"""
        return (
            f"ResourceSearch Plugin v{self.version}\n"
            f"状态: {'启用' if self.enable else '禁用'}\n"
            f"API: {self.api_url}\n"
            f"超时: {self.timeout}秒\n"
            f"最大结果数: {self.max_results}"
        )

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return
            
        # 获取消息内容
        content = message.get("Content", "").strip()
        chat_id = message.get("FromWxid", "")  # 群聊ID
        sender_id = message.get("SenderWxid", "")  # 发送者ID，修改为SenderWxid
        
        logger.debug(f"[ResourceSearch] 收到消息: chat_id={chat_id}, content={content}, sender_id={sender_id}")
        
        # 群聊消息处理
        is_group_chat = "@chatroom" in chat_id
        if is_group_chat:
            # 如果是群聊消息，检查是否需要处理
            if ":" in content:
                # 移除用户名前缀
                parts = content.split(":", 1)
                content = parts[1].strip()
        
        # 检查是否是帮助命令
        if content in ["帮助搜索", "搜索帮助", "资源搜索帮助"]:
            help_text = self.get_help()
            
            # 在群聊中使用send_at_message，添加换行
            if is_group_chat and sender_id:
                await bot.send_at_message(
                    chat_id,
                    "\n" + help_text,  # 添加换行
                    [sender_id]  # 使用列表传递要at的用户ID
                )
            else:
                await bot.send_text_message(
                    chat_id,
                    help_text
                )
            return
            
        # 检查是否包含搜索关键词
        for keyword in self.search_keywords:
            if content.startswith(keyword):
                logger.info(f"[ResourceSearch] 匹配到关键词，content: {content}")
                self.current_keyword = keyword
                
                # 提取搜索内容
                search_text = content[len(keyword):].strip()
                if not search_text:
                    reply_text = "请输入要搜索的内容\n例如：搜三体"
                    
                    # 在群聊中使用send_at_message
                    if is_group_chat and sender_id:
                        await bot.send_at_message(
                            chat_id,
                            "\n" + reply_text,  # 添加换行
                            [sender_id]  # 使用列表传递要at的用户ID
                        )
                    else:
                        await bot.send_text_message(
                            chat_id,
                            reply_text
                        )
                    return
                    
                try:
                    # 如果是全网搜索，先发送提示
                    if any(keyword.startswith(k) for k in ["全网搜", "搜资源"]):
                        reply_text = "🔍 正在进行全网搜索，请稍等30秒...\n期间请勿重复发送搜索"
                        
                        # 无需艾特用户，直接发送消息
                        await bot.send_text_message(
                            chat_id,
                            reply_text
                        )
                        time.sleep(1)
                        result = await self._search_all(search_text)
                    else:
                        # 普通搜索
                        result = await self._search_normal(search_text)
                        # 如果普通搜索未找到结果，尝试全网搜索
                        if "未找到" in result:
                            reply_text = "💡 普通搜索未找到结果，正在尝试全网搜索，请稍等30秒...\n期间请勿重复发送搜索"
                            
                            # 无需艾特用户，直接发送消息
                            await bot.send_text_message(
                                chat_id,
                                reply_text
                            )
                            time.sleep(1)
                            result = await self._search_all(search_text)
                    
                    # 发送搜索结果，使用send_at_message
                    if is_group_chat and sender_id:
                        await bot.send_at_message(
                            chat_id,
                            "\n" + result,  # 添加换行
                            [sender_id]  # 使用列表传递要at的用户ID
                        )
                    else:
                        await bot.send_text_message(
                            chat_id,
                            result
                        )
                except Exception as e:
                    logger.error(f"[ResourceSearch] 搜索出错: {e}")
                    
                    reply_text = f"搜索过程中出现错误: {str(e)}\n请稍后重试"
                    
                    # 在群聊中使用send_at_message
                    if is_group_chat and sender_id:
                        await bot.send_at_message(
                            chat_id,
                            "\n" + reply_text,  # 添加换行
                            [sender_id]  # 使用列表传递要at的用户ID
                        )
                    else:
                        await bot.send_text_message(
                            chat_id,
                            reply_text
                        )
                return

    async def _search_normal(self, keyword):
        """普通搜索接口"""
        try:
            # URL编码搜索关键词
            encoded_keyword = urllib.parse.quote(keyword)
            
            # 构建请求头
            headers = {
                'Accept': '*/*',
                'Accept-Charset': 'UTF-8',
                'Content-Type': 'application/json; charset=UTF-8',
                'page_no': '1',
                'page_size': '90'
            }
            
            # 发送请求
            response = requests.get(
                f"{self.api_url}/api/search?title={encoded_keyword}",
                headers=headers,
                timeout=self.timeout
            )
            
            # 检查响应状态
            if response.status_code != 200:
                logger.error(f"[ResourceSearch] 搜索失败，状态码：{response.status_code}")
                return "🔍 搜索暂时失败\n💡 提示：服务器可能繁忙，请稍后再试"
            
            # 解析响应数据
            data = response.json()
            if data['code'] != 200:
                return f"搜索失败：{data['message']}"
            
            # 提取搜索结果
            if isinstance(data['data'], list):
                items = data['data']
            else:
                items = data['data']['items']
            
            if not items:
                return (
                    f'💭 抱歉，未找到与"{keyword}"相关的资源\n'
                    f'💡 建议：\n'
                    f'1. 尝试更换关键词\n'
                    f'2. 确保名称输入正确\n'
                    f'3. 使用"全网搜"命令重新搜索\n'
                    f'4. 输入菜单即可呼出所有功能\n'
                    f'5. 大额流量卡19/月\nh5.gantanhao.com/url?value=akijF1744729274277'
                )
            
            # 构建返回消息
            result_msg = f"🔍 搜索结果 - {keyword}\n"
            result_msg += f"📑 共找到 {len(items)} 个相关资源\n\n"
            
            show_items = items[:min(len(items), self.max_results)]
            for item in show_items:
                result_msg += (
                    f"🎬 {item['title']}\n"
                    f"🔗 资源链接：{item['url']}\n\n"
                )
            
            result_msg += "💡提示:点击链接即可获取资源\n\n"
            result_msg += "没想要资源？请尝试：全网搜XX\n\n"
            result_msg += "大额流量卡19/月\nh5.gantanhao.com/url?value=akijF1744729274277\n"
            return result_msg
            
        except Exception as e:
            logger.error(f"[ResourceSearch] 解析响应失败: {e}")
            return f"解析搜索结果时出错：{str(e)}"

    async def _search_all(self, keyword):
        """全网搜索接口"""
        try:
            headers = {
                'Content-Type': 'application/json'
            }
            
            # 发送POST请求
            response = requests.post(
                f"{self.api_url}/api/other/all_search",
                json={"title": keyword},
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                logger.error(f"[ResourceSearch] 全网搜索失败，状态码：{response.status_code}")
                return "🔍 全网搜索暂时失败\n💡 提示：服务器可能繁忙，请稍后再试\n⚡ 建议：可以尝试使用普通搜索"
            
            data = response.json()
            if data['code'] != 200:
                return f"搜索失败：{data['message']}"
            
            if isinstance(data['data'], list):
                items = data['data']
            else:
                items = data['data']['items']
            
            if not items:
                return (
                    f'💭 抱歉，未找到与"{keyword}"相关的资源\n'
                    f'💡 建议：\n'
                    f'1. 尝试更换关键词\n'
                    f'2. 确保名称输入正确\n'
                    f'3. 使用"全网搜"命令重新搜索'
                )
            
            result_msg = f"🔍 搜索结果 - {keyword}\n"
            result_msg += f"🌐️ 共找到 {len(items)} 个相关资源\n\n"
            
            show_items = items[:min(len(items), self.max_results)]
            for item in show_items:
                result_msg += (
                    f"🌐️ {item['title']}\n"
                    f"🔗 资源链接：{item['url']}\n\n"
                )
            
            result_msg += "🌐️资源来源网络，30分钟后删除，请及时转存\n\n"
            result_msg += "⚠️搜剧指令：搜XXX\n\n"
            result_msg += "⚠️搜音乐指令：搜音乐XXX\n\n"
            result_msg += "大额流量卡19/月\nh5.gantanhao.com/url?value=akijF1744729274277\n"
            return result_msg
            
        except requests.exceptions.ReadTimeout:
            return "🔍 全网搜索超时\n💡 提示：全网搜索需要更长时间，请稍后重试"
        except Exception as e:
            logger.error(f"[ResourceSearch] 全网搜索失败: {e}")
            return "🔍 全网搜索出错\n💡 提示：服务器可能繁忙，请稍后再试\n⚡ 建议：可以尝试使用普通搜索"
