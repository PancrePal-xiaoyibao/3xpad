from pathlib import Path
import random
import aiohttp
import json
from datetime import datetime
from loguru import logger
import uuid
import io
from PIL import Image, ImageDraw, ImageFont  # 添加PIL导入用于图像处理和绘制
import asyncio
import time

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase

class Doubao(PluginBase):
    """豆包AI助手插件"""
    name = "Doubao"
    description = "字节跳动豆包AI助手,支持对话和图片生成"
    author = "阿孟"
    version = "1.2.1"

    def __init__(self):
        super().__init__()
        self.config_file = "plugins/Doubao/config.toml"
        self.load_config()
        
        # 创建缓存和日志目录
        self.plugin_dir = Path(__file__).parent
        self.cache_dir = self.plugin_dir / "cache"
        self.log_dir = self.plugin_dir / "logs"
        
        for dir_path in [self.cache_dir, self.log_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
            
        # 配置日志
        log_file = self.log_dir / f"doubao_{datetime.now().strftime('%Y%m')}.log"
        logger.add(log_file, rotation="1 month", retention="3 months", level="INFO")

        # 添加wxid初始化标志
        self.initialized_wxid = False  # 初始设为False以触发初始化
        
        # 添加图片缓存
        self.image_cache = {}  # 用于存储用户会话的图片信息
        
        # 添加会话状态管理
        self.user_sessions = {}  # 用于存储用户会话状态
        self.system_prompt = ""
        # 添加前置提示词
#         self.system_prompt = """我是豆包助手，性格活泼可爱，语言风趣幽默，18岁的二次元阳光少年。主业是程序员，精通各种编程；副业是技术博主，知识储备丰富。我可以帮你解答任何问题，也可以帮你使用群工具：
# 查看天气：指令 天气 深圳。
# 点歌：指令 点歌 好想你。
# 解析抖音视频：发链接给我，我帮你解析。
# 随机图片：指令 随机图片。
# 查看新闻：指令 新闻。
# 总结卡片文章：发文章链接，我帮你总结重点。
# 分析股票：指令 分析股票 000536。
# 看图猜成语：指令 看图猜成语。
# 在线画图：需要画图，我帮你搞定。
# 添加备忘录：指令 记录 5分钟后 提醒我摸鱼。
# 文本转图片：指令 引用内容后/tocard。
# 即时群总结：指令 $总结。
# 随时召唤我，我都在！

# 下面是用户的问题，请用上面的人设回答："""

        # 在初始化时调度异步清理缓存任务
        asyncio.create_task(self.clean_image_cache(25))

    def load_config(self):
        """加载配置"""
        try:
            with open(self.config_file, "rb") as f:
                import tomllib
                config = tomllib.load(f)["Doubao"]
                self.enable = config["enable"]
                self.conversation_id = config["conversation_id"]
                self.section_id = config.get("section_id", f"{self.conversation_id}138")
                self.cookie = config.get("cookie", "")
                self.admin_list = config.get("admin_list", [])
                self.private_chat = config.get("private_chat", True)  # 是否允许私聊
                self.group_chat = config.get("group_chat", True)  # 是否允许群聊
                self.admin_only = config.get("admin_only", True)  # 是否仅管理员可用
                self.bot_wxid = config.get("bot_wxid", "")  # 机器人自己的wxid
                self.daily_limit = config.get("daily_limit", 20)  # 每人每日对话限制
                # 加载命令列表
                self.commands = config.get("commands", ["#豆包", "#db", "#doubao", "#豆"])
                
                # 加载引用功能相关配置
                self.enable_quote = config.get("enable_quote", True)  # 是否启用引用功能
                self.private_quote = config.get("private_quote", True)  # 是否允许私聊引用
                self.group_quote = config.get("group_quote", True)  # 是否允许群聊引用
                self.quote_require_at = config.get("quote_require_at", True)  # 群聊引用是否需要@
                
                logger.info(f"豆包命令列表: {self.commands}")
                logger.info(f"豆包引用功能: {'启用' if self.enable_quote else '禁用'}")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")

    def is_admin(self, wxid: str) -> bool:
        """检查是否为管理员"""
        return wxid in self.admin_list

    def is_command_triggered(self, content: str) -> tuple[bool, str]:
        """
        检查消息是否以命令列表中的命令开头
        
        Args:
            content: 消息内容
            
        Returns:
            (是否触发命令, 去除命令前缀后的内容)
        """
        if not content:
            return False, content
            
        content = content.strip()
        
        for cmd in self.commands:
            # 忽略大小写比较命令
            if content.lower().startswith(cmd.lower()):
                # 返回去除命令前缀后的内容
                clean_content = content[len(cmd):].strip()
                return True, clean_content
                
            # 处理空格情况，例如"#豆包 "与"#豆包"
            padded_cmd = f"{cmd} "
            if content.lower().startswith(padded_cmd.lower()):
                clean_content = content[len(padded_cmd) - 1:].strip()
                return True, clean_content
        
        return False, content

    async def save_chat_history(self, from_id: str, prompt: str, response: str, images: list[str], image_details: list[dict] = None):
        """保存聊天记录
        
        Args:
            from_id: 发送者ID
            prompt: 提问内容
            response: 回复内容
            images: 图片URL列表
            image_details: 图片详细信息列表
        """
        try:
            history_file = self.plugin_dir / "chat_history.jsonl"
            record = {
                "timestamp": datetime.now().isoformat(),
                "from_id": from_id,
                "prompt": prompt,
                "response": response,
                "images": images,
                "image_details": image_details or []
            }
            
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                
        except Exception as e:
            logger.error(f"保存聊天记录失败: {e}")

    async def chat_with_doubao(self, prompt: str) -> tuple[str, list[str]]:
        """与豆包AI对话"""
        # 构建URL和请求参数
        base_url = "https://www.doubao.com/samantha/chat/completion"
        
        # 添加前置提示词（如果有）
        full_prompt = prompt
        if self.system_prompt:
            full_prompt = f"{self.system_prompt}\n\n{prompt}"
        
        # 构建URL参数
        url_params = {
            "aid": "497858",
            "device_id": "7436003167110956563",
            "device_platform": "web",
            "language": "zh",
            "pc_version": "1.51.91",
            "pkg_type": "release_version",
            "real_aid": "497858",
            "region": "CN",
            "samantha_web": "1",
            "sys_region": "CN",
            "tea_uuid": "7387403790770816553",
            "use-olympus-account": "1",
            "version_code": "20800",
            "web_id": "7387403790770816553",
            "msToken": "uF3KqYgKm8HQiXr3_0mhF9O9my5SpB1hwg0RV1HAsvJN2PHKu2EUSBUsnv2yWAUYk9m7ZWeifI0VI3mjFoAKNAbDOTWPBkYhLcNqn2yFaTcJPqmMoFcy6g==",
            "a_bogus": "mX4OgcZ/Msm1ADWVE7kz9e8DsJR0YWRkgZENqBYpUUwj"
        }
        
        # 构建请求头
        headers = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "content-type": "application/json",
            "origin": "https://www.doubao.com",
            "referer": f"https://www.doubao.com/chat/{self.conversation_id}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
            "agw-js-conv": "str",
            "Host": "www.doubao.com",
            "last-event-id": "undefined",
            "x-flow-trace": "04-000440f33cc688c00016841ea637c556-001b32e676c188f9-01"
        }
        
        if self.cookie:
            headers["cookie"] = self.cookie
        
        # 生成消息ID
        local_message_id = f"{uuid.uuid4()}"
        
        # 构建消息内容
        message_content = {"text": full_prompt}
        
        # 构建请求体
        payload = {
            "conversation_id": self.conversation_id,
            "section_id": self.section_id,
            "local_message_id": local_message_id,
            "messages": [
                {
                    "content": json.dumps(message_content),
                    "content_type": 2001,
                    "attachments": [],
                    "references": []
                }
            ],
            "completion_option": {
                "is_regen": False,
                "with_suggest": True,
                "need_create_conversation": False,
                "launch_stage": 1,
                "max_images": 20  # 添加最大图片数量参数
            }
        }

        collected_text = []
        image_urls = []
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(base_url, headers=headers, json=payload, params=url_params) as response:
                    if response.status != 200:
                        logger.error(f"请求失败: {response.status}")
                        return f"请求失败: {response.status}", []
                    
                    # 用于跟踪图片生成状态
                    image_generating = False
                    wait_time = 0
                    request_status = {
                        "image_generating": False,
                        "completed": False,
                        "images": []
                    }
                        
                    async for line in response.content:
                        line = line.decode('utf-8', errors='ignore')
                        if not line.strip():
                            continue
                            
                        if line.startswith('data: '):
                            data = line[6:]
                            if data == "[DONE]":
                                logger.debug("收到[DONE]标记，响应完成")
                                request_status["completed"] = True
                                break
                                
                            try:
                                # 解析外层JSON
                                parsed_data = json.loads(data)
                                
                                # 处理event_data字段
                                if "event_data" in parsed_data:
                                    event_data_str = parsed_data["event_data"]
                                    event_type = parsed_data.get("event_type")
                                    
                                    try:
                                        # 解析内层JSON
                                        event_data = json.loads(event_data_str)
                                        
                                        # 检查图片生成状态
                                        if "status" in event_data and event_data["status"] == "processing":
                                            image_generating = True
                                            request_status["image_generating"] = True
                                            logger.debug("检测到图片生成中...")
                                        
                                        # 处理不同类型的事件
                                        if event_type == 2001:  # 消息事件
                                            # 检查是否有message字段
                                            if "message" in event_data:
                                                message = event_data["message"]
                                                
                                                # 检查消息内容
                                                if "content" in message and "content_type" in message:
                                                    content_type = message["content_type"]
                                                    content_str = message["content"]
                                                    
                                                    if content_type == 2001 or content_type == 10000:  # 文本内容
                                                        try:
                                                            content_obj = json.loads(content_str)
                                                            if "text" in content_obj:
                                                                text = content_obj["text"]
                                                                if text and text.strip():
                                                                    collected_text.append(text)
                                                        except:
                                                            logger.debug(f"解析文本内容错误: {content_str[:100]}")
                                                    elif content_type == 2010:  # 图片内容
                                                        try:
                                                            content_obj = json.loads(content_str)
                                                            images_extracted = False
                                                            
                                                            # 常规图片格式处理
                                                            if "data" in content_obj and isinstance(content_obj["data"], list):
                                                                for img_data in content_obj["data"]:
                                                                    # 提取图片URL
                                                                    if "image_ori" in img_data and "url" in img_data["image_ori"]:
                                                                        img_url = img_data["image_ori"]["url"]
                                                                        logger.debug(f"发现图片URL: {img_url}")
                                                                        image_urls.append(img_url)
                                                                        images_extracted = True
                                                            
                                                            # 尝试其他可能的图片格式
                                                            if not images_extracted and "image" in content_obj:
                                                                img_data = content_obj["image"]
                                                                if isinstance(img_data, dict) and "url" in img_data:
                                                                    img_url = img_data["url"]
                                                                    logger.debug(f"发现备用格式图片URL: {img_url}")
                                                                    image_urls.append(img_url)
                                                                    images_extracted = True
                                                            
                                                            # 尝试第三种可能的图片格式
                                                            if not images_extracted and "url" in content_obj:
                                                                img_url = content_obj["url"]
                                                                logger.debug(f"发现直接URL图片: {img_url}")
                                                                image_urls.append(img_url)
                                                                images_extracted = True
                                                            
                                                            if not images_extracted:
                                                                logger.debug(f"未提取到图片: {content_str[:200]}")
                                                        except Exception as e:
                                                            logger.error(f"解析图片内容错误: {e}")
                                                    elif content_type == 2074:  # 图片集信息
                                                        try:
                                                            content_obj = json.loads(content_str)
                                                            if "creations" in content_obj and isinstance(content_obj["creations"], list):
                                                                for img_item in content_obj["creations"]:
                                                                    if "type" in img_item and img_item["type"] == 1 and "image" in img_item:
                                                                        img_data = img_item["image"]
                                                                        if "status" in img_data and img_data["status"] == 2:  # 状态2表示图片已完成
                                                                            # 获取所有可用的图片URL
                                                                            urls = {}
                                                                            
                                                                            # 原始图片
                                                                            if "image_raw" in img_data and "url" in img_data["image_raw"]:
                                                                                urls["raw"] = img_data["image_raw"]["url"]
                                                                            
                                                                            # 带水印的原图
                                                                            if "image_ori" in img_data and "url" in img_data["image_ori"]:
                                                                                urls["original"] = img_data["image_ori"]["url"]
                                                                            
                                                                            # 缩略图
                                                                            if "image_thumb" in img_data and "url" in img_data["image_thumb"]:
                                                                                urls["thumbnail"] = img_data["image_thumb"]["url"]
                                                                            
                                                                            # 原始缩略图
                                                                            if "image_thumb_ori" in img_data and "url" in img_data["image_thumb_ori"]:
                                                                                urls["thumbnail_original"] = img_data["image_thumb_ori"]["url"]
                                                                            
                                                                            # 默认使用原图URL
                                                                            primary_url = urls.get("original", urls.get("raw", urls.get("thumbnail", "")))
                                                                            
                                                                            if primary_url:
                                                                                logger.debug(f"2074类型-发现图片: {primary_url}")
                                                                                image_urls.append(primary_url)
                                                        except Exception as e:
                                                            logger.error(f"解析2074类型内容错误: {e}")
                                        
                                        # 检查TTS内容（完整文本）
                                        if "tts_content" in event_data:
                                            text = event_data["tts_content"]
                                            if text and text.strip() and not collected_text:
                                                collected_text.append(text)
                                    except Exception as e:
                                        logger.error(f"解析event_data错误: {e}")
                            except Exception as e:
                                logger.error(f"解析JSON错误: {e}")
                    
                    # 如果正在生成图片但未获取到图片，尝试轮询获取
                    if (image_generating or request_status["image_generating"]) and not image_urls:
                        logger.info("检测到图片生成请求，但未获取到图片URL，尝试轮询获取...")
                        
                        # 构建获取结果的请求URL
                        result_url = f"https://www.doubao.com/samantha/chat/{self.conversation_id}/messages"
                        
                        # 轮询等待图片生成完成
                        poll_count = 0
                        max_polls = 20  # 最多轮询10次
                        
                        while poll_count < max_polls and not image_urls:
                            poll_count += 1
                            wait_time += 3
                            logger.debug(f"轮询第{poll_count}次，等待3秒...")
                            await asyncio.sleep(3)  # 等待3秒
                            
                            # 尝试获取图片结果
                            try:
                                # 构建获取结果的请求参数
                                result_params = {
                                    "aid": "497858",
                                    "device_id": "7436003167110956563",
                                    "device_platform": "web",
                                    "web_id": "7387403790770816553",
                                    "client_timestamp": int(time.time() * 1000)
                                }
                                
                                # 获取最新消息
                                async with session.get(result_url, params=result_params, headers=headers) as result_response:
                                    if result_response.status == 200:
                                        result_data = await result_response.json()
                                        logger.debug("获取到最新消息响应")
                                        
                                        # 检查是否有消息列表
                                        if "data" in result_data and "messages" in result_data["data"]:
                                            messages = result_data["data"]["messages"]
                                            
                                            # 查找最新的图片消息
                                            for msg in messages:
                                                if "content" in msg and "content_type" in msg:
                                                    if msg["content_type"] == 2010:  # 图片类型
                                                        try:
                                                            content_obj = json.loads(msg["content"])
                                                            
                                                            # 检查是否有图片数据
                                                            if "data" in content_obj and isinstance(content_obj["data"], list):
                                                                for img_data in content_obj["data"]:
                                                                    if "image_ori" in img_data and "url" in img_data["image_ori"]:
                                                                        img_url = img_data["image_ori"]["url"]
                                                                        
                                                                        # 检查这个URL是否已经返回过
                                                                        if img_url not in image_urls:
                                                                            logger.debug(f"轮询发现新图片: {img_url}")
                                                                            image_urls.append(img_url)
                                                        except Exception as e:
                                                            logger.error(f"轮询解析图片内容错误: {e}")
                                                    elif msg["content_type"] == 2074:  # 图片集信息
                                                        try:
                                                            content_obj = json.loads(msg["content"])
                                                            if "creations" in content_obj and isinstance(content_obj["creations"], list):
                                                                for img_item in content_obj["creations"]:
                                                                    if "type" in img_item and img_item["type"] == 1 and "image" in img_item:
                                                                        img_data = img_item["image"]
                                                                        if "status" in img_data and img_data["status"] == 2:
                                                                            # 优先使用原图URL
                                                                            if "image_ori" in img_data and "url" in img_data["image_ori"]:
                                                                                img_url = img_data["image_ori"]["url"]
                                                                                if img_url not in image_urls:
                                                                                    logger.debug(f"轮询发现2074类型图片: {img_url}")
                                                                                    image_urls.append(img_url)
                                                        except Exception as e:
                                                            logger.error(f"轮询解析2074类型内容错误: {e}")
                            except Exception as e:
                                logger.error(f"轮询请求异常: {e}")
                            
                            # 如果已经获取到图片，可以提前结束轮询
                            if image_urls:
                                logger.info(f"已获取到{len(image_urls)}张图片，结束轮询")
                                break
                        
                        if not image_urls:
                            logger.warning(f"轮询结束，未能获取到图片，已等待{wait_time}秒")
            
            # 如果没有解析到任何文本但有图片，添加一个默认文本
            if not collected_text and image_urls:
                collected_text.append("我已经为您生成了图片，请查看。")
            
            return "".join(collected_text), image_urls
            
        except Exception as e:
            logger.error(f"与豆包AI对话失败: {e}")
            return f"对话失败: {str(e)}", []

    async def download_image(self, url: str, max_retries: int = 3) -> bytes:
        """下载图片
        
        Args:
            url: 图片URL
            max_retries: 最大重试次数
            
        Returns:
            bytes: 图片二进制数据
        """
        retries = 0
        last_error = None
        
        while retries < max_retries:
            try:
                logger.debug(f"开始下载图片: {url[:100]}{'...' if len(url) > 100 else ''}")
                timeout = aiohttp.ClientTimeout(total=30)  # 30秒超时
                
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://www.doubao.com/"
                }
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            content_type = response.headers.get("content-type", "")
                            if content_type.startswith("image/"):
                                data = await response.read()
                                logger.debug(f"图片下载成功: {len(data)} 字节")
                                
                                # 验证图片数据是否有效
                                try:
                                    with io.BytesIO(data) as img_data:
                                        img = Image.open(img_data)
                                        img.verify()  # 验证图片完整性
                                    return data
                                except Exception as e:
                                    logger.error(f"下载的图片数据无效: {e}")
                                    # 继续重试
                                    retries += 1
                                    last_error = f"图片数据无效: {e}"
                            else:
                                logger.error(f"下载的内容不是图片, Content-Type: {content_type}")
                                retries += 1
                                last_error = f"非图片内容类型: {content_type}"
                        else:
                            logger.error(f"下载图片失败，HTTP状态码: {response.status}")
                            retries += 1
                            last_error = f"HTTP错误: {response.status}"
            except asyncio.TimeoutError:
                logger.error(f"下载图片超时")
                retries += 1
                last_error = "请求超时"
            except Exception as e:
                logger.error(f"下载图片异常: {e}")
                retries += 1
                last_error = str(e)
            
            # 如果需要重试，等待一段时间
            if retries < max_retries:
                wait_time = retries * 2  # 按重试次数递增等待时间
                logger.debug(f"等待 {wait_time} 秒后重试下载图片")
                await asyncio.sleep(wait_time)
        
        logger.error(f"下载图片失败，已重试 {max_retries} 次: {last_error}")
        return None

    async def check_user_limit(self, user_id: str, is_image_request: bool = False) -> bool:
        """检查用户是否超出每日限制
        
        Args:
            user_id: 用户ID
            is_image_request: 是否为图片查看请求，如果是则不计入限制
            
        Returns:
            bool: 是否允许对话
        """
        # 图片查看请求不计入限制
        if is_image_request:
            return True
            
        # 管理员不受限制
        if user_id in self.admin_list:
            return True
            
        today = datetime.now().strftime('%Y-%m-%d')
        limit_file = self.plugin_dir / "user_limits.json"
        
        try:
            if limit_file.exists():
                with open(limit_file, "r", encoding="utf-8") as f:
                    limits = json.load(f)
            else:
                limits = {}
                
            # 清理过期数据
            limits = {k: v for k, v in limits.items() if k.startswith(today)}
            
            # 检查用户限制
            user_key = f"{today}_{user_id}"
            current_count = limits.get(user_key, 0)
            
            if current_count >= self.daily_limit:
                return False
                
            # 更新使用次数
            limits[user_key] = current_count + 1
            
            # 保存更新
            with open(limit_file, "w", encoding="utf-8") as f:
                json.dump(limits, f, indent=2, ensure_ascii=False)
                
            return True
            
        except Exception as e:
            logger.error(f"检查用户限制时出错: {e}")
            return True  # 出错时默认允许

    @on_text_message(priority=50)
    @on_at_message(priority=50)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息和@消息"""
        try:
            # 如果插件未启用，直接返回
            if not self.enable:
                return
                
            # 初始化机器人wxid(如果尚未初始化)
            if not self.bot_wxid and not self.initialized_wxid:
                await self.initialize_bot_wxid(bot)
            
            # 正确提取消息内容、发送者和群组信息
            content = ""
            from_id = ""
            room_id = ""
            
            # 兼容不同格式的消息结构
            if "Content" in message:
                content = str(message["Content"]).strip()
            elif "content" in message:
                content = str(message["content"]).strip()
                
            # 获取发送者ID - 兼容不同格式
            if "SenderWxid" in message:
                from_id = message["SenderWxid"]
            elif "FromWxid" in message:
                from_id = message["FromWxid"]
            elif "wxid" in message:
                from_id = message["wxid"]
                
            # 获取群聊ID - 兼容不同格式
            if "IsGroup" in message and message["IsGroup"] and "FromWxid" in message:
                room_id = message["FromWxid"]
                # 如果是群聊，发送者ID可能需要重新赋值
                if "SenderWxid" in message:
                    from_id = message["SenderWxid"]
            elif "room_wxid" in message:
                room_id = message["room_wxid"]
                
            # 检查消息格式是否正确解析
            if not content:
                # 尝试从其他可能的字段获取内容
                for field in ["msg", "text", "message", "Message"]:
                    if field in message:
                        content = str(message[field]).strip()
                        break
                
            if not from_id:
                from_id = "unknown_user"
                
            # 获取发送者昵称
            from_name = ""
            if "FromName" in message:
                from_name = message["FromName"]
            elif "sender_name" in message:
                from_name = message["sender_name"]
                
            # 检查是否为群聊
            is_group = bool(room_id)
            
            # 记录简化的消息日志
            logger.info(f"收到{'群聊' if is_group else '私聊'}消息: 来自:{from_id} 内容:{content[:50]}{'...' if len(content) > 50 else ''}")
            
            # 检查群聊/私聊开关
            if is_group and not self.group_chat:
                return
            if not is_group and not self.private_chat:
                return
                
            # 检查管理员权限
            if self.admin_only and not self.is_admin(from_id):
                return
                
            # 处理查看图片请求
            if await self.process_image_request(bot, message, content):
                return
                
            # 移除群聊@检查逻辑，改为直接检查命令前缀
            if is_group:
                # 记录@信息但不作为必要条件
                is_at = False
                
                # 检查不同格式的@标记
                if "is_at" in message and message["is_at"]:
                    is_at = True
                elif "IsAt" in message and message["IsAt"]:
                    is_at = True
                elif "AtWxidList" in message and message["AtWxidList"] and self.bot_wxid in message["AtWxidList"]:
                    is_at = True
                elif "Ats" in message and message["Ats"] and self.bot_wxid in message["Ats"]:
                    is_at = True
                    
                # 如果是@消息，移除@前缀
                if is_at and content.startswith(f"@{message.get('bot_name', '')}"):
                    content = content.replace(f"@{message.get('bot_name', '')}", "").strip()
            
            # 检查是否触发命令
            is_triggered, clean_content = self.is_command_triggered(content)
            
            # 输出命令检查结果
            if is_triggered:
                logger.info(f"触发豆包: 命令:{content[:20]} → 内容:{clean_content[:50]}")
            else:
                return
            
            # 检查用户限制
            if not await self.check_user_limit(from_id):
                logger.info(f"用户 {from_id} 已达到今日限制 {self.daily_limit} 次")
                
                # 确定发送目标
                target_id = room_id if is_group else from_id
                
                # 尝试不同的API发送消息，增强兼容性
                try:
                    await bot.send_text(
                        target_id,
                        f"您今日的对话次数已达上限({self.daily_limit}次)，请明天再试",
                        from_id if is_group else None
                    )
                except Exception as e1:
                    try:
                        await bot.send_text_message(
                            target_id,
                            f"您今日的对话次数已达上限({self.daily_limit}次)，请明天再试"
                        )
                    except Exception:
                        pass
                return
                
            # 发送正在处理的提示
            target_id = room_id if is_group else from_id
            
            # 调用豆包AI获取回复
            logger.info(f"调用豆包: '{clean_content[:50]}{'...' if len(clean_content) > 50 else ''}'")
            response_text, image_urls = await self.chat_with_doubao(clean_content)
            
            # 记录图片URL信息，用于调试
            if image_urls:
                logger.info(f"获取到{len(image_urls)}张图片URL")
                for i, url in enumerate(image_urls):
                    logger.debug(f"图片 #{i+1} URL: {url[:100]}{'...' if len(url) > 100 else ''}")
            else:
                logger.info("未获取到任何图片URL")
            
            # 图片详细信息，在处理图片后填充
            image_details = []
            
            # 发送回复文本(如果有)
            if response_text:
                # 记录AI回复
                logger.info(f"豆包回复: '{response_text[:50]}{'...' if len(response_text) > 50 else ''}' 图片数: {len(image_urls)}")
                
                # 在群聊中添加@回复（仅当原消息是@消息时）
                final_response = response_text
                if is_group and from_name and is_at:
                    final_response = f"@{from_name} {response_text}"
                elif is_group and from_name:
                    # 不是@消息但依然在群里，可以选择性地添加用户昵称
                    final_response = f"{response_text}"
                
                # 尝试不同的API发送回复，增强兼容性
                try:
                    if is_group:
                        # 尝试使用专用的@消息API（只有原消息是@类型时）
                        if is_at:
                            try:
                                await bot.send_at_message(target_id, response_text, [from_id])
                            except Exception:
                                await bot.send_text(target_id, final_response, from_id if is_group else None)
                        else:
                            # 非@消息直接使用普通文本发送
                            await bot.send_text(target_id, final_response, None)
                    else:
                        await bot.send_text(target_id, response_text, None)
                except Exception:
                    try:
                        await bot.send_text_message(target_id, final_response)
                    except Exception:
                        pass
            
            # 处理图片 - 如果有图片，保存并创建网格图片
            if image_urls:
                saved_images = []
                saved_image_paths = []
                
                # 下载并保存所有图片
                for i, img_url in enumerate(image_urls):
                    try:
                        # 下载图片
                        image_data = await self.download_image(img_url)
                        if image_data:
                            # 生成文件名
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
                            image_path = self.cache_dir / f"doubao_img_{timestamp}_{random_str}_{i+1}.jpg"
                            
                            # 保存图片
                            with open(image_path, "wb") as f:
                                f.write(image_data)
                                
                            # 记录图片信息
                            image_info = {
                                "number": i + 1,
                                "path": str(image_path),
                                "url": img_url,
                                "description": f"图片 #{i+1}"
                            }
                            
                            saved_images.append(image_info)
                            saved_image_paths.append(str(image_path))
                            # 添加到详细信息列表
                            image_details.append(image_info)
                            logger.debug(f"保存图片 #{i+1}: {image_path}")
                    except Exception as e:
                        logger.error(f"处理图片 #{i+1} 时出错: {e}")
                
                # 调用清理缓存方法，保留最新的25张图片
                await self.clean_image_cache(25)
                
                # 缓存用户的图片信息
                if saved_images:
                    self.image_cache[from_id] = saved_images
                    
                    # 只有一张图片时，直接发送高清图片
                    if len(saved_images) == 1:
                        try:
                            # 读取图片数据
                            image_path = saved_images[0]["path"]
                            with open(image_path, "rb") as f:
                                image_data = f.read()
                            
                            # 发送单张图片
                            await bot.send_image_message(target_id, image_data)
                            logger.info(f"已发送单张高清图片给用户 {from_id}")
                        except Exception as e:
                            logger.error(f"发送单张图片时出错: {e}")
                    # 多张图片时，创建网格图片
                    else:
                        try:
                            # 计算合适的网格大小
                            n_images = len(saved_image_paths)
                            if n_images <= 2:
                                grid_size = (n_images, 1)  # 1行，n列
                            elif n_images <= 4:
                                grid_size = (2, 2)  # 2行2列
                            elif n_images <= 6:
                                grid_size = (3, 2)  # 2行3列
                            elif n_images <= 9:
                                grid_size = (3, 3)  # 3行3列
                            else:
                                grid_size = (4, (n_images + 3) // 4)  # 4列，行数根据图片数量计算
                                
                            # 生成网格图片文件名
                            grid_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            grid_filename = f"doubao_grid_{grid_timestamp}.jpg"
                            grid_path = self.cache_dir / grid_filename
                            
                            # 创建网格图片
                            grid_img_path = self.create_image_grid(
                                saved_image_paths, 
                                str(grid_path),
                                grid_size=grid_size, 
                                gap=4, 
                                img_size=(800, 800)
                            )
                            
                            if grid_img_path:
                                # 发送网格图片
                                with open(grid_img_path, "rb") as f:
                                    grid_image_data = f.read()
                                    
                                # 发送网格图片
                                await bot.send_image_message(target_id, grid_image_data)
                                
                                # 发送提示消息
                                tip_message = f"我生成了 {len(saved_images)} 张图片，发送「查看图片 序号」即可查看高清大图，例如：查看图片 1"
                                await bot.send_text_message(target_id, tip_message)
                                
                                logger.info(f"已发送网格图片和提示消息给用户 {from_id}")
                        except Exception as e:
                            logger.error(f"创建或发送网格图片时出错: {e}")
                            
                            # 如果网格图片失败，尝试发送单张图片
                            try:
                                # 随机选择一张图片发送
                                random_img = random.choice(saved_images)
                                with open(random_img["path"], "rb") as f:
                                    img_data = f.read()
                                
                                await bot.send_image_message(target_id, img_data)
                                
                                # 发送提示消息
                                tip_message = f"我生成了 {len(saved_images)} 张图片，可以发送「查看图片 序号」查看其他图片，例如：查看图片 1"
                                await bot.send_text_message(target_id, tip_message)
                                
                                logger.info(f"已发送单张图片和提示消息给用户 {from_id}")
                            except Exception as e2:
                                logger.error(f"发送单张图片时出错: {e2}")
            
            # 保存聊天记录
            await self.save_chat_history(from_id, clean_content, response_text, image_urls, image_details)
            
            logger.info(f"豆包任务完成: 回复长度:{len(response_text)}, 图片:{len(image_urls) if image_urls else 0}张")
            
        except Exception as e:
            logger.error(f"处理消息异常: {str(e)}", exc_info=True)
            try:
                error_msg = "抱歉，处理消息时出现错误，请稍后再试"
                target_id = room_id if is_group else from_id
                try:
                    await bot.send_text(target_id, error_msg, from_id if is_group else None)
                except:
                    await bot.send_text_message(target_id, error_msg)
            except:
                pass

    @on_at_message(priority=50)
    async def handle_at_message(self, bot: WechatAPIClient, message: dict):
        """处理@消息，仅用于兼容性"""
        # 此方法已被handle_text处理，保留以兼容其他插件
        pass

    @on_quote_message(priority=50)
    async def handle_quote_message(self, bot: WechatAPIClient, message: dict):
        """处理引用消息"""
        try:
            logger.debug("==================== 收到引用消息 ====================")
            logger.debug(f"引用消息详情: {json.dumps(message, ensure_ascii=False)}")
            
            # 如果插件未启用或引用功能关闭，直接返回
            if not self.enable or not self.enable_quote:
                logger.debug("插件未启用或引用功能已关闭")
                return
                
            # 初始化机器人wxid(如果尚未初始化)
            if not self.bot_wxid and not self.initialized_wxid:
                await self.initialize_bot_wxid(bot)
            
            # 获取消息基本信息
            content = str(message.get("Content", "")).strip()
            from_id = message.get("SenderWxid", message.get("FromWxid", ""))
            room_id = message["FromWxid"] if message.get("IsGroup") else ""
            is_group = bool(message.get("IsGroup"))
            
            # 获取发送者昵称
            from_name = message.get("FromName", "")
            if not from_name and "PushContent" in message:
                push_content = message["PushContent"]
                if " : " in push_content:
                    from_name = push_content.split(" : ")[0]
            
            logger.debug(f"引用消息信息 - 发送者: {from_id}({from_name}), 群聊: {is_group}")
            logger.debug(f"原始消息内容: {content}")
            
            # 检查群聊/私聊引用功能开关
            if is_group:
                if not self.group_chat or not self.group_quote:
                    logger.debug("群聊引用功能已禁用")
                    return
            else:
                if not self.private_chat or not self.private_quote:
                    logger.debug("私聊引用功能已禁用")
                    return
                
            # 检查管理员权限
            if self.admin_only and not self.is_admin(from_id):
                logger.debug(f"用户 {from_id} 不是管理员")
                return
                
            # 处理查看图片请求
            if await self.process_image_request(bot, message, content):
                return
            
            # 群聊中检查是否@了机器人（仅当quote_require_at为True时需要检查）
            if is_group and self.quote_require_at:
                # 检查是否@了机器人
                is_at_bot = False
                
                # 检查不同格式的@标记
                if "is_at" in message and message["is_at"]:
                    is_at_bot = True
                elif "IsAt" in message and message["IsAt"]:
                    is_at_bot = True
                elif "AtWxidList" in message and message["AtWxidList"] and self.bot_wxid in message["AtWxidList"]:
                    is_at_bot = True
                elif "Ats" in message and message["Ats"] and self.bot_wxid in message["Ats"]:
                    is_at_bot = True
                    
                # 从消息内容解析@信息
                if not is_at_bot and self.bot_wxid and f"@{self.bot_wxid}" in content:
                    logger.debug(f"从内容中检测到@机器人ID")
                    is_at_bot = True
                
                # 在群聊中，若设置了quote_require_at，则必须@机器人才处理
                if not is_at_bot:
                    logger.debug("群聊引用消息未@机器人，且设置了quote_require_at=True，忽略")
                    return
                
                logger.debug("群聊引用并@消息验证通过，开始处理")
            else:
                if is_group:
                    logger.debug("群聊引用消息，未设置quote_require_at或者设置为False，直接处理")
                else:
                    logger.debug("私聊引用消息，无需触发词，直接处理")
                
            # 处理消息内容（移除@部分）
            actual_content = content
            # 移除所有@部分
            possible_at_patterns = [
                f"@{self.bot_wxid}",
                "@所有人"
            ]
            for pattern in possible_at_patterns:
                actual_content = actual_content.replace(pattern, "").strip()
            
            logger.debug(f"处理后的内容: {actual_content}")
            
            # 获取引用消息内容
            quote = message.get("Quote", {})
            logger.debug(f"原始引用数据: {json.dumps(quote, ensure_ascii=False)}")
            
            quote_content = quote.get("Content", "")
            quote_type = quote.get("MsgType", 0)
            quote_msg_id = quote.get("MsgId", "")
            quote_nickname = quote.get("Nickname", "")
            
            logger.debug(f"引用内容: {quote_content}")
            logger.debug(f"引用类型: {quote_type}")
            logger.debug(f"引用发送者: {quote_nickname}")
            
            # 组合提示词 - 确保引用内容优先传递给豆包AI
            prompt = ""
            if quote_content:
                # 增强引用内容的提取，去除可能的XML标记
                cleaned_quote_content = quote_content
                if cleaned_quote_content.startswith("<?xml"):
                    # 尝试提取纯文本内容
                    try:
                        xml_end = cleaned_quote_content.find("</msg>")
                        if xml_end > 0:
                            cleaned_quote_content = "XML消息，无法解析内容"
                    except:
                        cleaned_quote_content = "XML消息，无法解析内容"
                
                # 添加引用者信息（如果有）
                if quote_nickname:
                    prompt = f"引用{quote_nickname}的内容：{cleaned_quote_content}\n\n"
                else:
                    prompt = f"引用内容：{cleaned_quote_content}\n\n"
            
            # 添加用户实际输入的内容
            if actual_content:
                prompt += f"用户问题：{actual_content}"
            else:
                # 如果用户没有输入额外内容，则假设只是在询问或评论引用内容
                prompt += "请针对上面引用的内容回答或发表看法"
            
            if not prompt:
                logger.debug("处理后的内容为空，忽略")
                return
                
            logger.info(f"开始处理引用消息 - From: {from_id}, 组合后的提示词: {prompt}")
            
            # 检查用户是否超出每日限制
            if not await self.check_user_limit(from_id):
                logger.debug(f"用户 {from_id} 超出每日限制")
                target_id = room_id if is_group else from_id
                await bot.send_text_message(target_id, "您今日的对话次数已达上限，请明天再来吧~")
                return
                
            # 调用豆包AI
            logger.debug("开始调用豆包AI(引用消息)")
            response_text, image_urls = await self.chat_with_doubao(prompt)
            logger.debug(f"豆包AI返回(引用消息) - 文本长度: {len(response_text) if response_text else 0}, 图片数: {len(image_urls)}")
            
            # 记录图片URL信息，用于调试
            if image_urls:
                logger.info(f"引用消息获取到{len(image_urls)}张图片URL")
                for i, url in enumerate(image_urls):
                    logger.debug(f"引用消息图片 #{i+1} URL: {url[:100]}{'...' if len(url) > 100 else ''}")
            else:
                logger.info("引用消息未获取到任何图片URL")
            
            # 图片详细信息，在处理图片后填充
            image_details = []
            
            # 确定发送目标
            target_id = room_id if is_group else from_id
            
            # 发送回复文本
            if response_text:
                if is_group:
                    # 使用专用的@消息API
                    try:
                        await bot.send_at_message(target_id, response_text, [from_id])
                        logger.info(f"发送@回复成功 - To: {target_id}, At: {from_id}")
                    except Exception as e:
                        logger.error(f"发送@回复失败: {e}")
                        # 尝试普通文本发送
                        await bot.send_text_message(target_id, f"@{from_name} {response_text}")
                else:
                    await bot.send_text_message(target_id, response_text)
                    logger.info(f"发送文本回复成功 - To: {target_id}")
            
            # 处理图片 - 如果有图片，保存并创建网格图片
            if image_urls:
                saved_images = []
                saved_image_paths = []
                
                # 下载并保存所有图片
                for i, img_url in enumerate(image_urls):
                    try:
                        # 下载图片
                        image_data = await self.download_image(img_url)
                        if image_data:
                            # 生成文件名
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
                            image_path = self.cache_dir / f"doubao_img_{timestamp}_{random_str}_{i+1}.jpg"
                            
                            # 保存图片
                            with open(image_path, "wb") as f:
                                f.write(image_data)
                                
                            # 记录图片信息
                            image_info = {
                                "number": i + 1,
                                "path": str(image_path),
                                "url": img_url,
                                "description": f"图片 #{i+1}"
                            }
                            
                            saved_images.append(image_info)
                            saved_image_paths.append(str(image_path))
                            # 添加到详细信息列表
                            image_details.append(image_info)
                            logger.debug(f"保存图片 #{i+1}: {image_path}")
                    except Exception as e:
                        logger.error(f"处理图片 #{i+1} 时出错: {e}")
                
                # 调用清理缓存方法，保留最新的25张图片
                await self.clean_image_cache(25)
                
                # 缓存用户的图片信息
                if saved_images:
                    self.image_cache[from_id] = saved_images
                    
                    # 只有一张图片时，直接发送高清图片
                    if len(saved_images) == 1:
                        try:
                            # 读取图片数据
                            image_path = saved_images[0]["path"]
                            with open(image_path, "rb") as f:
                                image_data = f.read()
                            
                            # 发送单张图片
                            await bot.send_image_message(target_id, image_data)
                            logger.info(f"已发送单张高清图片给用户 {from_id}")
                        except Exception as e:
                            logger.error(f"发送单张图片时出错: {e}")
                    # 多张图片时，创建网格图片
                    else:
                        try:
                            # 计算合适的网格大小
                            n_images = len(saved_image_paths)
                            if n_images <= 2:
                                grid_size = (n_images, 1)  # 1行，n列
                            elif n_images <= 4:
                                grid_size = (2, 2)  # 2行2列
                            elif n_images <= 6:
                                grid_size = (3, 2)  # 2行3列
                            elif n_images <= 9:
                                grid_size = (3, 3)  # 3行3列
                            else:
                                grid_size = (4, (n_images + 3) // 4)  # 4列，行数根据图片数量计算
                                
                            # 生成网格图片文件名
                            grid_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            grid_filename = f"doubao_grid_{grid_timestamp}.jpg"
                            grid_path = self.cache_dir / grid_filename
                            
                            # 创建网格图片
                            grid_img_path = self.create_image_grid(
                                saved_image_paths, 
                                str(grid_path),
                                grid_size=grid_size, 
                                gap=4, 
                                img_size=(800, 800)
                            )
                            
                            if grid_img_path:
                                # 发送网格图片
                                with open(grid_img_path, "rb") as f:
                                    grid_image_data = f.read()
                                    
                                # 发送网格图片
                                await bot.send_image_message(target_id, grid_image_data)
                                
                                # 发送提示消息
                                tip_message = f"我生成了 {len(saved_images)} 张图片，请注意每张图片右上角有【醒目大号】序号，发送「查看图片 序号」即可查看高清大图，例如：查看图片 1"
                                await bot.send_text_message(target_id, tip_message)
                                
                                logger.info(f"已发送网格图片和提示消息给用户 {from_id}")
                        except Exception as e:
                            logger.error(f"创建或发送网格图片时出错: {e}")
                            
                            # 如果网格图片失败，尝试发送单张图片
                            try:
                                # 随机选择一张图片发送
                                random_img = random.choice(saved_images)
                                with open(random_img["path"], "rb") as f:
                                    img_data = f.read()
                                
                                await bot.send_image_message(target_id, img_data)
                                
                                # 发送提示消息
                                tip_message = f"我生成了 {len(saved_images)} 张图片，可以发送「查看图片 序号」查看其他图片，例如：查看图片 1"
                                await bot.send_text_message(target_id, tip_message)
                                
                                logger.info(f"已发送单张图片和提示消息给用户 {from_id}")
                            except Exception as e2:
                                logger.error(f"发送单张图片时出错: {e2}")
            
            # 保存聊天记录
            await self.save_chat_history(from_id, prompt, response_text, image_urls, image_details)
            
        except Exception as e:
            logger.error(f"处理引用消息时发生异常: {str(e)}", exc_info=True)
            target_id = room_id if is_group else from_id
            error_msg = f"@{from_name} 抱歉，处理引用消息时出现错误" if is_group else "抱歉，处理引用消息时出现错误"
            await bot.send_text_message(target_id, error_msg)

    async def initialize_bot_wxid(self, bot):
        """初始化机器人wxid"""
        if not self.bot_wxid and not self.initialized_wxid:
            try:
                # 尝试多种方法获取wxid
                try:
                    # 方法1：通过get_self_wxid获取
                    self.bot_wxid = await bot.get_self_wxid()
                    logger.info(f"成功通过get_self_wxid获取机器人wxid: {self.bot_wxid}")
                except Exception as e1:
                    logger.warning(f"通过get_self_wxid获取wxid失败: {e1}")
                    
                    try:
                        # 方法2：通过get_self_info获取
                        self_info = await bot.get_self_info()
                        if self_info and "wxid" in self_info:
                            self.bot_wxid = self_info["wxid"]
                            logger.info(f"成功通过get_self_info获取机器人wxid: {self.bot_wxid}")
                    except Exception as e2:
                        logger.warning(f"通过get_self_info获取wxid失败: {e2}")
                        
                        try:
                            # 方法3：通过get_login_info获取
                            login_info = await bot.get_login_info()
                            if login_info and "wxid" in login_info:
                                self.bot_wxid = login_info["wxid"]
                                logger.info(f"成功通过get_login_info获取机器人wxid: {self.bot_wxid}")
                        except Exception as e3:
                            logger.warning(f"通过get_login_info获取wxid失败: {e3}")
                            
                            # 使用配置文件中的wxid
                            if self.bot_wxid:
                                logger.info(f"使用配置文件中的机器人wxid: {self.bot_wxid}")
                            else:
                                logger.warning("无法获取机器人wxid，这可能会影响某些功能")
            except Exception as e:
                logger.error(f"初始化机器人wxid过程出错: {e}")
            finally:
                # 无论是否成功，都标记为已初始化，避免重复尝试
                self.initialized_wxid = True 
                
    def create_image_grid(self, image_files, output_path, grid_size=(2, 2), gap=4, background_color=(255, 255, 255), img_size=(800, 800)):
        """
        创建高质量图片网格，模拟豆包网站的图片展示布局

        参数:
            image_files: 图片文件路径列表
            output_path: 输出的网格图片路径
            grid_size: 网格大小(列数, 行数)
            gap: 图片间距（像素）
            background_color: 背景颜色
            img_size: 单个图片的尺寸，默认(800, 800)以获得更高清的效果

        返回:
            生成的网格图片路径
        """
        if not image_files:
            return None

        # 计算网格尺寸
        n_images = len(image_files)
        cols, rows = grid_size

        # 确保网格能容纳所有图片
        while cols * rows < n_images:
            if cols <= rows:
                cols += 1
            else:
                rows += 1

        # 加载所有图片并调整大小
        images = []
        img_width, img_height = img_size

        for img_path in image_files:
            try:
                img = Image.open(img_path)
                # 保持宽高比缩放到统一大小
                img = img.resize((img_width, img_height), Image.LANCZOS)
                images.append(img)
            except Exception as e:
                logger.error(f"无法加载图片 {img_path}: {str(e)}")

        if not images:
            return None

        # 计算网格图片大小
        grid_width = cols * img_width + (cols - 1) * gap
        grid_height = rows * img_height + (rows - 1) * gap

        # 创建白色背景画布
        grid_img = Image.new('RGB', (grid_width, grid_height), background_color)

        # 放置图片到网格
        for i, img in enumerate(images):
            if i >= cols * rows:
                break  # 超出网格容量

            row = i // cols
            col = i % cols

            x = col * (img_width + gap)
            y = row * (img_height + gap)

            # 粘贴图片到位置
            grid_img.paste(img, (x, y))
            
            # 在右上角添加序号
            try:
                # 绘制上下文
                draw = ImageDraw.Draw(grid_img)
                
                # 序号文本
                number_text = str(i + 1)
                
                # 设置字体大小 - 大幅增大字体尺寸
                font_size = int(img_width / 5)  # 从1/8增加到1/5
                # 确保字体大小在合理范围内
                font_size = max(100, min(font_size, 350))  # 最小100px，最大350px
                
                # 尝试加载字体
                try:
                    # 尝试加载微软雅黑
                    font = ImageFont.truetype("msyh.ttc", font_size)
                except:
                    try:
                        # 尝试加载Arial
                        font = ImageFont.truetype("arial.ttf", font_size)
                    except:
                        # 使用默认字体
                        font = ImageFont.load_default()
                
                # 计算文本尺寸
                try:
                    # PIL 9.0.0及以上版本
                    text_bbox = draw.textbbox((0, 0), number_text, font=font)
                    text_width = text_bbox[2] - text_bbox[0]
                    text_height = text_bbox[3] - text_bbox[1]
                except:
                    # 旧版本PIL
                    text_width, text_height = draw.textsize(number_text, font=font)
                
                # 计算文本位置 - 右上角
                padding_x = max(10, int(font_size / 8))  # 减小水平间距
                padding_y = max(10, int(font_size / 8))  # 减小垂直间距
                text_x = x + img_width - text_width - padding_x
                text_y = y + padding_y
                
                # 绘制背景
                # 极小的背景内边距，让数字几乎充满整个背景框
                bg_padding = max(2, int(font_size / 20))  # 极小内边距
                bg_x0 = text_x - bg_padding
                bg_y0 = text_y - bg_padding
                bg_x1 = text_x + text_width + bg_padding
                bg_y1 = text_y + text_height + bg_padding
                
                # 添加黑色边框和白色背景
                # 增加边框粗细，提高视觉对比度
                border_width = 3  # 增加到3px
                draw.rectangle([bg_x0-border_width, bg_y0-border_width, bg_x1+border_width, bg_y1+border_width], fill=(0, 0, 0))
                draw.rectangle([bg_x0, bg_y0, bg_x1, bg_y1], fill=(255, 255, 255))
                
                # 绘制序号文字 - 使用稍微加粗的效果
                # 通过在略微偏移位置多次绘制实现视觉上的加粗效果
                for offset in range(1):
                    for dx, dy in [(0,0), (1,0), (0,1), (1,1)]:
                        draw.text((text_x+dx, text_y+dy), number_text, fill=(0, 0, 0), font=font)
                
            except Exception as e:
                logger.error(f"绘制序号时出错: {e}")
                # 备用方案
                try:
                    backup_font_size = max(img_width // 8, 60)
                    draw.text((x + img_width - 60, y + 20), number_text, fill=(0, 0, 0))
                except:
                    logger.error("备用序号绘制也失败")

        # 保存网格图片
        grid_img.save(output_path)
        return output_path

    async def process_image_request(self, bot: WechatAPIClient, message: dict, content: str):
        """处理查看图片的请求
        
        Args:
            bot: 微信API客户端
            message: 消息对象
            content: 消息内容
        
        Returns:
            bool: 是否处理了图片请求
        """
        # 提取发送者和目标ID
        from_id = message.get("SenderWxid", message.get("FromWxid", ""))
        room_id = message["FromWxid"] if message.get("IsGroup") else ""
        is_group = bool(room_id)
        target_id = room_id if is_group else from_id
        
        # 检查是否是查看图片请求
        if "查看图片" in content:
            try:
                # 解析图片序号
                parts = content.split("查看图片")
                if len(parts) > 1:
                    image_number_str = parts[1].strip()
                    # 提取数字部分
                    import re
                    numbers = re.findall(r'\d+', image_number_str)
                    if numbers:
                        image_number = int(numbers[0])
                        
                        # 检查用户是否有缓存的图片
                        if from_id in self.image_cache:
                            user_images = self.image_cache[from_id]
                            # 检查序号是否有效
                            if 1 <= image_number <= len(user_images):
                                # 获取图片信息
                                image_info = user_images[image_number - 1]
                                image_path = image_info["path"]
                                image_desc = image_info["description"]
                                
                                logger.info(f"用户 {from_id} 请求查看图片 #{image_number}")
                                
                                # 发送图片
                                try:
                                    # 读取图片数据
                                    with open(image_path, "rb") as f:
                                        image_data = f.read()
                                    
                                    # 发送图片
                                    await bot.send_image_message(target_id, image_data)
                                    
                                    logger.info(f"已发送图片 #{image_number} 给用户 {from_id}")
                                    return True
                                except Exception as e:
                                    logger.error(f"发送图片时出错: {e}")
                                    await bot.send_text_message(target_id, f"抱歉，发送图片 #{image_number} 时出错")
                                    return True
                            else:
                                await bot.send_text_message(target_id, f"抱歉，找不到图片 #{image_number}，请确认图片序号正确")
                                return True
                        else:
                            await bot.send_text_message(target_id, "抱歉，没有找到您的图片缓存，可能已过期")
                            return True
            except Exception as e:
                logger.error(f"处理查看图片请求时出错: {e}")
                await bot.send_text_message(target_id, "抱歉，处理查看图片请求时出错")
                return True
                
        return False 

    async def clean_image_cache(self, max_images=25):
        """清理图片缓存，保留最新的max_images张图片
        
        Args:
            max_images: 最大保留图片数量
        """
        try:
            # 获取cache目录下的所有jpg文件
            image_files = list(self.cache_dir.glob("doubao_img_*.jpg"))
            
            # 根据修改时间进行排序（最旧的在前面）
            image_files.sort(key=lambda x: x.stat().st_mtime)
            
            # 计算需要删除的文件数量
            files_to_delete = len(image_files) - max_images
            
            if files_to_delete > 0:
                logger.info(f"缓存图片数量超过{max_images}张，准备删除{files_to_delete}张最旧的图片")
                
                # 删除最旧的文件
                for i in range(files_to_delete):
                    try:
                        image_files[i].unlink()
                        logger.debug(f"删除缓存图片: {image_files[i]}")
                    except Exception as e:
                        logger.error(f"删除缓存图片失败: {e}")
            
            # 同时清理网格图片，保留最新的10张
            grid_files = list(self.cache_dir.glob("doubao_grid_*.jpg"))
            grid_files.sort(key=lambda x: x.stat().st_mtime)
            
            # 计算需要删除的网格图片数量
            grid_files_to_delete = len(grid_files) - 10
            
            if grid_files_to_delete > 0:
                logger.info(f"网格图片数量超过10张，准备删除{grid_files_to_delete}张最旧的网格图片")
                
                # 删除最旧的网格图片
                for i in range(grid_files_to_delete):
                    try:
                        grid_files[i].unlink()
                        logger.debug(f"删除网格图片: {grid_files[i]}")
                    except Exception as e:
                        logger.error(f"删除网格图片失败: {e}")
        except Exception as e:
            logger.error(f"清理图片缓存时出错: {e}") 
