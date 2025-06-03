from utils.plugin_base import PluginBase
from utils.decorators import on_text_message, on_file_message, on_article_message
import aiohttp
import asyncio
import re
import os
import sys
import tomllib
import time
from loguru import logger
from typing import Dict, Optional, TYPE_CHECKING
import json
import html
import xml.etree.ElementTree as ET
from urllib.parse import quote
import random
# 分别尝试导入每个库，以便更精确地识别哪个库缺失
has_bs4 = True
has_requests = True
has_requests_html = True

try:
    from bs4 import BeautifulSoup
except ImportError:
    logger.warning("BeautifulSoup库未安装，无法使用部分内容提取功能")
    has_bs4 = False
try:
    import requests
except ImportError:
    logger.warning("requests库未安装，无法使用部分内容提取功能")
    has_requests = False

# 动态内容提取方法已移除，不再需要requests_html和lxml_html_clean
has_requests_html = False

# 总体判断是否可以使用高级内容提取方法
can_use_advanced_extraction = has_bs4 and has_requests

# 类型提示导入
if TYPE_CHECKING:
    from WechatAPI import WechatAPIClient

class AutoSummary(PluginBase):
    description = "自动总结文本内容和卡片消息"
    author = "老夏的金库"
    version = "1.3.0"

    URL_PATTERN = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[-\w./?=&]*'

    def __init__(self):
        super().__init__()
        self.name = "AutoSummary"

        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        with open(config_path, "rb") as f:
            config = tomllib.load(f)

        self.config = config.get("AutoSummary", {})
        dify_config = self.config.get("Dify", {})
        self.dify_enable = dify_config.get("enable", False)
        self.dify_api_key = dify_config.get("api-key", "")
        self.dify_base_url = dify_config.get("base-url", "")
        self.http_proxy = dify_config.get("http-proxy", "")

        settings = self.config.get("Settings", {})
        self.max_text_length = settings.get("max_text_length", 8000)
        self.black_url_list = settings.get("black_url_list", [])
        self.white_url_list = settings.get("white_url_list", [])
        # 从配置文件中读取缓存过期时间
        self.expiration_time = settings.get("expiration_time", 1800)  # 默认30分钟

        # 加载新的配置项
        # 总结命令触发词
        self.sum_trigger = self.config.get("sum_trigger", "/总结")
        # 构建触发词列表，包括基本触发词和衍生触发词
        self.summary_triggers = [
            self.sum_trigger,
            f"{self.sum_trigger}链接",
            f"{self.sum_trigger}内容",
            f"{self.sum_trigger}一下",
            f"帮我{self.sum_trigger}",
            "summarize"
        ]

        # 追问命令触发词
        self.qa_trigger = self.config.get("qa_trigger", "问")

        # 自动总结开关
        self.auto_sum = self.config.get("auto_sum", True)

        # 用户黑白名单
        self.white_user_list = self.config.get("white_user_list", [])
        self.black_user_list = self.config.get("black_user_list", [])

        # 群组黑白名单
        self.white_group_list = self.config.get("white_group_list", [])
        self.black_group_list = self.config.get("black_group_list", [])

        logger.info(f"AutoSummary插件配置加载完成: 触发词={self.sum_trigger}, 自动总结={self.auto_sum}")
        logger.info(f"缓存过期时间: {self.expiration_time}秒")
        logger.info(f"URL白名单: {self.white_url_list}")
        logger.info(f"URL黑名单: {self.black_url_list}")
        logger.info(f"用户白名单: {self.white_user_list}")
        logger.info(f"用户黑名单: {self.black_user_list}")
        logger.info(f"群组白名单: {self.white_group_list}")
        logger.info(f"群组黑名单: {self.black_group_list}")

        # 存储最近的链接和卡片信息
        self.recent_urls = {}  # 格式: {chat_id: {"url": url, "timestamp": timestamp}}
        self.recent_cards = {}  # 格式: {chat_id: {"info": card_info, "timestamp": timestamp}}

        # 存储总结内容缓存
        self.summary_cache = {}  # 格式: {chat_id: {"summary": summary, "original_content": content, "timestamp": timestamp}}

        self.http_session = aiohttp.ClientSession()

        if not self.dify_enable or not self.dify_api_key or not self.dify_base_url:
            logger.warning("Dify配置不完整，自动总结功能将被禁用")
            self.dify_enable = False

    async def close(self):
        if self.http_session:
            await self.http_session.close()
            logger.info("HTTP会话已关闭")

    def _check_url(self, url: str) -> bool:
        stripped_url = url.strip()
        if not stripped_url.startswith(('http://', 'https://')):
            return False
        if self.white_url_list and not any(stripped_url.startswith(white_url) for white_url in self.white_url_list):
            return False
        if any(stripped_url.startswith(black_url) for black_url in self.black_url_list):
            return False
        return True

    # 检查是否是总结命令
    def _is_summary_command(self, content: str) -> bool:
        content = content.strip().lower()
        # 检查是否以任何触发词开头，支持触发词后有不定数量的空格或没有空格
        for trigger in self.summary_triggers:
            # 使用正则表达式匹配触发词开头，后面可以跟任意字符
            if re.match(f"^{re.escape(trigger)}\\s*.*", content):
                return True
        return False

    # 检查是否是追问命令
    def _is_qa_command(self, content: str) -> bool:
        content = content.strip().lower()
        # 检查是否以追问触发词开头，支持触发词后有不定数量的空格或没有空格
        return re.match(f"^{re.escape(self.qa_trigger)}\\s*.*", content) is not None

    # 清理过期的链接、卡片和总结缓存
    def _clean_expired_items(self):
        current_time = time.time()
        # 清理过期的URL
        for chat_id in list(self.recent_urls.keys()):
            if current_time - self.recent_urls[chat_id]["timestamp"] > self.expiration_time:
                del self.recent_urls[chat_id]

        # 清理过期的卡片
        for chat_id in list(self.recent_cards.keys()):
            if current_time - self.recent_cards[chat_id]["timestamp"] > self.expiration_time:
                del self.recent_cards[chat_id]

        # 清理过期的总结缓存
        for chat_id in list(self.summary_cache.keys()):
            if current_time - self.summary_cache[chat_id]["timestamp"] > self.expiration_time:
                del self.summary_cache[chat_id]

    # 检查是否应该自动总结
    def _should_auto_summarize(self, chat_id: str, is_group: bool, sender_id: str = None) -> bool:
        """
        根据配置和黑白名单判断是否应该自动总结

        逻辑顺序：
        1. 首先检查白名单（无论全局开关如何，白名单中的用户/群组都自动总结）
        2. 然后检查全局开关（如果为false且不在白名单中，不自动总结）
        3. 最后检查黑名单（如果在黑名单中，不自动总结）

        Args:
            chat_id: 聊天ID（用户ID或群组ID）
            is_group: 是否是群聊
            sender_id: 发送者ID，在群聊中与chat_id不同

        Returns:
            bool: 是否应该自动总结
        """
        # 1. 首先检查白名单

        # 检查用户是否在白名单中
        if is_group and sender_id:
            # 群聊中的用户
            if sender_id in self.white_user_list:
                logger.info(f"群聊 {chat_id} 中的用户 {sender_id} 在用户白名单中，将自动总结")
                return True
        elif not is_group:
            # 私聊用户
            if chat_id in self.white_user_list:
                logger.info(f"用户 {chat_id} 在用户白名单中，将自动总结")
                return True

        # 检查群组是否在白名单中
        if is_group and chat_id in self.white_group_list:
            logger.info(f"群组 {chat_id} 在群组白名单中，将自动总结")
            return True

        # 2. 然后检查全局开关
        if not self.auto_sum:
            logger.info(f"自动总结已关闭，且{'群组' if is_group else '用户'} {chat_id} 不在白名单中，不会自动总结")
            return False

        # 3. 最后检查黑名单

        # 检查用户是否在黑名单中
        if is_group and sender_id:
            # 群聊中的用户
            if sender_id in self.black_user_list:
                logger.info(f"群聊 {chat_id} 中的用户 {sender_id} 在用户黑名单中，不会自动总结")
                return False
        elif not is_group:
            # 私聊用户
            if chat_id in self.black_user_list:
                logger.info(f"用户 {chat_id} 在用户黑名单中，不会自动总结")
                return False

        # 检查群组是否在黑名单中
        if is_group and chat_id in self.black_group_list:
            logger.info(f"群组 {chat_id} 在群组黑名单中，不会自动总结")
            return False

        # 全局开关为true，且不在黑名单中，自动总结
        logger.info(f"{'群组' if is_group else '用户'} {chat_id} 不在黑名单中，将自动总结")
        return True

    async def _fetch_url_content(self, url: str) -> Optional[str]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            }
            # 不在顶层设置超时参数

            # 先检查是否有重定向，获取最终URL
            final_url = url
            try:
                # 只发送HEAD请求来检查重定向，不获取实际内容
                async def check_redirect():
                    # 在任务中设置超时
                    timeout = aiohttp.ClientTimeout(total=30)
                    async with self.http_session.head(url, headers=headers, allow_redirects=True, timeout=timeout) as head_response:
                        if head_response.status == 200:
                            return str(head_response.url)
                        return url

                final_url = await asyncio.create_task(check_redirect())
                if final_url != url:
                    logger.info(f"检测到重定向: {url} -> {final_url}")
            except Exception as e:
                logger.warning(f"检查重定向失败: {e}, 使用原始URL")
                final_url = url

            # 使用 Jina AI 获取内容（使用最终URL）
            logger.info(f"使用 Jina AI 获取内容: {final_url}")
            try:
                # 检查是否是微信文章URL
                if "mp.weixin.qq.com" in final_url:
                    # 对微信URL进行完全编码处理
                    encoded_url = quote(final_url, safe='')
                    logger.info(f"检测到微信文章，使用完全编码URL: {encoded_url}")
                    jina_url = f"https://r.jina.ai/{encoded_url}"
                else:
                    jina_url = f"https://r.jina.ai/{final_url}"

                async def get_jina_content():
                    # 在任务中设置超时
                    timeout = aiohttp.ClientTimeout(total=30)
                    async with self.http_session.get(jina_url, headers=headers, timeout=timeout) as jina_response:
                        if jina_response.status == 200:
                            content = await jina_response.text()
                            return content
                        return None

                content = await asyncio.create_task(get_jina_content())

                # 区分微信平台和非微信平台的判断标准
                if "mp.weixin.qq.com" in final_url:
                    # 微信平台文章：检查内容是否为空和是否包含"环境异常"字段
                    if content and "环境异常" not in content:
                        logger.info(f"从 Jina AI 获取微信文章内容成功: {jina_url}, 内容长度: {len(content)}")
                        return content
                    else:
                        if not content:
                            logger.error(f"从 Jina AI 获取微信文章内容失败，返回为空，URL: {jina_url}")
                        elif "环境异常" in content:
                            logger.error(f"从 Jina AI 获取微信文章内容包含'环境异常'，URL: {jina_url}")
                        else:
                            logger.error(f"从 Jina AI 获取微信文章内容失败，未知原因，URL: {jina_url}")
                else:
                    # 非微信平台文章：只检查内容是否为空
                    if content:
                        logger.info(f"从 Jina AI 获取内容成功: {jina_url}, 内容长度: {len(content)}")
                        return content
                    else:
                        logger.error(f"从 Jina AI 获取内容失败，返回为空，URL: {jina_url}")
            except Exception as e:
                logger.error(f"使用Jina AI获取内容失败: {e}")

            # 如果 Jina AI 失败，尝试使用通用内容提取方法
            logger.info(f"Jina AI 失败，尝试使用通用内容提取方法: {final_url}")
            if can_use_advanced_extraction:
                try:
                    # 使用通用内容提取方法（JinaSum插件的第四种方法）
                    content = await asyncio.get_event_loop().run_in_executor(None, lambda: self._extract_content_general(final_url))

                    # 区分微信平台和非微信平台的判断标准
                    if "mp.weixin.qq.com" in final_url:
                        # 微信平台文章：检查内容是否足够长且不包含"环境异常"字段
                        if content and len(content) > 50 and "环境异常" not in content:
                            logger.info(f"通用内容提取方法成功获取微信文章: {final_url}, 内容长度: {len(content)}")
                            return content
                        else:
                            if not content or len(content) <= 50:
                                logger.warning(f"通用内容提取方法获取的微信文章内容过短或为空: {final_url}")
                            elif "环境异常" in content:
                                logger.warning(f"通用内容提取方法获取的微信文章内容包含'环境异常': {final_url}")
                    else:
                        # 非微信平台文章：只检查内容是否足够长
                        if content and len(content) > 50:
                            logger.info(f"通用内容提取方法成功: {final_url}, 内容长度: {len(content)}")
                            return content
                        else:
                            logger.warning(f"通用内容提取方法获取的内容过短或为空: {final_url}")
                except Exception as e:
                    logger.error(f"使用通用内容提取方法失败: {e}")

                # 动态内容提取方法已移除
                logger.warning(f"通用内容提取方法失败，无法获取内容: {final_url}")
            else:
                if not has_bs4 and not has_requests:
                    logger.warning("BeautifulSoup和requests库未安装，无法使用高级内容提取方法")
                elif not has_bs4:
                    logger.warning("BeautifulSoup库未安装，无法使用高级内容提取方法")
                elif not has_requests:
                    logger.warning("requests库未安装，无法使用高级内容提取方法")
                if not has_requests_html:
                    logger.warning("requests_html库未安装，动态内容提取功能不可用")

            # 所有方法都失败
            logger.error(f"所有内容提取方法均失败: {final_url}")
            return None
        except asyncio.TimeoutError:
            logger.error(f"获取URL内容超时: URL: {url}")
            return None
        except Exception as e:
            logger.error(f"获取URL内容时出错: {e}, URL: {url}")
            return None

    def _get_default_headers(self):
        """获取默认请求头"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
        ]
        selected_ua = random.choice(user_agents)

        return {
            "User-Agent": selected_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1"
        }

    def _extract_content_general(self, url, headers=None):
        """通用网页内容提取方法，使用静态页面提取

        使用静态提取方法获取网页内容

        Args:
            url: 网页URL
            headers: 可选的请求头，如果为None则使用默认

        Returns:
            str: 提取的内容，失败返回None
        """
        if not has_bs4:
            logger.error("BeautifulSoup库未安装，无法使用通用内容提取方法")
            return None

        if not has_requests:
            logger.error("requests库未安装，无法使用通用内容提取方法")
            return None

        try:
            # 如果没有提供headers，创建一个默认的
            if not headers:
                headers = self._get_default_headers()

            # 添加随机延迟以避免被检测为爬虫
            time.sleep(random.uniform(0.5, 2))

            # 创建会话对象
            session = requests.Session()

            # 设置基本cookies
            session.cookies.update({
                f"visit_id_{int(time.time())}": f"{random.randint(1000000, 9999999)}",
                "has_visited": "1",
            })

            # 发送请求获取页面
            logger.debug(f"通用提取方法正在请求: {url}")
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # 确保编码正确
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding

            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # 移除无用元素
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'iframe']):
                element.extract()

            # 寻找可能的标题
            title = None

            # 尝试多种标题选择器
            title_candidates = [
                soup.select_one('h1'),  # 最常见的标题标签
                soup.select_one('title'),  # HTML标题
                soup.select_one('.title'),  # 常见的标题类
                soup.select_one('.article-title'),  # 常见的文章标题类
                soup.select_one('.post-title'),  # 博客标题
                soup.select_one('[class*="title" i]'),  # 包含title的类
            ]

            for candidate in title_candidates:
                if candidate and candidate.text.strip():
                    title = candidate.text.strip()
                    break

            # 查找可能的内容元素
            content_candidates = []

            # 1. 尝试找常见的内容容器
            content_selectors = [
                'article', 'main', '.content', '.article', '.post-content',
                '[class*="content" i]', '[class*="article" i]',
                '.story', '.entry-content', '.post-body',
                '#content', '#article', '.body'
            ]

            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    content_candidates.extend(elements)

            # 2. 如果没有找到明确的内容容器，寻找具有最多文本的div元素
            if not content_candidates:
                paragraphs = {}
                # 查找所有段落和div
                for elem in soup.find_all(['p', 'div']):
                    text = elem.get_text(strip=True)
                    # 只考虑有实际内容的元素
                    if len(text) > 100:
                        paragraphs[elem] = len(text)

                # 找出文本最多的元素
                if paragraphs:
                    max_elem = max(paragraphs.items(), key=lambda x: x[1])[0]
                    # 如果是div，直接添加；如果是p，尝试找其父元素
                    if max_elem.name == 'div':
                        content_candidates.append(max_elem)
                    else:
                        # 找包含多个段落的父元素
                        parent = max_elem.parent
                        if parent and len(parent.find_all('p')) > 3:
                            content_candidates.append(parent)
                        else:
                            content_candidates.append(max_elem)

            # 3. 简单算法来评分和选择最佳内容元素
            best_content = None
            max_score = 0

            for element in content_candidates:
                # 计算文本长度
                text = element.get_text(strip=True)
                text_length = len(text)

                # 计算文本密度（文本长度/HTML长度）
                html_length = len(str(element))
                text_density = text_length / html_length if html_length > 0 else 0

                # 计算段落数量
                paragraphs = element.find_all('p')
                paragraph_count = len(paragraphs)

                # 检查是否有图片
                images = element.find_all('img')
                image_count = len(images)

                # 根据各种特征计算分数
                score = (
                    text_length * 1.0 +  # 文本长度很重要
                    text_density * 100 +  # 文本密度很重要
                    paragraph_count * 30 +  # 段落数量也很重要
                    image_count * 10  # 图片不太重要，但也是一个指标
                )

                # 减分项：如果包含许多链接，可能是导航或侧边栏
                links = element.find_all('a')
                link_text_ratio = sum(len(a.get_text(strip=True)) for a in links) / text_length if text_length > 0 else 0
                if link_text_ratio > 0.5:  # 如果链接文本占比过高
                    score *= 0.5

                # 更新最佳内容
                if score > max_score:
                    max_score = score
                    best_content = element

            # 如果找到内容，提取并清理文本
            static_content_result = None
            if best_content:
                # 首先移除内容中可能的广告或无关元素
                for ad in best_content.select('[class*="ad" i], [class*="banner" i], [id*="ad" i], [class*="recommend" i]'):
                    ad.extract()

                # 获取并清理文本
                content_text = best_content.get_text(separator='\n', strip=True)

                # 移除多余的空白行
                content_text = re.sub(r'\n{3,}', '\n\n', content_text)

                # 构建最终输出
                result = ""
                if title:
                    result += f"标题: {title}\n\n"

                result += content_text

                logger.debug(f"通用提取方法成功，提取内容长度: {len(result)}")
                static_content_result = result

            # 判断静态提取的内容质量
            content_is_good = False
            if static_content_result:
                # 内容长度检查
                if len(static_content_result) > 50:
                    content_is_good = True
                # 结构检查 - 至少应该有多个段落
                elif static_content_result.count('\n\n') >= 1:
                    content_is_good = True

            # 如果静态提取内容质量不佳，记录日志（动态提取方法已移除）
            if not content_is_good:
                logger.debug("静态提取内容质量不佳，但动态提取方法已移除")

            return static_content_result

        except Exception as e:
            logger.error(f"通用内容提取方法失败: {str(e)}")
            return None

    # 动态内容提取方法已移除

    async def _send_to_dify(self, content: str, is_xiaohongshu: bool = False, custom_prompt: str = None) -> Optional[str]:
        if not self.dify_enable:
            return None
        try:
            content = content[:self.max_text_length]

            # 如果有自定义问题，使用自定义问题作为提示词，并添加固定前缀
            if custom_prompt:
                logger.info(f"使用自定义问题: {custom_prompt}")
                prompt = f"""请根据下面**原文内容**回复：{custom_prompt}

