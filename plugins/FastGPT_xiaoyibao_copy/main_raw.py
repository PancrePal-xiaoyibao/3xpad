import asyncio
import json
import os
import tomllib
import traceback
from typing import Dict, List, Optional, Union

import aiohttp
from loguru import logger

from WechatAPI import WechatAPIClient
from database.XYBotDB import XYBotDB
from utils.decorators import *
from utils.plugin_base import PluginBase


class FastGPT(PluginBase):
    description = "FastGPT知识库问答插件"
    author = "老夏的金库"
    version = "1.0.0"
    is_ai_platform = True  # 标记为 AI 平台插件

    def __init__(self):
        super().__init__()

        try:
            # 读取主配置
            with open("main_config.toml", "rb") as f:
                main_config = tomllib.load(f)
            
            # 读取插件配置
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 获取FastGPT配置
            plugin_config = config.get("FastGPT", {})
            self.enable = plugin_config.get("enable", False)
            self.api_key = plugin_config.get("api-key", "")
            self.base_url = plugin_config.get("base-url", "https://api.fastgpt.in/api")
            self.app_id = plugin_config.get("app-id", "")
            
            # 获取命令配置
            self.commands = plugin_config.get("commands", [])
            self.command_tip = plugin_config.get("command-tip", "")
            
            # 获取功能配置
            self.detail = plugin_config.get("detail", False)
            self.max_tokens = plugin_config.get("max-tokens", 2000)
            self.http_proxy = plugin_config.get("http-proxy", "")
            
            # 获取积分配置
            self.price = plugin_config.get("price", 5)
            self.admin_ignore = plugin_config.get("admin_ignore", True)
            self.whitelist_ignore = plugin_config.get("whitelist_ignore", True)
            
            # 获取管理员配置
            self.admins = main_config.get("XYBot", {}).get("admins", [])
            
            # 初始化数据库
            self.db = XYBotDB()
            
            # 初始化聊天历史记录
            self.chat_history = {}
            
            logger.success("FastGPT 插件初始化成功")
            
        except Exception as e:
            logger.error(f"FastGPT 插件初始化失败: {e}")
            logger.error(traceback.format_exc())
            self.enable = False
            
    @on_text_message(priority=40)
    async def handle_text_message(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            return True  # 插件未启用，继续处理
            
        content = message.get("Content", "").strip()
        is_group = message.get("IsGroup", False)
        
        # 私聊模式：直接处理全部内容
        # 群聊模式：需要使用命令前缀
        if is_group:
            # 群聊模式需要使用唤醒词
            command = content.split(" ", 1)
            
            # 检查是否是FastGPT命令
            if not command[0] in self.commands:
                return True  # 不是本插件的命令，继续处理
            
            # 检查命令格式是否正确
            if len(command) < 2:
                await bot.send_at_message(
                    message["FromWxid"],
                    f"\n请输入问题内容，例如：{self.commands[0]} 什么是FastGPT?",
                    [message["SenderWxid"]]
                )
                return False  # 命令格式不正确，已处理，阻止后续处理
            
            # 获取问题内容
            query = command[1].strip()
            if not query:
                await bot.send_at_message(
                    message["FromWxid"],
                    f"\n请输入问题内容，例如：{self.commands[0]} 什么是FastGPT?",
                    [message["SenderWxid"]]
                )
                return False  # 查询内容为空，已处理，阻止后续处理
        else:
            # 私聊模式直接使用整个消息内容
            query = content
            
            # 如果消息为空则不处理
            if not query:
                return True  # 空消息，继续处理
        
        # 检查用户积分是否足够
        if not await self._check_point(bot, message):
            return False  # 积分不足，已处理，阻止后续处理
        
        # 生成聊天ID
        wxid = message["SenderWxid"]
        from_wxid = message["FromWxid"]
        chat_id = f"{wxid}_{from_wxid}_{self.app_id}"
        
        try:
            # 调用FastGPT API进行对话（仅使用非流式）
            result = await self._chat_complete(bot, message, query, chat_id)
                
            # 处理积分
            if result and self.price > 0:
                wxid = message["SenderWxid"]
                # 检查是否需要扣除积分
                if not (wxid in self.admins and self.admin_ignore) and not (self.db.get_whitelist(wxid) and self.whitelist_ignore):
                    self.db.add_points(wxid, -self.price)
                    
            return False  # 已处理消息，阻止后续处理
                
        except Exception as e:
            logger.error(f"FastGPT 调用失败: {e}")
            logger.error(traceback.format_exc())
            # 区分群聊和私聊
            if is_group:
                await bot.send_at_message(
                    from_wxid,
                    f"\n抱歉，FastGPT服务调用失败: {str(e)}",
                    [wxid]
                )
            else:
                await bot.send_text_message(
                    from_wxid,
                    f"抱歉，FastGPT服务调用失败: {str(e)}"
                )
            return False  # 处理出错，阻止后续处理
    
    async def _chat_complete(self, bot: WechatAPIClient, message: dict, query: str, chat_id: str) -> bool:
        """调用FastGPT API进行非流式对话"""
        wxid = message["SenderWxid"]
        from_wxid = message["FromWxid"]
        is_group = message.get("IsGroup", False)
        
        # 构建请求数据 - 支持多模态内容
        # 检查query中是否包含图片或文件链接
        content = []
        
        # 首先添加文本内容
        content.append({
            "type": "text",
            "text": query
        })
        
        # 检查消息中是否有图片内容
        if message.get("MsgType") == 3:  # 图片消息
            # 如果有图片内容，将图片链接添加到content中
            # 注意：这里假设图片内容已经上传到对象存储并有可访问的URL
            # 如果需要真正实现图片上传，需要额外开发该功能
            logger.warning("FastGPT: 检测到图片消息，但暂不支持直接处理微信图片")
            if is_group:
                await bot.send_at_message(
                    from_wxid,
                    "\n注意：FastGPT插件目前不支持直接处理微信图片，请先上传图片到图床获取URL后再查询",
                    [wxid]
                )
            else:
                await bot.send_text_message(
                    from_wxid,
                    "注意：FastGPT插件目前不支持直接处理微信图片，请先上传图片到图床获取URL后再查询"
                )
        
        # 检查消息内容中是否有图片或文件链接格式
        # 简单的URL检测，实际使用时可能需要更复杂的正则表达式
        url_patterns = [
            r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)',  # 图片链接
            r'https?://\S+\.(?:pdf|doc|docx|txt|md|html|xls|xlsx|csv|ppt|pptx)'  # 文件链接
        ]
        
        import re
        for pattern in url_patterns:
            urls = re.findall(pattern, query, re.IGNORECASE)
            for url in urls:
                if any(ext in url.lower() for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']):
                    # 图片链接
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": url
                        }
                    })
                    logger.info(f"FastGPT: 检测到图片链接 {url}")
                else:
                    # 文件链接
                    # 提取文件名
                    file_name = url.split('/')[-1]
                    content.append({
                        "type": "file_url",
                        "name": file_name,
                        "url": url
                    })
                    logger.info(f"FastGPT: 检测到文件链接 {url}")
        
        request_data = {
            "chatId": chat_id,
            "stream": False,  # 始终设置为非流式
            "detail": self.detail,
            "messages": [
                {
                    "role": "user",
                    "content": content if len(content) > 1 else query  # 如果只有文本内容，使用字符串形式
                }
            ]
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 设置代理
        proxy = self.http_proxy if self.http_proxy else None
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=request_data,
                proxy=proxy
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"FastGPT API调用失败: {error_text}")
                    # 区分群聊和私聊
                    if is_group:
                        await bot.send_at_message(
                            from_wxid,
                            f"\n抱歉，FastGPT服务返回错误: {error_text}",
                            [wxid]
                        )
                    else:
                        await bot.send_text_message(
                            from_wxid,
                            f"抱歉，FastGPT服务返回错误: {error_text}"
                        )
                    return False
                
                resp_json = await response.json()
                
                # 获取回复内容
                if self.detail:
                    # 详细模式
                    content = self._extract_content_from_detail(resp_json)
                else:
                    # 普通模式
                    content = resp_json["choices"][0]["message"]["content"]
                
                # 发送回复
                if is_group:
                    await bot.send_at_message(
                        from_wxid,
                        f"\n{content}",
                        [wxid]
                    )
                else:
                    await bot.send_text_message(
                        from_wxid,
                        f"{content}"
                    )
                return True
    
    def _extract_content_from_detail(self, response: dict) -> str:
        """从详细响应中提取内容"""
        try:
            if "choices" in response and len(response["choices"]) > 0:
                if "message" in response["choices"][0]:
                    return response["choices"][0]["message"]["content"]
                
            # 如果是插件响应，尝试从pluginOutput中获取
            if "responseData" in response:
                for item in response["responseData"]:
                    if item.get("moduleType") == "pluginOutput" and "pluginOutput" in item:
                        if "result" in item["pluginOutput"]:
                            return item["pluginOutput"]["result"]
                
            # 回退到choices
            if "choices" in response and len(response["choices"]) > 0:
                return response["choices"][0]["message"]["content"]
                
            return "未能获取有效回复"
        except Exception as e:
            logger.error(f"提取内容失败: {e}")
            return "内容解析失败"
    
    async def _check_point(self, bot: WechatAPIClient, message: dict) -> bool:
        """检查用户积分是否足够"""
        wxid = message["SenderWxid"]
        from_wxid = message["FromWxid"]
        is_group = message.get("IsGroup", False)
        
        # 管理员和白名单用户豁免
        if (wxid in self.admins and self.admin_ignore) or (self.db.get_whitelist(wxid) and self.whitelist_ignore):
            return True
            
        # 检查积分
        user_points = self.db.get_points(wxid)
        if user_points < self.price:
            if is_group:
                await bot.send_at_message(
                    from_wxid,
                    f"\n您的积分不足，使用FastGPT需要{self.price}积分，您当前有{user_points}积分",
                    [wxid]
                )
            else:
                await bot.send_text_message(
                    from_wxid,
                    f"您的积分不足，使用FastGPT需要{self.price}积分，您当前有{user_points}积分"
                )
            return False
            
        return True 