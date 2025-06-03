# -*- coding: utf-8 -*-
import json
import time
import struct
import random
import os
import httpx
import re
import requests
import base64
import tomllib
import asyncio
import aiohttp
from loguru import logger
from io import BytesIO
from typing import List, Dict, Union, Optional
import io
from datetime import datetime
import traceback

# 添加PIL库用于图片处理和验证
try:
    from PIL import Image
except ImportError:
    # 如果PIL库未安装，尝试安装
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
    from PIL import Image

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase
from .login import LoginHandler

class YuewenPlugin(PluginBase):
    description = "跃问AI助手插件"
    author = "xxxbot团伙"
    version = "0.2"

    def __init__(self):
        """初始化插件"""
        super().__init__()
        
        # 基本属性
        self.description = "跃问AI助手插件"
        self.author = "lanvent (adapted for xxxbot)"
        self.version = "0.2"
        
        # 插件状态
        self.enable = True  # 默认启用
        self.initialized = False
        
        # 用户会话状态
        self.waiting_for_image = {}  # 存储待处理的识图请求 {user_id: {prompt: "...", time: ...}}
        self.multi_image_data = {}   # 存储多图处理数据
        self.user_sessions = {}      # 用户会话状态
        
        # API参数
        self.current_base_url = "https://www.stepfun.com"
        self.api_version = 'new'    # 'new'=StepFun, 'old'=Yuewen
        
        # 会话相关
        self.current_chat_id = None
        self.current_chat_session_id = None
        
        # 登录凭据
        self.oasis_token = None
        self.oasis_webid = None
        self.token_expires_at = 0
        
        # 配置参数
        self.welcome = "您好，我是跃问 AI 助手，有什么可以帮您？"
        self.imgprompt = "这张图片是什么？"
        self.temperature = 0.9
        self.network_mode = True
        
        # 加载配置
        self._load_config()
        
        # 当前消息上下文，用于直接发送图片
        self.current_bot = None
        self.current_message = None
        self.image_directly_sent = False  # 标记图片是否已直接发送
        self.last_image_error = None      # 保存最近的图片生成错误信息
        self._last_upload_error = None    # 保存最近的图片上传错误信息
        
        # 定期刷新token的任务
        self.refresh_token_task = None
        
        # 错误计数和状态跟踪
        self.api_errors_count = 0
        
        # 从配置文件加载配置
        self._load_config()
        
        # 基础请求头，用于API请求
        self.base_headers = {
            'accept': '*/*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'no-cache',
            'origin': '', # 将在请求时动态设置
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': '', # 将在请求时动态设置
            'sec-ch-ua': '"Not/A)Brand";v="99", "Microsoft Edge";v="127", "Chromium";v="127"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0',
            'x-waf-client-type': 'fetch_sdk'
        }
        
        # HTTP会话
        self.http_session = None  # 将在async_init中创建
        
        # 设置API基本URL
        self.base_urls = {
            'old': 'https://yuewen.cn',
            'new': 'https://www.stepfun.com'
        }
        
        # 当前基本URL基于配置的API版本
        self.current_base_url = self.base_urls[self.config.get('api_version', 'old')]
        
        # 设置API版本属性
        self.api_version = self.config.get('api_version', 'old')
        
        # 创建LoginHandler实例并传递配置
        self.login_handler = LoginHandler(self.config)
        
        # 明确设置LoginHandler的插件引用
        self.login_handler._plugin = self
        
        # 确保login_handler有base_headers
        if hasattr(self.login_handler, 'base_headers'):
            self.login_handler.base_headers = self.base_headers.copy()
        
        # 用户状态
        self.oasis_webid = self.config.get('oasis_webid')
        self.oasis_token = self.config.get('oasis_token')
        self.need_login = self.config.get('need_login', True)
        self.current_model_id = self.config.get('current_model_id', 6)  # 默认模型ID
        self.network_mode = self.config.get('network_mode', True)   # 默认开启联网
        self.trigger_prefix = self.config.get('trigger_prefix', 'yw')
        
        # 图片配置
        image_config = self.config.get('image_config', {})
        self.pic_trigger_prefix = image_config.get('trigger', '识图')
        self.imgprompt = image_config.get('imgprompt', '解释下图片内容')
        
        # 会话状态
        self.current_chat_id = None  # 旧版API会话ID
        self.current_chat_session_id = None  # 新版API会话ID
        self.last_active_time = 0
        self.last_token_refresh = 0
        self.last_message = None  # 保存最近一次消息用于分享
        
        # 登录相关状态
        self.device_id = ""
        self.is_login_triggered = False
        self.waiting_for_verification = {}  # user_id -> phone_number
        self.login_users = set()  # 用于存储正在等待输入手机号的用户ID
        
        # 图片消息处理
        self.waiting_for_image = {}
        self.multi_image_data = {}
        self.max_images = 9
        
        # 模型列表
        self.models = {
            1: {"name": "deepseek r1", "id": 6, "can_network": True},
            2: {"name": "Step2", "id": 2, "can_network": True},
            3: {"name": "Step-R mini", "id": 4, "can_network": False},
            4: {"name": "Step 2-文学大师版", "id": 5, "can_network": False}
        }
        
        # 镜头语言映射（用于视频生成）
        self.camera_movements = {
            "向内": "Dolly In",
            "向外": "Dolly Out",
            "向上": "Tilt Up",
            "向下": "Tilt Down",
            "向左": "Pan Left",
            "向右": "Pan Right",
            "环绕": "Arc",
            "跟随": "Follow"
        }
        
        # 视频生成相关状态
        self.video_ref_waiting = {}
        self.video_waiting = {}
        
        # 创建临时目录用于存储分享图片等
        try:
            self.temp_dir = os.path.join(os.path.dirname(__file__), "temp")
            os.makedirs(self.temp_dir, exist_ok=True)
            logger.info(f"[Yuewen] 临时目录已创建: {self.temp_dir}")
        except Exception as e:
            logger.error(f"[Yuewen] 创建临时目录失败: {e}")
            self.temp_dir = None
        
        # 启用插件
        self.enable = self.config.get('enable', True)
        
        logger.info("[Yuewen] 同步初始化完成")
        
        # 启动异步初始化
        asyncio.create_task(self.async_init())
    
    async def on_enable(self, bot=None):
        """插件启用时调用，按XXXBot框架要求实现"""
        logger.info("[Yuewen] 插件已启用")
        self.enable = True
        if not self.http_session or self.http_session.closed:
            # 如果HTTP会话不存在或已关闭，创建新的会话
            self.http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                connector=aiohttp.TCPConnector(ssl=False)
            )
            # 将HTTP会话传递给LoginHandler
            self.login_handler.set_http_session(self.http_session)
        # 更新配置启用状态
        self.update_config({"enable": True})
        return True
    
    async def on_disable(self):
        """插件禁用时调用，按XXXBot框架要求实现"""
        logger.info("[Yuewen] 插件已禁用")
        self.enable = False
        # 关闭HTTP会话
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            self.http_session = None
        # 更新配置禁用状态
        self.update_config({"enable": False})
        return True
    
    def update_config(self, updates):
        """更新配置并保存到文件
        
        Args:
            updates: 包含要更新的配置键值对的字典
        """
        # 更新内存中的配置
        if isinstance(updates, dict):
            for k, v in updates.items():
                if k == 'image_config' and isinstance(v, dict) and isinstance(self.config.get('image_config'), dict):
                    # 处理嵌套的image_config
                    self.config['image_config'].update(v)
                else:
                    self.config[k] = v
                    
            # 更新相关状态变量
            if 'need_login' in updates:
                self.need_login = updates['need_login']
            if 'oasis_webid' in updates:
                self.oasis_webid = updates['oasis_webid']
            if 'oasis_token' in updates:
                self.oasis_token = updates['oasis_token']
            if 'current_model_id' in updates:
                self.current_model_id = updates['current_model_id']
            if 'network_mode' in updates:
                self.network_mode = updates['network_mode']
            if 'api_version' in updates:
                self.api_version = updates['api_version']
                self.current_base_url = self.base_urls[self.api_version]
            
            # 保存到配置文件
            self._save_config()
            
            logger.debug(f"[Yuewen] 配置已更新: {updates.keys()}")
        else:
            logger.error(f"[Yuewen] 配置更新失败: 不是有效的字典 {type(updates)}")

    def _save_config(self):
        """保存配置到TOML文件"""
        config_path = os.path.join(os.path.dirname(__file__), 'config.toml')
        
        # 保存到TOML（标准格式）
        try:
            import toml
            
            # 构造TOML格式（嵌套结构）
            toml_config = {"yuewen": {k: v for k, v in self.config.items() if k != "image_config"}}
            if "image_config" in self.config:
                toml_config["yuewen"]["image_config"] = self.config.get("image_config", {})
            
            with open(config_path, "w", encoding="utf-8") as f:
                toml.dump(toml_config, f)
            logger.info(f"[Yuewen] 配置已保存到TOML文件: {config_path}")
            return True
        except ImportError:
            logger.warning("[Yuewen] toml库未安装，无法保存TOML配置")
            return False
        except Exception as e:
            logger.error(f"[Yuewen] 保存TOML配置失败: {e}")
            return False
    
    async def async_init(self):
        """异步初始化插件，创建HTTP会话并设置给登录处理器"""
        try:
            # 创建HTTP会话
            self.http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                connector=aiohttp.TCPConnector(ssl=False)
            )
            
            # 将HTTP会话传递给LoginHandler
            if hasattr(self, 'login_handler') and self.login_handler:
                self.login_handler.set_http_session(self.http_session)
                logger.info("[Yuewen] HTTP会话已创建并设置给LoginHandler")
            else:
                logger.error("[Yuewen] LoginHandler未初始化，无法设置HTTP会话")
            
            # 检查登录状态 - _check_login_status_async返回True表示需要登录，False表示已登录
            try:
                need_login = await self._check_login_status_async()
                if need_login:
                    logger.info("[Yuewen] 用户未登录或登录已失效，需要重新登录")
                    self.need_login = True
                    self.update_config({"need_login": True})
                else:
                    logger.info("[Yuewen] 用户已登录，状态有效")
                    self.need_login = False
                    self.update_config({"need_login": False})
            except Exception as e:
                logger.error(f"[Yuewen] 检查登录状态失败: {e}")
                # 如果检查失败但存在令牌，假设令牌有效，避免强制登录
                if self.oasis_token:
                    logger.warning("[Yuewen] 检查登录状态失败，但存在令牌，继续使用现有令牌")
                    self.need_login = False
                    self.update_config({"need_login": False})
                
            logger.info("[Yuewen] 异步初始化完成")
        except Exception as e:
            logger.error(f"[Yuewen] 异步初始化失败: {e}")
    
    def _load_config(self):
        """加载TOML格式配置文件"""
        config_path = os.path.join(os.path.dirname(__file__), 'config.toml')
        
        try:
            # 优先尝试加载TOML配置
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f) # Changed variable name to avoid conflict
                yuewen_config = toml_data.get("yuewen", {})
                
                # 从TOML配置中提取图片配置子项
                image_config = yuewen_config.pop("image_config", {})
                
                # 创建扁平化的配置字典
                self.config = {
                    "enable": yuewen_config.get("enable", True),
                    "need_login": yuewen_config.get("need_login", True),
                    "oasis_webid": yuewen_config.get("oasis_webid"), # Defaults to None if not found
                    "oasis_token": yuewen_config.get("oasis_token"), # Defaults to None if not found
                    "current_model_id": yuewen_config.get("current_model_id", 6),
                    "network_mode": yuewen_config.get("network_mode", True),
                    "trigger_prefix": yuewen_config.get("trigger_prefix", "yw"),
                    "api_version": yuewen_config.get("api_version", "old"),
                    "image_config": {
                        "imgprompt": image_config.get("imgprompt", "解释下图片内容"),
                        "trigger": image_config.get("trigger", "识图")
                    }
                }
                logger.info(f"[Yuewen] 成功加载TOML配置文件: {config_path}")
                
        except FileNotFoundError:
            logger.info(f"[Yuewen] 配置文件 {config_path} 未找到，将创建默认配置文件。")
            self.config = {
                "enable": True,
                "need_login": True,
                "oasis_webid": None,
                "oasis_token": None,
                "current_model_id": 6,
                "network_mode": True,
                "trigger_prefix": "yw",
                "api_version": "old",
                "image_config": {
                    "imgprompt": "解释下图片内容",
                    "trigger": "识图"
                }
            }
            self._save_config() # 创建默认的 config.toml
            
        except tomllib.TOMLDecodeError as e:
            logger.error(f"[Yuewen] TOML配置文件 {config_path} 格式错误: {e}。将使用默认配置并尝试覆盖。")
            self.config = {
                "enable": True,
                "need_login": True,
                "oasis_webid": None,
                "oasis_token": None,
                "current_model_id": 6,
                "network_mode": True,
                "trigger_prefix": "yw",
                "api_version": "old",
                "image_config": {
                    "imgprompt": "解释下图片内容",
                    "trigger": "识图"
                }
            }
            self._save_config() # 尝试保存一个干净的默认配置
                
        except Exception as e:
            logger.error(f"[Yuewen] 加载配置时发生未知错误: {e}。将使用内存中的默认配置。")
            # Fallback to in-memory defaults without saving to avoid loop if save fails
            self.config = {
                "enable": True,
                "need_login": True,
                "oasis_webid": None,
                "oasis_token": None,
                "current_model_id": 6,
                "network_mode": True,
                "trigger_prefix": "yw",
                "api_version": "old",
                "image_config": {
                    "imgprompt": "解释下图片内容",
                    "trigger": "识图"
                }
            }

    def _get_user_id(self, message: dict) -> str:
        """从消息中提取用户ID"""
        from_wxid = message.get("FromWxid", "")
        is_group = message.get("IsGroup", False)
        
        if is_group:
            group_id = message.get("FromWxid", "")
            sender_wxid = message.get("SenderWxid", "")
            return f"{group_id}_{sender_wxid}" if sender_wxid else group_id
        else:
            return from_wxid
            
    async def _check_login_status_async(self):
        """检查登录状态（异步版本）
        @return: True表示需要登录，False表示已登录
        """
        # 如果配置中明确需要登录，直接返回True
        if self.config.get('need_login', True):
            self.need_login = True
            return True
            
        # 检查是否有必要的凭证
        if not self.oasis_webid or not self.oasis_token:
            logger.warning("[Yuewen] 缺少webid或token，需要登录")
            self.need_login = True
            self.update_config({"need_login": True})
            return True
            
        # 尝试刷新令牌验证有效性
        try:
            # 刷新令牌
            if hasattr(self.login_handler, 'refresh_token'):
                token_valid = await self.login_handler.refresh_token()
                # 如果刷新失败但存在令牌，可以继续使用
                if not token_valid and self.oasis_token:
                    logger.warning("[Yuewen] 刷新令牌失败，但存在令牌，继续使用现有令牌")
                    self.need_login = False
                    self.update_config({"need_login": False})
                    return False
                # 如果刷新失败且没有有效令牌，需要登录
                elif not token_valid:
                    logger.warning("[Yuewen] 令牌刷新失败，需要重新登录")
                    self.need_login = True
                    self.update_config({"need_login": True})
                    return True
                # 刷新成功，不需要登录
                else:
                    self.need_login = False
                    self.update_config({"need_login": False})
                    return False
            else:
                logger.error("[Yuewen] login_handler缺少refresh_token方法")
                # 如果没有刷新方法但存在令牌，也可以继续使用
                if self.oasis_token:
                    logger.warning("[Yuewen] 无法刷新令牌，但存在令牌，继续使用现有令牌")
                    self.need_login = False
                    self.update_config({"need_login": False})
                    return False
                else:
                    self.need_login = True
                    self.update_config({"need_login": True})
                    return True
        except Exception as e:
            logger.error(f"[Yuewen] 刷新令牌异常: {e}")
            # 出现异常但存在令牌，可以继续使用
            if self.oasis_token:
                logger.warning("[Yuewen] 刷新令牌异常，但存在令牌，继续使用现有令牌")
                self.need_login = False
                self.update_config({"need_login": False})
                return False
            else:
                self.need_login = True
                self.update_config({"need_login": True})
                return True
        
        # 令牌有效，不需要登录
        return False
        
    async def _initiate_login_async(self, bot, reply_to_wxid, user_id):
        """初始化登录流程（异步版本）"""
        try:
            # 检查是否已有等待验证的用户
            if user_id in self.waiting_for_verification:
                # 清除之前的状态
                self.waiting_for_verification.pop(user_id, None)
            
            # 无论是否有webid都重新注册设备，确保流程完整
            logger.info("[Yuewen] 正在注册设备...")
            await bot.send_text_message(reply_to_wxid, "⏳ 正在注册设备，请稍候...")
            
            # 异步调用登录处理器的注册设备方法
            if not await self.login_handler.register_device():
                await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败，请稍后重试")
                return False
            
            # 从登录处理器获取webid
            self.oasis_webid = self.login_handler.config.get('oasis_webid')
            
            # 成功注册设备后，检查是否有webid
            if not self.oasis_webid:
                await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败: 未获取到webid")
                return False
                
            logger.info(f"[Yuewen] 设备注册成功，webid={self.oasis_webid}")
            await bot.send_text_message(reply_to_wxid, "✅ 设备注册成功，正在初始化登录...")
            
            # 提示用户输入手机号
            await bot.send_text_message(
                reply_to_wxid, 
                "📱 请输入您的11位手机号码\n注意：此手机号将用于接收跃问的验证码"
            )
            
            # 标记此用户正在进行登录操作 - 使用空字符串作为占位符
            self.waiting_for_verification[user_id] = ""
            
            # 记录用户正在等待输入手机号
            self.login_users.add(user_id)
            self.is_login_triggered = True
            
            return True
        except Exception as e:
            logger.error(f"[Yuewen] 初始化登录流程失败: {e}", exc_info=True)
            await bot.send_text_message(reply_to_wxid, f"❌ 初始化登录失败: {str(e)}")
            return False
    
    async def _send_verification_code_async(self, bot, reply_to_wxid, user_id, phone_number):
        """发送验证码到手机（异步版本）"""
        try:
            # 检查手机号格式
            if not phone_number.isdigit() or len(phone_number) != 11:
                await bot.send_text_message(reply_to_wxid, "❌ 请输入有效的11位手机号码")
                return False
                
            await bot.send_text_message(reply_to_wxid, f"⏳ 正在发送验证码，请稍候...")
            
            # 确保有webid - 使用login_handler中的
            if not self.oasis_webid:
                # 更新webid
                self.oasis_webid = self.login_handler.config.get('oasis_webid')
                
                # 如果仍然没有，尝试重新注册设备
                if not self.oasis_webid:
                    logger.info("[Yuewen] 发送验证码前重新注册设备")
                    if not await self.login_handler.register_device():
                        await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败，无法发送验证码")
                        return False
                    
                    # 更新webid
                    self.oasis_webid = self.login_handler.config.get('oasis_webid')
                    
                    # 检查注册后是否有webid
                    if not self.oasis_webid:
                        await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败: 未获取到webid")
                        return False
                        
                    logger.info(f"[Yuewen] 设备注册成功，webid={self.oasis_webid}")
            
            # 使用异步版本发送验证码
            success = await self.login_handler.send_verify_code(phone_number)
            
            if success:
                # 保存手机号，等待后续输入验证码
                self.waiting_for_verification[user_id] = phone_number
                
                # 从登录状态列表移除，表示已完成手机号输入步骤
                if user_id in self.login_users:
                    self.login_users.remove(user_id)
                
                await bot.send_text_message(
                    reply_to_wxid, 
                    "✅ 验证码已发送，请输入收到的4位验证码完成登录"
                )
                return True
            else:
                # 验证码发送失败，清除等待状态
                if user_id in self.waiting_for_verification:
                    self.waiting_for_verification.pop(user_id, None)
                    
                await bot.send_text_message(
                    reply_to_wxid, 
                    f"❌ 验证码发送失败，请检查手机号是否正确或稍后重试"
                )
                return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 验证码发送处理异常: {e}", exc_info=True)
            # 清除等待状态
            if user_id in self.waiting_for_verification:
                self.waiting_for_verification.pop(user_id, None)
                
            await bot.send_text_message(reply_to_wxid, f"❌ 处理失败: {str(e)}")
            return False
    
    async def _verify_login_async(self, bot, reply_to_wxid, user_id, verify_code):
        """验证登录（异步版本）"""
        try:
            # 获取之前保存的手机号
            phone_number = self.waiting_for_verification.get(user_id)
            if not phone_number:
                await bot.send_text_message(reply_to_wxid, "❌ 验证失败：请先发送手机号获取验证码")
                return False
            
            # 向用户发送正在验证的消息
            await bot.send_text_message(reply_to_wxid, "⏳ 正在验证登录，请稍候...")
            
            # 使用登录处理器的异步方法进行登录验证
            if await self.login_handler.sign_in(mobile_num=phone_number, auth_code=verify_code):
                # 清除等待验证状态
                self.waiting_for_verification.pop(user_id, None)
                
                # 同步登录状态到当前插件
                self.need_login = False
                self.oasis_webid = self.login_handler.config.get('oasis_webid')
                self.oasis_token = self.login_handler.config.get('oasis_token')
                
                # 更新配置
                self.update_config({
                    'need_login': False,
                    'oasis_webid': self.oasis_webid,
                    'oasis_token': self.oasis_token
                })
                
                # 创建新会话
                await bot.send_text_message(reply_to_wxid, "✅ 登录成功，正在创建会话...")
                
                # 创建新会话
                if await self.create_chat_async():
                    await bot.send_text_message(reply_to_wxid, "✅ 会话创建成功，可以开始对话了")
                else:
                    await bot.send_text_message(reply_to_wxid, "⚠️ 登录成功，但会话创建失败，请发送'yw新建会话'尝试创建会话")
                
                logger.info("[Yuewen] 用户登录成功并创建会话")
                return True
            else:
                # 验证失败
                await bot.send_text_message(reply_to_wxid, "❌ 验证码错误或已过期，请重新发送'yw登录'进行登录")
                # 清除等待状态
                self.waiting_for_verification.pop(user_id, None)
                return False
            
        except Exception as e:
            logger.error(f"[Yuewen] 验证登录异常: {e}", exc_info=True)
            # 清除等待状态
            self.waiting_for_verification.pop(user_id, None)
            await bot.send_text_message(reply_to_wxid, f"❌ 验证登录出错: {str(e)}")
            return False
    
    async def _handle_commands_async(self, content):
        """处理内置命令（异步版本）"""
        if not content:
            return None
            
        # 打印模型命令
        if content == "打印模型":
            # 构建模型列表 - 无论API版本都显示可用模型
            output = ["可用模型："]
            for num, info in self.models.items():
                status = "（支持联网）" if info.get('can_network', True) else ""
                current = " ← 当前使用" if info['id'] == self.current_model_id else ""
                output.append(f"{num}. {info['name']}{status}{current}")
            return '\n'.join(output)
            
        # 模型切换命令
        if content.startswith("切换模型") or content.startswith("模型") or content.startswith("model"):
            # 如果是新版API，提示用户不支持
            if self.api_version == 'new':
                return "⚠️ 切换模型功能仅支持旧版API，请先发送'yw切换旧版'切换到旧版API"
                
            model_num = None
            # 尝试提取模型编号
            try:
                # 支持 "切换模型1", "切换模型 1", "模型1", "模型 1", "model1", "model 1" 等格式
                cmd_parts = content.replace("切换模型", "").replace("模型", "").replace("model", "").strip()
                if cmd_parts.isdigit():
                    model_num = int(cmd_parts)
            except:
                pass
                
            # 如果没有指定模型或模型无效，显示可用模型列表
            if not model_num or model_num not in self.models:
                models_info = "\n".join([f"{idx}. {model['name']}" for idx, model in self.models.items()])
                return f"可用模型列表：\n{models_info}\n\n使用方法：yw切换模型[编号] 进行切换"
                
            # 切换模型
            selected_model = self.models.get(model_num, {})
            self.current_model_id = selected_model["id"]
            self.update_config({"current_model_id": self.current_model_id})
            
            # 如果是deepseek r1模型(id=6)，强制开启联网模式
            if selected_model.get('id') == 6:  # deepseek r1模型ID
                self.network_mode = True
                self.update_config({"network_mode": True})
                # 同步启用深度思考模式
                await self._enable_deep_thinking_async()
            
            # 如果该模型不支持联网但是当前开启了联网，关闭联网
            elif not selected_model.get("can_network", True) and self.network_mode:
                self.network_mode = False
                self.update_config({"network_mode": False})
                
            # 创建新会话
            self.current_chat_id = None
            self.current_chat_session_id = None
            if not await self.create_chat_async():
                return f"⚠️ 已切换到 [{selected_model.get('name', '未知模型')}]，但新会话创建失败，请手动发送'yw新建会话'"
                
            # 同步服务器状态
            await self._sync_server_state_async()
            
            # 根据模型联网支持情况返回不同消息
            if not selected_model.get("can_network", True) and self.network_mode:
                return f"✅ 已切换到 [{selected_model.get('name', '未知模型')}]，该模型不支持联网，已自动关闭联网功能"
            else:
                return f"✅ 已切换至 [{selected_model.get('name', '未知模型')}]"
        
        # 联网模式命令
        elif content in ["联网", "开启联网", "打开联网"]:
            # 检查当前模型是否支持联网
            current_model_info = None
            for model_num, model_info in self.models.items():
                if model_info.get("id") == self.current_model_id:
                    current_model_info = model_info
                    break
                    
            if current_model_info and not current_model_info.get("can_network", True):
                return f"❌ 当前模型 [{current_model_info.get('name', '未知模型')}] 不支持联网，请先切换到支持联网的模型"
                
            # 如果已经是联网模式，提示用户
            if self.network_mode:
                return "ℹ️ 联网模式已经开启"
                
            # 开启联网模式
            self.network_mode = True
            self.update_config({"network_mode": True})
            
            # 尝试同步服务器状态
            try:
                await self._sync_server_state_async()
            except Exception as e:
                logger.error(f"[Yuewen] 同步网络状态失败: {e}")
                
            return "✅ 已开启联网模式"
            
        # 关闭联网模式命令
        elif content in ["不联网", "关闭联网", "禁用联网"]:
            # 如果已经是非联网模式，提示用户
            if not self.network_mode:
                return "ℹ️ 联网模式已经关闭"
                
            # 关闭联网模式
            self.network_mode = False
            self.update_config({"network_mode": False})
            
            # 尝试同步服务器状态
            try:
                await self._sync_server_state_async()
            except Exception as e:
                logger.error(f"[Yuewen] 同步网络状态失败: {e}")
                
            return "✅ 已关闭联网模式"
            
        # API版本切换命令
        elif content in ["切换旧版", "使用旧版", "旧版API"]:
            if self.api_version == 'old':
                return "ℹ️ 已经是旧版API模式"
                
            # 切换到旧版API
            self.api_version = 'old'
            self.current_base_url = self.base_urls['old']
            self.update_config({"api_version": "old"})
            
            # 清除会话
            self.current_chat_id = None
            self.current_chat_session_id = None
            
            return "✅ 已切换到旧版API模式，将在下一次对话创建新会话"
            
        elif content in ["切换新版", "使用新版", "新版API"]:
            if self.api_version == 'new':
                return "ℹ️ 已经是新版API模式"
                
            # 切换到新版API
            self.api_version = 'new'
            self.current_base_url = self.base_urls['new']
            self.update_config({"api_version": "new"})
            
            # 清除会话
            self.current_chat_id = None
            self.current_chat_session_id = None
            
            return "✅ 已切换到新版API模式，将在下一次对话创建新会话"
            
        # 分享命令
        elif content in ["分享", "share", "生成图片"]:
            # 检查是否支持分享功能
            if self.api_version == 'new':
                return "⚠️ 分享功能仅支持旧版API，请先发送'yw切换旧版'切换到旧版API"
                
            # 检查是否有最近的消息记录
            if not hasattr(self, 'last_message') or not self.last_message:
                return "⚠️ 没有可分享的消息记录，请先发送一条消息"
                
            # 检查最近消息是否超时
            current_time = time.time()
            if current_time - self.last_message.get('last_time', 0) > 180:  # 3分钟超时
                return "⚠️ 分享超时，请重新发送消息后再尝试分享"
                
            return "🔄 正在生成分享图片，请稍候..."
        
        # 深度思考模式
        elif content in ["深度思考", "enable_deep_thinking", "思考模式"]:
            if self.api_version != 'old':
                return "⚠️ 深度思考模式仅支持旧版API，请先发送'yw切换旧版'切换到旧版API"
        
            # 调用深度思考设置方法
            if await self._enable_deep_thinking_async():
                return "✅ 已开启深度思考模式"
            else:
                return "❌ 开启深度思考模式失败，请重试"
        
        # 帮助命令
        elif content in ["帮助", "help", "指令", "命令"]:
            current_api_version = "新版API" if self.api_version == 'new' else "旧版API"
            help_text = f"""📚 跃问AI助手指令 (当前: {current_api_version})：

【通用指令】
1. yw [问题] - 向AI提问
2. yw登录 - 重新登录账号
3. yw联网/不联网 - 开启/关闭联网功能
4. yw新建会话 - 开始新的对话
5. yw切换旧版/新版 - 切换API版本
6. yw识图 [描述] - 发送图片让AI分析

【仅限旧版API功能】
7. yw切换模型[编号] - 切换AI模型 (当前：{
    next((f"{idx}.{model['name']}" for idx, model in self.models.items() 
         if model['id'] == self.current_model_id), "未知")})
8. yw打印模型 - 显示所有可用模型
9. yw分享 - 生成对话分享图片
10. yw深度思考 - 启用思考模式
11. yw识图N [描述] - 分析N张图片
12. yw多图 [描述] - 分析多张图片

当前状态：联网{" ✓" if self.network_mode else " ✗"}
"""
            return help_text
            
        # 未匹配任何命令
        return None

    def _update_headers(self):
        """根据当前 API 版本更新通用请求头"""
        headers = self.base_headers.copy()
        # 使用 self.current_base_url 代替硬编码的 URL
        base_url = self.current_base_url
        token = self.oasis_token or self.config.get('oasis_token', '')
        webid = self.oasis_webid or self.config.get('oasis_webid', '')

        # 基本 Cookie 组件
        cookie_parts = []
        if webid:
             cookie_parts.append(f"Oasis-Webid={webid}")
        # 注意：新 API 可能需要不同的或额外的 Cookie
        if token:
             cookie_parts.append(f"Oasis-Token={token}")

        cookie_string = "; ".join(cookie_parts)

        # 两个版本通用的 Header
        common_headers = {
            'Cookie': cookie_string,
            'oasis-webid': webid,
            'origin': base_url, # 使用当前版本的 base_url
            'referer': f'{base_url}/', # Referer 可能需要根据具体端点调整
            'oasis-appid': '10200',
            'oasis-platform': 'web',
            'oasis-language': 'zh', # 新增，新版可能需要
            'connect-protocol-version': '1', # 两个版本似乎都需要
            'canary': 'false', # 两个版本似乎都需要
            'priority': 'u=1, i', # 两个版本似乎都需要
            'x-waf-client-type': 'fetch_sdk' # 两个版本似乎都需要
        }
        headers.update(common_headers)

        # --- 旧版 API 特有 Headers ---
        if self.api_version == 'old':
            logger.debug("[Yuewen] Adding Old API specific headers (RUM trace).")
            headers.update({
                 'x-rum-traceparent': self._generate_traceparent(),
                 'x-rum-tracestate': self._generate_tracestate(),
                 # 可能还有 'oasis-mode': '2' 等旧版特有的，根据需要添加回
                 'oasis-mode': '2',
            })
            # 确保移除新版可能添加的不兼容 header (如果 common_headers 中有的话)

        # --- 新版 API 特有 Headers ---
        elif self.api_version == 'new':
             logger.debug("[Yuewen] Adding New API specific headers (if any).")
             # 添加新版 API 特有的 Headers，例如 'Sec-Fetch-Dest': 'empty' 等
             # headers.update({ 'some-new-header': 'new-value'})
             # 移除旧版特有的 header
             headers.pop('x-rum-traceparent', None)
             headers.pop('x-rum-tracestate', None)
             headers.pop('oasis-mode', None) # 假设新版不需要

        return headers
    
    def _generate_traceparent(self):
        """生成跟踪父ID - 跃问服务器请求需要"""
        trace_id = ''.join(random.choices('0123456789abcdef', k=32))
        span_id = ''.join(random.choices('0123456789abcdef', k=16))
        return f"00-{trace_id}-{span_id}-01"
    
    def _generate_tracestate(self):
        """生成跟踪状态 - 跃问服务器请求需要"""
        return f"yuewen@rsid={random.getrandbits(64):016x}"

    async def create_chat_async(self):
        """创建新聊天会话（异步版本）"""
        # 检查是否需要登录
        if self.need_login or not self.oasis_webid or not self.oasis_token:
            logger.warning("[Yuewen] 未检测到有效登录凭证，请先登录")
            return False

        try:
            # 刷新token确保有效
            if not await self.login_handler.refresh_token():
                logger.error("[Yuewen] 刷新令牌失败，无法创建会话")
                return False
            
            # 根据API版本调用不同的会话创建函数
            if self.api_version == 'new':
                success = await self._create_chat_session_new_async()
                if success:
                    logger.info(f"[Yuewen] 新会话创建成功: {self.current_chat_session_id}")
                    self.last_active_time = time.time()
                    return True
                else:
                    logger.error("[Yuewen] 新会话创建失败")
                    return False
            else:
                success = await self._create_chat_old_async()
                if success:
                    logger.info(f"[Yuewen] 旧会话创建成功: {self.current_chat_id}")
                    self.last_active_time = time.time()
                    return True
                else:
                    logger.error("[Yuewen] 旧会话创建失败")
                    return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 创建会话失败: {e}", exc_info=True)
            return False

    async def _create_chat_old_async(self):
        """创建旧版API会话（异步版本）"""
        try:
            logger.info("[Yuewen] 尝试创建旧版API会话...")
            
            url = f"{self.current_base_url}/api/proto.chat.v1.ChatService/CreateChat"
            
            # 构建请求头 - 确保包含关键参数
            headers = self._update_headers()
            
            logger.debug(f"[Yuewen] 创建旧会话请求: URL={url}, headers={headers}")
            
            # 添加重试机制
            for retry in range(2):
                try:
                    # 异步发送请求
                    async with self.http_session.post(
                        url, 
                        headers=headers,
                        json={"chatName": "新会话"},
                        timeout=30
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            logger.debug(f"[Yuewen] 创建旧会话响应: {result}")
                            
                            # 从响应中提取chatId
                            if 'id' in result:
                                self.current_chat_id = result['id']
                                
                                # 保存到配置
                                self.update_config({
                                    'current_chat_id': self.current_chat_id
                                })
                                
                                logger.info(f"[Yuewen] 旧版API创建会话成功: {self.current_chat_id}")
                                
                                # 同步服务器状态 (设置模型和联网)
                                await self._sync_server_state_async()
                                
                                return True
                            elif 'chatId' in result:  # 尝试另一种可能的字段名
                                self.current_chat_id = result['chatId']
                                
                                # 保存到配置
                                self.update_config({
                                    'current_chat_id': self.current_chat_id
                                })
                                
                                logger.info(f"[Yuewen] 旧版API创建会话成功: {self.current_chat_id}")
                                
                                # 同步服务器状态 (设置模型和联网)
                                await self._sync_server_state_async()
                                
                                return True
                            else:
                                logger.error(f"[Yuewen] 旧版API创建会话失败: 响应缺少id字段 - {result}")
                                # 如果是第一次重试，继续尝试
                                if retry == 0:
                                    logger.info("[Yuewen] 尝试刷新令牌并重试创建会话...")
                                    if await self.login_handler.refresh_token():
                                        # 更新header中的Cookie
                                        headers = self._update_headers()
                                        continue
                                return False
                                
                        # 处理其他错误响应
                        error_text = await response.text()
                        logger.error(f"[Yuewen] 旧版API创建会话失败: {response.status}, {error_text}")
                        
                        # 如果是第一次重试，继续尝试
                        if retry == 0:
                            logger.info("[Yuewen] 尝试重试创建会话...")
                            if await self.login_handler.refresh_token():
                                # 更新header
                                headers = self._update_headers()
                                continue
                        
                        return False
                        
                except Exception as e:
                    logger.error(f"[Yuewen] 创建会话请求异常: {e}", exc_info=True)
                    # 如果是第一次重试，继续尝试
                    if retry == 0:
                        logger.info("[Yuewen] 尝试重试创建会话...")
                        if await self.login_handler.refresh_token():
                            # 更新header
                            headers = self._update_headers()
                            continue
                    return False
                    
            return False
            
        except Exception as e:
            logger.error(f"[Yuewen] 旧版API创建会话异常: {e}", exc_info=True)
            return False
    
    async def _create_chat_session_new_async(self):
        """创建新版API (stepfun.com) 会话（异步版本）"""
        logger.debug("[Yuewen] 调用_create_chat_session_new_async")
        
        for retry in range(2):
            # 获取适配新版的headers
            headers = self._update_headers()
            headers['Content-Type'] = 'application/json'
            
            # 新版创建会话的端点
            url = f'{self.current_base_url}/api/agent/capy.agent.v1.AgentService/CreateChatSession'
            logger.info(f"[Yuewen][New API] 尝试创建会话: {url}")
            
            try:
                # 异步发送请求
                async with self.http_session.post(
                    url,
                    headers=headers,
                    json={}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        # 提取 chatSessionId
                        session_data = data.get('chatSession')
                        if session_data and session_data.get('chatSessionId'):
                            self.current_chat_session_id = session_data['chatSessionId']
                            self.current_chat_id = None # 清空旧版 ID
                            self.last_active_time = time.time()
                            logger.info(f"[Yuewen][New API] 新建会话成功 SessionID: {self.current_chat_session_id}")
                            return True
                        else:
                            logger.error(f"[Yuewen][New API] 创建会话失败: 响应中缺少 chatSessionId - {await response.text()}")
                            return False
                    elif response.status == 401 and retry == 0:
                        if await self.login_handler.refresh_token():
                            continue
                        else:
                            logger.error("[Yuewen][New API] Token刷新失败")
                            return False
                            
                    error_text = await response.text()
                    logger.error(f"[Yuewen][New API] 创建会话失败: HTTP {response.status} - {error_text}")
                    if retry < 1: 
                        continue
                    return False
                    
            except Exception as e:
                if retry == 0:
                    if await self.login_handler.refresh_token():
                        continue
                logger.error(f"[Yuewen][New API] 创建会话失败: {str(e)}", exc_info=True)
                if retry < 1: 
                    continue
                return False
                
        return False
        
    async def _sync_server_state_async(self):
        """同步服务器状态(设置模型和网络搜索首选项)（异步版本）"""
        try:
            # 仅旧版API需要显式同步
            if self.api_version != 'old':
                return True
                
            # 确保有会话ID
            if not self.current_chat_id:
                logger.warning("[Yuewen] 同步服务器状态失败: 没有有效的会话ID")
                return False
                
            # 设置模型首选项
            model_success = False
            for model_num, model_info in self.models.items():
                if model_info.get("id") == self.current_model_id:
                    logger.info(f"[Yuewen] 同步模型设置: {model_info.get('name', '未知模型')} (ID: {self.current_model_id})")
                    model_success = await self._call_set_model_async(self.current_model_id)
                    break
            
            if not model_success:
                logger.warning(f"[Yuewen] 同步模型设置失败: {self.current_model_id}")
            
            # 设置网络搜索首选项
            network_success = await self._enable_search_async(self.network_mode)
            if not network_success:
                logger.warning(f"[Yuewen] 同步网络搜索设置失败: {self.network_mode}")
            
            return model_success and network_success
            
        except Exception as e:
            logger.error(f"[Yuewen] 同步服务器状态失败: {e}", exc_info=True)
            return False
    
    async def _call_set_model_async(self, model_id):
        """设置模型ID（异步版本）"""
        try:
            # 仅旧版API支持此操作
            if self.api_version != 'old':
                return False
                
            # 设置模型URL
            url = f"{self.current_base_url}/api/proto.user.v1.UserService/SetModelInUse"
            
            # 获取包含Cookie的headers
            headers = self._update_headers()
            headers.update({
                'Content-Type': 'application/json',
                'oasis-mode': '1',  # 使用mode 1，与创建会话保持一致
                'referer': f'{self.current_base_url}/chats/{self.current_chat_id}'
            })
            
            # 发送异步请求
            for retry in range(2):
                try:
                    async with self.http_session.post(
                        url,
                        headers=headers,
                        json={"modelId": model_id}
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get("result") == "RESULT_CODE_SUCCESS":
                                logger.info(f"[Yuewen] 模型设置成功: {model_id}")
                                return True
                                
                        # 如果是401错误，尝试刷新令牌并重试
                        elif response.status == 401 and retry == 0:
                            logger.warning("[Yuewen] 设置模型失败: 令牌无效，尝试刷新...")
                            if await self.login_handler.refresh_token():
                                # 更新headers (包含新的token)
                                headers = self._update_headers()
                                headers.update({
                                    'Content-Type': 'application/json',
                                    'oasis-mode': '1',
                                    'referer': f'{self.current_base_url}/chats/{self.current_chat_id}'
                                })
                                continue
                                
                        error_text = await response.text()
                        logger.error(f"[Yuewen] 设置模型失败: {response.status}, {error_text}")
                        return False
                        
                except Exception as e:
                    logger.error(f"[Yuewen] 设置模型请求异常: {e}", exc_info=True)
                    return False
                    
            return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 设置模型异常: {e}", exc_info=True)
            return False
    
    async def _enable_search_async(self, enable=True):
        """设置网络搜索功能状态（异步版本）"""
        try:
            # 仅旧版API支持此操作
            if self.config.get('api_version') != 'old':
                return False
                
            # 设置模型URL
            url = f"{self.current_base_url}/api/proto.user.v1.UserService/EnableSearch"
            
            # 获取包含Cookie的headers
            headers = self._update_headers()
            headers.update({
                'Content-Type': 'application/json',
                'oasis-mode': '1',  # 使用mode 1，与创建会话保持一致
                'referer': f'{self.current_base_url}/chats/{self.current_chat_id}'
            })
            
            # 发送异步请求
            for retry in range(2):
                try:
                    async with self.http_session.post(
                        url,
                        headers=headers,
                        json={"enable": enable}
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get("result") == "RESULT_CODE_SUCCESS":
                                logger.info(f"[Yuewen] 网络搜索设置成功: {enable}")
                                return True
                                
                        # 如果是401错误，尝试刷新令牌并重试
                        elif response.status == 401 and retry == 0:
                            logger.warning("[Yuewen] 设置网络搜索失败: 令牌无效，尝试刷新...")
                            if await self.login_handler.refresh_token():
                                # 更新headers (包含新的token)
                                headers = self._update_headers()
                                headers.update({
                                    'Content-Type': 'application/json',
                                    'oasis-mode': '1',
                                    'referer': f'{self.current_base_url}/chats/{self.current_chat_id}'
                                })
                                continue
                                
                        error_text = await response.text()
                        logger.error(f"[Yuewen] 设置网络搜索失败: {response.status}, {error_text}")
                        return False
                        
                except Exception as e:
                    logger.error(f"[Yuewen] 设置网络搜索请求异常: {e}", exc_info=True)
                    return False
                    
            return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 设置网络搜索异常: {e}", exc_info=True)
            return False

    # ======== 消息发送与处理 ========
    async def send_message_async(self, content):
        """发送消息到跃问AI并返回响应（异步版本）"""
        try:
            current_time = time.time()
            
            # 实现会话超时机制
            # 如果距离上次活动超过180秒(3分钟)，则重新创建会话
            session_timeout = 180  # 3分钟超时
            is_session_expired = self.last_active_time > 0 and (current_time - self.last_active_time) > session_timeout
            
            if is_session_expired:
                logger.info(f"[Yuewen] 会话超时({session_timeout}秒)，重新创建会话")
                # 重置会话信息
                self.current_chat_id = None
                self.current_chat_session_id = None
            
            # 检查是否有有效会话，没有则创建
            needs_new_session = False
            if self.api_version == 'new':
                needs_new_session = not self.current_chat_session_id
            else:
                needs_new_session = not self.current_chat_id
                
            if needs_new_session:
                logger.info("[Yuewen] 没有活动会话，正在创建新会话")
                for retry in range(2):
                    if await self.create_chat_async():
                        logger.info("[Yuewen] 会话创建成功")
                        break
                    elif retry == 0:
                        logger.warning("[Yuewen] 第一次创建会话失败，正在重试...")
                        # 等待短暂时间后重试
                        await asyncio.sleep(1)
                    else:
                        logger.error("[Yuewen] 创建会话失败")
                        return "创建会话失败，请尝试发送'yw新建会话'或检查网络连接"
            
            # 再次检查会话是否有效
            if (self.api_version == 'new' and not self.current_chat_session_id) or \
               (self.api_version == 'old' and not self.current_chat_id):
                return "无效的会话ID，请尝试发送'yw新建会话'创建新会话"
            
            # 更新最后活动时间
            self.last_active_time = current_time
            
            # 刷新token
            if not await self.login_handler.refresh_token():
                logger.warning("[Yuewen] 刷新令牌失败，但仍尝试发送消息")
            
            # 根据API版本发送消息
            if self.api_version == 'new':
                response = await self._send_message_new_async(content)
            else:
                response = await self._send_message_old_async(content)
            
            return response
        except Exception as e:
            logger.error(f"[Yuewen] 发送消息失败: {e}", exc_info=True)
            return f"发送消息失败: {str(e)}"
    
    async def _send_message_old_async(self, content, attachments=None):
        """发送消息到AI (旧版API)（异步版本）"""
        if not self.current_chat_id:
            logger.warning("[Yuewen] 未找到有效会话ID，尝试创建新会话...")
            if not await self._create_chat_old_async():
                logger.error("[Yuewen] 无法创建会话，无法发送消息")
                return None
                
        try:
            # 设置URL
            url = f"{self.current_base_url}/api/proto.chat.v1.ChatMessageService/SendMessageStream"
            
            # 构建请求包
            packet = self._construct_protocol_packet(content, attachments)
            
            # 获取包含Cookie的headers
            headers = self._update_headers()
            headers.update({
                'content-type': 'application/connect+json',
                'connect-protocol-version': '1'
            })
            
            # 发送异步请求
            async with self.http_session.post(
                url, 
                data=packet, 
                headers=headers, 
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status != 200:
                    # 处理错误响应
                    error_text = await response.text()
                    error_result = await self._handle_error_async(response, error_text)
                    return error_result
                    
                # 解析响应并返回文本
                start_time = time.time()
                
                # 检查响应中是否包含用户消息ID
                try:
                    # 尝试从响应或请求数据中提取用户消息ID
                    first_chunk = await response.content.readany()
                    if first_chunk:
                        # 尝试解析第一个chunk以获取消息ID
                        chunk_str = first_chunk.decode('utf-8', errors='ignore')
                        
                        # 使用正则表达式查找messageId
                        user_msg_match = re.search(r'"parentMessageId":"([^"]+)"', chunk_str)
                        if user_msg_match:
                            self.last_user_message_id = user_msg_match.group(1)
                            logger.debug(f"[Yuewen] 提取到用户消息ID: {self.last_user_message_id}")
                        
                        # 将数据放回响应流以供后续处理
                        response.content._buffer.appendleft(first_chunk)
                except Exception as e:
                    logger.error(f"[Yuewen] 提取用户消息ID时出错: {e}")
                
                # 使用旧版API专用的响应解析方法处理流式响应
                return await self._parse_stream_response_old_async(response, start_time)
        
        except Exception as e:
            logger.error(f"[Yuewen] 发送消息请求异常: {e}", exc_info=True)
            return f"发送消息请求异常: {str(e)}"
    
    async def _send_message_new_async(self, content, attachments=None):
        """发送消息到AI (新版API)（异步版本）"""
        # 重置图片直接发送标记
        self.image_directly_sent = False
        
        if not self.current_chat_session_id:
            logger.warning("[Yuewen] 未找到有效会话ID，尝试创建新会话...")
            if not await self._create_chat_session_new_async():
                logger.error("[Yuewen] 无法创建会话，无法发送消息")
                return None
        
        # 使用预防性令牌验证
        await self._ensure_token_valid_async()
        
        # 使用原始项目中确认有效的API端点
        url = f"{self.current_base_url}/api/agent/capy.agent.v1.AgentService/ChatStream"
        logger.debug(f"[Yuewen] 使用新版API发送消息: {url}")
        
        # 获取包含Cookie的headers
        headers = self._update_headers()
        
        # 确保headers完全匹配curl命令格式，精确对应curl
        headers.update({
            'accept': '*/*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'content-type': 'application/connect+json',
            'canary': 'false',
            'connect-protocol-version': '1',
            'priority': 'u=1, i',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'x-waf-client-type': 'fetch_sdk'
        })
        
        # 如果有attachments，添加对应的引用记录
        has_attachments = attachments and len(attachments) > 0
        if has_attachments:
            logger.debug(f"[Yuewen] 消息包含 {len(attachments)} 个图片附件")
        
        # 构建请求数据
        data = self._construct_protocol_packet_new(content, attachments)
        if not data:
            logger.error("[Yuewen] 构造请求数据失败")
            return None
            
        logger.debug(f"[Yuewen] 新版API请求包构造成功，长度: {len(data)}")
        
        try:
            # 发送异步请求获取响应
            async with self.http_session.post(
                url, 
                headers=headers,
                data=data,  # 使用data参数传递二进制数据，而不是json
                timeout=120
            ) as response:
                if response.status == 200:
                    start_time = time.time()
                    result_text = await self._parse_response_new_async(response, start_time)
                    return result_text
                else:
                    # 处理错误响应
                    error_text = await response.text()
                    error_msg = await self._handle_error_async(response, error_text)
                    logger.error(f"[Yuewen] 发送消息失败: {error_msg}, HTTP状态码: {response.status}")
                    # 记录详细的错误信息
                    logger.debug(f"[Yuewen] 请求URL: {url}")
                    logger.debug(f"[Yuewen] 请求数据长度: {len(data)}")
                    logger.debug(f"[Yuewen] 响应内容: {error_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"[Yuewen] 发送消息异常: {e}", exc_info=True)
            return None
    
    def _construct_protocol_packet(self, message, attachments=None):
        """构造旧版API的协议包"""
        if not self.current_chat_id:
            logger.error("[Yuewen] 旧版API构造协议包缺少chatId")
            return None

        # 按照原始yuewen.py构造payload
        payload = {
            "chatId": self.current_chat_id,
            "messageInfo": {
                "text": message,
                "author": {"role": "user"}
            },
            "messageMode": "SEND_MESSAGE",
            "modelId": self.current_model_id  # 旧API使用modelId
        }
        
        # 添加附件支持
        if attachments:
            payload["messageInfo"]["attachments"] = attachments
        
        try:
            # 转换为JSON字符串
            json_str = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
            encoded = json_str.encode('utf-8')
            
            # 旧版协议: Flag (0x00) + Length (big-endian 4 bytes) + JSON
            protocol_header = struct.pack('>BI', 0, len(encoded))
            return protocol_header + encoded
            
        except Exception as e:
            logger.error(f"[Yuewen] 构造协议包失败: {e}")
            return None
    
    def _construct_protocol_packet_new(self, content, attachments=None):
        """构造新版API的协议包"""
        logger.debug(f"[Yuewen] 构造新版API请求包，会话ID: {self.current_chat_session_id}")
        
        if not self.current_chat_session_id:
            logger.error("[Yuewen] 无效的会话ID")
            return None
        
        # 严格按照curl命令格式构造请求体
        payload = {
            "message": {
                "chatSessionId": self.current_chat_session_id,
                "content": {
                    "userMessage": {
                        "qa": {
                            "content": content # 发送纯文本内容
                        }
                    }
                }
            },
            "config": {
                # 新版 API 使用模型名称字符串
                "model": "deepseek-r1", 
                "enableReasoning": True, 
                "enableSearch": self.network_mode
            }
        }
        
        # 如果有附件 (图片)，添加到 payload，严格按照curl格式
        if attachments:
            # 确保attachments是一个列表
            if not isinstance(attachments, list):
                logger.error(f"[Yuewen] 无效的附件格式: {attachments}")
                return None
                
            # 确保 qa 存在
            if 'qa' not in payload['message']['content']['userMessage']:
                payload['message']['content']['userMessage']['qa'] = {}
            
            # 添加到qa.attachments，完全按照curl格式
            payload['message']['content']['userMessage']['qa']['attachments'] = attachments
            
            # 如果附件存在但文本内容为空，确保 content 字段存在
            if not payload['message']['content']['userMessage']['qa'].get('content'):
                payload['message']['content']['userMessage']['qa']['content'] = ""
                
            # 记录调试信息
            logger.debug(f"[Yuewen] 添加了 {len(attachments)} 个附件到请求")
        
        try:
            # 为调试记录最终的JSON
            try:
                debug_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
                if len(debug_json) < 1000:  # 限制日志大小
                    logger.debug(f"[Yuewen] 最终请求JSON: {debug_json}")
                else:
                    logger.debug(f"[Yuewen] 最终请求JSON长度: {len(debug_json)} (太长不记录完整内容)")
            except:
                pass
            
            # Connect 协议: Flag (0x00) + Length (big-endian 4 bytes) + JSON
            json_str = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
            encoded_json = json_str.encode('utf-8')
            length = len(encoded_json)
            
            # 使用与原始代码一致的格式：大端序, flag=0
            prefix = struct.pack('>BI', 0, length)
            framed_data = prefix + encoded_json
            
            logger.debug(f"[Yuewen] 新版API请求包构造成功，长度: {len(framed_data)}")
            return framed_data
            
        except Exception as e:
            logger.error(f"[Yuewen] 构造请求包异常: {e}")
            return None
    
    async def _parse_stream_response_async(self, response, start_time):
        """解析流式响应并返回结果（异步版本）"""
        try:
            # 初始化变量，用于跟踪响应状态
            message_id = None
            creation_id = None
            is_searching = False
            search_results = []
            final_text = ""
            chunk_texts = []
            received_chunk_count = 0
            has_finish_chunk = False
            
            # 使用正则表达式模式匹配消息ID
            msg_id_pattern = re.compile(r'"messageId":"([^"]+)"')
            
            # 记录当前处理的message开始时间
            process_start_time = time.time()
            
            async for line in response.content:
                line = line.decode('utf-8').strip()
                
                if not line:
                    continue
                    
                # 移除行首的length前缀
                if line[0].isdigit():
                    prefix_end = line.find('{')
                    if prefix_end != -1:
                        line = line[prefix_end:]
                    else:
                        # 如果没有找到JSON开始标记，跳过这一行
                        continue
                
                try:
                    data = json.loads(line) if line and line[0] == '{' else {}
                    
                    # 提取消息ID
                    if not message_id and line.find('messageId') != -1:
                        match = msg_id_pattern.search(line)
                        if match:
                            message_id = match.group(1)
                            # 保存bot回复的消息ID，用于后续分享功能
                            self.last_bot_message_id = message_id
                            logger.debug(f"[Yuewen] 提取到bot消息ID: {message_id}")
                    
                    # 处理搜索信息
                    if 'search' in data:
                        search_data = data.get('search', {})
                        if search_data.get('searching') is True:
                            is_searching = True
                        elif 'results' in search_data:
                            search_results.extend(search_data.get('results', []))
                    
                    # 处理创建ID (用于图片生成)
                    if 'creationId' in data:
                        creation_id = data.get('creationId')
                        
                    # 处理文本内容
                    if 'text' in data:
                        text_chunk = data.get('text', '')
                        if text_chunk:
                            chunk_texts.append(text_chunk)
                            received_chunk_count += 1
                    
                    # 处理结束标志
                    if 'done' in data and data['done']:
                        has_finish_chunk = True
                        logger.debug("[Yuewen] 收到流式响应结束标志")
                    
                except json.JSONDecodeError:
                    # 不是有效的JSON，可能是前缀或其他数据
                    continue
                except Exception as chunk_e:
                    logger.error(f"[Yuewen] 处理响应块异常: {chunk_e}")
                    continue
            
            # 合并所有文本块
            final_text = ''.join(chunk_texts)
            
            # 处理搜索结果
            search_info = None
            if is_searching and search_results:
                search_info = {
                    'results': search_results
                }
            
            # 记录最后一次交互的消息信息，用于分享功能
            if message_id:
                # 记录这次交互的信息（用于分享功能）
                if not hasattr(self, 'last_message'):
                    self.last_message = {}
                
                # 更新消息列表 - 确保格式符合分享API要求
                if not 'messages' in self.last_message:
                    self.last_message['messages'] = []
                
                # 清除旧的消息并添加新的消息
                self.last_message['messages'] = []
                
                # 添加用户消息（如果有）
                if hasattr(self, 'last_user_message_id') and self.last_user_message_id:
                    self.last_message['messages'].append({
                        "messageId": self.last_user_message_id,
                        "messageIndex": 1
                    })
                
                # 添加Bot消息
                self.last_message['messages'].append({
                    "messageId": message_id,
                    "messageIndex": 2 if self.last_user_message_id else 1
                })
                
                # 记录其他必要信息
                self.last_message['chat_id'] = self.current_chat_id
                self.last_message['last_time'] = time.time()
            
            # 计算总处理时间
            process_time = time.time() - process_start_time
            logger.debug(f"[Yuewen] 流式响应处理完成，共接收 {received_chunk_count} 个文本块，处理耗时 {process_time:.2f} 秒")
            
            # 如果没有获取到任何文本，检查是否有错误
            if not final_text and not creation_id:
                logger.warning("[Yuewen] 未能从流式响应中获取到文本或创建ID")
                return None, None, None
            
            # 返回处理后的结果
            return final_text, search_info, creation_id
            
        except Exception as e:
            logger.error(f"[Yuewen] 解析流式响应异常: {e}", exc_info=True)
            return None, None, None
    
    async def _parse_response_new_async(self, response, start_time=None):
        """解析新版API的响应（异步版本）"""
        if start_time is None:
            start_time = time.time()
        
        session_id = self.current_chat_session_id
        logger.debug(f"[Yuewen][New API] 开始解析响应，会话ID: {session_id}")
        
        content_type = response.headers.get('Content-Type', '')
        logger.debug(f"[Yuewen][New API] 响应Content-Type: {content_type}")
        
        result_text = ""
        buffer = b""
        has_received_content = False
        has_sent_partial_text = False  # 添加变量初始化，用于跟踪是否已发送部分文本
        message_done = False
        image_analysis_result = None
        
        try:  # Outer try (L2277)
            async for chunk in response.content.iter_any():
                if not chunk:
                    continue
                buffer += chunk
                
                while buffer:
                    if len(buffer) < 5:
                        break
                    
                    msg_type = buffer[0]
                    length = int.from_bytes(buffer[1:5], byteorder='big')
                    
                    if len(buffer) < 5 + length:
                        break
                    
                    frame_data = buffer[5:5+length]
                    buffer = buffer[5+length:]
                    
                    if length > 0:
                        try:  # Inner try
                            frame_json = json.loads(frame_data.decode('utf-8'))
                            if 'data' in frame_json:
                                event_data = frame_json.get('data', {}).get('event', {})
                                event_type = list(event_data.keys())[0] if event_data else "empty"
                                
                                if 'textEvent' in event_data:
                                    text = event_data['textEvent'].get('text', '')
                                    if text:
                                        result_text += text
                                        has_received_content = True
                                        # 仅在调试级别输出，减少日志量
                                        if text and len(text) > 20:
                                            logger.debug(f"[Yuewen][New API] 收到文本: {text[:20]}...")
                                elif 'reasoningEvent' in event_data:
                                    # 不显示思考过程，跳过reasoningEvent
                                    continue
                                elif 'pipelineEvent' in event_data:
                                    pipeline_data = event_data['pipelineEvent']
                                    if 'outputs' in pipeline_data:
                                        outputs = pipeline_data['outputs']
                                        for output_item in outputs:  # Renamed output to output_item to avoid conflict
                                            if 'text' in output_item:
                                                text_content = output_item.get('text', '')
                                                if text_content and text_content.strip():
                                                    result_text += text_content
                                                    has_received_content = True
                                                    # 降级为trace级别或注释掉
                                                    # logger.debug(f"[Yuewen][New API] 从管道事件提取文本: {text_content[:50]}...")
                                            if 'imageAnalysis' in output_item:
                                                image_analysis = output_item.get('imageAnalysis', {})
                                                if image_analysis:
                                                    image_analysis_result = image_analysis
                                                    logger.debug(f"[Yuewen][New API] 获取到图像分析结果")
                                    if 'output' in pipeline_data:  # Original 'output' variable name
                                        output_data = pipeline_data['output']  # Renamed to output_data
                                        if isinstance(output_data, dict) and 'text' in output_data:
                                            text_content = output_data.get('text', '')
                                            if text_content and text_content.strip():
                                                result_text += text_content
                                                has_received_content = True
                                                # 降级为trace级别或注释掉
                                                # logger.debug(f"[Yuewen][New API] 从管道事件提取文本: {text_content[:50]}...")
                                elif 'startEvent' in event_data:
                                    logger.debug("[Yuewen][New API] 处理开始")
                                elif 'heartBeatEvent' in event_data:
                                    pass
                                elif 'messageDoneEvent' in event_data:
                                    logger.debug("[Yuewen][New API] 收到消息完成事件")
                                    message_done = True
                                elif 'doneEvent' in event_data:
                                    logger.debug("[Yuewen][New API] 收到完成事件")
                                    message_done = True
                                elif 'errorEvent' in event_data:
                                    error_data = event_data['errorEvent']
                                    error_msg = error_data.get('message', '未知错误')
                                    logger.error(f"[Yuewen][New API] 错误: {error_msg}")
                                    return f"错误: {error_msg}"
                                elif 'messageEvent' in event_data:
                                    message_data = event_data['messageEvent'].get('message', {})
                                    if 'content' in message_data:
                                        msg_content = message_data['content']  # Renamed content to msg_content
                                        if 'assistantMessage' in msg_content:
                                            assistant_message = msg_content['assistantMessage']
                                            
                                            # 检查是否是图片生成任务 (参考旧代码逻辑)
                                            creation_info = assistant_message.get('creation', {})
                                            creation_items = creation_info.get('items', [])
                                            if creation_items:
                                                logger.info("[Yuewen][New API] Detected creation items in messageEvent.")
                                                for item in creation_items:
                                                    # 检查是否是图片生成任务
                                                    if (
                                                        item.get('type') == 'CREATION_TYPE_GEN_IMAGE' or
                                                        'image' in str(item.get('type', '')).lower()
                                                    ) and item.get('state') in [
                                                        'CREATION_STATE_RUNNING', 
                                                        'CREATION_STATE_PENDING', 
                                                        'CREATION_STATE_SUCCESS'
                                                    ]:
                                                        creation_id = item.get('creationId')
                                                        record_id = item.get('firstCreationRecordId') or creation_info.get('firstCreationRecordId')

                                                        if creation_id and record_id:
                                                            logger.info(f"[Yuewen][New API] 找到图片生成任务: CreationID={creation_id}, RecordID={record_id}, State={item.get('state')}")
                                                            
                                                            # 提前向用户发送提示，标记为正在处理图片
                                                            message_done = True
                                                            result_text += "\n\n[正在生成图片，请稍候...]"
                                                            
                                                            polling_start_time = time.time()
                                                            image_url, error_message = await self._get_image_result_new_async(creation_id, record_id)
                                                            polling_cost_time = time.time() - polling_start_time
                                                            
                                                            if image_url:
                                                                logger.info(f"[Yuewen][New API] 成功获取图片URL (轮询耗时{polling_cost_time:.2f}秒): {image_url}")
                                                                # 直接从result_text中移除处理提示和额外文本，这里不再添加URL到文本中
                                                                result_text = result_text.replace("[正在生成图片，请稍候...]", "")
                                                                
                                                                # 获取当前正在处理的消息对象，以便直接发送图片
                                                                from_wxid = self.current_message.get("FromWxid") if hasattr(self, 'current_message') and self.current_message else None
                                                                
                                                                if from_wxid:
                                                                    # 使用改进后的send_image_from_url方法发送图片
                                                                    try:
                                                                        send_success = await self.send_image_from_url(self.current_bot, from_wxid, image_url)
                                                                        
                                                                        if send_success:
                                                                            logger.info(f"[Yuewen][New API] 图片已直接发送至用户")
                                                                            # 设置图片已直接发送标记，避免额外处理
                                                                            self.image_directly_sent = True
                                                                            # 图片已经成功发送，直接返回，不做后续处理
                                                                            return (True, "IMAGE_SENT", "[图片已发送]")
                                                                        else:
                                                                            # 图片发送失败，在文本中添加图片URL
                                                                            logger.warning(f"[Yuewen][New API] 图片发送失败，在文本中添加URL")
                                                                            result_text = f"{result_text}\n\n[图片: {image_url}]"
                                                                    except Exception as img_err:
                                                                        # 记录异常但继续处理
                                                                        logger.error(f"[Yuewen][New API] 发送图片异常: {img_err}")
                                                                        result_text = f"{result_text}\n\n[图片: {image_url}]"
                                                            else:
                                                                logger.warning(f"[Yuewen][New API] 未能获取图片URL")
                                                # 如果处理了图片生成任务且成功获取URL，则已返回。若失败，则继续。
                                            
                                            # 处理正常的QA文本内容 (如果不是图片生成或图片生成失败)
                                            if 'qa' in assistant_message:
                                                qa_content = assistant_message['qa'].get('content', '')
                                                if qa_content and qa_content.strip():
                                                    result_text += qa_content
                                                    has_received_content = True
                                                    # 降级为trace级别或注释掉
                                                    # logger.debug(f"[Yuewen][New API] 收到QA内容: {qa_content[:50]}...")
                        except json.JSONDecodeError:
                            logger.warning(f"[Yuewen][New API] 无法解析JSON: {frame_data.decode('utf-8', errors='ignore')[:100]}...")
                        except Exception as parse_err:
                            logger.error(f"[Yuewen][New API] 解析帧数据异常: {parse_err}")
            
            # This block is after the loop, but still inside the OUTER TRY (L2277)
            elapsed = time.time() - start_time
            
            if not result_text and image_analysis_result:
                try:
                    result_text = self._construct_image_analysis_text(image_analysis_result)
                    has_received_content = bool(result_text)
                except Exception as img_err:
                    logger.error(f"[Yuewen][New API] 构造图像分析文本失败: {img_err}")
            
            # 如果已直接发送图片，不需要再返回文本消息
            if self.image_directly_sent:
                logger.info("[Yuewen][New API] 图片已直接发送，不再返回文本消息")
                return None
            
            if result_text or has_received_content:
                final_text = self._process_final_text(result_text)
                current_model = "DeepSeek R1"
                network_mode_str = "联网" if self.network_mode else "未联网"  # Renamed network_mode to network_mode_str
                model_info = f"使用{current_model}模型{network_mode_str}模式回答（耗时{elapsed:.2f}秒）："
                
                # 检查是否有图片生成失败的消息
                if "[图片生成失败或超时" in final_text:
                    # 图片生成失败的情况下，提取错误信息并移除它
                    failure_msg = ""
                    # 优先使用保存的具体错误消息
                    if hasattr(self, 'last_image_error') and self.last_image_error:
                        failure_msg = self.last_image_error
                        # 使用后清空，避免影响后续请求
                        self.last_image_error = None
                    # 如果没有保存的错误消息，尝试从文本中提取
                    elif "处理完所有响应帧，但未找到图片URL" in result_text:
                        failure_msg = "处理完所有响应帧，但未找到图片URL"
                    elif "图片生成失败或超时" in result_text:
                        failure_msg = "图片生成失败或超时"
                    
                    # 清理错误信息文本，把它从最终回复中移除
                    final_text = re.sub(r'\[图片生成失败或超时，耗时\d+\.\d+秒\]', '', final_text).strip()
                    
                    # 将错误消息添加到模型信息中
                    if failure_msg:
                        model_info = f"使用{current_model}模型{network_mode_str}模式回答（耗时{elapsed:.2f}秒）：{failure_msg}"
                
                logger.info(f"[Yuewen][New API] 收到回复，长度: {len(result_text)} (耗时{elapsed:.2f}秒)")
                return f"{model_info}{final_text}"
            else:
                logger.warning(f"[Yuewen][New API] 未收到有效回复 (耗时{elapsed:.2f}秒)")
                if message_done:
                    return f"处理图片完成，但未收到文本回复（耗时{elapsed:.2f}秒）"
                else:
                    return f"未收到有效回复（耗时{elapsed:.2f}秒），请尝试重新发送。"
        # except block for the outer try (L2277)
        except Exception as e: 
            logger.error(f"[Yuewen][New API] 解析响应异常: {e}", exc_info=True)
            return f"解析响应失败: {str(e)}"

    def _construct_image_analysis_text(self, analysis_data):
        """从图像分析结果构造文本描述"""
        try:
            # 判断分析数据的格式并提取有用信息
            result_text = []
            
            # 检查是否有直接的文本描述
            if isinstance(analysis_data, dict):
                # 提取描述
                if 'description' in analysis_data:
                    description = analysis_data['description']
                    if description and isinstance(description, str):
                        result_text.append(description)
                
                # 提取标签
                if 'tags' in analysis_data and analysis_data['tags']:
                    tags = analysis_data['tags']
                    if isinstance(tags, list) and tags:
                        tags_text = "识别标签: " + ", ".join(tags)
                        result_text.append(tags_text)
                
                # 提取对象识别结果
                if 'objects' in analysis_data and analysis_data['objects']:
                    objects = analysis_data['objects']
                    if isinstance(objects, list) and objects:
                        objects_text = "识别对象: " + ", ".join([obj.get('name', '') for obj in objects if 'name' in obj])
                        result_text.append(objects_text)
                
                # 提取任何文本内容
                for key, value in analysis_data.items():
                    if isinstance(value, str) and value.strip() and key not in ['description', 'tags']:
                        result_text.append(f"{key}: {value}")
            
            # 组合所有提取的文本
            if result_text:
                return "\n\n".join(result_text)
            else:
                return "图片已成功分析，但没有可提取的文本内容。"
                
        except Exception as e:
            logger.error(f"[Yuewen] 构造图像分析文本异常: {e}")
            return "无法构造图像分析结果。"

    async def _handle_error_async(self, response, error_text):
        """处理API错误响应，提供更友好的错误信息（异步版本）"""
        try:
            status_code = response.status
            logger.error(f"[Yuewen] API错误: HTTP {status_code}")
            logger.debug(f"[Yuewen] 错误响应内容: {error_text}")
            
            # 尝试解析错误JSON
            error_message = f"HTTP错误 {status_code}"
            try:
                error_json = json.loads(error_text)
                # 提取错误信息，格式可能不同
                if 'error' in error_json:
                    error_message = f"错误: {error_json['error']}"
                elif 'code' in error_json and 'message' in error_json:
                    error_message = f"错误码: {error_json['code']}, 消息: {error_json['message']}"
                elif 'msg' in error_json:
                    error_message = f"错误: {error_json['msg']}"
            except:
                # 无法解析为JSON，使用原始文本
                if error_text:
                    error_message = f"错误: {error_text[:100]}..."
            
            # 特殊处理常见错误
            if status_code == 401:
                return f"认证失败 (401): 令牌可能已过期。系统将自动尝试刷新令牌。"
            elif status_code == 404:
                return f"接口未找到 (404): API端点可能已更改或不存在。请确认正确的API端点。"
            elif status_code == 400:
                return f"请求错误 (400): {error_message}"
            elif status_code == 500:
                return f"服务器错误 (500): 服务器内部错误，请稍后重试。"
            elif status_code == 429:
                return f"请求过于频繁 (429): 超出服务器频率限制，请稍后重试。"
                
            # 增加API错误计数
            self.api_errors_count += 1
            
            # 如果错误太多，建议重置会话
            if self.api_errors_count > 3:
                self.api_errors_count = 0  # 重置计数
                self.current_chat_session_id = None
                self.current_chat_id = None
                # 强制创建新会话
                await self.create_chat_async()
                return f"{error_message} (已达到错误阈值，已重置会话)"
                
            return error_message
            
        except Exception as e:
            logger.error(f"[Yuewen] 处理错误响应时发生异常: {e}")
            return f"处理错误时发生异常: {str(e)}"

    # ======== 消息处理器 ========
    def _get_user_id(self, message: dict) -> str:
        """从消息中提取用户ID"""
        from_wxid = message.get("FromWxid", "")
        is_group = message.get("IsGroup", False)
        
        if is_group:
            group_id = message.get("FromWxid", "")
            sender_wxid = message.get("SenderWxid", "")
            return f"{group_id}_{sender_wxid}" if sender_wxid else group_id
        else:
            return from_wxid
            
    async def _check_login_status_async(self):
        """检查登录状态（异步版本）
        @return: True表示需要登录，False表示已登录
        """
        # 如果配置中明确需要登录，直接返回True
        if self.config.get('need_login', True):
            self.need_login = True
            return True
            
        # 检查是否有必要的凭证
        if not self.oasis_webid or not self.oasis_token:
            logger.warning("[Yuewen] 缺少webid或token，需要登录")
            self.need_login = True
            self.update_config({"need_login": True})
            return True
            
        # 尝试刷新令牌验证有效性
        try:
            # 刷新令牌
            if hasattr(self.login_handler, 'refresh_token'):
                token_valid = await self.login_handler.refresh_token()
                # 如果刷新失败但存在令牌，可以继续使用
                if not token_valid and self.oasis_token:
                    logger.warning("[Yuewen] 刷新令牌失败，但存在令牌，继续使用现有令牌")
                    self.need_login = False
                    self.update_config({"need_login": False})
                    return False
                # 如果刷新失败且没有有效令牌，需要登录
                elif not token_valid:
                    logger.warning("[Yuewen] 令牌刷新失败，需要重新登录")
                    self.need_login = True
                    self.update_config({"need_login": True})
                    return True
                # 刷新成功，不需要登录
                else:
                    self.need_login = False
                    self.update_config({"need_login": False})
                    return False
            else:
                logger.error("[Yuewen] login_handler缺少refresh_token方法")
                # 如果没有刷新方法但存在令牌，也可以继续使用
                if self.oasis_token:
                    logger.warning("[Yuewen] 无法刷新令牌，但存在令牌，继续使用现有令牌")
                    self.need_login = False
                    self.update_config({"need_login": False})
                    return False
                else:
                    self.need_login = True
                    self.update_config({"need_login": True})
                    return True
        except Exception as e:
            logger.error(f"[Yuewen] 刷新令牌异常: {e}")
            # 出现异常但存在令牌，可以继续使用
            if self.oasis_token:
                logger.warning("[Yuewen] 刷新令牌异常，但存在令牌，继续使用现有令牌")
                self.need_login = False
                self.update_config({"need_login": False})
                return False
            else:
                self.need_login = True
                self.update_config({"need_login": True})
                return True
        
        # 令牌有效，不需要登录
        return False
        
    async def _initiate_login_async(self, bot, reply_to_wxid, user_id):
        """初始化登录流程（异步版本）"""
        try:
            # 检查是否已有等待验证的用户
            if user_id in self.waiting_for_verification:
                # 清除之前的状态
                self.waiting_for_verification.pop(user_id, None)
            
            # 无论是否有webid都重新注册设备，确保流程完整
            logger.info("[Yuewen] 正在注册设备...")
            await bot.send_text_message(reply_to_wxid, "⏳ 正在注册设备，请稍候...")
            
            # 异步调用登录处理器的注册设备方法
            if not await self.login_handler.register_device():
                await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败，请稍后重试")
                return False
            
            # 从登录处理器获取webid
            self.oasis_webid = self.login_handler.config.get('oasis_webid')
            
            # 成功注册设备后，检查是否有webid
            if not self.oasis_webid:
                await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败: 未获取到webid")
                return False
                
            logger.info(f"[Yuewen] 设备注册成功，webid={self.oasis_webid}")
            await bot.send_text_message(reply_to_wxid, "✅ 设备注册成功，正在初始化登录...")
            
            # 提示用户输入手机号
            await bot.send_text_message(
                reply_to_wxid, 
                "📱 请输入您的11位手机号码\n注意：此手机号将用于接收跃问的验证码"
            )
            
            # 标记此用户正在进行登录操作 - 使用空字符串作为占位符
            self.waiting_for_verification[user_id] = ""
            
            # 记录用户正在等待输入手机号
            self.login_users.add(user_id)
            self.is_login_triggered = True
            
            return True
        except Exception as e:
            logger.error(f"[Yuewen] 初始化登录流程失败: {e}", exc_info=True)
            await bot.send_text_message(reply_to_wxid, f"❌ 初始化登录失败: {str(e)}")
            return False
    
    async def _send_verification_code_async(self, bot, reply_to_wxid, user_id, phone_number):
        """发送验证码到手机（异步版本）"""
        try:
            # 检查手机号格式
            if not phone_number.isdigit() or len(phone_number) != 11:
                await bot.send_text_message(reply_to_wxid, "❌ 请输入有效的11位手机号码")
                return False
                
            await bot.send_text_message(reply_to_wxid, f"⏳ 正在发送验证码，请稍候...")
            
            # 确保有webid - 使用login_handler中的
            if not self.oasis_webid:
                # 更新webid
                self.oasis_webid = self.login_handler.config.get('oasis_webid')
                
                # 如果仍然没有，尝试重新注册设备
                if not self.oasis_webid:
                    logger.info("[Yuewen] 发送验证码前重新注册设备")
                    if not await self.login_handler.register_device():
                        await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败，无法发送验证码")
                        return False
                    
                    # 更新webid
                    self.oasis_webid = self.login_handler.config.get('oasis_webid')
                    
                    # 检查注册后是否有webid
                    if not self.oasis_webid:
                        await bot.send_text_message(reply_to_wxid, "❌ 设备注册失败: 未获取到webid")
                        return False
                        
                    logger.info(f"[Yuewen] 设备注册成功，webid={self.oasis_webid}")
            
            # 使用异步版本发送验证码
            success = await self.login_handler.send_verify_code(phone_number)
            
            if success:
                # 保存手机号，等待后续输入验证码
                self.waiting_for_verification[user_id] = phone_number
                
                # 从登录状态列表移除，表示已完成手机号输入步骤
                if user_id in self.login_users:
                    self.login_users.remove(user_id)
                
                await bot.send_text_message(
                    reply_to_wxid, 
                    "✅ 验证码已发送，请输入收到的4位验证码完成登录"
                )
                return True
            else:
                # 验证码发送失败，清除等待状态
                if user_id in self.waiting_for_verification:
                    self.waiting_for_verification.pop(user_id, None)
                    
                await bot.send_text_message(
                    reply_to_wxid, 
                    f"❌ 验证码发送失败，请检查手机号是否正确或稍后重试"
                )
                return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 验证码发送处理异常: {e}", exc_info=True)
            # 清除等待状态
            if user_id in self.waiting_for_verification:
                self.waiting_for_verification.pop(user_id, None)
                
            await bot.send_text_message(reply_to_wxid, f"❌ 处理失败: {str(e)}")
            return False
    
    async def _verify_login_async(self, bot, reply_to_wxid, user_id, verify_code):
        """验证登录（异步版本）"""
        try:
            # 获取之前保存的手机号
            phone_number = self.waiting_for_verification.get(user_id)
            if not phone_number:
                await bot.send_text_message(reply_to_wxid, "❌ 验证失败：请先发送手机号获取验证码")
                return False
            
            # 向用户发送正在验证的消息
            await bot.send_text_message(reply_to_wxid, "⏳ 正在验证登录，请稍候...")
            
            # 使用登录处理器的异步方法进行登录验证
            if await self.login_handler.sign_in(mobile_num=phone_number, auth_code=verify_code):
                # 清除等待验证状态
                self.waiting_for_verification.pop(user_id, None)
                
                # 同步登录状态到当前插件
                self.need_login = False
                self.oasis_webid = self.login_handler.config.get('oasis_webid')
                self.oasis_token = self.login_handler.config.get('oasis_token')
                
                # 更新配置
                self.update_config({
                    'need_login': False,
                    'oasis_webid': self.oasis_webid,
                    'oasis_token': self.oasis_token
                })
                
                # 创建新会话
                await bot.send_text_message(reply_to_wxid, "✅ 登录成功，正在创建会话...")
                
                # 创建新会话
                if await self.create_chat_async():
                    await bot.send_text_message(reply_to_wxid, "✅ 会话创建成功，可以开始对话了")
                else:
                    await bot.send_text_message(reply_to_wxid, "⚠️ 登录成功，但会话创建失败，请发送'yw新建会话'尝试创建会话")
                
                logger.info("[Yuewen] 用户登录成功并创建会话")
                return True
            else:
                # 验证失败
                await bot.send_text_message(reply_to_wxid, "❌ 验证码错误或已过期，请重新发送'yw登录'进行登录")
                # 清除等待状态
                self.waiting_for_verification.pop(user_id, None)
                return False
            
        except Exception as e:
            logger.error(f"[Yuewen] 验证登录异常: {e}", exc_info=True)
            # 清除等待状态
            self.waiting_for_verification.pop(user_id, None)
            await bot.send_text_message(reply_to_wxid, f"❌ 验证登录出错: {str(e)}")
            return False
    
    async def _handle_commands_async(self, content):
        """处理内置命令（异步版本）"""
        if not content:
            return None
            
        # 打印模型命令
        if content == "打印模型":
            # 构建模型列表 - 无论API版本都显示可用模型
            output = ["可用模型："]
            for num, info in self.models.items():
                status = "（支持联网）" if info.get('can_network', True) else ""
                current = " ← 当前使用" if info['id'] == self.current_model_id else ""
                output.append(f"{num}. {info['name']}{status}{current}")
            return '\n'.join(output)
            
        # 模型切换命令
        if content.startswith("切换模型") or content.startswith("模型") or content.startswith("model"):
            # 如果是新版API，提示用户不支持
            if self.api_version == 'new':
                return "⚠️ 切换模型功能仅支持旧版API，请先发送'yw切换旧版'切换到旧版API"
                
            model_num = None
            # 尝试提取模型编号
            try:
                # 支持 "切换模型1", "切换模型 1", "模型1", "模型 1", "model1", "model 1" 等格式
                cmd_parts = content.replace("切换模型", "").replace("模型", "").replace("model", "").strip()
                if cmd_parts.isdigit():
                    model_num = int(cmd_parts)
            except:
                pass
                
            # 如果没有指定模型或模型无效，显示可用模型列表
            if not model_num or model_num not in self.models:
                models_info = "\n".join([f"{idx}. {model['name']}" for idx, model in self.models.items()])
                return f"可用模型列表：\n{models_info}\n\n使用方法：yw切换模型[编号] 进行切换"
                
            # 切换模型
            selected_model = self.models.get(model_num, {})
            self.current_model_id = selected_model["id"]
            self.update_config({"current_model_id": self.current_model_id})
            
            # 如果是deepseek r1模型(id=6)，强制开启联网模式
            if selected_model.get('id') == 6:  # deepseek r1模型ID
                self.network_mode = True
                self.update_config({"network_mode": True})
                # 同步启用深度思考模式
                await self._enable_deep_thinking_async()
            
            # 如果该模型不支持联网但是当前开启了联网，关闭联网
            elif not selected_model.get("can_network", True) and self.network_mode:
                self.network_mode = False
                self.update_config({"network_mode": False})
                
            # 创建新会话
            self.current_chat_id = None
            self.current_chat_session_id = None
            if not await self.create_chat_async():
                return f"⚠️ 已切换到 [{selected_model.get('name', '未知模型')}]，但新会话创建失败，请手动发送'yw新建会话'"
                
            # 同步服务器状态
            await self._sync_server_state_async()
            
            # 根据模型联网支持情况返回不同消息
            if not selected_model.get("can_network", True) and self.network_mode:
                return f"✅ 已切换到 [{selected_model.get('name', '未知模型')}]，该模型不支持联网，已自动关闭联网功能"
            else:
                return f"✅ 已切换至 [{selected_model.get('name', '未知模型')}]"
        
        # 联网模式命令
        elif content in ["联网", "开启联网", "打开联网"]:
            # 检查当前模型是否支持联网
            current_model_info = None
            for model_num, model_info in self.models.items():
                if model_info.get("id") == self.current_model_id:
                    current_model_info = model_info
                    break
                    
            if current_model_info and not current_model_info.get("can_network", True):
                return f"❌ 当前模型 [{current_model_info.get('name', '未知模型')}] 不支持联网，请先切换到支持联网的模型"
                
            # 如果已经是联网模式，提示用户
            if self.network_mode:
                return "ℹ️ 联网模式已经开启"
                
            # 开启联网模式
            self.network_mode = True
            self.update_config({"network_mode": True})
            
            # 尝试同步服务器状态
            try:
                await self._sync_server_state_async()
            except Exception as e:
                logger.error(f"[Yuewen] 同步网络状态失败: {e}")
                
            return "✅ 已开启联网模式"
            
        # 关闭联网模式命令
        elif content in ["不联网", "关闭联网", "禁用联网"]:
            # 如果已经是非联网模式，提示用户
            if not self.network_mode:
                return "ℹ️ 联网模式已经关闭"
                
            # 关闭联网模式
            self.network_mode = False
            self.update_config({"network_mode": False})
            
            # 尝试同步服务器状态
            try:
                await self._sync_server_state_async()
            except Exception as e:
                logger.error(f"[Yuewen] 同步网络状态失败: {e}")
                
            return "✅ 已关闭联网模式"
            
        # API版本切换命令
        elif content in ["切换旧版", "使用旧版", "旧版API"]:
            if self.api_version == 'old':
                return "ℹ️ 已经是旧版API模式"
                
            # 切换到旧版API
            self.api_version = 'old'
            self.current_base_url = self.base_urls['old']
            self.update_config({"api_version": "old"})
            
            # 清除会话
            self.current_chat_id = None
            self.current_chat_session_id = None
            
            return "✅ 已切换到旧版API模式，将在下一次对话创建新会话"
            
        elif content in ["切换新版", "使用新版", "新版API"]:
            if self.api_version == 'new':
                return "ℹ️ 已经是新版API模式"
                
            # 切换到新版API
            self.api_version = 'new'
            self.current_base_url = self.base_urls['new']
            self.update_config({"api_version": "new"})
            
            # 清除会话
            self.current_chat_id = None
            self.current_chat_session_id = None
            
            return "✅ 已切换到新版API模式，将在下一次对话创建新会话"
            
        # 分享命令
        elif content in ["分享", "share", "生成图片"]:
            # 检查是否支持分享功能
            if self.api_version == 'new':
                return "⚠️ 分享功能仅支持旧版API，请先发送'yw切换旧版'切换到旧版API"
                
            # 检查是否有最近的消息记录
            if not hasattr(self, 'last_message') or not self.last_message:
                return "⚠️ 没有可分享的消息记录，请先发送一条消息"
                
            # 检查最近消息是否超时
            current_time = time.time()
            if current_time - self.last_message.get('last_time', 0) > 180:  # 3分钟超时
                return "⚠️ 分享超时，请重新发送消息后再尝试分享"
                
            return "🔄 正在生成分享图片，请稍候..."
        
        # 深度思考模式
        elif content in ["深度思考", "enable_deep_thinking", "思考模式"]:
            if self.api_version != 'old':
                return "⚠️ 深度思考模式仅支持旧版API，请先发送'yw切换旧版'切换到旧版API"
        
            # 调用深度思考设置方法
            if await self._enable_deep_thinking_async():
                return "✅ 已开启深度思考模式"
            else:
                return "❌ 开启深度思考模式失败，请重试"
        
        # 帮助命令
        elif content in ["帮助", "help", "指令", "命令"]:
            current_api_version = "新版API" if self.api_version == 'new' else "旧版API"
            help_text = f"""📚 跃问AI助手指令 (当前: {current_api_version})：

【通用指令】
1. yw [问题] - 向AI提问
2. yw登录 - 重新登录账号
3. yw联网/不联网 - 开启/关闭联网功能
4. yw新建会话 - 开始新的对话
5. yw切换旧版/新版 - 切换API版本
6. yw识图 [描述] - 发送图片让AI分析

【仅限旧版API功能】
7. yw切换模型[编号] - 切换AI模型 (当前：{
    next((f"{idx}.{model['name']}" for idx, model in self.models.items() 
         if model['id'] == self.current_model_id), "未知")})
8. yw打印模型 - 显示所有可用模型
9. yw分享 - 生成对话分享图片
10. yw深度思考 - 启用思考模式
11. yw识图N [描述] - 分析N张图片
12. yw多图 [描述] - 分析多张图片

当前状态：联网{" ✓" if self.network_mode else " ✗"}
"""
            return help_text
            
        # 未匹配任何命令
        return None

    async def _get_image_result_new_async(self, creation_id: str, record_id: str):
        """轮询获取图片生成结果（StepFun新版API）
        
        Args:
            creation_id: 创建任务ID
            record_id: 记录ID
            
        Returns:
            tuple: (url, error_message) - 成功时url不为None，失败时error_message不为None
        """
        if not creation_id or not record_id:
            logger.error("[Yuewen][New API] 缺少必要的创建ID或记录ID")
            return None, "缺少必要的创建ID或记录ID"
            
        logger.info(f"[Yuewen][New API] 开始轮询图片生成状态: creation_id={creation_id}, record_id={record_id}")
        
        # 轮询参数
        max_polling_count = 60  # 最大轮询次数
        initial_delay = 1.0     # 初始延迟（秒）
        max_delay = 5.0         # 最大延迟（秒）
        current_delay = initial_delay
        
        # 使用用户提供的curl命令中的正确API端点
        poll_url = f"{self.current_base_url}/api/capy.creation.v1.CreationService/GetCreationRecordResultStream"
        
        # 准备请求头
        headers = self._update_headers()
        headers.update({
            'canary': 'false',
            'connect-protocol-version': '1',
            'content-type': 'application/connect+json',
            'origin': self.current_base_url,
            'priority': 'u=1, i',
            'x-waf-client-type': 'fetch_sdk'
        })
        
        # 准备cookies
        cookies = {
            'Oasis-Webid': self.oasis_webid or '',
            'Oasis-Token': self.oasis_token or '',
            'i18next': 'zh',
            'sidebar_state': 'false'
        }
        
        # 准备轮询请求体
        payload = {
            "creationId": creation_id,
            "creationRecordId": record_id
        }
        
        # 构建Connect格式的请求
        try:
            json_str = json.dumps(payload, separators=(',', ':'))
            # 根据Connect协议，添加0x00作为flag和4字节big-endian长度
            encoded_json = json_str.encode('utf-8')
            length = len(encoded_json)
            prefix = struct.pack('>BI', 0, length)  # Flag(1字节) + Length(4字节)
            request_data = prefix + encoded_json
            
            logger.debug(f"[Yuewen][New API] 构建请求数据，大小: {len(request_data)} 字节")
        except Exception as e:
            logger.error(f"[Yuewen][New API] 构建请求数据失败: {e}")
            return None, f"构建请求数据失败: {e}"
        
        try:
            # 发起轮询请求，使用较长的超时时间
            timeout = aiohttp.ClientTimeout(total=180)  # 3分钟超时
            
            async with aiohttp.ClientSession(cookies=cookies, timeout=timeout) as session:
                async with session.post(poll_url, headers=headers, data=request_data) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"[Yuewen][New API] 图片轮询请求失败: HTTP {response.status}, {error_text}")
                        return None, f"图片轮询请求失败: HTTP {response.status}, {error_text}"
                    
                    # 处理流式响应
                    buffer = bytearray()
                    image_url = None
                    
                    # 处理响应流
                    async for chunk in response.content.iter_any():
                        if not chunk:
                            continue
                        
                        buffer.extend(chunk)
                        
                        # 解析Connect协议帧
                        while len(buffer) >= 5:  # 至少需要5字节（flag + length）
                            try:
                                flags = buffer[0]
                                frame_length = struct.unpack('>I', buffer[1:5])[0]
                                
                                if len(buffer) < 5 + frame_length:
                                    # 数据不完整，等待更多数据
                                    break
                                
                                # 提取帧数据
                                frame_data = buffer[5:5+frame_length]
                                buffer = buffer[5+frame_length:]  # 移除已处理的帧
                                
                                # 解析JSON
                                if frame_length > 0:
                                    try:
                                        frame_json = json.loads(frame_data.decode('utf-8'))
                                        logger.debug(f"[Yuewen][New API] 收到图片轮询响应帧: {str(frame_json)[:100]}...")
                                        
                                        # 从帧中提取图片URL
                                        record = frame_json.get('body', {}).get('record', {})
                                        state = record.get('state')
                                        
                                        # 检查是否成功
                                        if state == 'CREATION_RECORD_STATE_SUCCESS':
                                            # 尝试从结果中提取URL
                                            result = record.get('result', {})
                                            gen_image = result.get('genImage', {})
                                            resources = gen_image.get('resources', [])
                                            
                                            if resources and len(resources) > 0:
                                                resource = resources[0].get('resource', {})
                                                image_data = resource.get('image', {})
                                                image_url = image_data.get('url')
                                                
                                                if image_url:
                                                    logger.info(f"[Yuewen][New API] 成功获取图片URL: {image_url}")
                                                    return image_url, None
                                        
                                        # 检查是否失败
                                        elif state in ['CREATION_RECORD_STATE_FAILED', 'CREATION_RECORD_STATE_REJECTED', 'CREATION_RECORD_STATE_CANCELED']:
                                            reason = record.get('failedReason') or record.get('rejectReason') or "未知原因"
                                            logger.error(f"[Yuewen][New API] 图片生成失败: {state}, 原因: {reason}")
                                            return None, f"图片生成失败: {state}, 原因: {reason}"
                                            
                                    except json.JSONDecodeError:
                                        logger.warning(f"[Yuewen][New API] 解析JSON帧失败: {frame_data[:100]}...")
                                    except Exception as e:
                                        logger.error(f"[Yuewen][New API] 处理帧异常: {e}")
                                
                                # 检查是否是结束帧
                                if flags & 0x02:
                                    logger.info("[Yuewen][New API] 收到结束帧")
                                    break
                                
                            except struct.error:
                                logger.error(f"[Yuewen][New API] 解析帧头失败: {buffer[:10]}...")
                                buffer = buffer[1:]  # 跳过当前字节继续尝试
                            except Exception as e:
                                logger.error(f"[Yuewen][New API] 处理帧异常: {e}")
                                buffer = buffer[5:]  # 跳过当前帧头继续尝试
                    
                    # 如果处理完所有响应后仍未提取到URL
                    if not image_url:
                        logger.warning("[Yuewen][New API] 处理完所有响应帧，但未找到图片URL")
                        return None, "处理完所有响应帧，但未找到图片URL"
                    
                    return image_url, None
                    
        except asyncio.TimeoutError:
            logger.error("[Yuewen][New API] 图片轮询请求超时")
            return None, "图片轮询请求超时"
        except aiohttp.ClientError as e:
            logger.error(f"[Yuewen][New API] 图片轮询请求客户端错误: {e}")
            return None, f"图片轮询请求客户端错误: {e}"
        except Exception as e:
            logger.error(f"[Yuewen][New API] 图片轮询请求异常: {e}", exc_info=True)
            return None, f"图片轮询请求异常: {e}"

    async def _process_multi_images_async(self, bot, images, prompt, from_wxid):
        """处理多张图片（异步版本）"""
        try:
            if self.api_version == 'new':
                # 新版API支持多图处理
                attachments = []
                
                for img in images:
                    # 构建符合新版API要求的附件结构
                    if 'response_data' in img:
                        # 使用完整响应数据构建附件
                        response_data = img['response_data']
                        attachment = {
                            "resource": {
                                "image": {
                                    "rid": response_data.get('rid'),
                                    "url": response_data.get('url'),
                                    "meta": response_data.get('meta', {"width": img['width'], "height": img['height']}),
                                    "mimeType": response_data.get('mimeType', "image/jpeg")
                                },
                                "rid": response_data.get('rid')
                            }
                        }
                        logger.debug(f"[Yuewen][New API] 使用完整响应数据构建附件: {response_data.get('rid')}")
                    else:
                        # 使用基本结构
                        attachment = {
                            "resource": {
                                "image": {
                                    "rid": img['file_id'],
                                    "url": f"https://chat-image.stepfun.com/tos-cn-i-9xxiciwj9y/{img['file_id']}~tplv-9xxiciwj9y-image.webp",
                                    "meta": {
                                        "width": img['width'],
                                        "height": img['height']
                                    },
                                    "mimeType": "image/jpeg"
                                },
                                "rid": img['file_id']
                            }
                        }
                        logger.debug(f"[Yuewen][New API] 使用基本结构构建附件: {img['file_id']}")
                    
                    attachments.append(attachment)
                
                logger.debug(f"[Yuewen][New API] 构建了 {len(attachments)} 个图片附件")
                
                # 重置图片直接发送标记
                self.image_directly_sent = False
                
                # 发送消息
                result = await self._send_message_new_async(prompt, attachments)
                
                # 发送结果 - 检查是否图片已经直接发送
                if result:
                    await bot.send_text_message(from_wxid, result)
                    return True
                elif hasattr(self, 'image_directly_sent') and self.image_directly_sent:
                    # 图片已经在处理响应期间直接发送给用户，无需发送错误消息
                    logger.info("[Yuewen][New API] 图片已直接发送给用户，多图处理成功")
                    return True
                else:
                    await bot.send_text_message(from_wxid, "❌ 处理多张图片失败，请稍后重试")
                    return False
            else:
                # 旧版API处理
                # 检查是否有活动会话
                if not self.current_chat_id:
                    logger.info("[Yuewen] 没有活动会话，尝试创建新会话")
                    if not await self.create_chat_async():
                        await bot.send_text_message(from_wxid, "❌ 创建会话失败，请重试")
                        return False
                
                # 构建多图片附件
                attachments = []
                for img in images:
                    attachments.append({
                        "fileId": img['file_id'],
                        "type": "image/jpeg",
                        "width": img['width'],
                        "height": img['height'],
                        "size": img['size']
                    })
                
                # 发送消息
                result = await self._send_message_old_async(prompt, attachments)
                
                # 发送结果
                if result:
                    await bot.send_text_message(from_wxid, result)
                    return True
                else:
                    await bot.send_text_message(from_wxid, "❌ 处理多张图片失败，请稍后重试")
                    return False
        
        except Exception as e:
            logger.error(f"[Yuewen] 处理多张图片异常: {e}", exc_info=True)
            await bot.send_text_message(from_wxid, f"❌ 处理多张图片出错: {str(e)}")
            return False

    async def _get_share_image_async(self, bot, chat_id, messages):
        """获取分享图片（异步版本）"""
        if self.api_version == 'new':
            logger.warning(f"[Yuewen] 分享图片功能仅支持旧版API")
            return None
            
        try:
            # 无论刷新频率如何，强制刷新令牌
            if hasattr(self.login_handler, 'refresh_token'):
                try:
                    logger.info("[Yuewen] 强制刷新令牌以获取分享图片")
                    refresh_success = await self.login_handler.refresh_token(force=True)
                    if not refresh_success:
                        logger.error("[Yuewen] 强制刷新令牌失败，分享图片可能会失败")
                except Exception as e:
                    logger.error(f"[Yuewen] 刷新令牌异常: {e}")
            
            # 获取token和webid
            token = self.config.get('oasis_token', '')
            webid = self.config.get('oasis_webid', '')
            
            if not token or not webid:
                logger.error("[Yuewen] 获取分享图片失败: 缺少令牌或webid")
                return None
            
            # 第一步：获取分享ID
            url = f"{self.current_base_url}/api/proto.chat.v1.ChatService/ChatShareSelectMessage"
            
            # 完全按照curl命令构建请求头
            headers = {
                'accept': '*/*',
                'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'canary': 'false',
                'connect-protocol-version': '1',
                'content-type': 'application/json',
                'oasis-appid': '10200',
                'oasis-mode': '2',
                'oasis-platform': 'web',
                'oasis-webid': webid,
                'origin': self.current_base_url,
                'priority': 'u=1, i',
                'referer': f'{self.current_base_url}/chats/{chat_id}',
                'sec-ch-ua': '"Chromium";v="136", "Microsoft Edge";v="136", "Not.A/Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
                'x-waf-client-type': 'fetch_sdk'
            }
            
            # 设置Cookie - 使用与curl命令一致的方式
            cookies = {
                'Oasis-Webid': webid,
                'Oasis-Token': token,
                'i18next': 'zh',
                '_tea_utm_cache_20002086': '{%22utm_source%22:%22share%22%2C%22utm_content%22:%22web_image_share%22}',
                'sidebar_state': 'false'
            }
            
            share_data = {
                "chatId": chat_id,
                "selectedMessageList": messages,
                "needTitle": True
            }
            
            logger.debug(f"[Yuewen] 获取分享ID请求：URL={url}, Headers={headers.keys()}, Data={share_data}")
            
            # 发送请求
            async with self.http_session.post(
                url,
                headers=headers,
                cookies=cookies,
                json=share_data,
                timeout=30
            ) as response:
                response_text = await response.text()
                
                if response.status != 200:
                    logger.error(f"[Yuewen] 获取分享ID失败: HTTP {response.status}, 响应: {response_text}")
                    return None
                    
                try:
                    share_result = json.loads(response_text)
                except json.JSONDecodeError:
                    logger.error(f"[Yuewen] 解析分享ID响应JSON失败: {response_text}")
                    return None
                    
                chat_share_id = share_result.get('chatShareId')
                if not chat_share_id:
                    logger.error(f"[Yuewen] 获取分享ID失败: 响应中缺少chatShareId: {share_result}")
                    return None
                
                logger.info(f"[Yuewen] 获取分享ID成功: {chat_share_id}, 标题: {share_result.get('title', '无标题')}")
                    
            # 第二步：生成分享图片
            url = f"{self.current_base_url}/api/proto.shareposter.v1.SharePosterService/GenerateChatSharePoster"
            poster_data = {
                "chatShareId": chat_share_id,
                "pageSize": 10,
                "shareUrl": f"{self.current_base_url}/share/{chat_share_id}?utm_source=share&utm_content=web_image_share&version=2",
                "width": 430,
                "scale": 3
            }
            
            # 更新referer为指向聊天页面
            headers['referer'] = f'{self.current_base_url}/chats/{chat_id}'
            
            logger.debug(f"[Yuewen] 生成分享图片请求：URL={url}, Headers={headers.keys()}, Data={poster_data}")
            
            # 发送请求
            async with self.http_session.post(
                url,
                headers=headers,
                cookies=cookies,
                json=poster_data,
                timeout=30
            ) as response:
                response_text = await response.text()
                
                if response.status != 200:
                    logger.error(f"[Yuewen] 生成分享图片失败: HTTP {response.status}, 响应: {response_text}")
                    return None
                    
                try:
                    poster_result = json.loads(response_text)
                except json.JSONDecodeError:
                    logger.error(f"[Yuewen] 解析分享图片响应JSON失败: {response_text}")
                    return None
                    
                static_url = poster_result.get('staticUrl')
                
                if not static_url:
                    logger.error(f"[Yuewen] 生成分享图片失败: 响应中缺少staticUrl: {poster_result}")
                    return None
                    
                logger.info(f"[Yuewen] 获取分享图片URL成功: {static_url}")
                return static_url
                
        except Exception as e:
            logger.error(f"[Yuewen] 获取分享图片异常: {e}", exc_info=True)
            return None

    async def _enable_deep_thinking_async(self):
        """启用深度思考模式（异步版本）"""
        try:
            if self.api_version != 'old':
                logger.warning("[Yuewen] 深度思考模式仅支持旧版API")
                return False
                
            # 设置深度思考URL
            url = f"{self.current_base_url}/api/proto.user.v1.UserService/EnableLlmDeepThinking"
            
            # 获取包含Cookie的headers
            headers = self._update_headers()
            headers.update({
                'Content-Type': 'application/json',
                'oasis-mode': '1',  # 使用mode 1，与创建会话保持一致
                'referer': f'{self.current_base_url}/chats/{self.current_chat_id}'
            })
            
            # 发送异步请求
            for retry in range(2):
                try:
                    async with self.http_session.post(
                        url,
                        headers=headers,
                        json={"enable": True}  # 启用深度思考
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            if result.get("result") == "RESULT_CODE_SUCCESS":
                                logger.info("[Yuewen] 深度思考模式设置成功")
                                return True
                                
                        # 如果是401错误，尝试刷新令牌并重试
                        elif response.status == 401 and retry == 0:
                            logger.warning("[Yuewen] 设置深度思考模式失败: 令牌无效，尝试刷新...")
                            if await self.login_handler.refresh_token():
                                # 更新headers (包含新的token)
                                headers = self._update_headers()
                                headers.update({
                                    'Content-Type': 'application/json',
                                    'oasis-mode': '1',
                                    'referer': f'{self.current_base_url}/chats/{self.current_chat_id}'
                                })
                                continue
                                
                        error_text = await response.text()
                        logger.error(f"[Yuewen] 设置深度思考模式失败: {response.status}, {error_text}")
                        return False
                        
                except Exception as e:
                    logger.error(f"[Yuewen] 设置深度思考模式请求异常: {e}", exc_info=True)
                    return False
                    
            return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 设置深度思考模式异常: {e}", exc_info=True)
            return False

    async def download_image(self, bot, message):
        """尝试用多种方法下载图片
        
        Args:
            bot: WechatAPIClient实例
            message: 消息字典
            
        Returns:
            bytes: 图片二进制数据，失败时返回None
        """
        try:
            msg_id = message.get("MsgId", "")
            from_wxid = message.get("FromWxid", "")
            
            if not msg_id or not from_wxid:
                logger.error("[Yuewen] 下载图片失败：缺少必要参数")
                return None
                
            logger.info(f"[Yuewen] 尝试下载图片: MsgId={msg_id}, FromWxid={from_wxid}")
            
            # 尝试方法1: 从消息中提取XML并解析aeskey和cdnmidimgurl
            try:
                # 获取图片消息的xml内容
                xml_content = message.get("Content", "")
                
                # 检查是否为字符串类型
                if not isinstance(xml_content, str):
                    logger.warning(f"[Yuewen] 消息Content不是字符串类型: {type(xml_content)}")
                    # 如果Content不是字符串，检查Xml字段
                    xml_content = message.get("Xml", "")
                    if not isinstance(xml_content, str):
                        logger.warning(f"[Yuewen] 消息Xml不是字符串类型: {type(xml_content)}")
                
                # 尝试解析XML
                if xml_content and "<msg>" in xml_content:
                    # 使用正则表达式提取aeskey和cdnmidimgurl
                    aeskey_match = re.search(r'aeskey=["\']([^"\']+)["\']', xml_content)
                    cdnurl_match = re.search(r'cdnmidimgurl=["\']([^"\']+)["\']', xml_content)
                    
                    if aeskey_match and cdnurl_match:
                        aeskey = aeskey_match.group(1)
                        cdnmidimgurl = cdnurl_match.group(1)
                        
                        logger.info(f"[Yuewen] 成功提取图片参数: aeskey={aeskey}, cdnmidimgurl={cdnmidimgurl}")
                        
                        # 调用WechatAPI的下载图片方法
                        try:
                            image_data = await bot.download_image(aeskey, cdnmidimgurl)
                            if image_data:
                                # 将base64数据转换为字节
                                image_bytes = base64.b64decode(image_data)
                                logger.info(f"[Yuewen] 方法1下载图片成功: {len(image_bytes)} 字节")
                                return image_bytes
                        except Exception as e:
                            logger.warning(f"[Yuewen] 调用API下载图片失败: {e}")
                else:
                    logger.warning(f"[Yuewen] 消息中未找到有效的XML内容")
            except Exception as e:
                logger.warning(f"[Yuewen] 方法1下载图片失败: {e}")
                
            # 尝试方法2: 如果消息包含图片路径，直接读取
            if "Image" in message and message["Image"]:
                image_path = message["Image"]
                try:
                    if os.path.exists(image_path):
                        with open(image_path, "rb") as f:
                            image_data = f.read()
                            if image_data and len(image_data) > 0:
                                logger.info(f"[Yuewen] 方法2读取图片成功: {len(image_data)} 字节")
                                return image_data
                except Exception as e:
                    logger.warning(f"[Yuewen] 方法2读取图片失败: {e}")
                    
            # 尝试方法3: 使用消息内容本身，如果是图片内容
            if "Content" in message and isinstance(message["Content"], str) and message["Content"].startswith("/9j/"):
                try:
                    # 可能是base64编码的图片
                    image_data = base64.b64decode(message["Content"])
                    if image_data and len(image_data) > 0:
                        logger.info(f"[Yuewen] 方法3直接解码Content成功: {len(image_data)} 字节")
                        return image_data
                except Exception as e:
                    logger.warning(f"[Yuewen] 方法3解码Content失败: {e}")
                
            # 返回失败
            logger.error("[Yuewen] 所有下载图片方法均失败")
            return None
            
        except Exception as e:
            logger.error(f"[Yuewen] 下载图片异常: {e}", exc_info=True)
            return None

    async def _ensure_token_valid_async(self):
        """确保令牌有效，如果即将过期则刷新
        
        Returns:
            bool: 如果令牌有效返回True，否则返回False
        """
        try:
            # 如果令牌为空，返回False
            if not self.oasis_token:
                logger.warning("[Yuewen] 令牌为空，无法确保有效性")
                return False
                
            # 计算令牌剩余时间
            if hasattr(self.login_handler, 'get_token_expiry_time'):
                expiry_time, remaining_seconds = self.login_handler.get_token_expiry_time()
                if remaining_seconds:
                    logger.debug(f"[Yuewen] 访问令牌状态: 过期时间={expiry_time}, 剩余={remaining_seconds}秒")
                    
                    # 如果剩余时间少于5分钟，刷新令牌
                    if remaining_seconds < 300:  # 5分钟 = 300秒
                        logger.info(f"[Yuewen] 令牌即将在 {remaining_seconds} 秒后过期，尝试刷新")
                        if await self.login_handler.refresh_token():
                            logger.info("[Yuewen] 令牌刷新成功")
                            return True
                        else:
                            logger.warning("[Yuewen] 令牌刷新失败")
                            return False
                    else:
                        logger.debug(f"[Yuewen] 访问令牌有效，剩余时间: {remaining_seconds}秒")
                        return True
                        
            # 如果无法检查过期时间，但有刷新方法，尝试刷新令牌
            if hasattr(self.login_handler, 'refresh_token'):
                logger.debug("[Yuewen] 无法检查令牌过期时间，尝试刷新令牌")
                refresh_result = await self.login_handler.refresh_token()
                return refresh_result or bool(self.oasis_token)
            
            # 如果没有刷新方法，只能假设令牌有效
            return bool(self.oasis_token)
        except Exception as e:
            logger.error(f"[Yuewen] 验证令牌有效性异常: {e}")
            
            # 发生异常时，尝试刷新令牌
            try:
                logger.debug("[Yuewen] 验证令牌异常后尝试刷新")
                if hasattr(self.login_handler, 'refresh_token'):
                    refresh_result = await self.login_handler.refresh_token()
                    return refresh_result or bool(self.oasis_token)
            except Exception as refresh_e:
                logger.error(f"[Yuewen] 令牌验证异常后刷新时出错: {refresh_e}")
                # 如果有令牌，即使刷新失败也继续使用
                return bool(self.oasis_token)
    
    async def send_image_from_url(self, bot, wxid, image_url):
        """从URL下载并发送图片，处理所有异常情况
        
        Args:
            bot: WechatAPIClient实例
            wxid: 接收者wxid
            image_url: 图片URL
            
        Returns:
            bool: 成功返回True，失败返回False
        """
        logger.info(f"[Yuewen] 开始处理图片URL: {image_url}")
        
        if not image_url:
            logger.error("[Yuewen] 下载图片失败: URL为空")
            return False
            
        # 预处理URL，确保签名正确编码，避免403错误
        processed_url = image_url
        if "x-signature=" in image_url:
            # 确保URL中的签名部分正确编码
            parts = image_url.split("x-signature=")
            if len(parts) > 1:
                base_url = parts[0]
                signature = parts[1]
                # 编码签名中的特殊字符
                signature_encoded = signature.replace("/", "%2F").replace("+", "%2B").replace("=", "%3D")
                processed_url = base_url + "x-signature=" + signature_encoded
                logger.debug(f"[Yuewen] URL签名已预处理: {processed_url[:50]}...")
        
        # 设置更全面的请求头，模仿浏览器行为
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://yuewen.cn/',
            'Origin': 'https://yuewen.cn',
            'Connection': 'keep-alive'
        }
        
        # 使用跃问的cookies提高请求成功率
        cookies = {
            'Oasis-Webid': self.oasis_webid or '',
            'Oasis-Token': self.oasis_token or '',
            'i18next': 'zh',
            'sidebar_state': 'false'
        }
        
        # 最大重试次数
        max_retries = 3
        
        # 尝试下载和发送
        for retry in range(max_retries):
            try:
                logger.info(f"[Yuewen] 尝试下载图片 (尝试 {retry+1}/{max_retries})")
                
                # 使用aiohttp进行异步请求，设置cookies和headers
                timeout_obj = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(cookies=cookies, timeout=timeout_obj) as session:
                    async with session.get(processed_url, headers=headers, allow_redirects=True, ssl=False) as response:
                        if response.status != 200:
                            logger.error(f"[Yuewen] 下载图片失败，状态码: {response.status}")
                            if retry < max_retries - 1:
                                await asyncio.sleep(1 * (retry + 1))
                                continue
                            return False
                        
                        # 读取图片数据
                        image_data = await response.read()
                        
                        # 验证图片数据
                        if not image_data or len(image_data) < 100:
                            logger.warning(f"[Yuewen] 下载的图片数据无效或太小: {len(image_data) if image_data else 0} 字节")
                            if retry < max_retries - 1:
                                await asyncio.sleep(1 * (retry + 1))
                                continue
                            return False
                        
                        # 验证并处理图片格式
                        try:
                            # 使用PIL验证图片数据
                            img = Image.open(io.BytesIO(image_data))
                            img_format = img.format
                            
                            # 记录原始图片信息
                            logger.info(f"[Yuewen] 图片格式: {img_format}, 尺寸: {img.width}x{img.height}, 大小: {len(image_data)} 字节")
                            
                            # 如果是WebP格式，转换为JPEG
                            if img_format == "WEBP":
                                logger.info("[Yuewen] 转换WebP图片为JPEG格式")
                                if img.mode in ('RGBA', 'LA'):
                                    # 如果有透明通道，添加白色背景
                                    background = Image.new(img.mode[:-1], img.size, (255, 255, 255))
                                    background.paste(img, img.split()[-1])  # -1表示alpha通道
                                    img = background
                                
                                # 保存为JPEG
                                img_byte_arr = io.BytesIO()
                                img.convert('RGB').save(img_byte_arr, format='JPEG', quality=95)
                                img_byte_arr.seek(0)
                                image_data = img_byte_arr.read()
                                logger.info(f"[Yuewen] 转换后大小: {len(image_data)} 字节")
                                
                        except Exception as img_err:
                            logger.warning(f"[Yuewen] 图片处理失败: {img_err}, 尝试直接使用原始数据")
                        
                        # 直接发送图片二进制数据
                        logger.info(f"[Yuewen] 开始发送图片 ({len(image_data)} 字节) 到 {wxid}")
                        
                        try:
                            # 发送图片
                            send_result = await bot.send_image_message(wxid, image_data)
                            
                            # 检查发送结果 - 修改返回值检查逻辑
                            if send_result and send_result.get("Success", False):
                                logger.info(f"[Yuewen] 成功发送图片给 {wxid}")
                                return True
                            else:
                                logger.error(f"[Yuewen] 发送图片失败，send_image_message返回: {send_result}")
                                
                                # 如果发送失败，尝试其他方式
                                if retry < max_retries - 1:
                                    logger.info("[Yuewen] 尝试其他格式发送图片")
                                    try:
                                        # 尝试转换为PNG格式
                                        img = Image.open(io.BytesIO(image_data))
                                        img_byte_arr = io.BytesIO()
                                        img.save(img_byte_arr, format='PNG')
                                        img_byte_arr.seek(0)
                                        image_data_png = img_byte_arr.read()
                                        
                                        # 尝试使用PNG格式发送
                                        logger.info(f"[Yuewen] 尝试使用PNG格式发送图片 ({len(image_data_png)} 字节)")
                                        retry_result = await bot.send_image_message(wxid, image_data_png)
                                        
                                        if retry_result and retry_result.get("Success", False):
                                            logger.info(f"[Yuewen] 使用PNG格式成功发送图片给 {wxid}")
                                            return True
                                    except Exception as png_err:
                                        logger.error(f"[Yuewen] PNG格式发送失败: {png_err}")
                                
                                # 如果仍然失败，等待重试
                                if retry < max_retries - 1:
                                    await asyncio.sleep(1 * (retry + 1))
                                    continue
                        except Exception as send_err:
                            logger.error(f"[Yuewen] 发送图片时出错: {send_err}", exc_info=True)
                            if retry < max_retries - 1:
                                await asyncio.sleep(1 * (retry + 1))
                                continue
            except aiohttp.ClientError as e:
                logger.error(f"[Yuewen] 下载图片网络错误: {e}")
                if retry < max_retries - 1:
                    await asyncio.sleep(1 * (retry + 1))
                    continue
            except asyncio.TimeoutError:
                logger.error(f"[Yuewen] 下载图片超时")
                if retry < max_retries - 1:
                    await asyncio.sleep(1 * (retry + 1))
                    continue
            except Exception as e:
                logger.error(f"[Yuewen] 处理图片时出现未预期的错误: {e}", exc_info=True)
                if retry < max_retries - 1:
                    await asyncio.sleep(1 * (retry + 1))
                    continue
        
        # 当所有重试都失败后，发送文本消息告知用户
        try:
            await bot.send_text_message(wxid, f"图片获取失败，请点击链接查看: {image_url}")
        except Exception as e:
            logger.error(f"[Yuewen] 发送失败信息也失败了: {e}")
        
        return False

    @on_text_message(priority=50)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            return True  # 插件未启用，允许后续插件处理
        
        # 保存当前bot和message引用，用于直接发送图片
        self.current_bot = bot
        self.current_message = message
        self.image_directly_sent = False  # 重置图片发送标记
        
        # 获取消息内容
        content = message.get("Content", "").strip()
        user_id = self._get_user_id(message)
        from_wxid = message.get("FromWxid")  # 用于发送回复
        
        # 提取前缀
        trigger_prefix = self.trigger_prefix.lower()
        
        # 检查是否是跃问相关命令
        is_command = content.lower().startswith(trigger_prefix)
        
        # 检查是否在验证流程中
        in_verification = user_id in self.waiting_for_verification
        in_login_flow = user_id in self.login_users
        
        # 如果不是命令也不是验证流程，让其他插件处理
        if not is_command and not in_verification and not in_login_flow:
            return True
        
        # 移除前缀，获取实际内容
        content = content[len(trigger_prefix):].strip() if is_command else content
        
        # 如果是登录流程中的手机号（11位数字）
        # 需要检查多种格式: 纯数字、带前缀无空格、带前缀有空格
        if in_login_flow:
            # 提取手机号 (查找内容中的11位连续数字)
            phone_match = re.search(r'1\d{10}', content)
            
            if phone_match:
                phone_number = phone_match.group(0)  # 提取匹配的手机号
                logger.info(f"[Yuewen] 检测到用户输入手机号: {phone_number}")
                await self._send_verification_code_async(bot, from_wxid, user_id, phone_number)
                return False
            elif content.isdigit() and len(content) == 11 and content.startswith('1'):
                # 原有逻辑，处理纯11位数字
                await self._send_verification_code_async(bot, from_wxid, user_id, content)
                return False
            elif content.isdigit() and len(content) == 11 and content.startswith('1'):
                # 处理带前缀的情况，使用处理后的content
                await self._send_verification_code_async(bot, from_wxid, user_id, content)
                return False
        
        # 如果等待验证码输入，检查4位数字
        if in_verification:
            # 先检查原始内容
            if content.isdigit() and len(content) == 4:
                await self._verify_login_async(bot, from_wxid, user_id, content)
                return False
            # 再检查去掉前缀后的内容
            elif content.isdigit() and len(content) == 4:
                await self._verify_login_async(bot, from_wxid, user_id, content)
                return False
        
        # 显式登录命令处理
        if content in ["登录", "登陆", "login"]:
            await self._initiate_login_async(bot, from_wxid, user_id)
            return False
        
        # 如果需要登录 - 检查登录状态
        if await self._check_login_status_async():
            # 只有当用户特别请求相关功能时才提示登录
            if is_command:
                await bot.send_text_message(
                    from_wxid, 
                    "⚠️ 跃问账号未登录或已失效，请先发送\"yw登录\"进行登录"
                )
            return False
        
        # 处理分享命令 - 在处理内置命令前单独处理
        if content in ["分享", "share", "生成图片"]:
            if self.api_version == 'new':
                await bot.send_text_message(from_wxid, "⚠️ 分享功能仅支持旧版API，请先发送'yw切换旧版'切换到旧版API")
                return False
                
            # 检查是否有最近的消息记录
            if not hasattr(self, 'last_message') or not self.last_message:
                await bot.send_text_message(from_wxid, "⚠️ 没有可分享的消息记录，请先发送一条消息")
                return False
                
            # 检查最近消息是否超时
            current_time = time.time()
            if current_time - self.last_message.get('last_time', 0) > 180:  # 3分钟超时
                await bot.send_text_message(from_wxid, "⚠️ 分享超时，请重新发送消息后再尝试分享")
                return False
                
            # 发送等待消息
            await bot.send_text_message(from_wxid, "🔄 正在生成分享图片，请稍候...")
            
            # 获取分享图片
            share_url = await self._get_share_image_async(
                bot,
                self.last_message['chat_id'], 
                self.last_message['messages']
            )
            
            # 发送分享图片
            if share_url:
                # 直接使用优化后的发送图片方法
                logger.info(f"[Yuewen] 开始下载并发送分享图片: {share_url}")
                
                try:
                    # 使用改进后的send_image_from_url方法
                    send_success = await self.send_image_from_url(bot, from_wxid, share_url)
                    
                    if not send_success:
                        # 如果发送失败，提供原始链接
                        logger.error(f"[Yuewen] 分享图片发送失败，提供原始链接")
                        await bot.send_text_message(from_wxid, f"分享图片发送失败，您可以直接访问: {share_url}")
                    else:
                        logger.info(f"[Yuewen] 分享图片发送成功")
                    
                    # 无论成功与否，立即返回，不做后续处理
                    return False  # 阻止后续插件处理
                except Exception as e:
                    logger.error(f"[Yuewen] 发送分享图片异常: {e}")
                    await bot.send_text_message(from_wxid, f"分享图片发送失败: {str(e)}")
                    return False
            else:
                await bot.send_text_message(from_wxid, "❌ 生成分享图片失败，请稍后重试")
                return False  # 阻止后续插件处理
        
        # 处理内置命令
        command_result = await self._handle_commands_async(content)
        if command_result is not None:
            # 这里command_result是命令处理的结果，是文字消息
            await bot.send_text_message(from_wxid, command_result)
            return False
        
        # 识图命令处理
        pic_trigger = self.pic_trigger_prefix
        if content.startswith(pic_trigger):
            # 检查是否是"识图N"格式，支持多张图片分析
            match = re.match(r'^识图(\d+)(\s+.*)?$', content)
            if match:
                img_count = int(match.group(1))
                if img_count < 1 or img_count > self.max_images:
                    await bot.send_text_message(
                        from_wxid,
                        f"⚠️ 图片数量必须在1-{self.max_images}之间"
                    )
                    return False
                    
                prompt = match.group(2).strip() if match.group(2) else self.imgprompt
                
                # 初始化多图处理数据
                self.multi_image_data[user_id] = {
                    'prompt': prompt,
                    'images': [],
                    'count': img_count
                }
                
                # 发送引导消息
                await bot.send_text_message(
                    from_wxid,
                    f"🖼 请依次发送{img_count}张图片，发送完毕后请发送'结束'开始处理"
                )
                return False
            else:
                # 单图模式，等待下一条信息是图片
                # 提取可能的提示词
                prompt = content[len(pic_trigger):].strip()
                if not prompt:
                    prompt = self.imgprompt
                    
                # 保存识图请求
                self.waiting_for_image[user_id] = {'prompt': prompt}
                
                # 发送引导消息
                await bot.send_text_message(from_wxid, "🖼 请发送一张图片")
                return False
        
        # 处理用户发送的"结束"消息，表示多图片上传完成
        if user_id in self.multi_image_data and content in ["结束", "完成", "处理"]:
            multi_data = self.multi_image_data[user_id]
            
            # 检查是否已上传足够的图片
            if len(multi_data['images']) < multi_data['count']:
                await bot.send_text_message(
                    from_wxid,
                    f"⚠️ 您还需要发送{multi_data['count'] - len(multi_data['images'])}张图片。发送完毕后请发送'结束'开始处理"
                )
                return False
                
            # 消息处理开始
            await bot.send_text_message(from_wxid, "🔄 正在处理图片，请稍候...")
            
            # 处理多图片
            await self._process_multi_images_async(
                bot,
                multi_data['images'], 
                multi_data['prompt'], 
                from_wxid
            )
            
            # 清除多图数据
            self.multi_image_data.pop(user_id, None)
            return False
        
        # 正常消息处理
        try:
            # 显示正在输入状态（如果API支持）
            if hasattr(bot, 'send_typing_status'):
                await bot.send_typing_status(from_wxid)
            else:
                logger.debug("[Yuewen] WechatAPIClient不支持send_typing_status方法，跳过显示输入状态")
            
            # 发送消息到AI
            response = await self.send_message_async(content)
            
            # 根据API版本处理不同的返回格式
            if self.api_version == 'new':
                # 新版API返回元组(text, search_info)
                if isinstance(response, tuple):
                    # 检查是否为特殊的图片已发送返回值
                    if len(response) >= 2 and response[0] is True and response[1] == "IMAGE_SENT":
                        logger.info("[Yuewen][New API] 检测到图片已发送的特殊返回值，中止后续处理")
                        return False  # 直接返回，不再处理任何文本消息
                    
                    # 正常处理文本和搜索结果返回值
                    text, search_info = response[0], response[1]
                    
                    # 如果图片已直接发送，不再发送文本回复
                    if self.image_directly_sent:
                        logger.info("[Yuewen][New API] 图片已直接发送至用户，不再发送文本回复")
                        return False
                    
                    # 发送文本回复
                    if text:
                        await bot.send_text_message(from_wxid, text)
                    else:
                        await bot.send_text_message(from_wxid, "❌ 未能获取有效回复")
                        return False
                    
                    # 处理搜索结果
                    if search_info and search_info.get('results'):
                        search_results = search_info.get('results', [])
                        if search_results:
                            # 准备搜索结果显示
                            result_text = "\n\n参考资料：\n"
                            for idx, result in enumerate(search_results[:3], 1):  # 最多显示前3个
                                title = result.get('title', '未知标题')
                                url = result.get('url', '#')
                                result_text += f"{idx}. {title}\n{url}\n\n"
                            
                            # 发送搜索结果
                            await bot.send_text_message(from_wxid, result_text)
                else:
                    # 检查图片是否已直接发送
                    if hasattr(self, 'image_directly_sent') and self.image_directly_sent:
                        logger.info("[Yuewen][New API] 图片已直接发送至用户，不再发送额外消息")
                        return False
                        
                    # 对于字符串类型的响应，直接发送（通常是错误消息）
                    if response:
                        await bot.send_text_message(from_wxid, response)
                    else:
                        await bot.send_text_message(from_wxid, "❌ 发送消息失败，请重试")
            else:
                # 旧版API返回单个字符串
                if response:
                    # 发送文本消息
                    await bot.send_text_message(from_wxid, response)
                else:
                    # 如果响应为空，发送错误消息
                    await bot.send_text_message(from_wxid, "❌ 未获得有效回复，请稍后重试")
        except Exception as e:
            logger.error(f"[Yuewen] 处理消息异常: {e}", exc_info=True)
            await bot.send_text_message(from_wxid, f"❌ 处理消息失败: {str(e)}")
        
        return False

    @on_image_message(priority=50)
    async def handle_image(self, bot: WechatAPIClient, message: dict):
        """处理图片消息"""
        if not self.enable:
            return True  # 插件未启用，允许后续插件处理
        
        # 获取用户ID
        user_id = self._get_user_id(message)
        from_wxid = message.get("FromWxid")  # 用于发送回复
        
        # 确保只处理等待图片的请求
        # 检查是否有等待处理的识图请求（单图模式）
        if user_id in self.waiting_for_image:
            logger.info(f"[Yuewen] 用户 {user_id} 正在等待图片，处理图片消息")
            # 下载图片
            image_data = await self.download_image(bot, message)
            
            if not image_data:
                await bot.send_text_message(from_wxid, "❌ 无法获取图片数据，请重试")
                return False
                
            # 根据API版本选择不同处理方式
            if self.api_version == 'new':
                # 上传图片 - 新版API
                file_id = await self._upload_image_new_async(image_data)
                
                if not file_id:
                    # 获取最后一次尝试上传的错误信息
                    error_detail = ""
                    if hasattr(self, '_last_upload_error') and self._last_upload_error:
                        error_detail = f": {self._last_upload_error}"
                    
                    await bot.send_text_message(from_wxid, f"❌ 图片上传失败{error_detail}\n请稍后重试或联系管理员检查日志")
                    return False
                    
                # 获取识图提示词
                prompt = self.waiting_for_image[user_id].get('prompt', self.imgprompt)
                
                # 创建图片附件
                # 获取图片尺寸
                try:
                    from PIL import Image
                    from io import BytesIO
                    img = Image.open(BytesIO(image_data))
                    width, height = img.size
                except Exception as e:
                    logger.error(f"[Yuewen] 获取图片尺寸失败: {e}")
                    width, height = 800, 600  # 使用默认尺寸
                    
                # 按照新版API要求构建图片附件
                if hasattr(self, '_last_image_response') and self._last_image_response:
                    # 使用服务器返回的完整元数据
                    response_data = self._last_image_response
                    
                    # 构建与curl命令格式完全匹配的附件
                    attachments = [{
                        "resource": {
                            "image": {
                                "rid": response_data.get('rid'),
                                "url": response_data.get('url'),
                                "meta": response_data.get('meta', {"width": width, "height": height}),
                                "mimeType": response_data.get('mimeType', "image/jpeg")
                            },
                            "rid": response_data.get('rid')
                        }
                    }]
                    logger.debug(f"[Yuewen][New API] 使用服务器返回的图片数据构建附件: {response_data.get('rid')}")
                else:
                    # 使用基本结构，如果没有完整响应
                    attachments = [{
                        "resource": {
                            "image": {
                                "rid": file_id,
                                "url": f"https://chat-image.stepfun.com/tos-cn-i-9xxiciwj9y/{file_id}~tplv-9xxiciwj9y-image.webp",
                                "meta": {
                                    "width": width,
                                    "height": height
                                },
                                "mimeType": "image/jpeg"
                            },
                            "rid": file_id
                        }
                    }]
                    logger.debug(f"[Yuewen][New API] 使用基本结构构建图片附件: {file_id}")
                
                # 发送消息
                await bot.send_text_message(from_wxid, "🔄 正在处理图片，请稍候...")
                result = await self._send_message_new_async(prompt, attachments)
                
                # 清除识图请求
                self.waiting_for_image.pop(user_id, None)
                
                # 发送结果
                if result:
                    # 检查是否为特殊的图片已发送返回值
                    if isinstance(result, tuple) and len(result) >= 2 and result[0] is True and result[1] == "IMAGE_SENT":
                        logger.info("[Yuewen][New API] 检测到图片已发送的特殊返回值，不再发送额外消息")
                        return False  # 直接返回，不再处理任何文本消息
                
                    # 检查结果中是否包含图片URL
                    if "生成的图片：" in result and "http" in result:
                        try:
                            # 提取图片URL
                            url_match = re.search(r'生成的图片：(https?://[^\s\n]+)', result)
                            if url_match:
                                image_url = url_match.group(1)
                                logger.info(f"[Yuewen] 提取到图片URL: {image_url}")
                                
                                try:
                                    # 使用辅助方法下载并发送图片
                                    image_sent = await self.send_image_from_url(bot, from_wxid, image_url)
                                    
                                    if image_sent:
                                        # 发送纯文本部分（如果有）
                                        text_parts = result.split("生成的图片：")
                                        if text_parts[0].strip():
                                            # 格式化文本，移除多余信息
                                            clean_text = self._process_final_text(text_parts[0])
                                            await bot.send_text_message(from_wxid, clean_text)
                                        
                                        # 图片已发送，不再进行后续处理
                                        return False
                                    else:
                                        # 图片发送失败，继续发送原始文本（包含URL）
                                        logger.warning(f"[Yuewen] 图片发送失败，将发送包含URL的文本")
                                except Exception as img_err:
                                    logger.error(f"[Yuewen] 处理图片URL时出错: {img_err}", exc_info=True)
                        except Exception as e:
                            logger.error(f"[Yuewen] 处理图片URL时出错: {e}", exc_info=True)
                    
                    # 如果没有图片URL或处理失败，发送原始文本结果
                    await bot.send_text_message(from_wxid, result)
                else:
                    await bot.send_text_message(from_wxid, "❌ 图片处理失败，请稍后重试")
                
                return False
                
            else:
                # 旧版API
                # 上传图片
                file_id = await self._upload_image_old_async(image_data)
                if not file_id:
                    await bot.send_text_message(from_wxid, "❌ 图片上传失败")
                    return False
                    
                # 检查文件状态
                if not await self._check_file_status_async(file_id):
                    await bot.send_text_message(from_wxid, "❌ 图片处理失败")
                    return False
                    
                # 获取图片尺寸
                try:
                    from PIL import Image
                    from io import BytesIO
                    img = Image.open(BytesIO(image_data))
                    width, height = img.size
                    file_size = len(image_data)
                except Exception as e:
                    logger.error(f"[Yuewen] 获取图片尺寸失败: {e}")
                    width, height = 800, 600
                    file_size = len(image_data)
                    
                # 创建图片附件
                attachments = [{
                    "fileId": file_id,
                    "type": "image/jpeg",
                    "width": width,
                    "height": height,
                    "size": file_size
                }]
                
                # 获取识图提示词
                prompt = self.waiting_for_image[user_id].get('prompt', self.imgprompt)
                
                # 发送消息
                await bot.send_text_message(from_wxid, "🔄 正在处理图片，请稍候...")
                result = await self._send_message_old_async(prompt, attachments)
                
                # 清除识图请求
                self.waiting_for_image.pop(user_id, None)
                
                # 发送结果
                if result:
                    await bot.send_text_message(from_wxid, result)
                else:
                    await bot.send_text_message(from_wxid, "❌ 图片处理失败，请稍后重试")
                    
                return False
        
        # 检查是否等待多张图片
        elif user_id in self.multi_image_data:
            logger.info(f"[Yuewen] 用户 {user_id} 正在等待多图上传，处理图片消息")
            multi_data = self.multi_image_data[user_id]
            try:
                # 下载图片
                image_data = await self.download_image(bot, message)
                
                if not image_data:
                    await bot.send_text_message(from_wxid, "❌ 无法获取图片数据，请重试")
                    return False
                    
                # 根据API版本选择不同的上传方法
                if self.api_version == 'new':
                    # 使用新版API上传图片
                    file_id = await self._upload_image_new_async(image_data)
                    if not file_id:
                        # 获取最后一次尝试上传的错误信息
                        error_detail = ""
                        if hasattr(self, '_last_upload_error') and self._last_upload_error:
                            error_detail = f": {self._last_upload_error}"
                        
                        await bot.send_text_message(from_wxid, f"❌ 图片上传失败{error_detail}\n请稍后重试或联系管理员检查日志")
                        return False
                        
                    # 获取图片尺寸
                    try:
                        from PIL import Image
                        from io import BytesIO
                        img = Image.open(BytesIO(image_data))
                        width, height = img.size
                    except Exception as e:
                        logger.error(f"[Yuewen] 获取图片尺寸失败: {e}")
                        width, height = 800, 600  # 使用默认尺寸
                        
                    # 保存上传结果，包括完整响应
                    image_info = {
                        'file_id': file_id,
                        'width': width,
                        'height': height,
                        'size': len(image_data)
                    }
                    
                    # 保存完整的服务器响应（如果有）
                    if hasattr(self, '_last_image_response') and self._last_image_response:
                        image_info['response_data'] = self._last_image_response
                        
                    # 添加到多图列表
                    multi_data['images'].append(image_info)
                else:
                    # 旧版API上传图片
                    file_id = await self._upload_image_old_async(image_data)
                    if not file_id:
                        await bot.send_text_message(from_wxid, "❌ 图片上传失败")
                        return False
                        
                    # 检查文件状态
                    if not await self._check_file_status_async(file_id):
                        await bot.send_text_message(from_wxid, "❌ 图片处理失败")
                        return False
                        
                    # 获取图片尺寸
                    try:
                        from PIL import Image
                        from io import BytesIO
                        img = Image.open(BytesIO(image_data))
                        width, height = img.size
                        file_size = len(image_data)
                    except Exception as e:
                        logger.error(f"[Yuewen] 获取图片尺寸失败: {e}")
                        width, height = 800, 600
                        file_size = len(image_data)
                        
                    # 添加到多图列表
                    multi_data['images'].append({
                        'file_id': file_id,
                        'width': width,
                        'height': height,
                        'size': file_size
                    })
                
                # 检查是否已收集足够的图片
                if len(multi_data['images']) >= multi_data['count']:
                    # 所有图片已收集完成，发送处理消息
                    await bot.send_text_message(from_wxid, "✅ 所有图片已接收完成，正在处理...")
                    
                    # 处理多图片
                    await self._process_multi_images_async(
                        bot,
                        multi_data['images'], 
                        multi_data['prompt'], 
                        from_wxid
                    )
                    
                    # 清除多图数据
                    self.multi_image_data.pop(user_id, None)
                else:
                    # 仍需更多图片
                    remaining = multi_data['count'] - len(multi_data['images'])
                    await bot.send_text_message(
                        from_wxid, 
                        f"✅ 已接收 {len(multi_data['images'])}/{multi_data['count']} 张图片，还需 {remaining} 张\n" + 
                        "请继续发送图片，发送完毕后请发送'结束'开始处理"
                    )
                    
                return False
                    
            except Exception as e:
                logger.error(f"[Yuewen] 处理多图片时出错: {e}", exc_info=True)
                await bot.send_text_message(from_wxid, f"❌ 处理图片出错: {str(e)}")
                return False
        
        else:
            # 用户没有pending的图片请求，忽略该图片
            logger.debug(f"[Yuewen] 用户 {user_id} 没有待处理的图片请求，忽略图片消息")
            return True  # 让其他插件处理

    def _process_final_text(self, text):
        """统一的文本后处理函数
        
        处理文本，移除不可见字符，规范化换行符等
        以改善用户阅读体验
        
        Args:
            text: 原始文本
            
        Returns:
            str: 处理后的文本
        """
        if not text:
            return ""
            
        # 移除Unicode零宽字符
        text = re.sub(r'[\u200b-\u200f\u2028-\u202f\ufeff]', '', text)
        
        # 规范化不同类型的换行符
        text = re.sub(r'\r\n', '\n', text)
        text = re.sub(r'\r', '\n', text)
        
        # 合并多个连续换行符为两个
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 处理markdown列表格式，确保列表项前有换行
        text = re.sub(r'([^\n])\n([-*]\s)', r'\1\n\n\2', text)
        
        # 从文本中移除模型信息前缀
        text = re.sub(r'^使用.*模型.*模式回答.*秒）：\s*\n+', '', text)
        
        # 移除图片生成相关的状态信息
        text = re.sub(r'\[正在生成图片，请稍候...\]', '', text)
        text = re.sub(r'\[图片已生成，耗时\d+\.\d+秒\]', '', text)
        text = re.sub(r'\[图片生成失败或超时，耗时\d+\.\d+秒\]', '', text)
        
        # 删除末尾的换行符
        text = text.rstrip()
        
        return text

    async def _upload_image_old_async(self, image_bytes):
        """上传图片到旧版API服务器（异步版本）"""
        if self.api_version == 'new':
            logger.warning("[Yuewen] _upload_image_old_async (old API) called in new API mode.")
            return None  # 在新模式下调用旧上传是错误的

        logger.debug("[Yuewen][Old API] Executing _upload_image_old_async.")
        try:
            if not image_bytes:
                logger.error("[Yuewen][Old API] 图片数据为空")
                return None

            file_size = len(image_bytes)
            logger.debug(f"[Yuewen][Old API] 准备上传图片，大小: {file_size} 字节")
            file_name = f"n_v{random.getrandbits(128):032x}.jpg"
            logger.debug(f"[Yuewen][Old API] 生成的文件名: {file_name}")

            headers = self._update_headers()  # 获取适配旧版的 headers
            # 添加旧版上传特有的 headers
            headers.update({
                'accept': '*/*',
                'accept-language': 'zh-CN,zh;q=0.9',
                'cache-control': 'no-cache',
                'content-type': 'image/jpeg',  # 明确指定
                'content-length': str(file_size),  # 明确指定
                'pragma': 'no-cache',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'stepchat-meta-size': str(file_size)  # 旧版特有
            })

            # 旧版 referer 可能需要带 chat ID
            if self.current_chat_id:
                headers['referer'] = f'{self.current_base_url}/chats/{self.current_chat_id}'
            else:
                headers['referer'] = f'{self.current_base_url}/chats/'  # 备用

            upload_url = f'{self.current_base_url}/api/storage?file_name={file_name}'
            logger.debug(f"[Yuewen][Old API] 开始上传图片到: {upload_url}")

            for retry in range(2):
                try:
                    # 使用异步HTTP客户端发送请求
                    async with self.http_session.put(
                        upload_url,
                        headers=headers,
                        data=image_bytes,  # 直接使用二进制数据
                        timeout=45
                    ) as response:
                        if response.status == 200:
                            upload_result = await response.json()
                            file_id = upload_result.get('id')
                            if file_id:
                                logger.debug(f"[Yuewen][Old API] 文件上传成功，ID: {file_id}")
                                # 旧版上传成功后，通常需要检查文件状态
                                if await self._check_file_status_async(file_id):
                                    logger.info(f"[Yuewen][Old API] File status check successful for ID: {file_id}")
                                    return file_id  # 返回文件 ID
                                else:
                                    logger.error(f"[Yuewen][Old API] File status check failed after upload for ID: {file_id}")
                                    return None  # 文件状态检查失败
                            else:
                                logger.error(f"[Yuewen][Old API] Upload success but file ID not found in response: {upload_result}")
                                return None

                        elif response.status == 401 and retry == 0:
                            logger.warning("[Yuewen][Old API] Token expired during upload, refreshing...")
                            if await self.login_handler.refresh_token():
                                # 刷新成功后，需要更新 headers 再次尝试
                                headers = self._update_headers()  # 重新获取基础 headers
                                # 重新添加上传特定 headers
                                headers.update({
                                    'accept': '*/*', 'accept-language': 'zh-CN,zh;q=0.9',
                                    'cache-control': 'no-cache', 'content-type': 'image/jpeg',
                                    'content-length': str(file_size), 'pragma': 'no-cache',
                                    'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'cors',
                                    'sec-fetch-site': 'same-origin', 'stepchat-meta-size': str(file_size)
                                })
                                if self.current_chat_id:
                                    headers['referer'] = f'{self.current_base_url}/chats/{self.current_chat_id}'
                                else:
                                    headers['referer'] = f'{self.current_base_url}/chats/'
                                logger.info("[Yuewen][Old API] Token refreshed, retrying upload...")
                                continue  # 重试
                            else:
                                logger.error("[Yuewen][Old API] Token refresh failed.")
                                return None  # 刷新失败，直接返回
                        else:
                            error_text = await response.text()
                            logger.error(f"[Yuewen][Old API] 上传失败: HTTP {response.status} - {error_text[:200]}")
                            # 其他错误，如果是第一次尝试，可以选择重试
                            if retry < 1:
                                continue
                            return None  # 重试后仍失败或非 401 错误

                except aiohttp.ClientError as e:
                    logger.error(f"[Yuewen][Old API] 上传 HTTP错误: {e}")
                    if retry == 0:
                        # 网络错误也尝试刷新 token 重试
                        if await self.login_handler.refresh_token():
                            continue
                    return None  # 重试失败或刷新失败
                except Exception as e:
                    logger.error(f"[Yuewen][Old API] 上传未知错误: {e}", exc_info=True)
                    # 未知错误通常不重试
                    return None
            # 循环结束仍未成功
            logger.error("[Yuewen][Old API] Upload failed after all retries.")
            return None
        except Exception as e:  # 捕获最外层的意外错误
            logger.error(f"[Yuewen][Old API] 上传图片函数失败: {e}", exc_info=True)
            return None

    async def _check_file_status_async(self, file_id):
        """检查文件状态（异步版本）"""
        if self.api_version == 'new':
            logger.warning(f"[Yuewen] _check_file_status_async called in new API mode, which is not supported.")
            return False  # 返回False表示失败

        max_retries = 5  # 最大重试次数
        retry_interval = 0.5  # 重试间隔(秒)
        
        headers = self._update_headers()
        headers.update({
            'Content-Type': 'application/json',
            'canary': 'false',
            'connect-protocol-version': '1',
            'oasis-appid': '10200',
            'oasis-mode': '2',
            'oasis-platform': 'web',
            'priority': 'u=1, i',
            'x-waf-client-type': 'fetch_sdk'
        })
        
        for i in range(max_retries):
            try:
                async with self.http_session.post(
                    f'{self.current_base_url}/api/proto.file.v1.FileService/GetFileStatus',
                    headers=headers,
                    json={"id": file_id},
                    timeout=10
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("fileStatus") == 1:  # 1表示成功
                            return True
                        elif not data.get("needFurtherCall", True):  # 如果不需要继续查询
                            return False
                    elif response.status == 401:
                        if await self.login_handler.refresh_token():
                            continue
                        return False
                    
                await asyncio.sleep(retry_interval)
            except Exception as e:
                logger.error(f"[Yuewen] 检查文件状态失败: {str(e)}")
                if i < max_retries - 1:  # 如果不是最后一次重试
                    await asyncio.sleep(retry_interval)
        
        return False

    async def _upload_image_new_async(self, image_bytes):
        """上传图片到新版 StepFun API (异步版本)"""
        logger.debug("[Yuewen][New API] Executing _upload_image_new_async.")
        
        # 重置错误信息
        self._last_upload_error = None
        
        if not image_bytes:
            logger.error("[Yuewen][New API] Image data is empty for upload.")
            self._last_upload_error = "图片数据为空"
            return None
            
        # 检查令牌有效性
        logger.debug("[Yuewen][New API] 上传前检查令牌有效性")
        token_valid = await self._ensure_token_valid_async()
        if not token_valid:
            logger.error("[Yuewen][New API] 令牌无效或刷新失败")
            self._last_upload_error = "认证令牌无效，请重新登录"
            return None

        # 上传参数
        upload_url = f'{self.current_base_url}/api/resource/image'
        file_name = f"upload_{int(time.time() * 1000)}.jpg"
        mime_type = 'image/jpeg'
        
        # 请求头 - 精确匹配curl
        headers = {
            'accept': '*/*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'oasis-appid': '10200',
            'oasis-platform': 'web',
            'origin': self.current_base_url,
            'priority': 'u=1, i',
            'referer': f'{self.current_base_url}/chats/{self.current_chat_session_id or "new"}',
            'sec-ch-ua': '"Chromium";v="136", "Microsoft Edge";v="136", "Not.A/Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
            'x-waf-client-type': 'fetch_sdk'
        }
        
        # 重试参数
        max_retries = 3
        retry_delay = 1.0
        
        for retry in range(max_retries):
            try:
                if retry > 0:
                    logger.warning(f"[Yuewen][New API] 上传图片重试 ({retry}/{max_retries})")
                    await asyncio.sleep(retry_delay * retry)
                
                # 准备Cookie (每次重试重新获取)
                cookies = {}
                
                # 获取令牌 - 使用完整令牌，不分割
                if self.config.get('oasis_webid'):
                    cookies['Oasis-Webid'] = self.config.get('oasis_webid')
                
                # 使用完整的复合令牌
                if self.config.get('oasis_token'):
                    token = self.config.get('oasis_token', '')
                    cookies['Oasis-Token'] = token
                    logger.debug(f"[Yuewen][New API] 使用令牌，长度: {len(token)}")
                else:
                    logger.error("[Yuewen][New API] 配置中未找到令牌")
                    self._last_upload_error = "未找到访问令牌"
                    return None
                
                # 添加其他必要Cookie
                cookies['i18next'] = 'zh'
                cookies['_tea_utm_cache_20002086'] = '{%22utm_source%22:%22share%22%2C%22utm_content%22:%22web_image_share%22}'
                cookies['sidebar_state'] = 'false'
                
                logger.debug(f"[Yuewen][New API] 上传URL: {upload_url}")
                logger.debug(f"[Yuewen][New API] 上传图片大小: {len(image_bytes)}字节")
                
                # 尝试使用requests库 (首选方式)
                try:
                    import requests
                    
                    logger.debug(f"[Yuewen][New API] 使用requests库上传图片")
                    
                    # 准备文件和表单数据 - 精确匹配curl格式
                    files = {
                        'file': (file_name, image_bytes, mime_type)
                    }
                    
                    data = {
                        'scene_id': 'image',
                        'mime_type': mime_type
                    }
                    
                    # 发送请求 - 不设置content-type，让requests自动处理multipart/form-data边界
                    response = requests.post(
                        upload_url,
                        headers=headers, 
                        cookies=cookies,
                        files=files,
                        data=data,
                        timeout=30
                    )
                    
                    status_code = response.status_code
                    
                    if status_code == 200:
                        try:
                            result = response.json()
                            if result and result.get('rid'):
                                rid = result['rid']
                                logger.info(f"[Yuewen][New API] 图片上传成功，rid: {rid}")
                                
                                # 存储完整的响应结果，以便后续构建图片附件时使用
                                self._last_image_response = result
                                
                                return rid
                            else:
                                logger.warning(f"[Yuewen][New API] 上传成功但找不到图片ID: {result}")
                                self._last_upload_error = "服务器返回数据不完整"
                        except Exception as e:
                            logger.error(f"[Yuewen][New API] 解析上传响应失败: {e}")
                            self._last_upload_error = "解析响应失败"
                    else:
                        response_text = response.text
                        logger.error(f"[Yuewen][New API] 上传失败: HTTP {status_code}")
                        logger.debug(f"[Yuewen][New API] 响应内容: {response_text[:200]}")
                        
                        if "token is illegal" in response_text:
                            logger.error("[Yuewen][New API] 令牌被拒绝")
                            self._last_upload_error = "令牌被服务器拒绝"
                            
                            # 尝试刷新令牌
                            current_time = time.time()
                            if not hasattr(self, 'last_token_refresh') or (current_time - self.last_token_refresh) > 30:
                                self.last_token_refresh = current_time
                                if await self.login_handler.refresh_token():
                                    logger.info("[Yuewen][New API] 令牌已刷新，将在下次重试")
                            else:
                                logger.warning("[Yuewen][New API] 令牌刷新太频繁，跳过")
                        elif status_code == 401:
                            logger.error("[Yuewen][New API] 未授权错误 (401)")
                            self._last_upload_error = "未授权 (401)"
                            
                            if await self.login_handler.refresh_token():
                                logger.info("[Yuewen][New API] 令牌已刷新，将在下次重试")
                            else:
                                logger.error("[Yuewen][New API] 令牌刷新失败")
                                self._last_upload_error = "令牌刷新失败"
                        else:
                            self._last_upload_error = f"HTTP {status_code}"
                            
                except ImportError:
                    # 回退到aiohttp - 如果requests不可用
                    logger.warning("[Yuewen][New API] requests库未安装，回退到aiohttp")
                    
                    # 生成一个随机边界 - 与curl类似
                    boundary = f"----WebKitFormBoundary{random.getrandbits(64):x}"
                    
                    # 设置Content-Type头，显式包含边界
                    headers['content-type'] = f'multipart/form-data; boundary={boundary}'
                    
                    # 手动构建multipart请求数据
                    data = bytearray()
                    
                    # 添加文件部分
                    data.extend(f'--{boundary}\r\n'.encode('utf-8'))
                    data.extend(f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode('utf-8'))
                    data.extend(f'Content-Type: {mime_type}\r\n\r\n'.encode('utf-8'))
                    data.extend(image_bytes)
                    data.extend(b'\r\n')
                    
                    # 添加scene_id字段
                    data.extend(f'--{boundary}\r\n'.encode('utf-8'))
                    data.extend(f'Content-Disposition: form-data; name="scene_id"\r\n\r\n'.encode('utf-8'))
                    data.extend(b'image\r\n')
                    
                    # 添加mime_type字段
                    data.extend(f'--{boundary}\r\n'.encode('utf-8'))
                    data.extend(f'Content-Disposition: form-data; name="mime_type"\r\n\r\n'.encode('utf-8'))
                    data.extend(f'{mime_type}\r\n'.encode('utf-8'))
                    
                    # 添加结束边界
                    data.extend(f'--{boundary}--\r\n'.encode('utf-8'))
                    
                    # 创建一个新的aiohttp会话用于上传
                    async with aiohttp.ClientSession(cookies=cookies) as session:
                        async with session.post(
                            upload_url,
                            headers=headers,
                            data=data,
                            timeout=30
                        ) as response:
                            status_code = response.status
                            
                            if status_code == 200:
                                try:
                                    result = await response.json()
                                    if result and result.get('rid'):
                                        rid = result['rid']
                                        logger.info(f"[Yuewen][New API] 图片上传成功，rid: {rid}")
                                        
                                        # 存储完整的响应结果，以便后续构建图片附件时使用
                                        self._last_image_response = result
                                        
                                        return rid
                                    else:
                                        logger.warning(f"[Yuewen][New API] 上传成功但找不到图片ID: {result}")
                                        self._last_upload_error = "服务器返回数据不完整"
                                except Exception as e:
                                    logger.error(f"[Yuewen][New API] 解析上传响应失败: {e}")
                                    self._last_upload_error = "解析响应失败"
                                    
                            else:
                                response_text = await response.text()
                                logger.error(f"[Yuewen][New API] 上传失败: HTTP {status_code}")
                                logger.debug(f"[Yuewen][New API] 响应内容: {response_text[:200]}")
                                
                                if "token is illegal" in response_text:
                                    logger.error("[Yuewen][New API] 令牌被拒绝")
                                    self._last_upload_error = "令牌被服务器拒绝"
                                    
                                    current_time = time.time()
                                    if not hasattr(self, 'last_token_refresh') or (current_time - self.last_token_refresh) > 30:
                                        self.last_token_refresh = current_time
                                        if await self.login_handler.refresh_token():
                                            logger.info("[Yuewen][New API] 令牌已刷新，将在下次重试")
                                    else:
                                        logger.warning("[Yuewen][New API] 令牌刷新太频繁，跳过")
                                elif status_code == 401:
                                    logger.error("[Yuewen][New API] 未授权错误 (401)")
                                    self._last_upload_error = "未授权 (401)"
                                    
                                    if await self.login_handler.refresh_token():
                                        logger.info("[Yuewen][New API] 令牌已刷新，将在下次重试")
                                    else:
                                        logger.error("[Yuewen][New API] 令牌刷新失败")
                                        self._last_upload_error = "令牌刷新失败"
                                else:
                                    self._last_upload_error = f"HTTP {status_code}"
            
            except Exception as e:
                logger.error(f"[Yuewen][New API] 上传图片时发生异常: {e}")
                logger.debug(f"[Yuewen][New API] 异常详情: {traceback.format_exc()}")
                self._last_upload_error = f"上传异常: {str(e)}"
        
        # 所有重试失败
        logger.error("[Yuewen][New API] 图片上传失败，重试次数用尽")
        if not self._last_upload_error:
            self._last_upload_error = "上传失败，请稍后重试"
        return None

    async def _parse_stream_response_old_async(self, response, start_time):
        """解析旧版API的流式响应（异步版本）"""
        buffer = bytearray()
        text_buffer = []
        has_thinking_stage = False
        is_done = False
        user_message_id = None
        ai_message_id = None

        try:
            current_model = next((m for m in self.models.values() if m['id'] == self.current_model_id), None)
            model_name = current_model['name'] if current_model else f"未知模型(ID: {self.current_model_id})"
            
            logger.debug(f"[Yuewen][Old API] 开始处理响应，使用模型: {model_name}")
            logger.debug(f"[Yuewen][Old API] 当前会话ID: {self.current_chat_id}")
            
            # 处理流式响应
            async for chunk in response.content.iter_chunked(1024):  # 使用aiohttp的异步迭代器
                buffer.extend(chunk)
                
                # 确保至少有5字节的头部
                while len(buffer) >= 5:
                    # 解析头部 (msg_type + length)
                    try:
                        msg_type, length = struct.unpack('>BI', buffer[:5])
                    except struct.error:
                        logger.warning(f"[Yuewen][Old API] Struct unpack error on buffer prefix: {buffer[:10].hex()}. Clearing buffer.")
                        buffer.clear()  # 清理损坏的buffer
                        break  # 跳出内部while，处理下一个chunk
                    
                    # 如果没有足够的数据继续
                    if len(buffer) < 5 + length:
                        break
                    
                    # 提取消息体
                    packet = buffer[5:5+length]
                    buffer = buffer[5+length:]  # 从buffer中移除已处理的数据包
                    
                    # 解析JSON数据包
                    try:
                        packet_str = packet.decode('utf-8')
                        data = json.loads(packet_str)
                        
                        # 处理textEvent事件（包含实际文本内容）
                        if 'textEvent' in data:
                            event = data['textEvent']
                            # 跳过思考阶段消息，不显示"正在思考..."
                            if event.get('stage') == 'TEXT_STAGE_THINKING':
                                has_thinking_stage = True
                                continue
                            if event.get('stage') and event.get('stage') != 'TEXT_STAGE_SOLUTION':
                                continue
                            content = event.get('text', '')
                            if content:
                                text_buffer.append(content)
                                # 仅在调试级别输出，减少日志量
                                if content and len(content) > 20:
                                    # 确保不输出太长的内容
                                    logger.debug(f"[Yuewen][Old API] 接收到文本: {content[:20]}...")
                        
                        # 处理startEvent事件（包含消息ID信息）
                        if 'startEvent' in data:
                            start_event = data['startEvent']
                            ai_message_id = start_event.get('messageId')
                            parent_id = start_event.get('parentMessageId')
                            if parent_id:
                                user_message_id = parent_id
                                
                        # 处理doneEvent事件（表示响应结束）
                        if 'doneEvent' in data:
                            is_done = True
                            logger.debug("[Yuewen][Old API] 接收到完成事件")
                            # 继续处理buffer中剩余内容，确保不丢失数据
                            
                    except json.JSONDecodeError as e:
                        # 尝试处理格式错误的JSON
                        logger.warning(f"[Yuewen][Old API] 解析JSON失败: {e}, 尝试修复...")
                        
                        # 检查是否是多个JSON对象连在一起
                        try:
                            # 尝试处理多个JSON对象
                            packet_parts = re.findall(r'\{.*?\}', packet_str)
                            for json_part in packet_parts:
                                try:
                                    part_data = json.loads(json_part)
                                    # 处理文本事件
                                    if 'textEvent' in part_data:
                                        event = part_data['textEvent']
                                        content = event.get('text', '')
                                        if content and event.get('stage') != 'TEXT_STAGE_THINKING':
                                            text_buffer.append(content)
                                    # 处理完成事件
                                    if 'doneEvent' in part_data:
                                        is_done = True
                                except:
                                    pass
                        except Exception as nested_err:
                            logger.error(f"[Yuewen][Old API] 尝试修复JSON失败: {nested_err}")
                            continue  # 跳过这个损坏的包

                    except Exception as e:
                        logger.error(f"[Yuewen][Old API] 处理数据包时发生未知错误: {e}")
                        continue  # 跳过这个包
            
            # 循环结束后检查是否收到done事件
            if not is_done:
                # 如果文本缓冲区有内容，可能只是没收到done，尝试返回已有内容
                if text_buffer:
                    logger.warning("[Yuewen][Old API] Stream ended but doneEvent not found, returning buffered text.")
                else:
                    logger.error("[Yuewen][Old API] Stream ended but doneEvent not found and no text received.")
                    return "响应未完成或为空，请重试"  # 返回错误信息
            
            # 计算耗时
            cost_time = time.time() - start_time
            
            # 组合最终文本
            final_text = ''.join(text_buffer)
            final_text = self._process_final_text(final_text)
            
            # 更新最近消息记录(用于分享)
            if self.current_chat_id and user_message_id and ai_message_id:
                logger.debug(f"[Yuewen][Old API] 记录消息ID - User: {user_message_id}, AI: {ai_message_id}")
                # 保存用户和AI消息ID，用于后续使用
                self.last_user_message_id = user_message_id
                self.last_bot_message_id = ai_message_id
                
                # 保存消息ID用于分享功能
                self.last_message = {
                    'chat_id': self.current_chat_id,
                    'messages': [
                        {'messageId': ai_message_id, 'messageIndex': 2},  # AI消息
                        {'messageId': user_message_id, 'messageIndex': 1}  # 用户消息
                    ],
                    'last_time': time.time()
                }
            
            # 构建返回结果
            if final_text:
                network_mode = "联网" if self.config.get('network_mode', False) else "未联网"
                status_info = f"使用{model_name}模型{network_mode}模式回答（耗时{cost_time:.2f}秒）："
                # 旧版 API 返回带分享提示的字符串
                share_info = "\n\n3分钟内发送yw分享获取回答图片"
                result = f"{status_info}{final_text}{share_info}"
                logger.info(f"[Yuewen][Old API] 响应成功 (使用{model_name}模型{network_mode}模式, 耗时{cost_time:.2f}秒)")
                return result
            
            logger.warning(f"[Yuewen][Old API] No valid text reply received (cost: {cost_time:.2f}s).")
            return f"未收到有效回复（耗时{cost_time:.2f}秒）"
            
        except Exception as e:
            logger.error(f"[Yuewen][Old API] 解析响应异常: {e}", exc_info=True)
            return f"解析响应异常: {str(e)}"