**原文内容**：
{content}
"""
            else:
                # 检查是否为GitHub个人主页
                is_github_profile = "github.com" in content and ("overview" in content.lower() or "repositories" in content.lower())

                if is_xiaohongshu:
                    prompt = f"""请对以下小红书笔记进行详细全面的总结，提供丰富的信息：
1. 📝 全面概括笔记的核心内容和主旨（2-3句话）
2. 🔑 详细的核心要点（5-7点，每点包含足够细节）
3. 💡 作者的主要观点、方法或建议（至少3点）
4. 💰 实用价值和可行的行动建议
5. 🏷️ 相关标签（3-5个）

请确保总结内容详尽，捕捉原文中所有重要信息，不要遗漏关键点。

**原文内容**：
{content}
"""
                elif is_github_profile:
                    prompt = f"""请对以下GitHub个人主页内容进行全面而详细的总结：
1. 📝 开发者身份和专业领域的完整概述（3-4句话）
2. 🔑 主要项目和贡献（列出所有可见的重要项目及其功能描述）
3. 💻 技术栈和专业技能（尽可能详细列出所有提到的技术）
4. 🚀 开发重点和特色项目（详细描述2-3个置顶项目）
5. 📊 GitHub活跃度和贡献情况
6. 🌟 个人成就和特色内容
7. 🏷️ 技术领域标签（4-6个）

