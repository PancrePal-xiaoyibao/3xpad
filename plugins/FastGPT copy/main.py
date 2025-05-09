# --- START OF FILE FastGPT/main.py ---
from typing import Optional, List, Dict, Any # 添加 Dict, Any
import asyncio
import base64 # 确保 base64 被导入
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
import uuid

# 优先尝试导入标准库的 tomllib (Python 3.11+)
try:
    import tomllib
except ImportError:
    # 如果失败，尝试导入 tomli (需要 pip install tomli)
    try:
        import tomli as tomllib
    except ImportError:
        # 如果两者都失败，将 tomllib 设为 None，后续逻辑会处理
        tomllib = None

import aiohttp
from loguru import logger
from PIL import Image, ImageFile

from WechatAPI import WechatAPIClient
from database.XYBotDB import XYBotDB
from utils.decorators import *
from utils.plugin_base import PluginBase

# 尝试导入 minio
try:
    from minio import Minio
    from minio.error import S3Error
    minio_available = True
except ImportError:
    minio_available = False
    # 不在这里打日志，推迟到 __init__ 中根据配置判断是否需要 minio 时再打

ImageFile.LOAD_TRUNCATED_IMAGES = True


class FastGPT(PluginBase):
    description = "FastGPT知识库问答插件"
    author = "老夏的金库"
    version = "1.3.0" # 版本号更新，体现新功能
    is_ai_platform = True

    def __init__(self):
        super().__init__()
        logger.info("Initializing FastGPT Plugin...")
        self.enable = False # 默认禁用，初始化成功后再启用

        # 1. 检查和安装依赖 (包括 tomli)
        self._check_and_install_dependencies()

        # 2. 再次确认 TOML 库是否可用
        if tomllib is None: # 如果模块顶部的导入尝试都失败了
            try:
                import tomli as final_tomllib_attempt # 尝试在依赖安装后再次导入tomli
                globals()['tomllib'] = final_tomllib_attempt # 更新全局别名
                logger.info("Successfully imported 'tomli' and aliased as 'tomllib' after dependency check.")
            except ImportError:
                logger.error("TOML library ('tomllib' or 'tomli') is not available even after dependency check. Cannot parse config.toml. FastGPT plugin will be disabled.")
                return # 初始化失败，保持 self.enable = False

        try:
            # 3. 读取主配置
            with open("main_config.toml", "rb") as f:
                main_config = tomllib.load(f)
            logger.debug("Main config loaded.")

            # 4. 读取插件配置
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            logger.debug(f"Attempting to load config from: {config_path}")

            with open(config_path, "rb") as f:
                plugin_config_data = tomllib.load(f)
                logger.debug(f"Plugin config loaded from {config_path}")

            plugin_config = plugin_config_data.get("FastGPT", {})
            self.plugin_config = plugin_config  # 保存整个配置以便后续使用

            if not plugin_config:
                logger.error("No [FastGPT] section found in config.toml")
                return
            # --- 开始读取配置 ---
            _enable_from_config = plugin_config.get("enable", False) # 临时变量
            logger.debug(f"Config enable status: {_enable_from_config}")

            self.api_key = plugin_config.get("api-key", "")
            self.base_url = plugin_config.get("base-url", "https://api.fastgpt.in/api")
            self.app_id = plugin_config.get("app-id", "")

            # 命令配置
            self.commands = plugin_config.get("commands", [])
            self.command_tip = plugin_config.get("command-tip", "")
            self.detail = plugin_config.get("detail", False)
            self.http_proxy = plugin_config.get("http-proxy", "")

            # 图片分析相关配置 (新增和修改)
            self.image_commands = plugin_config.get("image-commands", ["图片分析", "报告分析"])
            self.group_image_auto_upload_s3 = plugin_config.get("group_image_auto_upload_s3", True)
            self.image_context_ttl_seconds = plugin_config.get("image_context_ttl_seconds", 60)
            self.max_cached_images_per_user = plugin_config.get("max_cached_images_per_user", 5)
            self.default_image_analysis_prompt = plugin_config.get(
                "default_image_analysis_prompt",
                "请分析图片，识别主要内容，总结重点信息，并提示AI生成内容的使用风险。"
            )
            # 旧的 image_prompt 配置可以考虑移除或标记为废弃，以免混淆
            # self.image_prompt = plugin_config.get("image-prompts", "请描述这张图片的主要内容。") # 旧的，将被 default_image_analysis_prompt 替代

            # 积分系统配置
            self.price = plugin_config.get("price", 5)
            self.admin_ignore = plugin_config.get("admin_ignore", True)
            self.whitelist_ignore = plugin_config.get("whitelist_ignore", True)
            self.admins = main_config.get("XYBot", {}).get("admins", [])

            self.db = XYBotDB()

            # 图片处理相关配置
            self.storage_type = plugin_config.get("storage-type", "none").lower() # 默认 "none"
            self.image_tmp_dir = plugin_config.get("image-tmp-dir", "tmp/fastgpt_images")
            self.image_expire_time = plugin_config.get("image-expire-time", 300) # 本地临时文件过期时间
            self.cleanup_interval = plugin_config.get("cleanup-interval", 300) # 清理任务间隔
            self.max_image_size_bytes = plugin_config.get("max-image-size-bytes", 5 * 1024 * 1024)
            self.allowed_formats = [fmt.lower() for fmt in plugin_config.get("allowed-formats", ["jpg", "jpeg", "png", "gif", "webp"])]
            self.max_width = plugin_config.get("max-width", 2048)
            self.max_height = plugin_config.get("max-height", 2048)
            self.jpeg_quality = plugin_config.get("jpeg-quality", 85)

            self.s3_config = None
            self.s3_enable_local_backup = False
            if self.storage_type == "s3":
                global minio_available
                if not minio_available:
                    logger.error("Minio library is required for S3 storage but is not installed or failed to import. Please run 'pip install minio'. S3 storage will be disabled.")
                else:
                    self.s3_config = {
                        "access_key": plugin_config.get("s3-access-key", ""),
                        "secret_key": plugin_config.get("s3-secret-key", ""),
                        "endpoint": plugin_config.get("s3-endpoint", ""),
                        "bucket": plugin_config.get("s3-bucket", ""),
                        "secure": plugin_config.get("s3-secure", True),
                    }
                    if not all([self.s3_config["access_key"], self.s3_config["secret_key"], self.s3_config["endpoint"], self.s3_config["bucket"]]):
                        logger.error("S3 storage is enabled, but S3 configuration (access_key, secret_key, endpoint, bucket) is incomplete. S3 functionality will be disabled.")
                        self.s3_config = None
                    else:
                        access_key = self.s3_config["access_key"]
                        raw_bucket = self.s3_config["bucket"]
                        if not raw_bucket.startswith(f"{access_key}-"):
                            self.s3_config["bucket"] = f"{access_key}-{raw_bucket}"
                        logger.info(f"Using S3 bucket: {self.s3_config['bucket']}")
                        self.s3_enable_local_backup = plugin_config.get("s3-enable-local-backup", True)
                        logger.info(f"S3 local backup enabled: {self.s3_enable_local_backup}")

            elif self.storage_type != "none":
                 logger.warning(f"Unsupported storage_type '{self.storage_type}' configured. Only 's3' or 'none' are actively supported for generating image URLs for FastGPT. Image analysis might not work as expected without S3.")

            # --- 新增：初始化用户图片缓存 ---
            self.pending_user_images: Dict[str, List[Dict[str, Any]]] = {} # 例如: {"groupid_userid": [{"url": "...", "timestamp": ..., "msg_id": "..."}, ...]}
            logger.info("Initialized pending_user_images cache for group image analysis.")


            logger.debug(f"FastGPT initialization status check:")
            logger.debug(f"- enable from config: {_enable_from_config}")
            logger.debug(f"- api_key: {'set' if self.api_key else 'not set'}")
            logger.debug(f"- base_url: {'set' if self.base_url else 'not set'}")
            logger.debug(f"- app_id: {'set' if self.app_id else 'not set (optional)'}")
            logger.debug(f"- storage_type: {self.storage_type}")
            logger.debug(f"- s3_config valid: {bool(self.s3_config)}")
            logger.debug(f"- group_image_auto_upload_s3: {self.group_image_auto_upload_s3}")
            logger.debug(f"- image_context_ttl_seconds: {self.image_context_ttl_seconds}")
            logger.debug(f"- max_cached_images_per_user: {self.max_cached_images_per_user}")
            logger.debug(f"- default_image_analysis_prompt: {self.default_image_analysis_prompt[:50]}...")

            # 创建临时目录和启动清理任务 (本地备份或本地存储时)
            if (self.storage_type == "s3" and self.s3_enable_local_backup) or self.storage_type == "none": # "none" 时也可能用于临时文件，但此插件主要关注S3
                try:
                    os.makedirs(self.image_tmp_dir, exist_ok=True)
                    logger.info(f"Ensured image temp directory exists: {self.image_tmp_dir}")
                    # 清理任务现在也负责清理 pending_user_images
                    asyncio.create_task(self._cleanup_expired_items()) # 重命名清理任务
                    logger.info("Scheduled task for cleaning up expired local images and pending image contexts.")
                except OSError as e:
                    logger.error(f"Failed to create image_tmp_dir '{self.image_tmp_dir}': {e}. Local image backup/cleanup might fail.")


            if not _enable_from_config:
                logger.warning("FastGPT plugin is explicitly disabled in config.toml")
                return
            if not self.api_key:
                logger.error("FastGPT API key is not configured")
                return
            if not self.base_url:
                logger.error("FastGPT base URL is not configured")
                return

            self.enable = True
            logger.success("FastGPT Plugin initialized and enabled successfully")
            logger.info(f"Using base URL: {self.base_url}")
            if not self.app_id:
                logger.info("App ID not set, will use default conversation mode")

        except Exception as e:
            logger.error(f"FastGPT Plugin initialization failed: {e}")
            logger.error(traceback.format_exc())

    @on_text_message(priority=40)
    async def handle_text_message(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            logger.trace("FastGPT plugin is disabled, skipping text message.")
            return True

        content = message.get("Content", "").strip()
        is_group = message.get("IsGroup", False)
        sender_wxid = message.get("SenderWxid")
        from_wxid = message.get("FromWxid") # 群聊时是群ID，私聊时是对方ID

        logger.debug(f"Received text message: Group={is_group}, Sender={sender_wxid}, From={from_wxid}, Content='{content[:50]}...'")

        # --- 新增：群聊图片分析指令处理 ---
        if is_group:
            # 尝试去除@信息，如果存在的话 (假设@机器人 的格式)
            # 注意：这里的实现可能需要根据实际的 @ 格式调整
            cleaned_content = content
            if content.startswith("@"): # 简单判断，可能需要更鲁棒的 @机器人 移除逻辑
                parts = content.split(" ", 1)
                if len(parts) > 1:
                    cleaned_content = parts[1].strip()
                else: # 只有@机器人，没有后续内容
                    cleaned_content = ""
            
            is_image_analysis_command = any(cmd.lower() in cleaned_content.lower() for cmd in self.image_commands)
            
            if is_image_analysis_command:
                logger.info(f"Group message from {sender_wxid} in {from_wxid} matches image analysis command: '{cleaned_content}'")
                if not (self.storage_type == "s3" and self.s3_config):
                    logger.warning("Image analysis command received, but S3 storage is not configured. Cannot proceed.")
                    # 可以选择回复用户S3未配置，或静默处理
                    # await self._send_error_message(bot, message, "图片分析功能依赖S3存储，当前未正确配置。")
                    return True # 让其他插件处理

                cache_key = f"{from_wxid}_{sender_wxid}"
                user_cached_images = list(self.pending_user_images.get(cache_key, [])) # 复制列表
                
                current_time = time.time()
                valid_images = [
                    img_info for img_info in user_cached_images 
                    if (current_time - img_info['timestamp']) <= self.image_context_ttl_seconds
                ]

                if not valid_images:
                    logger.info(f"No valid (non-expired) cached images found for {cache_key} for analysis.")
                    tip_message = "我没有找到您最近发送的需要分析的图片哦。请先发送图片，60秒内再用指令（如：图片分析）告诉我需要分析。"
                    # 如果user_cached_images不为空但valid_images为空，说明是过期了
                    if user_cached_images and not valid_images:
                        tip_message = "您之前发送的图片已超时（超过60秒），请重新发送图片后再试。"
                        # 清理掉该用户所有已过期的缓存
                        self.pending_user_images.pop(cache_key, None)
                        logger.info(f"Cleared all expired images for {cache_key} due to timeout on command.")
                    
                    await bot.send_at_message(from_wxid, f"\n{tip_message}", [sender_wxid])
                    return False # 消息已处理 (提示用户)

                # 分析最新的一张有效图片
                image_to_analyze = valid_images[-1] # 最新的在列表尾部
                logger.info(f"Found image to analyze for {cache_key}: {image_to_analyze['url']} (MsgId: {image_to_analyze['msg_id']})")

                # if not await self._check_point(bot, message):
                #     logger.info(f"User {sender_wxid} has insufficient points for FastGPT image analysis.")
                #     return False

                # 添加日志：准备API调用
                logger.info(f"Preparing FastGPT API call for image analysis")
                image_prompt_text = self.default_image_analysis_prompt
                messages_payload = [
                    {"role": "user", "content": [
                        {"type": "text", "text": image_prompt_text},
                        {"type": "image_url", "image_url": {"url": image_to_analyze['url']}}
                    ]}
                ]
                # chat_id 可以包含图片信息以示区分，或保持简单
                chat_id = f"{sender_wxid}_{self.app_id if self.app_id else 'default'}_image_analysis_{image_to_analyze['msg_id']}"
                logger.info(f"Calling FastGPT API for image analysis. ChatId: {chat_id}, Image URL: {image_to_analyze['url']}")

                # 添加日志：开始API调用
                logger.info(f"Starting FastGPT API call")
                result_content, success = await self._call_fastgpt_api(bot, message, messages_payload, chat_id)


                # 添加日志：API调用结果
                logger.info(f"FastGPT API call completed. Success: {success}")

                if success:
                    logger.info(f"FastGPT API call for image analysis successful for {cache_key}.")
                    await bot.send_at_message(from_wxid, f"\n{result_content}", [sender_wxid])
                    if self.price > 0:
                        if not (sender_wxid in self.admins and self.admin_ignore) and \
                           not (self.db.get_whitelist(sender_wxid) and self.whitelist_ignore):
                            self.db.add_points(sender_wxid, -self.price)
                            logger.info(f"Deducted {self.price} points from user {sender_wxid} for image analysis.")
                    
                    # 从缓存中移除被分析过的图片
                    if cache_key in self.pending_user_images:
                        try:
                            self.pending_user_images[cache_key].remove(image_to_analyze)
                            logger.info(f"Removed analyzed image {image_to_analyze['msg_id']} from cache for {cache_key}.")
                            if not self.pending_user_images[cache_key]: # 如果列表空了
                                self.pending_user_images.pop(cache_key, None)
                                logger.info(f"User cache for {cache_key} is now empty and removed.")
                        except ValueError:
                            logger.warning(f"Attempted to remove image {image_to_analyze['msg_id']} from cache for {cache_key}, but it was not found. (Might have been cleaned up or removed concurrently)")
                else:
                    logger.warning(f"FastGPT API call for image analysis failed for {cache_key}.")
                    # _call_fastgpt_api 内部会发送错误信息
                return False # 消息已处理

        # --- 原有的文本消息处理逻辑 ---
        query = ""
        if is_group: # 普通文本指令 (非图片分析)
            parts = content.split(" ", 1)
            command_word = parts[0]
            # 如果是图片分析指令，上面已经处理过了，这里不再重复匹配
            # 仅处理配置的普通文本命令
            if not command_word in self.commands:
                logger.trace(f"Command '{command_word}' not in FastGPT text commands, skipping.")
                return True
            if len(parts) < 2 or not parts[1].strip():
                logger.warning(f"Invalid command format or empty query for command '{command_word}'.")
                await bot.send_at_message(
                    from_wxid,
                    f"\n{self.command_tip or '请输入问题内容'}，例如：{self.commands[0]} 什么是FastGPT?",
                    [sender_wxid]
                )
                return False
            query = parts[1].strip()
        else: # 私聊
            query = content
            if not query:
                logger.trace("Private chat message is empty, skipping.")
                return True

        if not await self._check_point(bot, message):
            logger.info(f"User {sender_wxid} has insufficient points for FastGPT text query.")
            return False

        chat_id = f"{sender_wxid}_{self.app_id if self.app_id else 'default'}_text"
        logger.debug(f"Generated chatId for FastGPT text query: {chat_id}")

        try:
            messages_payload = [{"role": "user", "content": query}]
            logger.info(f"Calling FastGPT API for text query. ChatId: {chat_id}")
            result_content, success = await self._call_fastgpt_api(bot, message, messages_payload, chat_id)

            if success:
                logger.info(f"FastGPT API call successful for text query. Replying to user.")
                if is_group:
                    await bot.send_at_message(from_wxid, f"\n{result_content}", [sender_wxid])
                else:
                    await bot.send_text_message(from_wxid, result_content)
                if self.price > 0:
                    if not (sender_wxid in self.admins and self.admin_ignore) and \
                       not (self.db.get_whitelist(sender_wxid) and self.whitelist_ignore):
                        self.db.add_points(sender_wxid, -self.price)
                        logger.info(f"Deducted {self.price} points from user {sender_wxid} for text query.")
            else:
                logger.warning(f"FastGPT API call failed for text query. ChatId: {chat_id}")
            return False
        except Exception as e:
            logger.error(f"FastGPT text message handling failed: {e}")
            logger.error(traceback.format_exc())
            await self._send_error_message(bot, message, "处理您的文本请求时发生内部错误。")
            return False

    @on_image_message(priority=40)
    async def handle_image_message(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            logger.trace("FastGPT plugin is disabled, skipping image message.")
            return True

        is_group = message.get("IsGroup", False)
        sender_wxid = message.get("SenderWxid")
        from_wxid = message.get("FromWxid") # 群聊时是群ID，私聊时是对方ID
        msg_id = message.get("MsgId", str(uuid.uuid4()))
        # content字段在图片消息中通常不包含用户文本，特别是在群聊中，所以不再依赖它来触发图片分析

        logger.info(f"Received image message: MsgId={msg_id}, Group={is_group}, Sender={sender_wxid}, From={from_wxid}")

        # --- S3可用性检查 ---
        if not (self.storage_type == "s3" and self.s3_config):
            if is_group and self.group_image_auto_upload_s3:
                logger.warning(f"MsgId={msg_id}: Group image auto upload is enabled, but S3 storage is not configured. Cannot cache image for analysis.")
            elif not is_group:
                logger.warning(f"MsgId={msg_id}: Private image received, but S3 storage is not configured. Cannot analyze image.")
            # 可以选择性地回复用户S3未配置，或静默处理
            # await self._send_error_message(bot, message, "图片处理功能依赖S3存储，当前未正确配置。")
            return True # 让其他插件处理，或者表示无法处理

        # --- 群聊图片处理：上传并缓存 ---
        if is_group:
            if self.group_image_auto_upload_s3:
                logger.info(f"MsgId={msg_id}: Group image received. Attempting to upload to S3 and cache for potential analysis by user {sender_wxid} in {from_wxid}.")
                try:
                    image_data = await self._extract_image_data_from_message(bot, message)
                    if not image_data:
                        # _extract_image_data_from_message 内部应该已经记录错误
                        # 不在此处发送错误给用户，因为这只是后台缓存行为
                        logger.warning(f"MsgId={msg_id}: Failed to extract image data for caching. User will not be notified at this stage.")
                        return True # 允许其他插件处理

                    processed_image_data, image_format = await self._preprocess_image(image_data, msg_id)
                    if not processed_image_data:
                        logger.warning(f"MsgId={msg_id}: Failed to preprocess image for caching.")
                        return True

                    image_public_url = await self._save_to_s3_storage(processed_image_data, msg_id, image_format)
                    if not image_public_url:
                        logger.warning(f"MsgId={msg_id}: Failed to save image to S3 for caching.")
                        return True
                    
                    logger.info(f"MsgId={msg_id}: Image successfully uploaded to S3: {image_public_url}. Caching for user {sender_wxid} in group {from_wxid}.")
                    
                    cache_key = f"{from_wxid}_{sender_wxid}"
                    user_images_list = self.pending_user_images.get(cache_key, [])
                    
                    image_info = {
                        'url': image_public_url,
                        'timestamp': time.time(),
                        'msg_id': msg_id # 使用消息ID作为图片的唯一标识之一
                    }
                    
                    user_images_list.append(image_info)
                    
                    # 维护缓存大小
                    while len(user_images_list) > self.max_cached_images_per_user:
                        removed_image = user_images_list.pop(0) # 移除最旧的
                        logger.debug(f"Cache for {cache_key} exceeded max size. Removed oldest image: {removed_image['msg_id']}")
                    
                    self.pending_user_images[cache_key] = user_images_list
                    logger.info(f"Cached image {msg_id} for {cache_key}. Current cache size for user: {len(user_images_list)}. Total users in cache: {len(self.pending_user_images)}")
                    
                    # 不在此处回复用户，等待文本指令触发分析
                    return True # 图片已缓存，但让其他插件有机会处理原始图片消息（例如转发）
                
                except Exception as e:
                    logger.error(f"MsgId={msg_id}: Error during group image caching process for {sender_wxid} in {from_wxid}: {e}")
                    logger.error(traceback.format_exc())
                    # 仍然返回True，避免阻塞其他插件
                    return True
            else:
                logger.trace(f"MsgId={msg_id}: Group image auto upload to S3 is disabled. Skipping caching.")
                return True # 不缓存，让其他插件处理

        # --- 私聊图片处理：直接分析 (维持原有逻辑) ---
        else: # not is_group (私聊)
            logger.info(f"MsgId={msg_id}: Private image received. Proceeding with direct analysis for user {sender_wxid}.")
            if not await self._check_point(bot, message):
                logger.info(f"MsgId={msg_id}: User {sender_wxid} has insufficient points for FastGPT image analysis.")
                return False

            try:
                image_data = await self._extract_image_data_from_message(bot, message)
                if not image_data:
                    await self._send_error_message(bot, message, "无法解析图片数据。")
                    return False
                
                processed_image_data, image_format = await self._preprocess_image(image_data, msg_id)
                if not processed_image_data:
                    await self._send_error_message(bot, message, "图片处理失败。")
                    return False

                image_public_url = await self._save_to_s3_storage(processed_image_data, msg_id, image_format)
                if not image_public_url:
                    await self._send_error_message(bot, message, "图片上传到S3失败。")
                    return False
                
                logger.info(f"MsgId={msg_id}: Image uploaded to S3 for private analysis. Public URL: {image_public_url}")

                chat_id = f"{sender_wxid}_{self.app_id if self.app_id else 'default'}_private_image_{msg_id}"
                image_prompt_text = self.default_image_analysis_prompt # 使用统一的默认提示词

                messages_payload = [
                    {"role": "user", "content": [
                        {"type": "text", "text": image_prompt_text},
                        {"type": "image_url", "image_url": {"url": image_public_url}}
                    ]}
                ]
                logger.info(f"MsgId={msg_id}: Calling FastGPT API for private image analysis. ChatId: {chat_id}")
                result_content, success = await self._call_fastgpt_api(bot, message, messages_payload, chat_id)

                if success:
                    logger.info(f"MsgId={msg_id}: FastGPT API call for private image successful.")
                    await bot.send_text_message(from_wxid, result_content) # 私聊直接发送
                    if self.price > 0:
                        if not (sender_wxid in self.admins and self.admin_ignore) and \
                           not (self.db.get_whitelist(sender_wxid) and self.whitelist_ignore):
                            self.db.add_points(sender_wxid, -self.price)
                            logger.info(f"MsgId={msg_id}: Deducted {self.price} points from user {sender_wxid} for private image analysis.")
                else:
                    logger.warning(f"MsgId={msg_id}: FastGPT API call for private image failed.")
                    # _call_fastgpt_api 内部会发送错误信息
                return False # 消息已处理
            except Exception as e:
                logger.error(f"FastGPT private image message handling failed for MsgId={msg_id}: {e}")
                logger.error(traceback.format_exc())
                await self._send_error_message(bot, message, "处理您的图片时发生内部错误。")
                return False

    async def _extract_image_data_from_message(self, bot: WechatAPIClient, message: dict) -> Optional[bytes]:
        msg_id = message.get("MsgId", "unknown_msg_id")
        content = message.get("Content")
        logger.debug(f"MsgId={msg_id}: Attempting to extract image data. Content type: {type(content)}")

        if isinstance(content, bytes):
            # logger.info(f"MsgId={msg_id}: Content is bytes. Size: {len(content)}") # 已有类似日志
            try:
                # 简单的验证是否是图片数据头，更可靠的是尝试打开
                Image.open(io.BytesIO(content))
                logger.info(f"MsgId={msg_id}: Extracted image data directly from bytes content. Size: {len(content)}")
                return content
            except Exception as e:
                logger.warning(f"MsgId={msg_id}: Content is bytes but not a valid image: {e}")
                # 尝试调用 get_msg_image作为备选，如果平台API支持且有必要
                # if message.get("MsgSvrId"): # 或其他判断是否可调用get_msg_image的条件
                #    logger.info(f"MsgId={msg_id}: Bytes content was not image, attempting get_msg_image fallback.")
                #    # ... (调用 get_msg_image 的逻辑)
                return None
        elif isinstance(content, str):
            # Base64 编码的图片数据 (常见于某些机器人框架)
            # 常见图片格式的Base64前缀
            base64_prefixes = {
                '/9j/': 'jpeg', 'iVBOR': 'png', 'R0lGOD': 'gif', 'UklGR': 'webp', # webp 'RIFF...WEBPVP8 '
                'Qk0=': 'bmp' # BMP (BM)
            }
            is_base64_img = False
            for prefix in base64_prefixes:
                if content.startswith(prefix):
                    is_base64_img = True
                    break
            
            if is_base64_img:
                logger.info(f"MsgId={msg_id}: Content appears to be base64 encoded image string.")
                try:
                    # 确保padding正确
                    missing_padding = len(content) % 4
                    if missing_padding:
                        content += '=' * (4 - missing_padding)
                    image_data = base64.b64decode(content)
                    Image.open(io.BytesIO(image_data)) # 验证
                    logger.info(f"MsgId={msg_id}: Successfully decoded base64 image data. Size: {len(image_data)}")
                    return image_data
                except Exception as e:
                    logger.error(f"MsgId={msg_id}: Failed to decode base64 string or invalid image data: {e}. Head: {content[:100]}...")
                    return None

            # XML 格式 (常见于PC微信)
            if content.strip().startswith("<msg>"):
                logger.info(f"MsgId={msg_id}: Content appears to be XML, attempting to parse for image details.")
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(content)
                    img_element = root.find('.//img')
                    if img_element is not None:
                        # AESKey 和 FileId 等信息可能用于通过特定API下载，这里我们主要关注长度信息用于分块
                        cdn_thumb_aes_key = img_element.get('aeskey')
                        cdn_thumb_url = img_element.get('cdnthumburl')
                        cdn_thumb_len = img_element.get('cdnthumblength')
                        
                        # 优先使用高清图信息，如果存在
                        data_len_str = img_element.get('hdlength') or img_element.get('length')
                        
                        if data_len_str and data_len_str.isdigit():
                            data_len = int(data_len_str)
                            logger.info(f"MsgId={msg_id}: XML specifies image data length: {data_len}. Attempting chunked download via get_msg_image.")
                            
                            # 检查 MsgSvrId 是否存在，某些框架可能需要它
                            # msg_svr_id = message.get("MsgSvrId") or message.get("NewMsgId") # 根据框架调整
                            # if not msg_svr_id:
                            #    logger.warning(f"MsgId={msg_id}: MsgSvrId not found in message, get_msg_image might fail.")
                            
                            full_image_data = bytearray()
                            # chunk_size = 65536 # 64KB, 可根据API调整
                            chunk_size = 1024 * 512 # 512KB 尝试一个更大的chunk size
                            num_chunks = (data_len + chunk_size - 1) // chunk_size
                            
                            # `to_wxid` 在 get_msg_image 中通常指消息的来源方。
                            # 对于群消息，FromWxid是群ID，SenderWxid是发送者。
                            # 对于私聊消息，FromWxid是对方ID。
                            # get_msg_image的to_wxid参数可能需要根据bot API的具体实现来确定
                            # 通常是消息的直接来源，即 `message.get("FromWxid")`
                            api_target_wxid = message.get("FromWxid")
                            if message.get("IsGroup") and message.get("ChatRoomWxid"): # 如果是群消息且有ChatRoomWxid
                                api_target_wxid = message.get("ChatRoomWxid")


                            logger.debug(f"MsgId={msg_id}: Preparing to download {num_chunks} chunks for image of size {data_len} from target {api_target_wxid}.")

                            for i in range(num_chunks):
                                try:
                                    logger.debug(f"MsgId={msg_id}: Requesting chunk {i+1}/{num_chunks}, start_pos: {i * chunk_size}")
                                    chunk_data = await bot.get_msg_image(
                                        msg_id=msg_id, # 使用原始消息ID
                                        to_wxid=api_target_wxid, # 消息来源的群ID或用户ID
                                        data_len=data_len,
                                        start_pos=i * chunk_size
                                    )
                                    if chunk_data and len(chunk_data) > 0:
                                        full_image_data.extend(chunk_data)
                                        logger.debug(f"MsgId={msg_id}: Chunk {i+1}/{num_chunks} downloaded, size: {len(chunk_data)}. Total downloaded: {len(full_image_data)}")
                                    else:
                                        logger.error(f"MsgId={msg_id}: Chunk {i+1}/{num_chunks} download failed or returned empty data.")
                                        # 如果一个分块失败，可能需要重试或中止
                                        return None # 中止
                                except Exception as chunk_e:
                                    logger.error(f"MsgId={msg_id}: Error downloading chunk {i+1}/{num_chunks}: {chunk_e}", exc_info=True)
                                    return None # 中止
                                await asyncio.sleep(0.1) # 短暂延时避免请求过于频繁

                            if len(full_image_data) == data_len:
                                logger.info(f"MsgId={msg_id}: Chunked image download successful. Total size: {len(full_image_data)}")
                                # 验证一下是否是图片
                                try:
                                    Image.open(io.BytesIO(full_image_data))
                                    return bytes(full_image_data)
                                except Exception as img_val_e:
                                    logger.error(f"MsgId={msg_id}: Downloaded data is not a valid image: {img_val_e}")
                                    return None
                            else:
                                logger.error(f"MsgId={msg_id}: Chunked download size mismatch. Expected {data_len}, got {len(full_image_data)}.")
                                return None
                        else:
                            logger.warning(f"MsgId={msg_id}: No valid image length (hdlength/length) found in XML or it's zero. XML: {content[:300]}...")
                    else:
                        logger.warning(f"MsgId={msg_id}: No <img> tag found in XML content. XML: {content[:200]}...")
                except ET.ParseError as e:
                    logger.error(f"MsgId={msg_id}: XML parse error: {e}. XML snippet: {content[:200]}...")
                except Exception as e_xml: # 其他XML处理错误
                    logger.error(f"MsgId={msg_id}: Error processing XML for image: {e_xml}", exc_info=True)
        else:
            logger.warning(f"MsgId={msg_id}: Unhandled content type for image extraction: {type(content)}. Content snippet: {str(content)[:100] if content else 'None'}")

        # 作为最后的备选方案，如果消息中有MsgSvrId（或其他可用于直接获取完整图片的ID），尝试直接调用一次get_msg_image，不分块
        # 这取决于 get_msg_image API 的行为，如果它能返回完整图片当 data_len 和 start_pos 不指定或特定值时
        # msg_svr_id_for_direct_fetch = message.get("MsgSvrId") or message.get("NewMsgId")
        # if msg_svr_id_for_direct_fetch and not isinstance(content, bytes): # 避免重复尝试如果content已经是bytes
        #     logger.info(f"MsgId={msg_id}: Attempting direct full image download using get_msg_image as a fallback.")
        #     try:
        #         # 这里的参数可能需要调整，例如 data_len=0 或不传，start_pos=0 或不传
        #         # target_wxid_direct = message.get("FromWxid")
        #         # image_data_direct = await bot.get_msg_image(msg_id=msg_id, to_wxid=target_wxid_direct)
        #         # if image_data_direct:
        #         #     Image.open(io.BytesIO(image_data_direct)) # 验证
        #         #     logger.info(f"MsgId={msg_id}: Successfully downloaded full image directly. Size: {len(image_data_direct)}")
        #         #     return image_data_direct
        #         # else:
        #         #     logger.warning(f"MsgId={msg_id}: Direct full image download returned no data.")
        #         pass # 实际实现时需要bot API支持
        #     except Exception as e_direct:
        #         logger.error(f"MsgId={msg_id}: Error during direct full image download: {e_direct}")
        
        logger.warning(f"MsgId={msg_id}: Could not extract image data from message through any known method.")
        return None


    async def _preprocess_image(self, image_data: bytes, msg_id: str) -> Optional[tuple[bytes, str]]:
        logger.debug(f"MsgId={msg_id}: Starting image preprocessing. Original size: {len(image_data)} bytes.")
        try:
            img = Image.open(io.BytesIO(image_data))
            original_format = (img.format or "unknown").lower()
            logger.info(f"MsgId={msg_id}: Image opened. Format: {original_format}, Mode: {img.mode}, Dims: {img.size}")

            # 确定目标格式
            target_format_ext = original_format
            if original_format not in self.allowed_formats:
                logger.warning(f"MsgId={msg_id}: Original format '{original_format}' is not in allowed_formats {self.allowed_formats}. Converting to PNG.")
                target_format_ext = "png" # 默认转换目标为PNG
            
            # 如果是GIF，只取第一帧 (除非有更复杂的GIF处理需求)
            if original_format == 'gif' and target_format_ext != 'gif': # 如果目标不是保留GIF
                logger.info(f"MsgId={msg_id}: GIF image detected. Using the first frame for processing.")
                img.seek(0) # 定位到第一帧
                # 如果GIF转为PNG/JPEG等，需要确保模式正确
                if img.mode == 'P' or img.mode == 'PA':
                    logger.debug(f"MsgId={msg_id}: GIF first frame mode is {img.mode}. Converting to RGBA before saving to {target_format_ext}.")
                    img = img.convert('RGBA') # 转换为RGBA以保留透明度信息或便于后续处理


            # 处理透明度：如果目标格式是JPEG (不支持透明度)
            if target_format_ext in ("jpeg", "jpg") and img.mode in ('RGBA', 'LA', 'P', 'PA'):
                # 对于P模式（调色板），检查是否有透明度
                has_transparency_in_palette = False
                if img.mode == 'P' and 'transparency' in img.info:
                    try:
                        # 检查透明度是否真的被使用 (例如，不是所有像素都是不透明的)
                        if isinstance(img.info['transparency'], bytes): # bytes for palette alpha
                             if any(alpha < 255 for alpha in img.info['transparency']):
                                has_transparency_in_palette = True
                        elif isinstance(img.info['transparency'], int): # single transparent color index
                            has_transparency_in_palette = True # Simplistic check, assume it's used
                    except Exception as e_trans_check:
                         logger.warning(f"MsgId={msg_id}: Error checking palette transparency details: {e_trans_check}")

                if img.mode in ('RGBA', 'LA', 'PA') or has_transparency_in_palette:
                    logger.info(f"MsgId={msg_id}: Image mode is {img.mode} (has alpha/palette transparency) and target is JPEG. Converting to RGB with white background.")
                    try:
                        # 创建一个白色背景
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        # 如果原始图像是P模式且有透明度，先转为RGBA再粘贴
                        paste_image = img
                        if img.mode == 'P' and has_transparency_in_palette:
                            paste_image = img.convert('RGBA')
                        
                        # 使用alpha通道作为mask进行粘贴
                        if paste_image.mode == 'RGBA':
                            background.paste(paste_image, mask=paste_image.split()[-1])
                        elif paste_image.mode == 'LA' or paste_image.mode == 'PA': # LA/PA
                             background.paste(paste_image.convert("RGBA"), mask=paste_image.convert("RGBA").split()[-1])
                        else: # 对于没有alpha的P模式（但上面逻辑应已处理），或RGB等直接粘贴
                            background.paste(paste_image)
                        img = background
                        logger.info(f"MsgId={msg_id}: Image converted to RGB. New mode: {img.mode}")
                    except Exception as alpha_e:
                        logger.error(f"MsgId={msg_id}: Failed to remove alpha channel or handle palette transparency: {alpha_e}", exc_info=True)
                        # 可以选择返回None，或者尝试用不带透明度的方式保存（如果Pillow支持）
                        # For safety, return None if alpha removal fails for JPEG target
                        return None, ""
            
            # 调整尺寸
            if img.width > self.max_width or img.height > self.max_height:
                logger.info(f"MsgId={msg_id}: Resizing image from {img.size} to fit within ({self.max_width}x{self.max_height}).")
                img.thumbnail((self.max_width, self.max_height), Image.Resampling.LANCZOS)
                logger.info(f"MsgId={msg_id}: Image resized to {img.size}.")

            output_buffer = io.BytesIO()
            save_params = {}
            
            # 确定Pillow保存时使用的格式名
            pil_save_format = ""
            if target_format_ext in ("jpeg", "jpg"):
                pil_save_format = "JPEG"
                save_params['quality'] = self.jpeg_quality
                save_params['optimize'] = True
            elif target_format_ext == "png":
                pil_save_format = "PNG"
                save_params['optimize'] = True # PNG也有优化选项
                # save_params['compress_level'] = 6 # 0-9, default 6. Higher is more compression but slower.
            elif target_format_ext == "webp":
                try:
                    Image.new('RGB', (1,1)).save(io.BytesIO(), format='WEBP') # 测试WEBP支持
                    pil_save_format = "WEBP"
                    save_params['quality'] = 80 # WebP quality
                    # save_params['lossless'] = False # True for lossless, False for lossy
                except Exception:
                    logger.warning(f"MsgId={msg_id}: Pillow does not support WEBP saving. Falling back to PNG for original format '{original_format}'.")
                    pil_save_format = "PNG" # 回退到PNG
                    target_format_ext = "png" # 更新目标扩展名
                    save_params = {'optimize': True}
            else: # 其他允许的格式，直接使用其大写作为Pillow格式
                if target_format_ext in self.allowed_formats:
                    pil_save_format = target_format_ext.upper()
                    if pil_save_format == "JPEG": # 以防万一有如 'JPG' -> 'JPEG'
                        save_params['quality'] = self.jpeg_quality
                        save_params['optimize'] = True
                    elif pil_save_format == "GIF": # 如果目标是保留GIF
                        # 对于GIF保存，参数较多，如 duration, loop. 简单保存第一帧或原始GIF（如果未修改）
                        # 如果img对象是原始GIF且未被修改（如resize），可以直接用原始数据，但这里是处理过的img
                        # 如果img被修改 (resize, frame extraction), 保存为GIF会复杂
                        # 目前逻辑是GIF转其他格式时取第一帧，如果目标仍是GIF，需要更复杂的处理来保留动画
                        # 简化：如果目标是GIF且允许，这里可能需要特殊逻辑，或接受只保存单帧GIF
                        logger.warning(f"MsgId={msg_id}: Target format is GIF. Current preprocessing might only save a single frame if modifications occurred.")
                        # 若要保存多帧GIF，需要迭代img.seek()并保存所有帧，Pillow save()有 append_images 参数
                else: # 不应该到这里，因为前面已处理不在allowed_formats的情况
                    logger.error(f"MsgId={msg_id}: Unexpected target_format_ext '{target_format_ext}' after initial checks.")
                    return None, ""
            
            if not pil_save_format:
                logger.error(f"MsgId={msg_id}: Could not determine a valid PIL save format for target_format_ext '{target_format_ext}'.")
                return None, ""

            logger.debug(f"MsgId={msg_id}: Saving image to buffer as {pil_save_format} with params: {save_params}. Final extension: {target_format_ext}")
            img.save(output_buffer, format=pil_save_format, **save_params)
            processed_image_data = output_buffer.getvalue()

            if len(processed_image_data) > self.max_image_size_bytes:
                logger.warning(f"MsgId={msg_id}: Processed image size {len(processed_image_data)} bytes exceeds max limit {self.max_image_size_bytes} bytes. Aborting.")
                # 可以在这里尝试进一步压缩，例如降低JPEG质量，但这会增加复杂性
                # 简单起见，直接返回None
                return None, ""

            logger.info(f"MsgId={msg_id}: Image preprocessing successful. Final size: {len(processed_image_data)} bytes, Format: {target_format_ext}")
            return processed_image_data, target_format_ext
        
        except IOError as e_pil_io: # Pillow的IOError通常指无法识别格式或文件损坏
            logger.error(f"MsgId={msg_id}: Pillow IO error during image preprocessing (e.g., unsupported format, corrupted image): {e_pil_io}", exc_info=True)
            # 尝试获取原始数据的前几个字节，有助于判断问题
            logger.debug(f"MsgId={msg_id}: Raw image data (first 64 bytes hex): {image_data[:64].hex()}")
            return None, ""
        except Exception as e:
            logger.error(f"MsgId={msg_id}: Generic error during image preprocessing: {e}", exc_info=True)
            return None, ""

    async def _save_to_s3_storage(self, image_data: bytes, msg_id: str, image_format_ext: str) -> Optional[str]:
        if not self.s3_config:
            logger.error(f"MsgId={msg_id}: S3 storage is not configured or Minio client is unavailable. Cannot save image.")
            return None

        # 生成更具唯一性的文件名，包含时间戳和部分UUID，防止msg_id可能重复（虽然不太可能）
        timestamp_str = str(int(time.time()))
        unique_suffix = uuid.uuid4().hex[:8] # 短UUID
        unique_filename = f"{msg_id}_{timestamp_str}_{unique_suffix}.{image_format_ext.lower()}"
        
        logger.debug(f"MsgId={msg_id}: Generated S3 unique filename: {unique_filename}")

        try:
            client = Minio(
                endpoint=self.s3_config["endpoint"],
                access_key=self.s3_config["access_key"],
                secret_key=self.s3_config["secret_key"],
                secure=self.s3_config["secure"]
            )
            bucket_name = self.s3_config["bucket"]
            
            # 确保bucket存在 (可选，但建议Minio SDK有此功能时使用)
            # found = client.bucket_exists(bucket_name)
            # if not found:
            #     try:
            #         client.make_bucket(bucket_name)
            #         logger.info(f"MsgId={msg_id}: S3 Bucket '{bucket_name}' did not exist and was created.")
            #     except S3Error as e_make_bucket:
            #         logger.error(f"MsgId={msg_id}: S3 Bucket '{bucket_name}' does not exist and failed to create it: {e_make_bucket}. Cannot upload.")
            #         return None
            # else:
            #     logger.debug(f"MsgId={msg_id}: S3 Bucket '{bucket_name}' exists.")


            content_type = f"image/{image_format_ext.lower()}" # MIME类型
            image_stream = io.BytesIO(image_data)
            image_length = len(image_data)

            logger.info(f"MsgId={msg_id}: Uploading to S3. Bucket: {bucket_name}, Object: {unique_filename}, Size: {image_length}B, ContentType: {content_type}")
            
            client.put_object(
                bucket_name,
                unique_filename,
                image_stream,
                image_length,
                content_type=content_type
                # metadata={"original_msg_id": msg_id} # 可以添加元数据
            )
            logger.info(f"MsgId={msg_id}: Image successfully uploaded to S3 object: s3://{bucket_name}/{unique_filename}")

            # 构建公开可访问的URL (这取决于S3服务的配置和endpoint是否直接可公网访问)
            s3_url_protocol = "https" if self.s3_config["secure"] else "http"
            s3_endpoint_host = self.s3_config['endpoint'].split('//')[-1] # 移除可能的 http(s):// 前缀
            
            # 有些S3兼容存储的endpoint可能已经包含了bucket (path-style access)
            # 或者需要自己拼接 (virtual-hosted style)
            # 简单拼接，对于 MinIO server 和 AWS S3 应该是 virtual-hosted 风格 (bucket.endpoint) 或 path-style (endpoint/bucket)
            # 这里的实现假设endpoint是域名，bucket是名称，生成path-style URL
            # 如果S3服务配置为强制virtual-hosted，URL格式会是 https://bucket_name.s3_endpoint_host/object_name
            # 为简单起见，先用path-style:
            s3_url = f"{s3_url_protocol}://{s3_endpoint_host.rstrip('/')}/{bucket_name.strip('/')}/{unique_filename}"
            
            # 尝试获取预签名URL (如果对象不是公开可读) - 但FastGPT通常需要直接公网URL
            # presigned_url = client.presigned_get_object(bucket_name, unique_filename, expires=datetime.timedelta(hours=1))
            # logger.debug(f"MsgId={msg_id}: Generated presigned S3 URL (expires in 1h): {presigned_url}")
            # return presigned_url # 如果用预签名URL

            logger.info(f"MsgId={msg_id}: Constructed S3 public-style URL: {s3_url}")


            if self.s3_enable_local_backup:
                logger.debug(f"MsgId={msg_id}: S3 local backup is enabled. Saving a copy locally.")
                try:
                    # 确保本地备份目录存在
                    os.makedirs(self.image_tmp_dir, exist_ok=True) 
                    local_backup_path = os.path.join(self.image_tmp_dir, unique_filename)
                    with open(local_backup_path, "wb") as f:
                        f.write(image_data)
                    logger.info(f"MsgId={msg_id}: Local backup of S3 image saved to: {local_backup_path}")
                except Exception as e_backup:
                    logger.error(f"MsgId={msg_id}: Failed to save S3 local backup to '{self.image_tmp_dir}': {e_backup}")
            
            return s3_url # 返回直接拼接的URL

        except S3Error as s3e:
            logger.error(f"MsgId={msg_id}: MinIO S3 operation failed: {s3e}", exc_info=True)
            # 根据错误类型可以给出更具体的提示，例如权限问题、bucket不存在等
            if "AccessDenied" in str(s3e):
                logger.error(f"MsgId={msg_id}: S3 Access Denied. Check credentials and bucket policies.")
            elif "NoSuchBucket" in str(s3e):
                 logger.error(f"MsgId={msg_id}: S3 Bucket '{self.s3_config['bucket']}' does not exist.")
        except Exception as e:
            logger.error(f"MsgId={msg_id}: An unexpected error occurred during S3 storage operation: {e}", exc_info=True)
        
        return None

    async def _call_fastgpt_api(self, bot: WechatAPIClient, message: dict, messages_payload: list, chat_id: str) -> tuple[Optional[str], bool]:
        request_data = {
            "chatId": chat_id,
            "stream": False, # FastGPT通常是流式，但简单实现先用非流式
            "detail": self.detail,
            "messages": messages_payload
        }
        if self.app_id: # 如果配置了app_id，则加入请求中 (FastGPT可能需要)
            request_data["appId"] = self.app_id
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        proxy = self.http_proxy if self.http_proxy else None
        api_url = f"{self.base_url.rstrip('/')}/v1/chat/completions"

        logger.debug(f"Calling FastGPT API. URL: {api_url}, ChatId: {chat_id}, AppId: {self.app_id or 'N/A'}, Detail: {self.detail}")
        # 为了日志简洁，只打印messages_payload中用户消息的文本部分或图片URL提示
        log_payload_summary = []
        for msg_item in messages_payload:
            if msg_item.get("role") == "user":
                content = msg_item.get("content")
                if isinstance(content, str):
                    log_payload_summary.append(f"UserText: {content[:70]}...")
                elif isinstance(content, list):
                    summary_parts = []
                    for part in content:
                        if part.get("type") == "text":
                            summary_parts.append(f"UserTextPart: {part.get('text', '')[:50]}...")
                        elif part.get("type") == "image_url":
                            summary_parts.append(f"UserImageURL: {part.get('image_url', {}).get('url', '')[-50:]}") # 只看URL尾部
                    log_payload_summary.append(", ".join(summary_parts))
        logger.trace(f"FastGPT Request Payload Summary: {'; '.join(log_payload_summary)}")
        # logger.trace(f"Full FastGPT Request (beware of large image data if any embedded): {json.dumps(request_data, ensure_ascii=False)}")


        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, headers=headers, json=request_data, proxy=proxy, timeout=aiohttp.ClientTimeout(total=120)) as response: # 增加超时到120s
                    response_text = await response.text()
                    logger.debug(f"FastGPT API Response Status: {response.status}")
                    if response.status != 200: # 200是成功
                        logger.error(f"FastGPT API call failed. Status: {response.status}. Response Text (first 500 chars): {response_text[:500]}")
                        error_detail = response_text
                        try: # 尝试解析JSON错误信息
                            error_json = json.loads(response_text)
                            if isinstance(error_json, dict):
                                error_detail = error_json.get("message", error_json.get("error", {}).get("message", str(error_json)))
                        except json.JSONDecodeError:
                            pass #保持原始文本
                        await self._send_error_message(bot, message, f"FastGPT服务返回错误 ({response.status}): {error_detail[:200]}")
                        return None, False

                    # 尝试解析响应
                    try:
                        resp_json = json.loads(response_text)
                        logger.trace(f"FastGPT API JSON Response (first 500 chars of stringified): {str(resp_json)[:500]}")
                    except json.JSONDecodeError as json_e:
                        logger.error(f"FastGPT API JSON decode error: {json_e}. Response Text: {response_text[:500]}", exc_info=True)
                        await self._send_error_message(bot, message, "FastGPT响应格式错误 (非JSON)。")
                        return None, False

                    # 从响应中提取内容 (这部分高度依赖FastGPT API的具体返回结构)
                    # 假设 content 在 choices[0].message.content
                    content_to_return = None
                    choices = resp_json.get("choices")
                    if choices and isinstance(choices, list) and len(choices) > 0:
                        first_choice = choices[0]
                        if isinstance(first_choice, dict):
                            message_part = first_choice.get("message")
                            if isinstance(message_part, dict):
                                content_to_return = message_part.get("content")
                    
                    # 如果 detail=true，FastGPT 可能有不同的结构，如包含 responseData
                    if content_to_return is None and self.detail and "responseData" in resp_json:
                        logger.debug("Trying to extract content from 'responseData' due to detail=true and no primary content found.")
                        # responseData的结构可能是一个列表或字典，这里需要根据实际情况调整
                        # 示例：假设 responseData 是个列表，里面有包含文本的项
                        if isinstance(resp_json["responseData"], list):
                            for item in resp_json["responseData"]:
                                if isinstance(item, dict):
                                    if item.get("moduleType") == "text" and item.get("text", {}).get("content"):
                                        content_to_return = item["text"]["content"]
                                        logger.debug(f"Extracted content from responseData.text.content: {str(content_to_return)[:100]}...")
                                        break
                                    # 检查是否有 pluginOutput (工具调用结果)
                                    if item.get("moduleType") == "pluginOutput" and item.get("pluginOutput", {}).get("text"):
                                        content_to_return = item["pluginOutput"]["text"] # 假设插件输出是文本
                                        logger.debug(f"Extracted content from responseData.pluginOutput.text: {str(content_to_return)[:100]}...")
                                        break
                                    if item.get("moduleType") == "answer" and item.get("text", {}).get("content"): # V4.6.6+ 可能的结构
                                        content_to_return = item["text"]["content"]
                                        logger.debug(f"Extracted content from responseData.answer.text.content: {str(content_to_return)[:100]}...")
                                        break

                    # 最后的兜底，如果FastGPT直接在顶层返回了 text 字段
                    if content_to_return is None and resp_json.get("text"):
                        content_to_return = resp_json.get("text")
                        logger.debug(f"Extracted content from top-level 'text' field: {str(content_to_return)[:100]}...")


                    if content_to_return is None:
                        logger.error(f"FastGPT: Could not extract meaningful content from response. Full response (first 500 chars): {response_text[:500]}")
                        await self._send_error_message(bot, message, "FastGPT未能返回有效内容。")
                        return None, False
                    
                    logger.info(f"FastGPT API call successful. Extracted content (first 100 chars): '{str(content_to_return)[:100]}...'")
                    return str(content_to_return), True

        except aiohttp.ClientConnectorError as e_conn:
            logger.error(f"FastGPT API connection error (e.g., DNS resolution, TCP connect): {e_conn}", exc_info=True)
            await self._send_error_message(bot, message, f"连接FastGPT服务失败: {type(e_conn).__name__}")
        except aiohttp.ClientResponseError as e_resp: # HTTP status errors not caught above (e.g. 401, 403 before json load)
             logger.error(f"FastGPT API HTTP error: {e_resp.status}, message='{e_resp.message}'", exc_info=True)
             await self._send_error_message(bot, message, f"FastGPT服务HTTP错误 ({e_resp.status})")
        except aiohttp.ClientError as e_client: # Other generic client errors (timeout, etc.)
            logger.error(f"FastGPT API call failed due to a client-side error: {e_client}", exc_info=True)
            await self._send_error_message(bot, message, f"调用FastGPT时发生网络客户端错误: {type(e_client).__name__}")
        except asyncio.TimeoutError: # Explicitly catch timeout if not caught by ClientError
            logger.error(f"FastGPT API call timed out after 120s.", exc_info=True)
            await self._send_error_message(bot, message, "调用FastGPT服务超时。")
        except Exception as e: # Catch-all for unexpected errors
            logger.error(f"An unexpected error occurred during FastGPT API call: {e}", exc_info=True)
            await self._send_error_message(bot, message, f"调用FastGPT时发生未知错误: {type(e).__name__}")
        
        return None, False

    async def _send_error_message(self, bot: WechatAPIClient, message: dict, error_text: str):
        is_group = message.get("IsGroup", False)
        sender_wxid = message.get("SenderWxid")
        from_wxid = message.get("FromWxid")
        msg_id = message.get("MsgId", "N/A")
        
        logger.warning(f"Sending error to user {sender_wxid} (in {from_wxid if is_group else 'private chat'}, terkait MsgId: {msg_id}): {error_text}")
        
        full_error_msg = f"抱歉，FastGPT操作失败了：{error_text}"
        if len(full_error_msg) > 500: # 避免消息过长
            full_error_msg = full_error_msg[:497] + "..."

        try:
            if is_group:
                await bot.send_at_message(from_wxid, f"\n{full_error_msg}", [sender_wxid])
            else:
                await bot.send_text_message(from_wxid, full_error_msg)
        except Exception as e_send:
            logger.error(f"Failed to send error message to user {sender_wxid}: {e_send}")


    async def _check_point(self, bot: WechatAPIClient, message: dict) -> bool:
        # wxid = message.get("SenderWxid")
        if self.price <= 0:
            logger.trace(f"Point check for {wxid}: Price is {self.price}, access granted.")
            return True
        
        # # 以下是原有的积分检查逻辑，暂时注释掉
        # is_admin = wxid in self.admins
        # is_whitelisted = self.db.get_whitelist(wxid)

        # if is_admin and self.admin_ignore:
        #     logger.debug(f"Point check for {wxid}: User is admin and admin_ignore is true. Access granted.")
        #     return True
        # if is_whitelisted and self.whitelist_ignore:
        #     logger.debug(f"Point check for {wxid}: User is whitelisted and whitelist_ignore is true. Access granted.")
        #     return True
            
        # user_points = self.db.get_points(wxid)
        # if user_points < self.price:
        #     error_msg = f"您的积分不足，本次操作需{self.price}分，您的当前积分为{user_points}分。"
        #     logger.info(f"Point check for {wxid}: Insufficient points. Required: {self.price}, Has: {user_points}.")
        #     await self._send_error_message(bot, message, error_msg)
        #     return False
        
        # logger.debug(f"Point check for {wxid}: Sufficient points. Required: {self.price}, Has: {user_points}. Access granted.")
        # return True

    def _check_and_install_dependencies(self):
        # (此方法与您提供的版本基本一致，主要确保Minio和Tomli的检查逻辑)
        logger.info("Checking and installing dependencies for FastGPT plugin...")
        pip_command_available = [True] 
        global minio_available

        def _install_with_pip(package_import_name: str, package_pip_name: str, requirement_str: Optional[str] = None) -> bool:
            if not pip_command_available[0]:
                logger.warning(f"pip command not available, skipping installation of {package_pip_name}.")
                return False
            try:
                __import__(package_import_name)
                logger.debug(f"Dependency '{package_import_name}' is already installed.")
                return True
            except ImportError:
                install_target = requirement_str if requirement_str else package_pip_name
                logger.info(f"Attempting to install '{install_target}' via pip...")
                try:
                    # 使用 subprocess.run 获取更详细的输出（如果需要）
                    result = subprocess.run([sys.executable, "-m", "pip", "install", install_target],
                                            capture_output=True, text=True, check=False) # check=False 手动检查
                    if result.returncode == 0:
                        logger.success(f"Successfully installed '{install_target}'.")
                        __import__(package_import_name) # 验证导入
                        return True
                    else:
                        logger.error(f"Failed to install '{install_target}' via pip. Return code: {result.returncode}")
                        logger.error(f"Pip stdout: {result.stdout.strip()}")
                        logger.error(f"Pip stderr: {result.stderr.strip()}")
                        return False
                except ImportError: # 即使安装成功也可能导入失败（例如PATH问题或安装到了错误的环境）
                    logger.error(f"Installed '{install_target}' but still cannot import '{package_import_name}'. Check Python environment and paths.")
                except FileNotFoundError: 
                    logger.error("pip command not found. Cannot install dependencies automatically. Please install pip.")
                    pip_command_available[0] = False
                except Exception as e_install: # 其他pip执行错误
                    logger.error(f"An unexpected error occurred while trying to install '{install_target}': {e_install}")
            return False

        requirements_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
        if os.path.exists(requirements_path):
            logger.info(f"Processing requirements.txt from {requirements_path}")
            try:
                with open(requirements_path, 'r') as f:
                    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                if requirements:
                    if pip_command_available[0]:
                        logger.info(f"Installing dependencies from requirements.txt: {requirements}")
                        # 安装 requirements.txt 中的所有包
                        result_req = subprocess.run([sys.executable, "-m", "pip", "install", *requirements],
                                                    capture_output=True, text=True, check=False)
                        if result_req.returncode == 0:
                            logger.success("Successfully installed dependencies from requirements.txt.")
                            # 特别检查 Minio 是否安装成功 (如果它在 requirements.txt 中)
                            if any("minio" in req.split("==")[0].split(">=")[0].split("<=")[0].strip().lower() for req in requirements):
                                try: 
                                    __import__("minio")
                                    minio_available = True
                                    logger.info("Minio successfully imported after installation from requirements.txt.")
                                except ImportError: 
                                    minio_available = False
                                    logger.error("Minio was in requirements.txt but failed to import after installation.")
                        else:
                            logger.error(f"Failed to install from requirements.txt. Return code: {result_req.returncode}")
                            logger.error(f"Pip stdout: {result_req.stdout.strip()}")
                            logger.error(f"Pip stderr: {result_req.stderr.strip()}")
                    else:
                        logger.warning("pip not available, skipping installation from requirements.txt.")
            except Exception as e_req:
                logger.error(f"Error processing requirements.txt: {e_req}", exc_info=True)
        else:
            logger.info("requirements.txt not found. Proceeding with manual checks for core dependencies.")

        # 确保Pillow安装
        _install_with_pip("PIL", "Pillow", "Pillow>=9.0.0")

        # tomli (仅当标准库 tomllib 不可用时)
        if tomllib is None: 
            if not _install_with_pip("tomli", "tomli", "tomli>=1.1.0"):
                logger.warning("'tomli' fallback could not be installed. TOML parsing might fail if standard 'tomllib' is unavailable.")
            # `__init__` 开头会再次尝试导入并更新全局 tomllib 别名

        # Minio (再次检查，以防 requirements.txt 未包含或处理失败)
        # minio_available 的状态在函数开始时已经确定或从全局获取
        if not minio_available: # 如果到现在 minio 仍然不可用
            logger.info("Minio is not yet available. Attempting to install it now as a core dependency for S3 storage.")
            if _install_with_pip("minio", "minio", "minio>=7.0.0"):
                minio_available = True # 更新状态
                logger.info("Minio successfully installed and imported.")
            else:
                # 保持 minio_available = False
                logger.warning("Minio could not be installed. S3 related functionalities will be unavailable.")
        else:
            logger.info("Minio dependency is already available.")
            
        logger.info("Dependency check/installation process finished.")


    async def _cleanup_expired_items(self): # 重命名以反映其双重职责
        if not os.path.exists(self.image_tmp_dir) and not (self.storage_type == "s3" and self.s3_enable_local_backup):
             logger.info(f"Local image temp directory {self.image_tmp_dir} does not exist and S3 local backup is off. Local file cleanup part of task will be skipped.")
        
        logger.info(f"Starting periodic cleanup task. Interval: {self.cleanup_interval}s.")
        logger.info(f" - Local image tmp dir: {self.image_tmp_dir}, Expire: {self.image_expire_time}s (if S3 local backup or local storage used)")
        logger.info(f" - Pending user image contexts in memory, Expire: {self.image_context_ttl_seconds}s")

        while True:
            await asyncio.sleep(self.cleanup_interval)
            current_time = time.time()
            
            # 1. 清理本地临时图片文件 (来自S3备份)
            cleaned_files_count = 0
            if os.path.exists(self.image_tmp_dir) and (self.storage_type == "s3" and self.s3_enable_local_backup):
                logger.debug(f"Running local image file cleanup in {self.image_tmp_dir} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                try:
                    for filename in os.listdir(self.image_tmp_dir):
                        file_path = os.path.join(self.image_tmp_dir, filename)
                        try:
                            if os.path.isfile(file_path):
                                # 使用 getmtime 获取最后修改时间
                                if current_time - os.path.getmtime(file_path) > self.image_expire_time:
                                    os.remove(file_path)
                                    cleaned_files_count += 1
                                    logger.debug(f"Cleaned expired local image file: {file_path}")
                        except Exception as e_file:
                            logger.error(f"Error processing file {file_path} during local cleanup: {e_file}")
                    if cleaned_files_count > 0:
                        logger.info(f"Local image file cleanup: Cleaned {cleaned_files_count} files from {self.image_tmp_dir}.")
                    else:
                        logger.debug("Local image file cleanup: No files cleaned in this run.")
                except Exception as e_listdir:
                    logger.error(f"Error listing directory {self.image_tmp_dir} for cleanup: {e_listdir}", exc_info=True)

            # 2. 清理内存中的 pending_user_images 缓存
            cleaned_contexts_count = 0
            cleaned_user_keys_count = 0
            logger.debug(f"Running pending user image context cleanup in memory at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 创建一个副本进行迭代，以允许在循环中修改原始字典
            cache_keys_to_check = list(self.pending_user_images.keys()) 
            
            for cache_key in cache_keys_to_check:
                if cache_key not in self.pending_user_images: # 可能在迭代过程中被其他协程移除了
                    continue

                user_images_list = self.pending_user_images[cache_key]
                # 从列表前面（旧的）开始移除过期项
                original_list_len = len(user_images_list)
                
                # 使用列表推导式重建列表，只保留未过期的
                valid_images_in_list = [
                    img_info for img_info in user_images_list 
                    if (current_time - img_info['timestamp']) <= self.image_context_ttl_seconds
                ]
                
                num_removed = original_list_len - len(valid_images_in_list)
                if num_removed > 0:
                    cleaned_contexts_count += num_removed
                    self.pending_user_images[cache_key] = valid_images_in_list
                    logger.debug(f"Cleaned {num_removed} expired image contexts for user key '{cache_key}'.")

                if not self.pending_user_images[cache_key]: # 如果清理后列表为空
                    self.pending_user_images.pop(cache_key, None)
                    cleaned_user_keys_count += 1
                    logger.info(f"Removed empty user image context list for key '{cache_key}'.")
            
            if cleaned_contexts_count > 0 or cleaned_user_keys_count > 0 :
                logger.info(f"Pending image context cleanup: Cleaned {cleaned_contexts_count} individual image contexts and removed {cleaned_user_keys_count} empty user keys. Cache size: {len(self.pending_user_images)} users.")
            else:
                logger.debug("Pending image context cleanup: No contexts cleaned in this run.")

            # 总日志
            if cleaned_files_count == 0 and cleaned_contexts_count == 0 and cleaned_user_keys_count == 0:
                logger.debug("Cleanup task run complete: No items (files or contexts) were cleaned.")
            else:
                logger.info("Cleanup task run complete.")

            # 捕获任务本身的异常
            # (移到循环外，因为上面的try-except已经处理了内部逻辑的异常)
            # await asyncio.sleep(self.cleanup_interval) # 已在循环开始处

        # 循环外的异常处理 (如果需要的话，但通常循环内的更重要)
        # except Exception as e_task_main:
        #    logger.error(f"Main cleanup task loop encountered an error: {e_task_main}", exc_info=True)
        #    await asyncio.sleep(self.cleanup_interval / 2) # 错误后稍作等待再重试循环 (如果适用)

    async def _extract_image_urls(self, text: str) -> List[str]: # 未使用，保留
        # (此方法未被新逻辑使用，保持原样)
        image_urls = []
        try:
            # 更通用的URL匹配，但可能不够精确，需根据实际情况调整
            # 此处仅为示例，FastGPT的图片通常通过API的image_url参数传递，而不是从文本中提取
            url_pattern = r'https?://[^\s/$.?#].[^\s]*\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s]*)?'
            image_urls = re.findall(url_pattern, text, re.IGNORECASE)
        except Exception as e: 
            logger.error(f"Error extracting image URLs from text: {e}", exc_info=True)
        
        if image_urls: 
            logger.info(f"Extracted {len(image_urls)} potential image URLs from text: {image_urls}")
        return image_urls

# --- END OF FILE FastGPT/main.py ---