import os
import json
import uuid
import time
import base64
import tomllib  # Python 3.11+; 如果是Python < 3.11，需要使用tomli第三方库
import aiohttp
import asyncio
import io
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import traceback
import copy
import threading
import urllib.parse
from io import BytesIO
from typing import Dict, Any, Optional, List, Tuple, Union, Set
from collections import defaultdict
import random
import string
import hashlib
import re
import logging

from PIL import Image
from loguru import logger

from utils.decorators import on_text_message, on_image_message, schedule
from utils.plugin_base import PluginBase
from WechatAPI import WechatAPIClient

# 设置日志
logger = logging.getLogger('gemini_image')

class GeminiImageXXX(PluginBase):
    """基于Google Gemini的图像生成插件 (XXXBot移植版)
    
    功能：
    1. 生成图片：根据文本描述生成图片
    2. 编辑图片：根据文本描述修改已有图片
    3. 支持会话模式，可以连续对话修改图片
    4. 支持积分系统控制使用
    """
    
    description = "基于Google Gemini的图像生成插件"
    author = "Lingyuzhou (XXXBot移植版)"
    version = "1.0.0"
    
    # 请求体大小限制常量（单位：字节）- 限制为4MB，避免413错误
    MAX_REQUEST_SIZE = 4 * 1024 * 1024
    # 会话中保留的最大消息数量
    MAX_CONVERSATION_MESSAGES = 10
    
    # 会话类型常量
    SESSION_TYPE_GENERATE = "generate"  # 生成图片模式
    SESSION_TYPE_EDIT = "edit"          # 编辑图片模式
    SESSION_TYPE_REFERENCE = "reference" # 参考图编辑模式
    SESSION_TYPE_MERGE = "merge"        # 融图模式
    SESSION_TYPE_ANALYSIS = "analysis"   # 图片分析模式
    
    def __init__(self):
        """初始化插件配置"""
        super().__init__()
        
        # 初始化API相关变量
        self.api_key = ""
        self.model = "gemini-2.0-flash-exp-image-generation"
        self.base_url = "https://generativelanguage.googleapis.com/v1"
        self.enable = False
        self.save_dir = ""
        self.conversation_expire_seconds = 180
        self.max_conversation_messages = 10
        self.reference_image_wait_timeout = 180  # 参考图片等待超时时间(秒)
        self.merge_image_wait_timeout = 180      # 融图等待超时时间(秒)
        self.reverse_image_wait_timeout = 180    # 反推图片等待超时时间(秒)
        self.analysis_image_wait_timeout = 180   # 识图等待超时时间(秒)
        self.follow_up_timeout = 180             # 追问超时时间(秒)
        self.image_cache_timeout = 300           # 图片缓存超时时间(秒)
        
        # 初始化代理相关变量
        self.proxy_url = ""
        self.enable_proxy = False
        self.use_proxy_service = False
        self.proxy_service_url = ""
        
        # 初始化翻译相关变量
        self.enable_translate = False
        self.translate_api_base = ""
        self.translate_api_key = ""
        self.translate_model = ""
        
        # 积分相关配置
        self.enable_points = False
        self.generate_image_cost = 0
        self.edit_image_cost = 0
        self.analysis_image_cost = 0
        self.reverse_image_cost = 0
        
        # 命令配置
        self.generate_commands = ["g生成", "g画图", "g画"]
        self.edit_commands = ["g改图", "g编辑"]
        self.reference_edit_commands = ["g参考图"]
        self.merge_commands = ["g融图"]
        self.exit_commands = ["g结束对话", "g结束"]
        self.image_analysis_commands = ["g识图"]
        self.image_reverse_commands = ["g反推"]
        self.follow_up_commands = ["g追问"]
        self.translate_on_commands = ["g开启翻译"]
        self.translate_off_commands = ["g关闭翻译"]
        
        # 会话数据结构
        self.conversations = {}  # 会话ID -> 会话内容
        self.last_conversation_time = {}  # 会话ID -> 最后交互时间
        self.conversation_session_types = {}  # 会话ID -> 会话类型
        self.last_images = {}  # 会话ID -> 最后图片路径
        
        # 图片缓存
        self.image_cache = {}  # 会话ID -> {content: 二进制数据, timestamp: 时间戳}
        
        # 用户翻译设置
        self.user_translate_settings = {}  # 用户ID -> 是否翻译
        
        # 图片分析相关
        self.last_analysis_image = {}  # 用户ID -> 图片数据
        self.last_analysis_time = {}  # 用户ID -> 分析时间戳
        
        # 等待状态
        self.waiting_for_reference_image = {}  # 用户ID -> 等待参考图片的提示词
        self.waiting_for_reference_image_time = {}  # 用户ID -> 开始等待参考图片的时间戳
        self.waiting_for_reverse_image = {}  # 用户ID -> 是否等待反推图片
        self.waiting_for_reverse_image_time = {}  # 用户ID -> 开始等待反推图片的时间戳
        self.waiting_for_analysis_image = {}  # 用户ID -> 等待识图的问题
        self.waiting_for_analysis_image_time = {}  # 用户ID -> 开始等待识图的时间戳
        self.waiting_for_merge_image = {}  # 用户ID -> 等待的融图提示词
        self.waiting_for_merge_image_time = {}  # 用户ID -> 开始等待融图的时间戳
        
        # 融图相关变量
        self.waiting_for_merge_image_first = {}  # 用户ID -> 是否等待第一张融图图片
        self.waiting_for_merge_image_first_time = {}  # 用户ID -> 开始等待第一张融图图片的时间戳
        self.waiting_for_merge_image_second = {}  # 用户ID -> 是否等待第二张融图图片
        self.waiting_for_merge_image_second_time = {}  # 用户ID -> 开始等待第二张融图图片的时间戳
        self.merge_image_first = {}  # 用户ID -> 第一张融图图片数据
        self.merge_first_image = {}  # 用户ID -> 第一张融图图片数据
        
        # 加载配置
        self._load_config()
        
        # 确保保存目录存在
        self.save_dir = os.path.join(os.path.dirname(__file__), self.save_dir)
        os.makedirs(self.save_dir, exist_ok=True)
        
        # 验证关键配置
        if not self.api_key:
            logger.warning("GeminiImageXXX插件未配置API密钥")
            
        logger.info("GeminiImageXXX插件初始化成功")
        if self.enable_proxy:
            logger.info(f"GeminiImageXXX插件已启用代理: {self.proxy_url}")
        
        # 创建临时目录
        self.temp_dir = os.path.join(os.path.dirname(__file__), "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"GeminiImageXXX插件临时目录已创建: {self.temp_dir}")

    async def async_init(self):
        """异步初始化，在插件启动时被调用"""
        if not self.enable:
            return
        
        logger.info("GeminiImageXXX插件异步初始化...")
        # 此处可以添加需要异步执行的初始化操作
        # 例如检查API密钥有效性等
        
    async def on_enable(self, bot=None):
        """插件启用时调用"""
        logger.info(f"{self.__class__.__name__} 插件已启用")
        
    async def on_disable(self):
        """插件禁用时调用"""
        logger.info(f"{self.__class__.__name__} 插件已禁用")
        # 关闭可能的网络会话等
        
    @schedule('interval', minutes=5)
    async def cleanup_tasks(self, bot: WechatAPIClient):
        """定期清理过期会话和缓存"""
        if not self.enable:
            return
        
        logger.debug("执行GeminiImageXXX定期清理任务...")
        self._cleanup_expired_conversations()
        self._cleanup_image_cache()
        
        # 清理临时目录中的旧文件
        try:
            now = time.time()
            temp_files_cleaned = 0
            if os.path.exists(self.temp_dir):
                for filename in os.listdir(self.temp_dir):
                    file_path = os.path.join(self.temp_dir, filename)
                    # 只清理超过1小时的文件
                    if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > 3600:
                        try:
                            os.remove(file_path)
                            temp_files_cleaned += 1
                        except Exception as e:
                            logger.warning(f"清理临时文件失败: {file_path}, 错误: {e}")
            
            if temp_files_cleaned > 0:
                logger.info(f"清理了 {temp_files_cleaned} 个过期的临时文件")
        except Exception as e:
            logger.error(f"清理临时文件时发生错误: {e}")
            logger.exception(e)
    
    def _load_config(self):
        """加载插件配置"""
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            
            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", True)
            self.api_key = basic_config.get("gemini_api_key", "")
            self.model = basic_config.get("model", "gemini-2.0-flash-exp-image-generation")
            self.save_dir = basic_config.get("save_path", "temp_images")
            self.conversation_expire_seconds = basic_config.get("conversation_expire_seconds", 180)
            self.max_conversation_messages = basic_config.get("max_conversation_messages", 10)
            
            # 超时配置
            self.reference_image_wait_timeout = basic_config.get("reference_image_wait_timeout", 180)
            self.merge_image_wait_timeout = basic_config.get("merge_image_wait_timeout", 180)
            self.reverse_image_wait_timeout = basic_config.get("reverse_image_wait_timeout", 180)
            self.analysis_image_wait_timeout = basic_config.get("analysis_image_wait_timeout", 180)
            self.follow_up_timeout = basic_config.get("follow_up_timeout", 180)
            self.image_cache_timeout = basic_config.get("image_cache_timeout", 300)
            
            # 命令配置
            cmd_config = config.get("commands", {})
            self.generate_commands = cmd_config.get("generate", ["g生成", "g画图", "g画"])
            self.edit_commands = cmd_config.get("edit", ["g编辑图片", "g改图"])
            self.reference_edit_commands = cmd_config.get("reference_edit", ["g参考图", "g编辑参考图"])
            self.merge_commands = cmd_config.get("merge", ["g融图"])
            self.image_reverse_commands = cmd_config.get("image_reverse", ["g反推提示", "g反推"])
            self.image_analysis_commands = cmd_config.get("image_analysis", ["g解析图片", "g识图"])
            self.follow_up_commands = cmd_config.get("follow_up", ["g追问"])
            self.exit_commands = cmd_config.get("exit_session", ["g结束对话", "g结束"])
            self.translate_on_commands = cmd_config.get("translate_on", ["g开启翻译", "g启用翻译"])
            self.translate_off_commands = cmd_config.get("translate_off", ["g关闭翻译", "g禁用翻译"])
            
            # 积分配置
            points_config = config.get("points", {})
            self.enable_points = points_config.get("enable_points", False)
            self.generate_image_cost = points_config.get("generate_image_cost", 10)
            self.edit_image_cost = points_config.get("edit_image_cost", 15)
            self.analysis_image_cost = points_config.get("analysis_image_cost", 5)
            self.reverse_image_cost = points_config.get("reverse_image_cost", 5)
            
            # 代理配置
            proxy_config = config.get("proxy", {})
            self.enable_proxy = proxy_config.get("enable_proxy", False)
            self.proxy_url = proxy_config.get("proxy_url", "")
            self.use_proxy_service = proxy_config.get("use_proxy_service", True)
            self.proxy_service_url = proxy_config.get("proxy_service_url", "")
            
            # 翻译配置
            translate_config = config.get("translate", {})
            self.enable_translate = translate_config.get("enable", True)
            self.translate_api_base = translate_config.get("api_base", "https://open.bigmodel.cn/api/paas/v4")
            self.translate_api_key = translate_config.get("api_key", "")
            self.translate_model = translate_config.get("model", "glm-4-flash")
            
            # 设置基本API URL
            self.base_url = "https://generativelanguage.googleapis.com/v1"
            
            logger.info("配置加载成功")
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            logger.exception(e)
    
    def _get_user_id(self, message: dict) -> str:
        """从消息中获取用户ID"""
        # 获取用户ID，优先使用wxid
        user_id = message.get("FromWxid", "")
        
        # 如果是群聊，尝试获取实际发送者ID
        room_wxid = message.get("FromWxid", "")
        is_room = room_wxid.endswith("@chatroom") if room_wxid else False
        if is_room and message.get("ActualSenderWxid"):
            user_id = message.get("ActualSenderWxid", "")
            
        return user_id
    
    def _get_conversation_key(self, message: dict) -> str:
        """获取会话标识符"""
        # 直接使用用户ID作为会话键
        return self._get_user_id(message)
    
    def _should_translate_for_user(self, user_id: str) -> bool:
        """检查是否应该为用户翻译提示词"""
        # 全局设置
        if not self.enable_translate:
            return False
            
        # 用户个人设置
        if user_id in self.user_translate_settings:
            return self.user_translate_settings[user_id]
            
        # 默认行为 - 默认启用翻译
        return True
    
    def _cleanup_expired_conversations(self):
        """清理过期会话"""
        current_time = time.time()
        expired_keys = []
        
        for key, last_time in list(self.last_conversation_time.items()):
            if current_time - last_time > self.conversation_expire_seconds:
                expired_keys.append(key)
                
        for key in expired_keys:
            if key in self.conversations:
                del self.conversations[key]
            if key in self.last_conversation_time:
                del self.last_conversation_time[key]
            if key in self.conversation_session_types:
                del self.conversation_session_types[key]
        
        # 检查并清理过长的会话，防止请求体过大
        for key, conversation in list(self.conversations.items()):
            messages = conversation.get("messages", [])
            if len(messages) > self.max_conversation_messages:
                # 保留最近的消息
                excess = len(messages) - self.max_conversation_messages
                self.conversations[key]["messages"] = messages[excess:]
                logger.info(f"会话 {key} 长度超过限制，已裁剪为最新的 {self.max_conversation_messages} 条消息")
    
    def _cleanup_image_cache(self):
        """清理过期的图片缓存"""
        current_time = time.time()
        expired_keys = []
        
        for key, cache_data in self.image_cache.items():
            if current_time - cache_data["timestamp"] > self.image_cache_timeout:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.image_cache[key]
            logger.debug(f"清理过期图片缓存: {key}")
    
    def _clear_conversation(self, conversation_key):
        """清除指定会话的所有数据"""
        if conversation_key in self.conversations:
            del self.conversations[conversation_key]
        if conversation_key in self.last_conversation_time:
            del self.last_conversation_time[conversation_key]
        if conversation_key in self.last_images:
            del self.last_images[conversation_key]
        if conversation_key in self.conversation_session_types:
            del self.conversation_session_types[conversation_key]
        
        logger.info(f"已清空会话 {conversation_key} 的数据")
    
    def _add_message_to_conversation(self, conversation_key, role, parts):
        """添加消息到会话历史，并进行长度控制"""
        if conversation_key not in self.conversations:
            self.conversations[conversation_key] = {"messages": [], "conversation_id": ""}
        
        # 添加新消息
        self.conversations[conversation_key]["messages"].append({
            "role": role,
            "parts": parts
        })
        
        # 更新最后交互时间
        self.last_conversation_time[conversation_key] = time.time()
        
        # 控制会话长度，保留最近的消息
        if len(self.conversations[conversation_key]["messages"]) > self.max_conversation_messages:
            # 移除最旧的消息，保留最新的max_conversation_messages条
            excess = len(self.conversations[conversation_key]["messages"]) - self.max_conversation_messages
            self.conversations[conversation_key]["messages"] = self.conversations[conversation_key]["messages"][excess:]
            logger.info(f"会话 {conversation_key} 长度超过限制，已裁剪为最新的 {self.max_conversation_messages} 条消息")
        
        return self.conversations[conversation_key]["messages"]
    
    def _create_or_reset_conversation(self, conversation_key: str, session_type: str, preserve_id: bool = False) -> None:
        """创建新会话或重置现有会话
        
        Args:
            conversation_key: 会话标识符
            session_type: 会话类型（使用会话类型常量）
            preserve_id: 是否保留现有会话ID
        """
        # 检查是否需要保留会话ID
        conversation_id = ""
        if preserve_id and conversation_key in self.conversations:
            conversation_id = self.conversations[conversation_key].get("conversation_id", "")
            
        # 创建新的空会话
        self.conversations[conversation_key] = {
            "messages": [],
            "conversation_id": conversation_id
        }
        
        # 更新会话类型和时间戳
        self.conversation_session_types[conversation_key] = session_type
        self.last_conversation_time[conversation_key] = time.time()
        
        logger.info(f"已创建/重置会话 {conversation_key}，类型: {session_type}")
    
    def _save_temp_image(self, image_data: bytes, prefix: str = "gem_img") -> Optional[str]:
        """保存临时图片文件
        
        Args:
            image_data: 图片二进制数据
            prefix: 文件名前缀
            
        Returns:
            str: 保存的图片路径，失败则返回None
        """
        try:
            # 确保临时目录存在
            os.makedirs(self.temp_dir, exist_ok=True)
            
            timestamp = int(time.time())
            random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            filename = f"{prefix}_{timestamp}_{random_str}.png"
            filepath = os.path.join(self.temp_dir, filename)
            
            with open(filepath, "wb") as f:
                f.write(image_data)
                
            logger.info(f"已保存临时图片: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"保存临时图片失败: {e}")
            return None
    
    @on_text_message(priority=60)
    async def handle_text_commands(self, bot: WechatAPIClient, message: dict):
        """处理文本消息命令"""
        if not self.enable:
            return True  # 插件未启用，允许后续插件处理
            
        # 获取消息内容和用户ID
        content = message.get("Content", "").strip()
        user_id = self._get_user_id(message)
        conversation_key = self._get_conversation_key(message)
        
        # 检查各种命令
        
        # 1. 反推提示词命令
        for cmd in ["g反推提示", "g反推"]:
            if content == cmd:
                # 记录更详细的日志
                logger.info(f"收到反推图片命令: {cmd}，用户ID: {user_id}")
                
                # 重置之前可能存在的等待状态
                if user_id in self.waiting_for_reverse_image:
                    logger.info(f"重置已存在的反推图片等待状态: {user_id}")
                
                # 使用时间戳作为值，而不仅仅是True，这样更容易调试
                current_time = time.time()
                self.waiting_for_reverse_image[user_id] = current_time
                self.waiting_for_reverse_image_time[user_id] = current_time
                
                # 立即记录设置的等待状态
                logger.info(f"已设置反推图片等待状态: user_id={user_id}, timestamp={current_time}")
                
                # 发送更明确的提示消息
                await bot.send_text_message(
                    message["FromWxid"], 
                    "请在3分钟内发送需要反推提示词的图片"
                )
                
                # 检查并记录当前的等待状态
                logger.info(f"当前等待反推图片的用户列表: {list(self.waiting_for_reverse_image.keys())}")
                
                return False  # 阻止其他插件处理
        
        # 2. 识图命令
        for cmd in ["g分析图片", "g识图"]:
            if content.startswith(cmd):
                question = content[len(cmd):].strip()
                
                # 设置等待图片状态，并保存问题
                self.waiting_for_analysis_image[user_id] = question if question else "分析这张图片的内容，包括主要对象、场景、风格、颜色等关键特征，用简洁清晰的中文进行描述。"
                self.waiting_for_analysis_image_time[user_id] = time.time()
                
                await bot.send_text_message(message["FromWxid"], "请在3分钟内发送需要分析的图片")
                return False  # 阻止其他插件处理
        
        # 3. 追问命令
        for cmd in ["g追问"]:
            if content.startswith(cmd):
                question = content[len(cmd):].strip()
                await self._process_follow_up(bot, message, user_id, question)
                return False  # 阻止其他插件处理
                
        # 4. 翻译控制命令
        for cmd in ["g开启翻译", "g启用翻译"]:
            if content == cmd:
                self.user_translate_settings[user_id] = True
                await bot.send_text_message(message["FromWxid"], "已开启前置翻译功能，接下来的图像生成和编辑将自动将中文提示词翻译成英文")
                return False  # 阻止其他插件处理
                
        for cmd in ["g关闭翻译", "g禁用翻译"]:
            if content == cmd:
                self.user_translate_settings[user_id] = False
                await bot.send_text_message(message["FromWxid"], "已关闭前置翻译功能，接下来的图像生成和编辑将直接使用原始中文提示词")
                return False  # 阻止其他插件处理
                
        # 5. 结束对话命令
        for cmd in ["g结束对话", "g结束"]:
            if content == cmd:
                self._clear_conversation(conversation_key)
                await bot.send_text_message(message["FromWxid"], "已结束Gemini图像生成对话，下次需要时请使用命令重新开始")
                return False  # 阻止其他插件处理
                
        # 6. 生成图片命令
        for cmd in ["g生成图片", "g画图", "g画一个", "g画"]:
            if content.startswith(cmd):
                prompt = content[len(cmd):].strip()
                if not prompt:
                    await bot.send_text_message(message["FromWxid"], f"请在命令后输入提示词，例如：{cmd} 一只可爱的猫咪")
                    return False  # 阻止其他插件处理
                
                # 处理生成图片请求
                await self._process_generate_image(bot, message, user_id, conversation_key, prompt)
                return False  # 阻止其他插件处理
                
        # 7. 编辑图片命令
        for cmd in ["g编辑图片", "g改图"]:
            if content.startswith(cmd):
                prompt = content[len(cmd):].strip()
                if not prompt:
                    await bot.send_text_message(message["FromWxid"], f"请提供编辑描述，格式：{cmd} [描述]")
                    return False  # 阻止其他插件处理
                
                # 处理编辑图片请求
                await self._process_edit_image(bot, message, user_id, conversation_key, prompt)
                return False  # 阻止其他插件处理
                
        # 8. 参考图编辑命令
        for cmd in ["g参考图", "g编辑参考图"]:
            if content.startswith(cmd):
                prompt = content[len(cmd):].strip()
                if not prompt:
                    await bot.send_text_message(message["FromWxid"], f"请提供编辑描述，格式：{cmd} [描述]")
                    return False  # 阻止其他插件处理
                
                # 设置等待参考图片状态
                self.waiting_for_reference_image[user_id] = prompt
                self.waiting_for_reference_image_time[user_id] = time.time()
                
                # 提示用户上传图片
                await bot.send_text_message(message["FromWxid"], "请发送需要编辑的参考图片")
                return False  # 阻止其他插件处理
                
        # 9. 融图命令
        for cmd in ["g融图"]:
            if content.startswith(cmd):
                prompt = content[len(cmd):].strip()
                if not prompt:
                    await bot.send_text_message(message["FromWxid"], f"请提供融图描述，格式：{cmd} [描述]")
                    return False  # 阻止其他插件处理
                
                # 设置等待融图图片状态
                self.waiting_for_merge_image[user_id] = prompt
                self.waiting_for_merge_image_time[user_id] = time.time()
                self.waiting_for_merge_image_first[user_id] = True
                
                # 提示用户上传图片
                await bot.send_text_message(message["FromWxid"], "请发送融图的第一张图片")
                return False  # 阻止其他插件处理
                
        # 如果没有匹配到任何命令，允许其他插件处理
        return True
    
    async def _process_follow_up(self, bot: WechatAPIClient, message: dict, user_id: str, question: str):
        """处理追问请求"""
        # 检查是否有最近的识图记录
        if user_id not in self.last_analysis_image or user_id not in self.last_analysis_time:
            await bot.send_text_message(message["FromWxid"], "没有找到最近的识图记录，请先使用识图功能")
            return
        
        # 检查是否超时
        if time.time() - self.last_analysis_time[user_id] > self.follow_up_timeout:
            # 清理状态
            del self.last_analysis_image[user_id]
            del self.last_analysis_time[user_id]
            
            await bot.send_text_message(message["FromWxid"], "追问超时，请重新使用识图功能")
            return
        
        # 添加中文回答要求
        question = question + "，请用简洁的中文进行回答。"
        
        try:
            # 显示处理中消息
            await bot.send_text_message(message["FromWxid"], "正在分析图片，请稍候...")
            
            # 调用API分析图片
            analysis_result = await self._analyze_image(self.last_analysis_image[user_id], question)
            if analysis_result:
                # 更新时间戳
                self.last_analysis_time[user_id] = time.time()
                
                # 添加追问提示
                analysis_result += "\n💬3min内输入g追问+问题，可继续追问"
                await bot.send_text_message(message["FromWxid"], analysis_result)
            else:
                await bot.send_text_message(message["FromWxid"], "图片分析失败，请稍后重试")
        except Exception as e:
            logger.error(f"处理追问请求异常: {str(e)}")
            logger.exception(e)
            await bot.send_text_message(message["FromWxid"], f"图片分析失败: {str(e)}")
            
    async def _process_generate_image(self, bot: WechatAPIClient, message: dict, user_id: str, conversation_key: str, prompt: str):
        """处理生成图片请求"""
        # 检查API密钥是否配置
        if not self.api_key:
            await bot.send_text_message(message["FromWxid"], "请先在配置文件中设置Gemini API密钥")
            return
        
        # 检查当前会话类型，如果不是生成图片模式或不存在，则创建/重置会话
        current_session_type = self.conversation_session_types.get(conversation_key)
        if current_session_type != self.SESSION_TYPE_GENERATE:
            logger.info(f"检测到会话类型变更: {current_session_type} -> {self.SESSION_TYPE_GENERATE}，自动重置会话")
            self._create_or_reset_conversation(conversation_key, self.SESSION_TYPE_GENERATE, False)
        
        # 获取会话历史
        conversation_history = self.conversations.get(conversation_key, {}).get("messages", [])
        
        # 翻译提示词
        try:
            if self._should_translate_for_user(user_id):
                translated_prompt = await self._translate_prompt(prompt)
                if translated_prompt and translated_prompt != prompt:
                    logger.info(f"翻译成功: {prompt} -> {translated_prompt}")
                    prompt = translated_prompt
                else:
                    logger.warning("翻译失败或未发生变化，使用原始提示词")
            else:
                logger.info("用户未启用翻译，使用原始提示词")
        except Exception as e:
            logger.error(f"翻译提示词失败: {e}")
            logger.error(traceback.format_exc())
            await bot.send_text_message(message["FromWxid"], "翻译配置不完整，使用原始提示词")
        
        # 移除这行提示消息，避免与_send_alternating_content中的重复
        # await bot.send_text_message(message["FromWxid"], "正在生成图片，请稍候...")
            
        # 生成图片
        try:
            image_text_pairs, final_text, error_message = await self._generate_image(prompt, conversation_history)
            
            if error_message:
                await bot.send_text_message(message["FromWxid"], error_message)
                return
                
            if not image_text_pairs and not final_text:
                await bot.send_text_message(message["FromWxid"], "生成图片失败，请稍后再试")
                return
                
            # 使用交替发送功能处理文本和图片
            await self._send_alternating_content(bot, message, image_text_pairs, final_text)
            
            # 更新会话历史
            if conversation_key not in self.conversations:
                self.conversations[conversation_key] = {"messages": [], "conversation_id": ""}
                self.conversation_session_types[conversation_key] = self.SESSION_TYPE_GENERATE
            
            # 添加新消息到会话历史    
            self._add_message_to_conversation(conversation_key, "user", [{"text": prompt}])
            self._add_message_to_conversation(conversation_key, "assistant", [{"text": "已生成图片"}])
            
            # 保存最后一张图片的路径(如果有多张图片)
            if image_text_pairs:
                try:
                    # 创建临时目录
                    temp_dir = os.path.join(os.path.dirname(__file__), "temp")
                    os.makedirs(temp_dir, exist_ok=True)
                    
                    # 保存最后一张图片用于后续编辑
                    last_image_data = image_text_pairs[-1][0]
                    timestamp = int(time.time())
                    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                    safe_filename = f"gemini_last_{timestamp}_{random_str}.png"
                    image_path = os.path.join(temp_dir, safe_filename)
                    
                    with open(image_path, "wb") as f:
                        f.write(last_image_data)
                    
                    # 保存最后生成的图片路径
                    self.last_images[conversation_key] = image_path
                except Exception as e:
                    logger.error(f"保存最后一张图片失败: {e}")
        except Exception as e:
            logger.error(f"生成图片过程中出错: {e}")
            logger.error(traceback.format_exc())
            await bot.send_text_message(message["FromWxid"], f"生成图片时出错: {str(e)}")

    async def _process_edit_image(self, bot: WechatAPIClient, message: dict, user_id: str, conversation_key: str, prompt: str):
        """处理编辑图片请求"""
        # 检查API密钥是否配置
        if not self.api_key:
            await bot.send_text_message(message["FromWxid"], "请先在配置文件中设置Gemini API密钥")
            return
        
        # 尝试获取最近图片
        image_data = self._get_recent_image(conversation_key)
        if not image_data:
            # 检查是否有最后生成的图片
            if conversation_key in self.last_images:
                last_image_path = self.last_images[conversation_key]
                if os.path.exists(last_image_path):
                    try:
                        # 读取图片数据
                        with open(last_image_path, "rb") as f:
                            image_data = f.read()
                    except Exception as e:
                        logger.error(f"读取图片文件失败: {e}")
                        await bot.send_text_message(message["FromWxid"], "读取图片文件失败，请重新生成图片后再编辑")
                        return
                else:
                    # 图片文件已丢失
                    await bot.send_text_message(message["FromWxid"], "找不到之前生成的图片，请重新生成图片后再编辑")
                    return
            else:
                # 没有之前生成的图片
                await bot.send_text_message(message["FromWxid"], "请先使用生成图片命令生成一张图片，或者上传一张图片后再编辑")
                return
        
        # 检查当前会话类型，如果不是编辑图片模式则创建/重置会话
        current_session_type = self.conversation_session_types.get(conversation_key)
        if current_session_type != self.SESSION_TYPE_EDIT:
            logger.info(f"检测到会话类型变更: {current_session_type} -> {self.SESSION_TYPE_EDIT}，保留会话ID并重置")
            self._create_or_reset_conversation(conversation_key, self.SESSION_TYPE_EDIT, True)
        
        # 检查是否需要翻译提示词
        should_translate = self._should_translate_for_user(user_id)
        if should_translate:
            try:
                translated_prompt = await self._translate_prompt(prompt, user_id)
                logger.info(f"翻译成功: {prompt} -> {translated_prompt}")
                prompt = translated_prompt
            except Exception as e:
                logger.error(f"翻译提示词失败: {e}")
        
        # 发送处理中消息
        await bot.send_text_message(message["FromWxid"], "正在编辑图片，请稍候...")
        
        # 获取会话历史
        conversation_history = self.conversations.get(conversation_key, {}).get("messages", [])
        
        try:
            # 调用API编辑图片
            result_image, text_response = await self._edit_image(prompt, image_data, conversation_history)
            
            if result_image:
                logger.info(f"图片编辑成功，结果大小: {len(result_image)} 字节")
                
                # 保存编辑后的图片
                image_path = self._save_temp_image(result_image, "edited")
                if not image_path:
                    await bot.send_text_message(message["FromWxid"], "保存编辑后的图片失败")
                    return
                
                # 更新最后图片记录和图片缓存
                self.last_images[conversation_key] = image_path
                self.image_cache[conversation_key] = {
                    "content": result_image,
                    "timestamp": time.time()
                }
                
                # 添加用户提示到会话历史
                self._add_message_to_conversation(
                    conversation_key,
                    "user",
                    [{"text": prompt}])
                
                # 添加模型回复到会话历史
                model_parts = []
                if text_response:
                    model_parts.append({"text": text_response})
                model_parts.append({"image_url": image_path})
                
                self._add_message_to_conversation(
                    conversation_key,
                    "model",
                    model_parts)
                
                # 准备回复文本 - 仅在新会话时提供额外指导
                if len(self.conversations[conversation_key]["messages"]) <= 2:  # 如果是新会话
                    reply_text = f"图片编辑成功！（已开始图像对话，可以继续发送命令修改图片。需要结束时请发送\"{self.exit_commands[0]}\"）"
                    await bot.send_text_message(message["FromWxid"], reply_text)
                
                # 改进图片发送逻辑，优先使用二进制数据
                try:
                    # 优先使用二进制数据发送
                    await bot.send_image_message(message["FromWxid"], result_image)
                    logger.info("使用二进制数据发送图片成功")
                except Exception as e:
                    logger.error(f"使用二进制数据发送图片失败: {str(e)}")
                    # 回退方案：尝试使用文件路径发送
                    try:
                        with open(image_path, "rb") as f:
                            img_binary = f.read()
                            await bot.send_image_message(message["FromWxid"], img_binary)
                            logger.info(f"使用文件读取方式发送图片成功: {image_path}")
                    except Exception as e2:
                        logger.error(f"使用文件读取方式发送图片失败: {str(e2)}")
                        try:
                            await bot.send_image_message(message["FromWxid"], image_path)
                            logger.info(f"使用文件路径发送图片成功: {image_path}")
                        except Exception as e3:
                            logger.error(f"所有图片发送方式均失败: {str(e3)}")
                            await bot.send_text_message(message["FromWxid"], "图片发送失败，请稍后重试")
                
            else:
                logger.error(f"图片编辑失败，API响应: {text_response}")
                # 检查是否有文本响应，可能是内容被拒绝
                if text_response:
                    # 内容审核拒绝的情况，发送拒绝消息
                    translated_response = self._translate_gemini_message(text_response)
                    await bot.send_text_message(message["FromWxid"], translated_response)
                else:
                    await bot.send_text_message(message["FromWxid"], "图片编辑失败，请稍后再试或修改提示词")
        except Exception as e:
            logger.error(f"编辑图片失败: {str(e)}")
            logger.exception(e)
            await bot.send_text_message(message["FromWxid"], f"编辑图片失败: {str(e)}")

    async def _edit_image(self, prompt: str, image_data: bytes, conversation_history: List[Dict] = None) -> Tuple[Optional[bytes], Optional[str]]:
        """调用Gemini API编辑图片，返回图片数据和文本响应"""
        # 根据配置决定使用直接调用还是通过代理服务调用
        if self.use_proxy_service and self.proxy_service_url:
            # 使用代理服务调用API
            url = f"{self.proxy_service_url.rstrip('/')}/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            headers = {
                "Content-Type": "application/json"
            }
            params = {}  # 不需要在URL参数中传递API密钥
        else:
            # 直接调用Google API
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            headers = {
                "Content-Type": "application/json",
            }
            params = {
                "key": self.api_key
            }
        
        # 将图片数据转换为Base64编码
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        
        # 构建请求数据
        if conversation_history and len(conversation_history) > 0:
            # 有会话历史，构建上下文
            # 处理会话历史中的图片格式
            processed_history = []
            for msg in conversation_history:
                # 转换角色名称，确保使用 "user" 或 "model"
                role = msg["role"]
                if role == "assistant":
                    role = "model"
                
                processed_msg = {"role": role, "parts": []}
                for part in msg["parts"]:
                    if "text" in part:
                        processed_msg["parts"].append({"text": part["text"]})
                    elif "image_url" in part:
                        # 需要读取图片并转换为inlineData格式
                        try:
                            with open(part["image_url"], "rb") as f:
                                img_data = f.read()
                                # 压缩图片
                                img_data = await self._compress_image(img_data, max_size=800, quality=85)
                                img_base64 = base64.b64encode(img_data).decode("utf-8")
                                processed_msg["parts"].append({
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": img_base64
                                    }
                                })
                        except Exception as e:
                            logger.error(f"处理历史图片失败: {e}")
                            # 跳过这个图片
                processed_history.append(processed_msg)

            # 构建多模态请求
            # 压缩当前图片
            compressed_image_data = await self._compress_image(image_data, max_size=800, quality=85)
            compressed_image_base64 = base64.b64encode(compressed_image_data).decode("utf-8")
            
            user_message = {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg", 
                            "data": compressed_image_base64
                        }
                    }
                ]
            }

            data = {
                "contents": processed_history + [user_message],
                "generationConfig": {
                    "responseModalities": ["Text", "Image"]
                }
            }
        else:
            # 无会话历史，直接使用提示和图片
            data = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt
                            },
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": image_base64
                                }
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["Text", "Image"]
                }
            }
        
        # 创建代理配置
        proxies = None
        if self.enable_proxy and self.proxy_url and not self.use_proxy_service:
            # 只有在直接调用Google API且启用了代理时才使用代理
            proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url
            }
        
        try:
            # 添加重试逻辑
            max_retries = 10
            retry_count = 0
            retry_delay = 1
            
            async with aiohttp.ClientSession() as session:
                while retry_count <= max_retries:
                    try:
                        # 计算请求体大小
                        request_data = json.dumps(data)
                        request_size = len(request_data)
                        logger.info(f"Gemini API请求体大小: {request_size} 字节 ({request_size/1024/1024:.2f} MB)")
                        
                        # 检查请求体大小是否超过限制
                        if request_size > self.MAX_REQUEST_SIZE:
                            logger.warning(f"请求体大小 ({request_size/1024/1024:.2f} MB) 超出限制，尝试清理会话历史")
                            
                            # 如果请求体过大，简化为只有当前提示和图片
                            data = {
                                "contents": [
                                    {
                                        "parts": [
                                            {
                                                "text": prompt
                                            },
                                            {
                                                "inlineData": {
                                                    "mimeType": "image/png",
                                                    "data": image_base64
                                                }
                                            }
                                        ]
                                    }
                                ],
                                "generationConfig": {
                                    "responseModalities": ["Text", "Image"]
                                }
                            }
                            
                            # 重新计算请求体大小
                            request_data = json.dumps(data)
                            request_size = len(request_data)
                            logger.info(f"重建后的请求体大小: {request_size} 字节 ({request_size/1024/1024:.2f} MB)")
                        
                        # 发送请求
                        async with session.post(
                            url, 
                            headers=headers, 
                            params=params, 
                            json=data,
                            proxy=proxies["https"] if proxies else None,
                            timeout=60
                        ) as response:
                            logger.info(f"Gemini API响应状态码: {response.status}")
                            
                            if response.status == 200 or response.status != 503:
                                response_text = await response.text()
                                break
                            
                            # 如果是503错误且未达到最大重试次数，继续重试
                            if response.status == 503 and retry_count < max_retries:
                                logger.warning(f"Gemini API服务过载 (状态码: 503)，将进行重试 ({retry_count+1}/{max_retries})")
                                retry_count += 1
                                await asyncio.sleep(retry_delay)
                                retry_delay = min(retry_delay * 1.5, 10)  # 增加延迟，但最多10秒
                                continue
                            else:
                                response_text = await response.text()
                                break
                            
                    except Exception as e:
                        logger.error(f"请求异常: {str(e)}")
                        if retry_count < max_retries:
                            logger.warning(f"请求异常，将进行重试 ({retry_count+1}/{max_retries})")
                            retry_count += 1
                            await asyncio.sleep(retry_delay)
                            retry_delay = min(retry_delay * 1.5, 10)
                            continue
                        else:
                            raise
            
            # 如果所有重试都失败
            if not response or not response.status:
                logger.error("图片编辑失败，所有重试尝试均失败")
                return None, "API调用失败，所有重试尝试均失败"
                
            if response.status == 200:
                # 先记录响应内容，便于调试
                logger.debug(f"Gemini API原始响应内容长度: {len(response_text)}, 前100个字符: {response_text[:100] if response_text else '空'}")
                
                # 检查响应内容是否为空
                if not response_text.strip():
                    logger.error("Gemini API返回了空响应")
                    return None, "API返回了空响应，请检查网络连接或代理服务配置"
                
                try:
                    result = json.loads(response_text)
                    # 记录解析后的JSON结构
                    logger.debug(f"Gemini API响应JSON结构: 已获取")
                except json.JSONDecodeError as json_err:
                    logger.error(f"JSON解析错误: {str(json_err)}, 响应内容: {response_text[:200]}")
                    # 检查是否是代理服务问题
                    if self.use_proxy_service:
                        logger.error("可能是代理服务配置问题，尝试禁用代理服务或检查代理服务实现")
                        return None, "API响应格式错误，可能是代理服务配置问题。请检查代理服务实现或暂时禁用代理服务。"
                    return None, f"API响应格式错误: {str(json_err)}"
                
                # 检查是否有内容安全问题
                candidates = result.get("candidates", [])
                if candidates and len(candidates) > 0:
                    finish_reason = candidates[0].get("finishReason", "")
                    if finish_reason == "SAFETY":
                        logger.warning("Gemini API返回SAFETY，图片内容可能违反安全政策")
                        return None, "内容被安全系统拦截，请修改您的提示词"
                    
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    
                    # 处理文本和图片响应
                    text_response = None
                    image_data = None
                    
                    for part in parts:
                        # 处理文本部分
                        if "text" in part and part["text"]:
                            text_response = part["text"]
                        
                        # 处理图片部分
                        if "inlineData" in part:
                            inlineData = part.get("inlineData", {})
                            if inlineData and "data" in inlineData:
                                # 返回Base64解码后的图片数据
                                image_data = base64.b64decode(inlineData["data"])
                    
                    if not image_data:
                        logger.error(f"API响应中没有找到图片数据")
                    
                    return image_data, text_response
                
                logger.error(f"未找到编辑后的图片数据")
                return None, None
            else:
                logger.error(f"Gemini API调用失败 (状态码: {response.status}): {response_text}")
                error_message = f"API调用失败，状态码: {response.status}"
                
                # 特殊处理一些常见错误
                if response.status == 400:
                    error_message = "请求格式错误，请检查API版本或参数"
                elif response.status == 401:
                    error_message = "API密钥无效或未授权"
                elif response.status == 403:
                    error_message = "没有访问权限，请检查API密钥或账户状态"
                elif response.status == 429:
                    error_message = "请求过于频繁，请稍后再试"
                
                return None, error_message
        except Exception as e:
            logger.error(f"API调用异常: {str(e)}")
            logger.exception(e)
            return None, f"API调用异常: {str(e)}"

    def _translate_gemini_message(self, text: str) -> str:
        """将Gemini API的英文消息翻译成中文"""
        # 内容安全过滤消息
        if "SAFETY" in text:
            return "抱歉，您的请求可能违反了内容安全政策，无法生成或编辑图片。请尝试修改您的描述，提供更为安全、合规的内容。"
        
        # 处理API响应中的特定错误
        if "finishReason" in text:
            return "抱歉，图片处理失败，请尝试其他描述或稍后再试。"
            
        # 常见的内容审核拒绝消息翻译
        if "I'm unable to create this image" in text:
            if "sexually suggestive" in text:
                return "抱歉，我无法创建这张图片。我不能生成带有性暗示或促进有害刻板印象的内容。请提供其他描述。"
            elif "harmful" in text or "dangerous" in text:
                return "抱歉，我无法创建这张图片。我不能生成可能有害或危险的内容。请提供其他描述。"
            elif "violent" in text:
                return "抱歉，我无法创建这张图片。我不能生成暴力或血腥的内容。请提供其他描述。"
            else:
                return "抱歉，我无法创建这张图片。请尝试修改您的描述，提供其他内容。"
        
        # 其他常见拒绝消息
        if "cannot generate" in text or "can't generate" in text:
            return "抱歉，我无法生成符合您描述的图片。请尝试其他描述。"
        
        if "against our content policy" in text:
            return "抱歉，您的请求违反了内容政策，无法生成相关图片。请提供其他描述。"
        
        # 默认情况，原样返回
        return text

    def _get_recent_image(self, conversation_key: str) -> Optional[bytes]:
        """获取最近的图片数据"""
        logger.info(f"尝试获取会话 {conversation_key} 的最近图片")
        
        # 尝试直接从缓存获取
        if conversation_key in self.image_cache:
            cache_data = self.image_cache[conversation_key]
            if time.time() - cache_data["timestamp"] <= self.image_cache_timeout:
                logger.info(f"成功从缓存直接获取图片数据，大小: {len(cache_data['content'])} 字节")
                return cache_data["content"]
        
        # 如果缓存中没有或已过期，尝试从文件中读取
        if conversation_key in self.last_images:
            last_image_path = self.last_images[conversation_key]
            if os.path.exists(last_image_path):
                try:
                    with open(last_image_path, "rb") as f:
                        image_data = f.read()
                        # 加入缓存
                        self.image_cache[conversation_key] = {
                            "content": image_data,
                            "timestamp": time.time()
                        }
                        logger.info(f"从最后图片路径读取并加入缓存: {last_image_path}")
                        return image_data
                except Exception as e:
                    logger.error(f"从文件读取图片失败: {e}")
        
        logger.warning(f"未找到会话 {conversation_key} 的最近图片")
        return None 

    @on_image_message(priority=60)
    async def handle_image_message(self, bot: WechatAPIClient, message: dict):
        """处理图片消息"""
        if not self.enable:
            return True  # 插件禁用，传递给其他插件
            
        # 获取用户ID
        user_id = self._get_user_id(message)
        conversation_key = self._get_conversation_key(message)
        
        # 清理过期会话和图片缓存
        self._cleanup_expired_conversations()
        self._cleanup_image_cache()
        
        # 尝试读取图片数据
        image_data = None
        try:
            # 首先尝试从Image字段获取图片路径
            image_path = message.get("Image")
            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    image_data = f.read()
                logger.info(f"成功从路径读取图片数据: {image_path}，大小: {len(image_data)} 字节")
            else:
                # 尝试从消息中直接获取图片数据
                image_content = message.get("Content")
                if image_content and isinstance(image_content, str) and image_content.startswith("/9j/"):
                    try:
                        # 看起来是base64编码的图片数据
                        logger.debug("检测到base64编码的图片数据，直接解码")
                        image_data = base64.b64decode(image_content)
                        logger.info(f"base64图片数据解码成功，大小: {len(image_data)} 字节")
                    except Exception as e:
                        logger.error(f"base64图片数据解码失败: {e}")
                else:
                    logger.warning(f"未能找到有效的图片数据，Image路径: {image_path}, Content长度: {len(image_content) if image_content else 0}")
                    return True  # 没有图片数据，传递给其他插件
        except Exception as e:
            logger.error(f"读取图片数据失败: {e}")
            return True  # 读取图片数据失败，传递给其他插件
        
        if not image_data:
            logger.warning("未能获取图片数据")
            return True  # 没有图片数据，传递给其他插件
            
        # 缓存图片数据
        self.image_cache[conversation_key] = {
            "content": image_data,
            "timestamp": time.time()
        }
        
        # 如果user_id与conversation_key不同，也用user_id缓存
        if user_id != conversation_key:
            self.image_cache[user_id] = {
                "content": image_data,
                "timestamp": time.time()
            }
            
        logger.info(f"已缓存用户 {user_id} 的图片，大小: {len(image_data)} 字节")
        
        # 添加诊断日志，检查等待状态
        logger.info(f"检查用户 {user_id} 的等待状态...")
        logger.info(f"当前等待反推图片的用户列表: {list(self.waiting_for_reverse_image.keys())}")
        logger.info(f"当前等待识图的用户列表: {list(self.waiting_for_analysis_image.keys())}")
        logger.info(f"当前等待参考图的用户列表: {list(self.waiting_for_reference_image.keys())}")
        logger.info(f"当前等待融图的用户列表: {list(self.waiting_for_merge_image.keys())}")
        
        # 处理等待状态的图片上传
        if user_id in self.waiting_for_reverse_image:
            # 记录详细日志
            logger.info(f"检测到用户 {user_id} 有待处理的反推图片请求")
            logger.info(f"反推图片等待时间: {time.time() - self.waiting_for_reverse_image_time.get(user_id, 0):.2f}秒")
            logger.info(f"反推图片等待值: {self.waiting_for_reverse_image.get(user_id)}")
            
            # 检查是否已超时
            if time.time() - self.waiting_for_reverse_image_time.get(user_id, 0) > self.reverse_image_wait_timeout:
                # 清理超时状态
                wait_value = self.waiting_for_reverse_image.pop(user_id, None)
                self.waiting_for_reverse_image_time.pop(user_id, None)
                logger.warning(f"反推图片上传超时: {user_id}, 等待值: {wait_value}")
                await bot.send_text_message(message["FromWxid"], "反推图片上传超时，请重新发送命令")
                return False  # 阻止其他插件处理
            
            # 清理状态
            wait_value = self.waiting_for_reverse_image.pop(user_id, None)
            wait_time = self.waiting_for_reverse_image_time.pop(user_id, None)
            logger.info(f"清理用户 {user_id} 的反推图片等待状态: value={wait_value}, time={wait_time}")
            
            # 处理反推
            logger.info(f"接收到用户 {user_id} 的反推图片，开始处理反推提示词")
            try:
                await self._process_reverse_image(bot, message, user_id, image_data)
            except Exception as e:
                logger.error(f"处理反推图片时出错: {str(e)}")
                logger.exception(e)
                await bot.send_text_message(message["FromWxid"], f"处理反推图片失败: {str(e)}")
            return False  # 阻止其他插件处理
            
        elif user_id in self.waiting_for_reference_image:
            # 检查是否已超时
            if time.time() - self.waiting_for_reference_image_time.get(user_id, 0) > self.reference_image_wait_timeout:
                # 清理超时状态
                prompt = self.waiting_for_reference_image.pop(user_id, None)
                self.waiting_for_reference_image_time.pop(user_id, None)
                logger.warning(f"参考图片上传超时: {user_id}, prompt: {prompt}")
                await bot.send_text_message(message["FromWxid"], "参考图片上传超时，请重新发送命令")
                return False  # 阻止其他插件处理
                
            # 获取之前保存的提示词并清理状态
            prompt = self.waiting_for_reference_image.pop(user_id)
            self.waiting_for_reference_image_time.pop(user_id, None)
            
            logger.info(f"接收到用户 {user_id} 的参考图片，开始处理参考图编辑，提示词: {prompt}")
            
            # 处理参考图片编辑请求
            await self._process_reference_edit(bot, message, user_id, conversation_key, prompt, image_data)
            return False  # 阻止其他插件处理
            
        elif user_id in self.waiting_for_analysis_image:
            # 处理识图分析
            question = self.waiting_for_analysis_image.pop(user_id)
            self.waiting_for_analysis_image_time.pop(user_id, None)
            
            logger.info(f"接收到用户 {user_id} 的识图图片，开始处理识图，问题: {question}")
            await self._process_image_analysis(bot, message, user_id, image_data, question)
            return False
            
        elif user_id in self.waiting_for_merge_image:
            # 处理融图
            if user_id in self.waiting_for_merge_image_first and self.waiting_for_merge_image_first[user_id]:
                # 接收第一张图片
                prompt = self.waiting_for_merge_image[user_id]
                
                # 保存第一张图片
                self.merge_first_image[user_id] = image_data
                
                # 更新状态，等待第二张图片
                self.waiting_for_merge_image_first[user_id] = False
                self.waiting_for_merge_image_first_time[user_id] = time.time()
                
                # 发送提示
                await bot.send_text_message(message["FromWxid"], f"已接收第一张图片，请发送第二张图片")
                return False  # 阻止其他插件处理
            else:
                # 接收第二张图片
                prompt = self.waiting_for_merge_image.pop(user_id)
                first_image = self.merge_first_image.pop(user_id, None)
                
                # 清理状态
                self.waiting_for_merge_image_time.pop(user_id, None)
                self.waiting_for_merge_image_first.pop(user_id, None)
                if hasattr(self, 'waiting_for_merge_image_first_time') and user_id in self.waiting_for_merge_image_first_time:
                    self.waiting_for_merge_image_first_time.pop(user_id, None)
                
                if not first_image:
                    # 如果没有第一张图片，报错
                    await bot.send_text_message(message["FromWxid"], "未找到第一张图片，请重新开始融图流程")
                    return False  # 阻止其他插件处理
                    
                # 处理融图
                logger.info(f"接收到用户 {user_id} 的第二张融图图片，开始融图处理")
                await self._process_merge_image(bot, message, user_id, conversation_key, prompt, first_image, image_data)
                return False  # 阻止其他插件处理
            
        # 不是期望的图片上传，继续处理
        logger.info(f"用户 {user_id} 没有待处理的图片请求，忽略图片消息")
        return True

    async def _process_reference_edit(self, bot: WechatAPIClient, message: dict, user_id: str, conversation_key: str, prompt: str, image_data: bytes):
        """处理参考图编辑请求"""
        try:
            # 显示处理中消息
            await bot.send_text_message(message["FromWxid"], "正在处理参考图编辑，请稍候...")
            
            # 检查积分（如果启用）
            if self.enable_points:
                # 这里应该添加积分检查逻辑
                pass
            
            # 保存图片为临时文件
            temp_path = self._save_temp_image(image_data, "ref_img")
            if temp_path:
                self.last_images[conversation_key] = temp_path
            
            # 准备会话历史（如果需要）
            conversation_history = self.conversations.get(conversation_key, {}).get("messages", [])
            
            # 调用图片编辑API
            edited_image, error_msg = await self._edit_image(prompt, image_data, conversation_history)
            
            if edited_image:
                # 保存编辑后的图片
                save_path = self._save_temp_image(edited_image, "gem_ref")
                if save_path:
                    # 更新最后图片路径
                    self.last_images[conversation_key] = save_path
                    
                    # 更新图片缓存
                    self.image_cache[conversation_key] = {
                        "content": edited_image,
                        "timestamp": time.time()
                    }
                    if user_id != conversation_key:
                        self.image_cache[user_id] = {
                            "content": edited_image,
                            "timestamp": time.time()
                        }
                    
                    # 发送编辑后的图片
                    try:
                        # 直接使用编辑后的图片数据发送，避免文件IO操作
                        await bot.send_image_message(message["FromWxid"], edited_image)
                        logger.info("使用二进制数据成功发送编辑后的图片")
                    except Exception as e:
                        logger.error(f"使用二进制数据发送编辑后的图片失败: {str(e)}")
                        try:
                            # 读取图片数据并发送
                            with open(save_path, "rb") as f:
                                img_binary = f.read()
                                await bot.send_image_message(message["FromWxid"], img_binary)
                                logger.info(f"使用文件读取方式发送编辑后的图片: {save_path}")
                        except Exception as e2:
                            logger.error(f"使用文件读取方式发送编辑后的图片失败: {str(e2)}")
                            try:
                                # 尝试使用路径发送
                                await bot.send_image_message(message["FromWxid"], save_path)
                                logger.info(f"使用路径方式发送编辑后的图片: {save_path}")
                            except Exception as e3:
                                logger.error(f"所有图片发送方式均失败: {str(e3)}")
                                await bot.send_text_message(message["FromWxid"], "发送编辑后的图片失败，请重试")
                                return
                    
                    # 添加到会话历史
                    # 用户输入
                    self._add_message_to_conversation(
                        conversation_key,
                        "user",
                        [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_data).decode("utf-8")}}
                        ]
                    )
                    
                    # 模型响应
                    self._add_message_to_conversation(
                        conversation_key,
                        "model",
                        [
                            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(edited_image).decode("utf-8")}}
                        ]
                    )
                else:
                    await bot.send_text_message(message["FromWxid"], "图片保存失败，请重试")
            else:
                # 翻译错误消息
                if error_msg:
                    error_msg = self._translate_gemini_message(error_msg)
                    
                await bot.send_text_message(message["FromWxid"], f"参考图编辑失败: {error_msg or '未知错误'}")
        except Exception as e:
            logger.error(f"处理参考图编辑异常: {str(e)}")
            logger.exception(e)
            await bot.send_text_message(message["FromWxid"], f"处理参考图编辑时出错: {str(e)}")
    
    async def _process_merge_image(self, bot: WechatAPIClient, message: dict, user_id: str, conversation_key: str, prompt: str, first_image: bytes, second_image: bytes):
        """处理融图请求"""
        try:
            # 显示处理中消息
            await bot.send_text_message(message["FromWxid"], "正在处理融图，请稍候...")
            
            # 检查积分（如果启用）
            if self.enable_points:
                # 这里应该添加积分检查逻辑
                pass
            
            # 准备会话上下文
            self._create_or_reset_conversation(conversation_key, self.SESSION_TYPE_MERGE, False)
            
            # 构建请求体
            fusion_prompt = f"融合这两张图片。{prompt}" if prompt else "融合这两张图片，创造一个协调的组合图像。"
            
            # 用户输入
            self._add_message_to_conversation(
                conversation_key,
                "user",
                [
                    {"text": fusion_prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(first_image).decode("utf-8")}},
                    {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(second_image).decode("utf-8")}}
                ]
            )
            
            # 调用API
            try:
                # API调用逻辑与_edit_image类似，但需要处理两张图片
                # 此处简化为直接调用_edit_image，实际可能需要修改
                merged_image, error_msg = await self._edit_image(fusion_prompt, first_image, self.conversations.get(conversation_key, {}).get("messages", []))
                
                if merged_image:
                    # 保存融合后的图片
                    save_path = self._save_temp_image(merged_image, "gem_merge")
                    if save_path:
                        # 更新最后图片路径
                        self.last_images[conversation_key] = save_path
                        
                        # 更新图片缓存
                        self.image_cache[conversation_key] = {
                            "content": merged_image,
                            "timestamp": time.time()
                        }
                        if user_id != conversation_key:
                            self.image_cache[user_id] = {
                                "content": merged_image,
                                "timestamp": time.time()
                            }
                        
                        # 发送融合后的图片
                        try:
                            # 直接使用二进制数据发送，避免文件IO操作
                            await bot.send_image_message(message["FromWxid"], merged_image)
                            logger.info("使用二进制数据成功发送融合后的图片")
                        except Exception as e:
                            logger.error(f"使用二进制数据发送融合后的图片失败: {str(e)}")
                            try:
                                # 读取图片数据并发送
                                with open(save_path, "rb") as f:
                                    img_binary = f.read()
                                    await bot.send_image_message(message["FromWxid"], img_binary)
                                    logger.info(f"使用文件读取方式发送融合后的图片: {save_path}")
                            except Exception as e2:
                                logger.error(f"使用文件读取方式发送融合后的图片失败: {str(e2)}")
                                try:
                                    # 尝试使用路径发送
                                    await bot.send_image_message(message["FromWxid"], save_path)
                                    logger.info(f"使用路径方式发送融合后的图片: {save_path}")
                                except Exception as e3:
                                    logger.error(f"所有图片发送方式均失败: {str(e3)}")
                                    await bot.send_text_message(message["FromWxid"], "发送融合后的图片失败，请重试")
                                    return
                        
                        # 添加到会话历史
                        self._add_message_to_conversation(
                            conversation_key,
                            "model",
                            [
                                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(merged_image).decode("utf-8")}}
                            ]
                        )
                    else:
                        await bot.send_text_message(message["FromWxid"], "图片保存失败，请重试")
                else:
                    # 翻译错误消息
                    if error_msg:
                        error_msg = self._translate_gemini_message(error_msg)
                        
                    await bot.send_text_message(message["FromWxid"], f"融图失败: {error_msg or '未知错误'}")
            except Exception as e:
                logger.error(f"调用融图API异常: {str(e)}")
                logger.exception(e)
                await bot.send_text_message(message["FromWxid"], f"调用融图API时出错: {str(e)}")
        except Exception as e:
            logger.error(f"处理融图异常: {str(e)}")
            logger.exception(e)
            await bot.send_text_message(message["FromWxid"], f"处理融图时出错: {str(e)}")
    
    async def _process_reverse_image(self, bot: WechatAPIClient, message: dict, user_id: str, image_data: bytes):
        """处理图片反向生成提示词功能"""
        try:
            # 保存图片到临时文件，确保图片可以被正确处理
            temp_path = self._save_temp_image(image_data, "reverse_img")
            if not temp_path:
                logger.error("保存反推图片到临时文件失败")
                await bot.send_text_message(message["FromWxid"], "保存图片失败，请重试")
                return
                
            logger.info(f"已保存反推图片到临时文件: {temp_path}")
            
            # 显示处理中消息
            await bot.send_text_message(message["FromWxid"], "正在分析图片，请稍候...")
            
            # 尝试三种不同的方法处理图片
            success = False
            error_messages = []
            
            try:
                # 将图片转换为Base64格式
                image_base64 = base64.b64encode(image_data).decode("utf-8")
                logger.info(f"图片成功转换为Base64格式，长度: {len(image_base64)}")
                
                # 提示词（中文）
                prompt = "请详细分析这张图片的内容，包括主要对象、场景、风格、颜色等关键特征。如果图片包含文字，也请提取出来。请用简洁清晰的中文进行描述。"
                
                # 构建请求数据
                data = {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/jpeg",  # 使用更通用的mime类型
                                        "data": image_base64
                                    }
                                },
                                {
                                    "text": prompt
                                }
                            ]
                        }
                    ]
                }
                
                # 根据配置决定使用直接调用还是通过代理服务调用
                if self.use_proxy_service and self.proxy_service_url:
                    url = f"{self.proxy_service_url.rstrip('/')}/v1beta/models/{self.model}:generateContent?key={self.api_key}"
                    headers = {
                        "Content-Type": "application/json"
                    }
                    params = {}
                    logger.info(f"使用代理服务URL: {self.proxy_service_url}")
                else:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
                    headers = {
                        "Content-Type": "application/json",
                    }
                    params = {
                        "key": self.api_key
                    }
                    logger.info("使用直接API请求")
                
                # 创建代理配置
                proxies = None
                if self.enable_proxy and self.proxy_url and not self.use_proxy_service:
                    proxies = {
                        "http": self.proxy_url,
                        "https": self.proxy_url
                    }
                    logger.info(f"使用代理: {self.proxy_url}")
                
                # 添加重试逻辑
                max_retries = 3  # 最大重试次数
                retry_count = 0
                retry_delay = 1  # 初始重试延迟（秒）
                response = None
                result = None
                response_status = None
                
                logger.info(f"开始执行反推图片请求，URL: {url}")
                
                while retry_count <= max_retries:
                    try:
                        # 发送请求
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                url,
                                headers=headers,
                                params=params,
                                json=data,
                                proxy=proxies["https"] if proxies else None,
                                timeout=60
                            ) as response:
                                response_status = response.status
                                logger.info(f"图片分析API响应状态码: {response_status}")
                                
                                # 如果成功或不是可重试的错误，跳出循环
                                if response_status == 200 or response_status not in [429, 500, 502, 503, 504]:
                                    try:
                                        result = await response.json()
                                        logger.info("成功解析API响应为JSON")
                                        break
                                    except Exception as json_error:
                                        logger.error(f"解析API响应JSON失败: {str(json_error)}")
                                        result = None
                                        # 尝试读取文本内容
                                        try:
                                            text_content = await response.text()
                                            logger.error(f"API响应文本内容: {text_content[:500]}...")
                                            error_messages.append(f"API响应解析失败: {str(json_error)}")
                                        except:
                                            pass
                                        break
                                
                                # 如果是可重试的错误且未达到最大重试次数，继续重试
                                if retry_count < max_retries:
                                    logger.warning(f"API请求返回状态码 {response_status}，将进行重试 ({retry_count+1}/{max_retries})")
                                    retry_count += 1
                                    await asyncio.sleep(retry_delay)
                                    retry_delay = min(retry_delay * 2, 5)  # 增加延迟，但最多5秒
                                    continue
                                else:
                                    logger.error(f"达到最大重试次数，最后状态码: {response_status}")
                                    error_messages.append(f"API请求失败，状态码: {response_status}")
                                    break
                            
                    except Exception as e:
                        logger.error(f"图片分析请求异常: {str(e)}")
                        if retry_count < max_retries:
                            logger.warning(f"图片分析请求异常，将进行重试 ({retry_count+1}/{max_retries})")
                            retry_count += 1
                            await asyncio.sleep(retry_delay)
                            retry_delay = min(retry_delay * 2, 5)
                            continue
                        else:
                            logger.error(f"图片分析请求异常，达到最大重试次数: {str(e)}")
                            error_messages.append(f"网络请求异常: {str(e)}")
                            break
                
                # 处理API响应
                if result and response_status == 200:
                    candidates = result.get("candidates", [])
                    if candidates and len(candidates) > 0:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        
                        # 提取文本响应
                        text_response = None
                        for part in parts:
                            if "text" in part:
                                text_response = part["text"]
                                break
                        
                        if text_response:
                            logger.info(f"成功获取反推结果，文本长度: {len(text_response)}")
                            
                            # 清理输出路径
                            try:
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)
                                    logger.debug(f"已清理临时文件: {temp_path}")
                            except Exception as e:
                                logger.warning(f"清理临时文件失败: {e}")
                            
                            # 发送反推结果
                            await bot.send_text_message(message["FromWxid"], text_response)
                            logger.info("反推图片结果已发送给用户")
                            success = True
                            # 成功处理，不需要继续尝试
                        else:
                            logger.warning("API响应中没有文本内容")
                            error_messages.append("API响应中没有文本内容")
                    else:
                        logger.warning("API响应中没有candidates字段或为空")
                        error_messages.append("API未返回有效响应")
                else:
                    logger.warning(f"API请求失败或返回非200状态码: {response_status}")
                    
            except Exception as process_error:
                logger.error(f"处理反推请求过程中出错: {str(process_error)}")
                logger.exception(process_error)
                error_messages.append(f"处理图片分析失败: {str(process_error)}")
            
            # 如果所有尝试都失败，发送错误信息给用户
            if not success:
                if error_messages:
                    error_summary = "\n".join(error_messages[:3])  # 只显示前三个错误
                    await bot.send_text_message(message["FromWxid"], f"图片分析失败，请稍后重试。\n错误信息: {error_summary}")
                else:
                    await bot.send_text_message(message["FromWxid"], "图片分析失败，请稍后重试。")
                    
        except Exception as outer_error:
            logger.error(f"反推图片整体处理异常: {str(outer_error)}")
            logger.exception(outer_error)
            await bot.send_text_message(message["FromWxid"], f"图片分析失败: {str(outer_error)}")
            return
    
    async def _process_multi_image_response(self, result: dict) -> Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]:
        """
        处理Gemini API返回的多图片响应
        
        Args:
            result: API返回的JSON结果
            
        Returns:
            Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]: 图片数据和文本对列表, 最终文本, 错误消息
        """
        try:
            # 检查API响应是否包含候选内容
            candidates = result.get("candidates", [])
            if not candidates or len(candidates) == 0:
                # 检查是否包含promptFeedback
                prompt_feedback = result.get("promptFeedback", {})
                if prompt_feedback:
                    block_reason = prompt_feedback.get("blockReason", "")
                    if block_reason:
                        logger.warning(f"提示词被阻止: {block_reason}")
                        return [], None, f"提示词被拒绝: {block_reason}"
                
                logger.warning("API响应中没有候选内容")
                return [], None, "API响应中没有候选内容"
            
            # 检查是否有内容安全或其他问题导致失败
            first_candidate = candidates[0]
            finish_reason = first_candidate.get("finishReason", "")
            
            # 处理已知的失败原因
            if finish_reason == "SAFETY":
                logger.warning("内容安全过滤: 请求被安全系统拒绝")
                return [], None, "请求被内容安全系统拒绝，请修改提示词后重试"
            elif finish_reason == "RECITATION":
                logger.warning("内容重复: API检测到提示词中存在重复或引用内容")
                return [], None, "API检测到提示词中存在重复或引用内容，请修改后重试"
            elif finish_reason == "IMAGE_SAFETY":
                logger.warning("图片安全过滤: 生成的图片被安全系统拒绝")
                return [], None, "生成的图片被内容安全系统拒绝，请修改提示词后重试"
            elif finish_reason and finish_reason != "STOP":
                logger.warning(f"其他失败原因: {finish_reason}")
                return [], None, f"生成失败，原因: {finish_reason}"
            
            # 处理正常响应
            content = first_candidate.get("content", {})
            parts = content.get("parts", [])
            
            # 提取文本和图片
            image_text_pairs = []  # 存储(图片数据, 图片文本)对
            final_text = ""  # 存储主文本响应
            
            # 分组处理模式
            current_text = ""  # 当前处理的文本
            
            for part in parts:
                if "text" in part:
                    text_content = part["text"].strip()
                    if text_content:
                        current_text = text_content
                        final_text = text_content  # 保存最后一个文本为最终文本
                
                elif "inlineData" in part:
                    inline_data = part.get("inlineData", {})
                    if inline_data and "data" in inline_data:
                        try:
                            # 将Base64数据转换为图片
                            image_data = base64.b64decode(inline_data["data"])
                            
                            # 将当前文本与图片配对
                            image_text_pairs.append((image_data, current_text))
                            current_text = ""  # 重置当前文本，避免重复
                        except Exception as e:
                            logger.error(f"处理图片数据失败: {e}")
            
            return image_text_pairs, final_text, None
            
        except Exception as e:
            logger.error(f"处理API响应异常: {e}")
            logger.exception(e)
            return [], None, f"处理API响应失败: {str(e)}"
    
    async def _process_image_analysis(self, bot: WechatAPIClient, message: dict, user_id: str, image_data: bytes, question: str):
        """处理图片分析请求"""
        try:
            # 保存图片到临时文件，确保图片可以被正确处理
            temp_path = self._save_temp_image(image_data, "analysis_img")
            if not temp_path:
                await bot.send_text_message(message["FromWxid"], "保存图片失败，请重试")
                return
                
            logger.info(f"已保存分析图片到临时文件: {temp_path}")
            
            # 显示处理中消息
            await bot.send_text_message(message["FromWxid"], "正在分析图片，请稍候...")
            
            # 调用API分析图片
            analysis_result = await self._analyze_image(image_data, question)
            
            if analysis_result:
                # 保存最近图片分析记录，便于追问
                self.last_analysis_image[user_id] = image_data
                self.last_analysis_time[user_id] = time.time()
                
                # 添加追问提示
                analysis_result += "\n\n💬3min内输入g追问+问题，可继续追问"
                
                # 发送分析结果
                await bot.send_text_message(message["FromWxid"], analysis_result)
                
                # 清理临时文件
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                        logger.debug(f"已清理临时文件: {temp_path}")
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")
            else:
                await bot.send_text_message(message["FromWxid"], "图片分析失败，请稍后重试")
        except Exception as e:
            logger.error(f"处理图片分析异常: {str(e)}")
            logger.exception(e)
            await bot.send_text_message(message["FromWxid"], f"处理图片分析时出错: {str(e)}")
    
    async def _analyze_image(self, image_data: bytes, question: str) -> Optional[str]:
        """调用API分析图片"""
        # 确保使用中文回答
        if not question.strip().endswith("。") and not "中文" in question:
            question = question + "。请用简洁的中文回答。"
            
        try:
            # 构建请求体
            encoded_image = base64.b64encode(image_data).decode("utf-8")
            
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": question},
                            {
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": encoded_image
                                }
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.4,
                    "topP": 0.95,
                    "topK": 64,
                    "maxOutputTokens": 2048,
                }
            }
            
            # 调用API
            headers = {
                "Content-Type": "application/json"
            }
            
            url = f"{self.base_url}/models/gemini-pro-vision:generateContent?key={self.api_key}"
            
            # 使用aiohttp发送请求
            async with aiohttp.ClientSession() as session:
                # 配置代理
                if self.enable_proxy and self.proxy_url:
                    session_kwargs = {"proxy": self.proxy_url}
                else:
                    session_kwargs = {}
                
                # 使用代理服务
                if self.use_proxy_service and self.proxy_service_url:
                    url = f"{self.proxy_service_url}?url={urllib.parse.quote_plus(url)}"
                    logger.info(f"使用代理服务，代理URL: {url}")
                
                # 构建请求
                request_body = json.dumps(payload)
                
                # 发送请求
                async with session.post(url, headers=headers, data=request_body, **session_kwargs) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            result = json.loads(response_text)
                            
                            # 解析响应
                            candidates = result.get("candidates", [])
                            if candidates and len(candidates) > 0:
                                content = candidates[0].get("content", {})
                                parts = content.get("parts", [])
                                
                                text_response = ""
                                for part in parts:
                                    if "text" in part:
                                        text_response += part["text"]
                                
                                return text_response
                            
                            logger.error(f"API响应中找不到有效内容: {response_text[:200]}")
                            return None
                        except json.JSONDecodeError as e:
                            logger.error(f"解析API响应异常: {str(e)}, 响应内容: {response_text[:200]}")
                            return None
                    else:
                        logger.error(f"API调用失败 (状态码: {response.status}): {response_text}")
                        return None
        except Exception as e:
            logger.error(f"分析图片异常: {str(e)}")
            logger.exception(e)
            return None

    async def _generate_image(self, prompt: str, conversation_history: List[Dict] = None) -> Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]:
        """调用Gemini API生成图片，返回图片数据和文本响应列表"""
        # 根据配置决定使用直接调用还是通过代理服务调用
        if self.use_proxy_service and self.proxy_service_url:
            # 使用代理服务调用API
            url = f"{self.proxy_service_url.rstrip('/')}/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            headers = {
                "Content-Type": "application/json"
            }
            params = {}  # 不需要在URL参数中传递API密钥
        else:
            # 直接调用Google API
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            headers = {
                "Content-Type": "application/json",
            }
            params = {
                "key": self.api_key
            }
        
        # 构建请求数据
        if conversation_history and len(conversation_history) > 0:
            # 有会话历史，构建上下文
            processed_history = []
            for msg in conversation_history:
                role = msg["role"]
                if role == "assistant":
                    role = "model"
                
                processed_msg = {"role": role, "parts": []}
                for part in msg["parts"]:
                    if "text" in part:
                        processed_msg["parts"].append({"text": part["text"]})
                    elif "image_url" in part:
                        try:
                            with open(part["image_url"], "rb") as f:
                                image_data = f.read()
                                # 压缩图片数据以减小请求大小
                                image_data = await self._compress_image(image_data, max_size=600, quality=80)
                                image_base64 = base64.b64encode(image_data).decode("utf-8")
                                processed_msg["parts"].append({
                                    "inlineData": {
                                        "mimeType": "image/jpeg",
                                        "data": image_base64
                                    }
                                })
                        except Exception as e:
                            logger.error(f"处理历史图片失败: {e}")
                    elif "inline_data" in part:
                        # 直接使用inlineData格式
                        processed_msg["parts"].append({
                            "inlineData": {
                                "mimeType": part["inline_data"]["mime_type"],
                                "data": part["inline_data"]["data"]
                            }
                        })
                processed_history.append(processed_msg)
            
            # 最终请求用户消息不需要重复添加，已包含在processed_history中
            data = {
                "contents": processed_history,
                "generationConfig": {
                    "responseModalities": ["Text", "Image"],
                    "temperature": 0.4,
                    "topP": 0.8,
                    "topK": 40
                }
            }
            
            # 记录处理后的请求数据（安全版本）
            safe_data = copy.deepcopy(data)
            for msg in safe_data["contents"]:
                for part in msg["parts"]:
                    if "inlineData" in part and "data" in part["inlineData"]:
                        part["inlineData"]["data"] = f"[BASE64_DATA_LENGTH: {len(part['inlineData']['data'])}]"
            logger.debug(f"请求数据结构: {safe_data}")
            
        else:
            data = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["Text", "Image"],
                    "temperature": 0.4,
                    "topP": 0.8,
                    "topK": 40
                }
            }
        
        proxies = None
        if self.enable_proxy and self.proxy_url and not self.use_proxy_service:
            proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url
            }
        
        try:
            logger.info(f"开始调用Gemini API生成图片，模型: {self.model}")
            
            max_retries = 15
            retry_count = 0
            retry_delay = 1
            response = None
            
            while retry_count <= max_retries:
                try:
                    # 计算请求体大小
                    request_data = json.dumps(data)
                    request_size = len(request_data)
                    logger.info(f"Gemini API请求体大小: {request_size} 字节 ({request_size/1024/1024:.2f} MB)")
                    
                    # 检查请求体大小是否超过限制
                    if request_size > self.MAX_REQUEST_SIZE:
                        logger.warning(f"请求体大小 ({request_size/1024/1024:.2f} MB) 超出限制，尝试清理会话历史")
                        
                        # 提取最后一条用户消息
                        last_user_message = None
                        if conversation_history and len(conversation_history) > 0:
                            for msg in reversed(conversation_history):
                                if msg.get("role") == "user":
                                    last_user_message = msg
                                    break
                            
                        # 重建请求数据，不包含历史
                        data = {
                            "contents": [
                                {
                                    "parts": [
                                        {
                                            "text": prompt
                                        }
                                    ]
                                }
                            ],
                            "generationConfig": {
                                "responseModalities": ["Text", "Image"],
                                "temperature": 0.4,
                                "topP": 0.8,
                                "topK": 40
                            }
                        }
                        
                        # 重新计算请求体大小
                        request_data = json.dumps(data)
                        request_size = len(request_data)
                        logger.info(f"重建后的请求体大小: {request_size} 字节 ({request_size/1024/1024:.2f} MB)")
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url, 
                            headers=headers, 
                            params=params, 
                            json=data,
                            proxy=proxies['https'] if proxies else None,
                            timeout=60
                        ) as response:
                            
                            logger.info(f"Gemini API响应状态码: {response.status}")
                            
                            if response.status == 200 or response.status != 503:
                                response_json = await response.json()
                                break
                            
                            if response.status == 503 and retry_count < max_retries:
                                logger.warning(f"Gemini API服务过载 (状态码: 503)，将进行重试 ({retry_count+1}/{max_retries})")
                                retry_count += 1
                                await asyncio.sleep(retry_delay)
                                retry_delay = min(retry_delay * 1.5, 10)
                                continue
                            else:
                                break
                        
                except Exception as e:
                    logger.error(f"请求异常: {str(e)}")
                    if retry_count < max_retries:
                        logger.warning(f"请求异常，将进行重试 ({retry_count+1}/{max_retries})")
                        retry_count += 1
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 1.5, 10)
                        continue
                    else:
                        raise
            
            if response is None or response.status != 200:
                return [], None, f"API调用失败，状态码: {response.status if response else 'unknown'}"
            
            # 处理多图片响应
            image_text_pairs, final_text, error_message = await self._process_multi_image_response(response_json)
            
            if error_message:
                return [], None, error_message
            
            if not image_text_pairs and not final_text:
                logger.warning("API返回成功但没有图片数据")
                if final_text:
                    logger.info(f"API返回的文本内容: {final_text[:100]}...")
            
            return image_text_pairs, final_text, None
                
        except Exception as e:
            logger.error(f"生成图片失败: {str(e)}")
            logger.exception(e)
            return [], None, f"生成图片失败: {str(e)}"

    async def _compress_image(self, image_data: bytes, max_size: int = 800, quality: int = 85, format: str = 'JPEG') -> bytes:
        """压缩图片，控制尺寸和质量以减小请求体大小
        
        Args:
            image_data: 原始图片二进制数据
            max_size: 图片的最大尺寸（宽度或高度的最大值）
            quality: JPEG压缩质量 (1-100)
            format: 输出格式 ('JPEG', 'PNG', etc.)
            
        Returns:
            bytes: 压缩后的图片数据
        """
        try:
            # 使用PIL打开图片
            img = Image.open(BytesIO(image_data))
            
            # 转换为RGB模式，解决某些透明PNG的问题
            if img.mode in ('RGBA', 'LA') and format == 'JPEG':
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            
            # 调整大小，保持纵横比
            width, height = img.size
            if width > max_size or height > max_size:
                if width > height:
                    new_width = max_size
                    new_height = int(height * (max_size / width))
                else:
                    new_height = max_size
                    new_width = int(width * (max_size / height))
                
                logger.info(f"调整图片大小: {width}x{height} -> {new_width}x{new_height}")
                img = img.resize((new_width, new_height), Image.LANCZOS)
            
            # 将图片保存到BytesIO对象中
            output = BytesIO()
            if format == 'JPEG':
                img.save(output, format=format, quality=quality, optimize=True)
            else:
                img.save(output, format=format, optimize=True)
            
            # 获取压缩后的图片数据
            compressed_data = output.getvalue()
            
            # 记录压缩效果
            compression_ratio = len(compressed_data) / len(image_data)
            logger.info(f"图片压缩: {len(image_data)} -> {len(compressed_data)} 字节，比率: {compression_ratio:.2f}")
            
            return compressed_data
        except Exception as e:
            logger.error(f"压缩图片失败: {str(e)}")
            logger.exception(e)
            # 如果压缩失败，返回原始图片数据
            return image_data

    async def _translate_prompt(self, prompt: str, user_id: str = None) -> str:
        """将中文提示词翻译成英文
        
        Args:
            prompt: 原始提示词（中文）
            user_id: 用户ID，可选参数，用于未来可能的用户特定翻译设置
            
        Returns:
            翻译后的提示词（英文），如果翻译失败则返回原始提示词
        """
        # 如果提示词为空，直接返回
        if not prompt or len(prompt.strip()) == 0:
            return prompt
        
        # 如果提示词已经是英文，直接返回
        if self._is_mostly_english(prompt):
            return prompt
        
        # 检查全局翻译设置
        if not self.enable_translate:
            return prompt
        
        # 检查翻译API配置
        if not self.translate_api_base or not self.translate_api_key or not self.translate_model:
            logger.warning("翻译配置不完整，使用原始提示词")
            return prompt
        
        try:
            # 构建请求数据
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.translate_api_key}"
            }
            
            data = {
                "model": self.translate_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的中英翻译专家。你的任务是将用户输入的中文提示词翻译成英文，用于AI图像生成。请确保翻译准确、自然，并保留原始提示词的意图和风格。不要添加任何解释或额外内容，只需提供翻译结果。"
                    },
                    {
                        "role": "user",
                        "content": f"请将以下中文提示词翻译成英文，用于AI图像生成：\n\n{prompt}"
                    }
                ]
            }
            
            # 发送请求
            url = f"{self.translate_api_base.rstrip('/')}/chat/completions"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data, timeout=10) as response:
                    if response.status == 200:
                        result = await response.json()
                        translated_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                        
                        # 清理翻译结果，移除可能的引号和多余空格
                        translated_text = translated_text.strip('"\'').strip()
                        
                        if translated_text:
                            logger.info(f"翻译成功: {prompt} -> {translated_text}")
                            return translated_text
            
            logger.warning(f"翻译失败: {response.status}")
            return prompt
            
        except Exception as e:
            logger.error(f"翻译出错: {str(e)}")
            return prompt
    
    def _is_mostly_english(self, text: str) -> bool:
        """判断文本是否主要由英文组成
        
        Args:
            text: 要检查的文本
            
        Returns:
            bool: 如果文本主要由英文组成则返回True
        """
        # 计算英文字符比例
        english_chars = sum(1 for c in text if ord('a') <= ord(c.lower()) <= ord('z'))
        total_chars = len(text.strip())
        
        # 如果总字符数为0，返回False
        if total_chars == 0:
            return False
        
        # 如果英文字符比例超过70%，认为是英文
        return english_chars / total_chars > 0.7

    async def _send_alternating_content(self, bot: WechatAPIClient, message: dict, image_text_pairs: List[Tuple[bytes, str]], final_text: Optional[str]) -> None:
        """
        处理并发送图像和文本内容
        
        Args:
            bot: 微信API客户端
            message: 消息字典
            image_text_pairs: 图片数据和文本对列表 [(image_data, text), ...]
            final_text: 最后的文本内容(可选)
        """
        user_id = message["FromWxid"]
        conversation_key = self._get_conversation_key(message)
        sent_contents = set()  # 用于避免发送重复内容
        
        # 创建临时目录
        os.makedirs(self.temp_dir, exist_ok=True)
        
        try:
            # 保存所有图片到本地（不先发送处理中提示，避免重复）
            image_paths = []
            for i, (image_data, text) in enumerate(image_text_pairs):
                # 生成图片文件名
                timestamp = int(time.time())
                random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                filename = f"gemini_{timestamp}_{random_str}_{i}.png"
                image_path = os.path.join(self.temp_dir, filename)
                
                # 保存图片
                with open(image_path, "wb") as f:
                    f.write(image_data)
                    
                image_paths.append((image_path, text))
                logger.info(f"已保存生成的图片: {image_path}")
            
            # 按顺序发送图片和文本
            for i, (image_path, text) in enumerate(image_paths):
                # 1. 尝试直接从内存发送图片
                image_idx = i
                current_image_data = image_text_pairs[image_idx][0]
                
                try:
                    # 优先使用二进制数据直接发送图片，避免文件IO操作
                    await bot.send_image_message(user_id, current_image_data)
                    logger.info(f"使用二进制数据成功发送图片 #{image_idx+1}")
                except Exception as e:
                    logger.error(f"使用二进制数据发送图片失败: {str(e)}，尝试从文件读取")
                    try:
                        # 如果直接发送失败，尝试从文件读取并发送
                        with open(image_path, "rb") as f:
                            file_data = f.read()
                            await bot.send_image_message(user_id, file_data)
                            logger.info(f"使用文件数据成功发送图片 #{image_idx+1}: {image_path}")
                    except Exception as e2:
                        logger.error(f"从文件发送图片也失败了: {str(e2)}")
                        await bot.send_text_message(user_id, f"图片 #{image_idx+1} 发送失败，请查看日志")
                
                # 2. 如果有关联文本且不重复，则发送文本
                if text and text not in sent_contents:
                    await bot.send_text_message(user_id, text)
                    sent_contents.add(text)
                    logger.info(f"发送图片 #{image_idx+1} 的关联文本，长度: {len(text)}")
            
            # 3. 如果有最终文本且不重复，则发送
            if final_text and final_text not in sent_contents:
                await bot.send_text_message(user_id, final_text)
                logger.info(f"发送最终文本，长度: {len(final_text)}")
            
            # 更新最后图片路径（如果有）
            if image_paths:
                last_image_path = image_paths[-1][0]
                self.last_images[conversation_key] = last_image_path
                logger.info(f"更新用户 {user_id} 的最后图片路径: {last_image_path}")
                
        except Exception as e:
            logger.error(f"处理和发送图像内容时出错: {str(e)}")
            logger.exception(e)
            await bot.send_text_message(user_id, "发送图片时出错，请查看日志")
            
        # 清理临时文件
        try:
            for image_path, _ in image_paths:
                if os.path.exists(image_path) and image_path != self.last_images.get(conversation_key):
                    os.remove(image_path)
                    logger.debug(f"已清理临时图片文件: {image_path}")
        except Exception as e:
            logger.warning(f"清理临时图片文件时出错: {str(e)}")