请确保总结极其全面，不要遗漏任何重要细节，应包含个人简介、项目描述、技术栈等所有相关信息。

**原文内容**：
{content}
"""
                else:
                    prompt = f"""你是一个新闻专家，请对以下**原文内容**进行摘要，提炼出核心观点和关键信息,要求语言简洁、准确、客观，并保持原文的主要意思。请不要添加个人评论或解读，仅对原文内容进行概括。输出不超过300字，不要使用加粗等markdown格式符号，包括以下4个部分：\n 标题（此处直接使用原文标题，禁止使用“标题”字眼）\n\n 📖 总结（一句话概括网页核心内容）\n\n💡 关键要点（用数字序号列出3-5个文章的核心内容）\n\n🏷 标签: #xx #xx（列出3到4个）。\n示例：Dify工作流分享-JinaSum\n\n📖 总结\n本文介绍了如何通过 Dify 工作流实现网页内容的自动总结，使用了 Jina 和 Firecrawl 两种方式。\n\n💡 关键要点 \n1. 工作流节点设置：创建一个包含开始节点、HTTP请求节点、LLM节点和结束节点的工作流。\n2. 网页链接输入：用户在开始节点输入要总结的网页链接。\n3. 网页内容爬取：利用 Jina 或 Firecrawl 服务爬取网页内容并转换为 Markdown 格式。\n4. 内容爬取：LLM节点接收爬取内容，并通过预设提示词进行总结。\n5. 整理结果：结束节点负责输出最终整理的总结内容。\n\n🏷 标签: #Dify #工作流 #自动总结 #Jina #Firecrawl

