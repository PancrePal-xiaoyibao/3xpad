import os
import json
import tomllib
import traceback
import aiohttp
import uuid
import time
import base64
import asyncio
import re
from typing import Dict, List, Optional, Tuple
from loguru import logger
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class SiliconFlow(PluginBase):
    description = "硅基流动API插件"
    author = "老夏的金库"
    version = "1.3.1"
    is_ai_platform = True

    def __init__(self):
        super().__init__()
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))

        # 初始化存储目录
        self.image_temp_dir = os.path.join(self.plugin_dir, "temp_images")
        os.makedirs(self.image_temp_dir, exist_ok=True)

        # 清理旧的临时文件
        self.cleanup_temp_files()

        # 图片缓存，用于存储用户生成的图片
        # 格式: {wxid: {"images": [image_data1, image_data2, ...], "timestamp": time.time()}}
        self.user_image_cache = {}

        try:
            # 读取配置
            config_path = os.path.join(self.plugin_dir, "config.toml")
            with open(config_path, "rb") as f:
                config = tomllib.load(f)

            # 主配置
            self.config = config.get("SiliconFlow", {})
            self.enable = self.config.get("enable", False)

            # 文本模型配置
            self.text_config = config.get("TextGeneration", {})
            self.text_enable = self.text_config.get("enable", False)
            self.text_api_key = self.text_config.get("api-key", "")
            self.text_base_url = self.text_config.get("base-url", "https://api.siliconflow.cn/v1")
            self.default_model = self.text_config.get("default-model", "Qwen/QwQ-32B")
            self.commands = self.text_config.get("commands", ["硅基", "sf", "SiliconFlow"])

            # 图片生成配置
            self.image_config = config.get("ImageGeneration", {})
            self.image_enable = self.image_config.get("enable", False)
            self.image_api_key = self.image_config.get("api-key", "")
            self.image_base_url = self.image_config.get("base-url", "https://api.siliconflow.cn/v1")
            self.image_model = self.image_config.get("image-model", "Kwai-Kolors/Kolors")
            self.image_size = self.image_config.get("image-size", "1024x1024")
            self.image_steps = self.image_config.get("image-steps", 20)
            self.image_guidance_scale = self.image_config.get("image-guidance-scale", 7.5)
            self.image_commands = self.image_config.get("image-commands", ["画图", "绘图", "生成图片"])
            self.image_batch_size = self.image_config.get("image-batch-size", 4)

            # 视觉模型配置
            self.vision_config = config.get("VisionRecognition", {})
            self.vision_enable = self.vision_config.get("enable", False)
            self.vision_api_key = self.vision_config.get("api-key", "")
            self.vision_base_url = self.vision_config.get("base-url", "https://api.siliconflow.cn/v1")
            self.vision_model = self.vision_config.get("vision-model", "Qwen/Qwen2.5-VL-72B-Instruct")
            self.auto_analyze_images = self.vision_config.get("auto_analyze_images", True)
            self.vision_prompt = self.vision_config.get("vision_prompt", "请详细描述这张图片的内容")

            # 临时文件清理配置
            self.cleanup_days = self.config.get("cleanup_days", 3)

            logger.success("SiliconFlow插件初始化成功")

        except Exception as e:
            logger.error(f"初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            self.enable = False

    def cleanup_temp_files(self):
        """清理过期的临时文件"""
        try:
            if not os.path.exists(self.image_temp_dir):
                return

            current_time = time.time()
            cleanup_seconds = self.cleanup_days * 24 * 60 * 60  # 转换为秒

            count = 0
            for filename in os.listdir(self.image_temp_dir):
                file_path = os.path.join(self.image_temp_dir, filename)

                # 跳过目录
                if os.path.isdir(file_path):
                    continue

                # 检查文件修改时间
                file_mod_time = os.path.getmtime(file_path)
                if current_time - file_mod_time > cleanup_seconds:
                    try:
                        os.remove(file_path)
                        count += 1
                    except Exception as e:
                        logger.error(f"删除临时文件 {file_path} 失败: {str(e)}")

            if count > 0:
                logger.info(f"已清理 {count} 个过期临时文件")

            # 清理过期的图片缓存
            expired_users = []
            for wxid, cache_data in self.user_image_cache.items():
                if current_time - cache_data["timestamp"] > cleanup_seconds:
                    expired_users.append(wxid)

            for wxid in expired_users:
                del self.user_image_cache[wxid]

            if expired_users:
                logger.info(f"已清理 {len(expired_users)} 个用户的图片缓存")

        except Exception as e:
            logger.error(f"清理临时文件失败: {str(e)}")
            logger.error(traceback.format_exc())

    def create_image_grid(self, images: List[bytes]) -> bytes:
        """将多张图片拼接成一张网格图片"""
        try:
            # 确保有图片
            if not images:
                logger.error("没有图片可供拼接")
                return None

            # 打开所有图片
            pil_images = []
            for img_data in images:
                try:
                    img = Image.open(BytesIO(img_data))
                    # 统一转换为RGB模式
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    pil_images.append(img)
                except Exception as e:
                    logger.error(f"打开图片失败: {str(e)}")

            if not pil_images:
                logger.error("没有有效的图片可供拼接")
                return None

            # 确定网格大小
            num_images = len(pil_images)
            if num_images == 1:
                grid_size = (1, 1)
            elif num_images == 2:
                grid_size = (1, 2)
            elif num_images <= 4:
                grid_size = (2, 2)
            elif num_images <= 6:
                grid_size = (2, 3)
            elif num_images <= 9:
                grid_size = (3, 3)
            else:
                grid_size = (4, 4)

            # 调整所有图片大小为相同尺寸
            target_size = (512, 512)  # 每个图片的目标大小
            for i in range(len(pil_images)):
                pil_images[i] = pil_images[i].resize(target_size, Image.LANCZOS)

            # 创建空白画布
            grid_width = grid_size[1] * target_size[0]
            grid_height = grid_size[0] * target_size[1]
            grid_image = Image.new('RGB', (grid_width, grid_height), color='white')

            # 添加图片到网格
            for i, img in enumerate(pil_images):
                if i >= grid_size[0] * grid_size[1]:
                    break  # 超出网格大小，不再添加

                row = i // grid_size[1]
                col = i % grid_size[1]
                x = col * target_size[0]
                y = row * target_size[1]

                # 在图片上添加序号
                draw = ImageDraw.Draw(img)
                # 尝试加载字体，如果失败则使用默认字体
                try:
                    font_path = os.path.join(self.plugin_dir, "fonts", "msyh.ttc")
                    if os.path.exists(font_path):
                        font = ImageFont.truetype(font_path, 48)
                    else:
                        font = ImageFont.load_default()
                except Exception:
                    font = ImageFont.load_default()

                # 添加序号，白色文字带黑色描边
                number = str(i + 1)
                text_x = 20
                text_y = 20
                # 添加黑色描边
                for offset_x, offset_y in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
                    draw.text((text_x + offset_x, text_y + offset_y), number, fill="black", font=font)
                # 添加白色文字
                draw.text((text_x, text_y), number, fill="white", font=font)

                grid_image.paste(img, (x, y))

            # 转换为字节流
            output = BytesIO()
            grid_image.save(output, format='JPEG', quality=95)
            output.seek(0)
            return output.getvalue()

        except Exception as e:
            logger.error(f"创建图片网格失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def get_cached_images(self, wxid: str) -> List[bytes]:
        """获取用户缓存的图片"""
        if wxid in self.user_image_cache:
            return self.user_image_cache[wxid]["images"]
        return []

    def cache_images(self, wxid: str, images: List[bytes]):
        """缓存用户的图片"""
        self.user_image_cache[wxid] = {
            "images": images,
            "timestamp": time.time()
        }

    async def get_image_data(self, bot: WechatAPIClient, message: dict) -> bytes:
        """获取图片原始数据并进行验证"""
        try:
            if "MsgId" not in message:
                logger.error("消息中缺少MsgId字段")
                return b""

            image_data = await bot.get_msg_image(message["MsgId"])
            if not image_data:
                logger.error("获取的图片数据为空")
                return b""

            if len(image_data) < 1024:
                logger.error(f"获取的图片数据过小: {len(image_data)}字节")
                return b""

            if image_data[:2] != b"\xff\xd8" and image_data[:8] != b"\x89PNG\r\n\x1a\n":
                logger.error("获取的图片数据不是有效的JPEG或PNG格式")
                return b""

            return image_data
        except Exception as e:
            logger.error(f"获取图片数据失败: {str(e)}")
            return b""

    async def download_file(self, url: str) -> bytes:
        """下载文件并返回文件内容"""
        try:
            logger.info(f"开始下载文件: {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        logger.info(f"文件下载成功，大小: {len(content)} 字节")
                        return content
                    else:
                        logger.error(f"文件下载失败: HTTP {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"下载文件时发生错误: {e}")
            logger.error(traceback.format_exc())
            return None

    async def generate_image(self, prompt: str, wxid: str, bot: WechatAPIClient) -> bool:
        """生成图片并发送拼接后的图片给用户"""
        try:
            # 发送提示消息
            await bot.send_text_message(wxid, f"正在生成图片，请稍候...")

            data = {
                "model": self.image_model,
                "prompt": prompt,
                "negative_prompt": "模糊, 低质量, 变形",
                "image_size": self.image_size,
                "num_inference_steps": self.image_steps,
                "guidance_scale": self.image_guidance_scale,
                "response_format": "url",
                "n": self.image_batch_size  # 生成多张图片
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.image_api_key}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.image_base_url}/images/generations",
                    headers=headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"API错误[{response.status}]: {error}")
                        await bot.send_text_message(wxid, "图片生成失败，请稍后再试")
                        return False

                    response_data = await response.json()
                    logger.debug(f"API响应: {json.dumps(response_data, indent=2)}")

                    if not isinstance(response_data, dict) or "data" not in response_data:
                        logger.error("API返回格式错误")
                        await bot.send_text_message(wxid, "API返回格式错误，请稍后再试")
                        return False

                    # 获取图片URL列表
                    image_urls = response_data["data"]

                    # 下载所有图片
                    downloaded_images = []
                    for i, img in enumerate(image_urls, 1):
                        url = img.get('url', '')
                        if not url:
                            continue

                        # 下载图片
                        image_data = await self.download_file(url)
                        if not image_data:
                            logger.error(f"下载图片失败: {url}")
                            continue

                        # 保存图片到临时文件
                        temp_file = os.path.join(self.image_temp_dir, f"temp_image_{int(time.time())}_{i}.png")
                        try:
                            with open(temp_file, "wb") as f:
                                f.write(image_data)
                            downloaded_images.append(image_data)
                            logger.info(f"成功下载图片 {i}/{len(image_urls)}")
                        except Exception as e:
                            logger.error(f"保存图片失败: {str(e)}")
                        finally:
                            # 删除临时文件
                            try:
                                if os.path.exists(temp_file):
                                    os.remove(temp_file)
                                    logger.debug(f"已删除临时文件: {temp_file}")
                            except Exception as e:
                                logger.error(f"删除临时文件失败: {str(e)}")

                    if not downloaded_images:
                        await bot.send_text_message(wxid, "所有图片下载失败，请稍后再试")
                        return False

                    # 缓存图片供用户选择
                    self.cache_images(wxid, downloaded_images)

                    # 创建图片网格
                    grid_image = self.create_image_grid(downloaded_images)
                    if not grid_image:
                        await bot.send_text_message(wxid, "创建图片网格失败，将发送单独的图片")
                        # 发送单独的图片
                        for i, img_data in enumerate(downloaded_images, 1):
                            await bot.send_image_message(wxid, img_data)
                            logger.info(f"成功发送单独图片 {i}/{len(downloaded_images)}")
                    else:
                        # 发送网格图片
                        await bot.send_image_message(wxid, grid_image)
                        logger.info("成功发送图片网格")

                        # 发送选择提示
                        await bot.send_text_message(wxid, f"已生成 {len(downloaded_images)} 张图片，回复数字(1-{len(downloaded_images)})可查看原图")

                    return True
        except asyncio.TimeoutError:
            logger.error("图片生成请求超时")
            await bot.send_text_message(wxid, "图片生成请求超时，请稍后再试")
            return False
        except Exception as e:
            logger.error(f"生成图片失败: {str(e)}")
            logger.error(traceback.format_exc())
            await bot.send_text_message(wxid, f"生成图片失败: {str(e)}")
            return False

    async def analyze_image(self, image_data: bytes) -> str:
        """分析图片内容"""
        try:
            if len(image_data) > 10 * 1024 * 1024:
                return "图片过大，请上传小于10MB的图片"

            image_base64 = base64.b64encode(image_data).decode('utf-8')

            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": self.vision_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                            "detail": "low"
                        }
                    }
                ]
            }]

            data = {
                "model": self.vision_model,
                "messages": messages,
                "max_tokens": 800,
                "temperature": 0.7
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.vision_api_key}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.vision_base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=180
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"视觉API错误[{response.status}]: {error}")
                        return "图片分析服务错误"

                    result = await response.json()
                    logger.debug(f"视觉API响应: {json.dumps(result, indent=2)}")

                    if not isinstance(result, dict) or "choices" not in result:
                        logger.error("视觉API返回格式错误")
                        return "无法解析响应"

                    return result["choices"][0].get("message", {}).get("content", "无法获取分析结果")
        except asyncio.TimeoutError:
            logger.error("图片分析请求超时")
            return "图片分析超时，请稍后再试"
        except Exception as e:
            logger.error(f"分析图片失败: {str(e)}")
            logger.error(traceback.format_exc())
            return "图片分析服务暂时不可用"

    @on_text_message(priority=50)
    async def handle_text_message(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            return True

        content = message["Content"].strip()
        wxid = message["FromWxid"]

        # 检查是否是选择图片的数字
        if wxid in self.user_image_cache and content.isdigit():
            index = int(content) - 1
            cached_images = self.user_image_cache[wxid]["images"]
            if 0 <= index < len(cached_images):
                # 发送选中的图片
                await bot.send_text_message(wxid, f"正在发送第 {index+1} 张图片...")
                await bot.send_image_message(wxid, cached_images[index])
                logger.info(f"发送用户选择的图片: {index+1}")
                return False
            elif len(cached_images) > 0:
                await bot.send_text_message(wxid, f"请输入有效的数字(1-{len(cached_images)})")
                return False

        # 检查图片生成命令
        for cmd in self.image_commands:
            if content.startswith(cmd):
                if not self.image_enable or not self.image_api_key:
                    await bot.send_text_message(wxid, "图片生成功能未启用")
                    return False

                prompt = content[len(cmd):].strip()
                if not prompt:
                    await bot.send_text_message(wxid, f"请输入图片描述，例如：{cmd} 一只猫")
                    return False

                # 调用新的generate_image方法，生成图片并发送拼接图
                success = await self.generate_image(prompt, wxid, bot)
                if not success:
                    await bot.send_text_message(wxid, "图片生成失败，请稍后再试")
                return False

        # 检查AI对话命令
        for cmd in self.commands:
            if content.startswith(cmd):
                if not self.text_enable or not self.text_api_key:
                    await bot.send_text_message(wxid, "文本生成功能未启用")
                    return False

                prompt = content[len(cmd):].strip()
                if not prompt:
                    await bot.send_text_message(wxid, f"请输入问题，例如：{cmd} 你好")
                    return False

                response = await self.call_chat_api([{"role": "user", "content": prompt}])
                await bot.send_text_message(wxid, response)
                return False

        return True

    @on_image_message(priority=50)
    async def handle_image_message(self, bot: WechatAPIClient, message: dict):
        """自动处理所有图片消息"""
        if not self.enable or not self.vision_enable or not self.auto_analyze_images:
            return True

        wxid = message["FromWxid"]

        try:
            image_data = await self.get_image_data(bot, message)
            if not image_data:
                await bot.send_text_message(wxid, "无法获取有效的图片内容")
                return False

            analysis = await self.analyze_image(image_data)
            await bot.send_text_message(wxid, analysis)
            return False
        except Exception as e:
            logger.error(f"处理图片消息失败: {str(e)}")
            await bot.send_text_message(wxid, "图片分析失败，请稍后再试")
            return False

    async def call_chat_api(self, messages: List[Dict[str, str]]) -> str:
        """调用对话API"""
        try:
            data = {
                "model": self.default_model,
                "messages": messages,
                "max_tokens": self.text_config.get("max_tokens", 800),
                "temperature": self.text_config.get("temperature", 0.7),
                "top_p": self.text_config.get("top_p", 0.8)
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.text_api_key}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.text_base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=180
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"对话API错误[{response.status}]: {error}")
                        return "服务暂时不可用"

                    result = await response.json()
                    if not isinstance(result, dict) or "choices" not in result:
                        logger.error("对话API返回格式错误")
                        return "无法解析响应"

                    return result["choices"][0].get("message", {}).get("content", "无法获取回复").strip()
        except asyncio.TimeoutError:
            logger.error("对话API请求超时")
            return "请求超时，请稍后再试"
        except Exception as e:
            logger.error(f"调用API失败: {str(e)}")
            logger.error(traceback.format_exc())
            return "服务请求失败"