**原文内容**：
{content}
"""
            headers = {
                "Authorization": f"Bearer {self.dify_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": {},
                "query": prompt,
                "response_mode": "blocking",
                "conversation_id": None,
                "user": "auto_summary"
            }
            url = f"{self.dify_base_url}/chat-messages"

            # 创建一个异步任务来处理HTTP请求，并设置超时
            async def make_request():
                # 设置超时时间为60秒
                timeout = aiohttp.ClientTimeout(total=60)
                async with self.http_session.post(
                    url=url,
                    headers=headers,
                    json=payload,
                    proxy=self.http_proxy if self.http_proxy else None,
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("answer", "")
                    else:
                        error_text = await response.text()
                        logger.error(f"调用Dify API失败: {response.status} - {error_text}")
                        return None

            # 执行请求任务
            return await make_request()
        except asyncio.TimeoutError:
            logger.error("调用Dify API超时")
            return None
        except Exception as e:
            logger.error(f"调用Dify API时出错: {e}")
            return None

    def _process_xml_message(self, message: Dict) -> Optional[Dict]:
        try:
            content = message.get("Content", "")
            msg_id = message.get('MsgId', '')
            logger.info(f"插件处理XML消息: MsgId={msg_id}")

            # 检查消息类型
            msg_type = message.get("MsgType", 0)
            logger.info(f"消息类型: {msg_type}")

            # 检查内容是否为XML
            if not content.strip().startswith('<'):
                logger.warning("消息内容不是XML格式")
                return None

            logger.debug(f"完整XML内容: {content}")

            try:
                root = ET.fromstring(content)
                logger.info(f"解析XML根节点: {root.tag}")

                # 记录所有子节点以便调试
                for child in root:
                    logger.debug(f"子节点: {child.tag}")
            except ET.ParseError as e:
                logger.error(f"XML解析错误: {str(e)}")
                logger.error(f"XML内容片段: {content[:200]}...")
                return None

            appmsg = root.find('appmsg')
            if appmsg is None:
                logger.warning("未找到 appmsg 节点")
                return None

            logger.info("找到 appmsg 节点")

            # 记录appmsg的所有子节点
            for child in appmsg:
                logger.debug(f"appmsg子节点: {child.tag} = {child.text if child.text else ''}")

            title_elem = appmsg.find('title')
            des_elem = appmsg.find('des')
            url_elem = appmsg.find('url')
            type_elem = appmsg.find('type')

            title = title_elem.text if title_elem is not None and title_elem.text else ""
            description = des_elem.text if des_elem is not None and des_elem.text else ""
            url = url_elem.text if url_elem is not None and url_elem.text else None
            type_value = type_elem.text if type_elem is not None and type_elem.text else ""

            logger.info(f"提取的标题: {title}")
            logger.info(f"提取的描述: {description}")
            logger.info(f"提取的URL: {url}")
            logger.info(f"消息类型值: {type_value}")

            if url is None or not url.strip():
                logger.warning("URL为空，跳过处理")
                return None

            url = html.unescape(url)
            logger.info(f"处理后的URL: {url}")

            # 检查是否是小红书
            is_xiaohongshu = '<appname>小红书</appname>' in content
            if is_xiaohongshu:
                logger.info("检测到小红书卡片")

            result = {
                'title': title,
                'description': description,
                'url': url,
                'is_xiaohongshu': is_xiaohongshu,
                'type': type_value
            }
            logger.info(f"提取的信息: {result}")
            return result

        except ET.ParseError as e:
            logger.error(f"XML解析错误: {str(e)}")
            logger.error(f"XML内容片段: {content[:200] if 'content' in locals() else ''}...")
            return None
        except Exception as e:
            logger.error(f"处理XML消息时出错: {str(e)}")
            logger.exception(e)
            return None

    async def _process_url(self, url: str, chat_id: str, custom_prompt: str = None) -> Optional[str]:
        try:
            url_content = await self._fetch_url_content(url)
            if not url_content:
                return None

            # 获取总结内容
            summary = await self._send_to_dify(url_content, custom_prompt=custom_prompt)

            if summary:
                # 缓存总结内容和原始内容
                self.summary_cache[chat_id] = {
                    "summary": summary,
                    "original_content": url_content,
                    "timestamp": time.time()
                }
                logger.info(f"已缓存总结内容，chat_id={chat_id}, 总结长度={len(summary)}")

            return summary
        except asyncio.TimeoutError:
            logger.error(f"处理URL时超时: {url}")
            return None
        except Exception as e:
            logger.error(f"处理URL时出错: {e}")
            return None

    async def _handle_card_message(self, bot: 'WechatAPIClient', chat_id: str, info: Dict, custom_prompt: str = None) -> bool:
        try:
            # 发送正在处理的消息
            await bot.send_text_message(chat_id, "🎉正在为您生成总结，请稍候...")

            # 获取URL内容
            url = info['url']
            logger.info(f"开始获取卡片URL内容: {url}")
            url_content = await self._fetch_url_content(url)

            if not url_content:
                logger.warning(f"无法获取卡片内容: {url}")
                await bot.send_text_message(chat_id, "❌ 抱歉，无法获取卡片内容")
                return False

            logger.info(f"成功获取卡片内容，长度: {len(url_content)}")

            # 构建要总结的内容
            content_to_summarize = f"""
标题：{info['title']}
描述：{info['description']}
正文：{url_content}
"""

            # 发送正在生成总结的消息
            #await bot.send_text_message(chat_id, "🔍 正在为您生成详细内容总结，请稍候...")

            # 调用Dify API生成总结
            is_xiaohongshu = info.get('is_xiaohongshu', False)
            logger.info(f"开始生成总结, 是否小红书: {is_xiaohongshu}")

            # 使用自定义问题（如果有）
            if custom_prompt:
                logger.info(f"使用自定义问题处理卡片: {custom_prompt}")
                summary = await self._send_to_dify(content_to_summarize, is_xiaohongshu=is_xiaohongshu, custom_prompt=custom_prompt)
            else:
                summary = await self._send_to_dify(content_to_summarize, is_xiaohongshu=is_xiaohongshu)

            if not summary:
                logger.error("生成总结失败")
                await bot.send_text_message(chat_id, "❌ 抱歉，生成总结失败")
                return False

            logger.info(f"成功生成总结，长度: {len(summary)}")

            # 根据卡片类型设置前缀
            # prefix = "🎯 小红书笔记详细总结如下" if is_xiaohongshu else "🎯 卡片内容详细总结如下"
            # await bot.send_text_message(chat_id, f"{prefix}：\n\n{summary}")

            # 缓存总结内容和原始内容
            self.summary_cache[chat_id] = {
                "summary": summary,
                "original_content": content_to_summarize,
                "timestamp": time.time()
            }
            logger.info(f"已缓存卡片总结内容，chat_id={chat_id}, 总结长度={len(summary)}")

            # 发送总结，直接返回内容，不添加前缀
            await bot.send_text_message(chat_id, f"{summary}")
            logger.info("总结已发送")
            return False  # 阻止后续处理

        except asyncio.TimeoutError:
            logger.error("处理卡片消息时超时")
            await bot.send_text_message(chat_id, "❌ 抱歉，处理卡片内容时超时，请稍后再试")
            return False
        except Exception as e:
            logger.error(f"处理卡片消息时出错: {e}")
            logger.exception(e)  # 记录完整堆栈信息
            await bot.send_text_message(chat_id, "❌ 抱歉，处理卡片内容时出现错误")
            return False

    @on_text_message(priority=50)
    async def handle_text_message(self, bot: 'WechatAPIClient', message: Dict) -> bool:
        if not self.dify_enable:
            return True

        content = message.get("Content", "")
        chat_id = message.get("FromWxid", "")
        is_group = message.get("IsGroup", False)
        sender_id = message.get("SenderWxid", "")  # 发送者ID，在群聊中与chat_id不同

        # 在日志中记录消息类型
        chat_type = "群聊" if is_group else "私聊"
        logger.info(f"收到{chat_type}文本消息: chat_id={chat_id}, sender_id={sender_id}, content={content[:100]}...")
        content = html.unescape(content)

        # 清理过期的链接和卡片
        self._clean_expired_items()

        # 检查是否是追问命令
        if self._is_qa_command(content):
            logger.info(f"检测到追问命令: {content}")

            # 检查是否有总结缓存
            if chat_id in self.summary_cache:
                # 提取问题内容，使用正则表达式处理不定数量的空格
                question_match = re.match(f"^{re.escape(self.qa_trigger)}\\s*(.*?)$", content)
                question = question_match.group(1).strip() if question_match else ""

                if not question:
                    await bot.send_text_message(chat_id, "❓ 请在追问命令后提供具体问题，例如：问这篇文章的主要观点是什么？")
                    return False

                logger.info(f"提取到追问问题: {question}")

                # 构建追问提示词
                cache_data = self.summary_cache[chat_id]
                original_content = cache_data["original_content"]

                # 发送追问到Dify
                try:
                    # 发送追问到Dify，直接使用custom_prompt参数传递问题
                    answer = await self._send_to_dify(original_content, custom_prompt=question)

                    if answer:
                        # 发送回答
                        await bot.send_text_message(chat_id, f"{answer}")
                        # 更新缓存时间戳
                        self.summary_cache[chat_id]["timestamp"] = time.time()
                        return False
                    else:
                        await bot.send_text_message(chat_id, "❌ 抱歉，无法回答您的问题")
                        return False
                except asyncio.TimeoutError:
                    logger.error("处理追问时超时")
                    await bot.send_text_message(chat_id, "❌ 抱歉，处理追问过程中超时，请稍后再试")
                    return False
                except Exception as e:
                    logger.error(f"处理追问时出错: {e}")
                    await bot.send_text_message(chat_id, "❌ 抱歉，处理追问过程中出现错误")
                    return False
            else:
                await bot.send_text_message(chat_id, f"❌ 没有找到最近的总结内容，请先使用{self.sum_trigger}命令生成总结")
                return False

        # 检查是否是总结命令
        elif self._is_summary_command(content):
            logger.info(f"检测到总结命令: {content}")

            # 检查是否是 "{sum_trigger} [自定义问题] [URL]" 或 "{sum_trigger} [URL]" 格式
            # 支持触发词和自定义问题之间有不定数量的空格或没有空格
            url_pattern = f"({self.sum_trigger})\\s*(.*?)\\s*({self.URL_PATTERN})"
            url_match = re.search(url_pattern, content)

            if url_match:
                # 从命令中提取URL和可能的自定义问题
                url = re.findall(self.URL_PATTERN, content)[0]
                logger.info(f"从总结命令中提取URL: {url}")

                # 提取自定义问题（如果有）
                custom_prompt = None

                # 使用正则表达式匹配结果提取自定义问题
                if url_match and len(url_match.groups()) >= 3:
                    # 第二个捕获组是自定义问题部分
                    custom_prompt_part = url_match.group(2).strip()
                    if custom_prompt_part:
                        custom_prompt = custom_prompt_part
                        logger.info(f"使用正则提取到自定义问题: {custom_prompt}")

                # 如果正则提取失败，使用替换方法尝试提取
                if not custom_prompt:
                    # 使用正则表达式移除触发词，支持触发词后有不定数量的空格或没有空格
                    content_without_trigger = re.sub(f"^{re.escape(self.sum_trigger)}\\s*", "", content, 1).strip()
                    # 移除URL
                    content_without_url = content_without_trigger.replace(url, "", 1).strip()

                    if content_without_url:
                        custom_prompt = content_without_url
                        logger.info(f"使用替换方法提取到自定义问题: {custom_prompt}")

                if self._check_url(url):
                    try:
                        #await bot.send_text_message(chat_id, "🔍 正在为您生成详细内容总结，请稍候...")
                        summary = await self._process_url(url, chat_id, custom_prompt)
                        if summary:
                            # await bot.send_text_message(chat_id, f"🎯 详细内容总结如下：\n\n{summary}")
                            # 直接返回总结内容，不添加前缀
                            await bot.send_text_message(chat_id, f"{summary}")
                            return False
                        else:
                            await bot.send_text_message(chat_id, "❌ 抱歉，生成总结失败")
                            return False
                    except asyncio.TimeoutError:
                        logger.error("处理URL时超时")
                        await bot.send_text_message(chat_id, "❌ 抱歉，处理过程中超时，请稍后再试")
                        return False
                    except Exception as e:
                        logger.error(f"处理URL时出错: {e}")
                        await bot.send_text_message(chat_id, "❌ 抱歉，处理过程中出现错误")
                        return False

            # 如果不是 "{sum_trigger} [URL]" 格式，检查是否有最近的URL
            elif chat_id in self.recent_urls:
                url = self.recent_urls[chat_id]["url"]
                logger.info(f"开始总结最近的URL: {url}")

                # 提取可能的自定义问题
                custom_prompt = None
                # 使用正则表达式移除触发词，支持触发词后有不定数量的空格或没有空格
                content_without_trigger = re.sub(f"^{re.escape(self.sum_trigger)}\\s*", "", content, 1).strip()

                if content_without_trigger:
                    custom_prompt = content_without_trigger
                    logger.info(f"提取到自定义问题: {custom_prompt}")

                try:
                    #await bot.send_text_message(chat_id, "🔍 正在为您生成详细内容总结，请稍候...")
                    summary = await self._process_url(url, chat_id, custom_prompt)
                    if summary:
                        # await bot.send_text_message(chat_id, f"🎯 详细内容总结如下：\n\n{summary}")
                        # 直接返回总结内容，不添加前缀
                        await bot.send_text_message(chat_id, f"{summary}")
                        # 总结后删除该URL（总结内容已经缓存到summary_cache中）
                        del self.recent_urls[chat_id]
                        return False
                    else:
                        await bot.send_text_message(chat_id, "❌ 抱歉，生成总结失败")
                        return False
                except asyncio.TimeoutError:
                    logger.error("处理URL时超时")
                    await bot.send_text_message(chat_id, "❌ 抱歉，处理过程中超时，请稍后再试")
                    return False
                except Exception as e:
                    logger.error(f"处理URL时出错: {e}")
                    await bot.send_text_message(chat_id, "❌ 抱歉，处理过程中出现错误")
                    return False

            # 检查是否有最近的卡片
            elif chat_id in self.recent_cards:
                card_info = self.recent_cards[chat_id]["info"]
                logger.info(f"开始总结最近的卡片: {card_info['title']}")

                # 提取可能的自定义问题
                custom_prompt = None
                # 使用正则表达式移除触发词，支持触发词后有不定数量的空格或没有空格
                content_without_trigger = re.sub(f"^{re.escape(self.sum_trigger)}\\s*", "", content, 1).strip()

                if content_without_trigger:
                    custom_prompt = content_without_trigger
                    logger.info(f"提取到卡片自定义问题: {custom_prompt}")

                try:
                    # 处理卡片消息，传入自定义问题
                    await self._handle_card_message(bot, chat_id, card_info, custom_prompt)
                    # 总结后删除该卡片
                    del self.recent_cards[chat_id]
                    return False
                except asyncio.TimeoutError:
                    logger.error("处理卡片时超时")
                    await bot.send_text_message(chat_id, "❌ 抱歉，处理过程中超时，请稍后再试")
                    return False
                except Exception as e:
                    logger.error(f"处理卡片时出错: {e}")
                    await bot.send_text_message(chat_id, "❌ 抱歉，处理过程中出现错误")
                    return False

            # 没有最近的URL或卡片，也不是 "{sum_trigger} [URL]" 格式
            else:
                # 注释掉提示消息，避免在非总结指令中触发
                # await bot.send_text_message(chat_id, f"❌ 没有找到可以总结的链接或卡片，请先发送链接或卡片，然后再发送{self.sum_trigger}命令，或者直接发送\"{self.sum_trigger} [URL]\"")
                return False

        # 如果不是总结命令，检查是否包含URL
        urls = re.findall(self.URL_PATTERN, content)
        if urls:
            url = urls[0]
            logger.info(f"找到URL: {url}")

            # 检查是否是直接发给bot的消息
            is_to_bot = not is_group or message.get("IsAt", False)

            # 如果是直接发给bot的消息，不缓存URL，继续向下传递
            if is_to_bot:
                logger.info(f"URL消息直接发给bot，不缓存: {url}")
                return True

            # 只有群聊中非@bot的URL消息才缓存
            if is_group and not message.get("IsAt", False) and self._check_url(url):
                # 存储URL供后续使用
                self.recent_urls[chat_id] = {
                    "url": url,
                    "timestamp": time.time()
                }
                logger.info(f"已存储群聊非@bot的URL: {url} 供后续手动总结使用")
                # await bot.send_text_message(chat_id, f"🔗 检测到链接，发送\"{self.sum_trigger}\"命令可以生成内容总结")

        return True

    @on_article_message(priority=50)
    async def handle_article_message(self, bot: 'WechatAPIClient', message: Dict) -> bool:
        """处理文章类型消息（微信公众号文章等）"""
        if not self.dify_enable:
            return True

        chat_id = message.get("FromWxid", "")
        msg_id = message.get("MsgId", "")
        is_group = message.get("IsGroup", False)
        sender_id = message.get("SenderWxid", "")  # 发送者ID，在群聊中与chat_id不同

        # 在日志中记录消息类型
        chat_type = "群聊" if is_group else "私聊"
        logger.info(f"收到{chat_type}文章消息: MsgId={msg_id}, chat_id={chat_id}, sender_id={sender_id}")

        try:
            # 处理XML消息
            card_info = self._process_xml_message(message)
            if not card_info:
                logger.warning("文章消息解析失败")
                return True

            logger.info(f"识别为文章消息: {card_info['title']}")

            # 存储卡片信息供后续使用
            self.recent_cards[chat_id] = {
                "info": card_info,
                "timestamp": time.time()
            }
            logger.info(f"已存储文章信息: {card_info['title']} 供后续总结使用")

            # 检查是否应该自动总结
            # 传入群ID/用户ID和发送者ID
            if self._should_auto_summarize(chat_id, is_group, sender_id):
                logger.info(f"自动总结文章: {card_info['title']}")
                try:
                    # 处理卡片消息
                    await self._handle_card_message(bot, chat_id, card_info)
                    # 总结后删除该卡片
                    del self.recent_cards[chat_id]
                    return False
                except Exception as e:
                    logger.error(f"自动处理文章时出错: {e}")
                    logger.exception(e)
                    await bot.send_text_message(chat_id, "❌ 抱歉，自动处理文章时出现错误")
                    return True  # 出错时继续处理消息
            else:
                # 不自动总结，发送提示
                # await bot.send_text_message(chat_id, f"📰 检测到文章，发送\"{self.sum_trigger}\"命令可以生成内容总结")
                pass

            return True
        except Exception as e:
            logger.error(f"处理文章消息时出错: {e}")
            logger.exception(e)
            return True

    @on_file_message(priority=50)
    async def handle_file_message(self, bot: 'WechatAPIClient', message: Dict) -> bool:
        """处理文件类型消息（包括卡片消息）"""
        if not self.dify_enable:
            return True

        chat_id = message.get("FromWxid", "")
        msg_type = message.get("MsgType", 0)
        is_group = message.get("IsGroup", False)
        sender_id = message.get("SenderWxid", "")  # 发送者ID，在群聊中与chat_id不同

        # 检查是否是卡片消息（类型49）
        if msg_type != 49:
            logger.info(f"非卡片消息，跳过处理: MsgType={msg_type}")
            return True

        # 在日志中记录消息类型
        chat_type = "群聊" if is_group else "私聊"
        logger.info(f"收到{chat_type}卡片消息: MsgType={msg_type}, chat_id={chat_id}, sender_id={sender_id}")

        try:
            # 处理XML消息
            card_info = self._process_xml_message(message)
            if not card_info:
                logger.warning("卡片消息解析失败")
                return True

            logger.info(f"识别为卡片消息: {card_info['title']}")

            # 存储卡片信息供后续使用
            self.recent_cards[chat_id] = {
                "info": card_info,
                "timestamp": time.time()
            }
            logger.info(f"已存储卡片信息: {card_info['title']} 供后续总结使用")

            # 检查是否应该自动总结
            # 传入群ID/用户ID和发送者ID
            if self._should_auto_summarize(chat_id, is_group, sender_id):
                logger.info(f"自动总结卡片: {card_info['title']}")
                try:
                    # 处理卡片消息
                    await self._handle_card_message(bot, chat_id, card_info)
                    # 总结后删除该卡片
                    del self.recent_cards[chat_id]
                    return False
                except Exception as e:
                    logger.error(f"自动处理卡片时出错: {e}")
                    logger.exception(e)
                    await bot.send_text_message(chat_id, "❌ 抱歉，自动处理卡片时出现错误")
                    return True  # 出错时继续处理消息
            else:
                # 不自动总结，发送提示
                # await bot.send_text_message(chat_id, f"📎 检测到卡片，发送\"{self.sum_trigger}\"命令可以生成内容总结")
                pass

            return True
        except Exception as e:
            logger.error(f"处理文件消息时出错: {e}")
            logger.exception(e)
            return True
