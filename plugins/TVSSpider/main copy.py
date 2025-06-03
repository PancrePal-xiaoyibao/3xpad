import os
import re
import json
import aiohttp  # 替换requests为aiohttp
import asyncio
import traceback
import tomllib  # 新增tomllib库，用于解析TOML文件
from typing import Dict, List, Tuple, Optional, Union, Any
from urllib.parse import quote
from bs4 import BeautifulSoup
from loguru import logger
from utils.plugin_base import PluginBase
from utils.decorators import on_text_message
from WechatAPI import WechatAPIClient

class TVSSpider(PluginBase):
    description = "TVS1网站视频搜索插件"
    author = "BEelzebub"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.plugin_dir = os.path.dirname(__file__)
        config_path = os.path.join(self.plugin_dir, "config.toml")
        
        # 搜索结果缓存，格式为 {用户ID: {'results': [...], 'keyword': '...', 'timestamp': ...}}
        self.search_cache = {}
        # 缓存过期时间（秒）
        self.cache_expire_time = 300  # 5分钟
        
        try:
            # 尝试使用tomllib加载配置文件
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            
            # 设置默认值
            self.enable = True
            self.command = "TVS"
            self.whitelist_groups = []  # 白名单群组
            self.base_url = "https://www.tvs1.vip"
            self.max_results = 10
            self.enable_emoji = True
            self.timeout = 10
            self.retry_times = 2
            
            # 读取basic节点配置
            if "basic" in config:
                basic_config = config["basic"]
                self.base_url = basic_config.get("base_url", self.base_url)
                self.command = basic_config.get("command_prefix", self.command)
                
            # 读取display节点配置
            if "display" in config:
                display_config = config["display"]
                self.max_results = display_config.get("max_results", self.max_results)
                self.enable_emoji = display_config.get("enable_emoji", self.enable_emoji)
                
            # 读取request节点配置
            if "request" in config:
                request_config = config["request"]
                self.timeout = request_config.get("timeout", self.timeout)
                self.retry_times = request_config.get("retry_times", self.retry_times)
                
            # 读取全局配置（如果有的话）
            self.enable = config.get("enable", True)
            self.whitelist_groups = config.get("whitelist_groups", self.whitelist_groups)
                
            logger.info(f"[TVSSpider] 加载配置成功: 命令={self.command}, 基础URL={self.base_url}, 最大结果数={self.max_results}")
            
        except Exception as e:
            logger.error(f"[TVSSpider] 加载配置失败: {str(e)}, 使用默认配置")
            logger.error(traceback.format_exc())
            self.enable = True
            self.command = "TVS"
            self.base_url = "https://www.tvs1.vip"
            self.max_results = 10
            self.enable_emoji = True
            self.whitelist_groups = []
            self.timeout = 10
            self.retry_times = 2
            
        # 初始化请求头信息
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Connection': 'keep-alive',
        }

    async def async_init(self):
        """异步初始化插件"""
        try:
            # 检查网站是否可访问
            if await self.check_site_accessibility():
                logger.info(f"[TVSSpider] 插件初始化完成，TVS1网站可访问")
            else:
                logger.warning(f"[TVSSpider] 插件初始化完成，但TVS1网站当前不可访问")
        except Exception as e:
            logger.error(f"[TVSSpider] 插件异步初始化失败: {str(e)}")
            self.enable = False

    async def check_site_accessibility(self) -> bool:
        """检查网站是否可访问"""
        retry_count = 0
        while retry_count < self.retry_times:
            try:
                logger.info(f"[TVSSpider] 正在检查站点可访问性: {self.base_url}")
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.base_url, headers=self.headers, timeout=self.timeout) as response:
                        if response.status == 200:
                            logger.info(f"[TVSSpider] 站点可访问: {self.base_url}")
                            return True
                        else:
                            logger.warning(f"[TVSSpider] 站点返回非200状态码: {response.status}")
            except Exception as e:
                logger.error(f"[TVSSpider] 网站访问检查失败: {str(e)}")
            
            retry_count += 1
            if retry_count < self.retry_times:
                logger.info(f"[TVSSpider] 将在2秒后进行第{retry_count+1}次重试...")
                await asyncio.sleep(2)
                
        logger.error(f"[TVSSpider] 站点不可访问: {self.base_url}，已重试{self.retry_times}次")
        return False

    @on_text_message(priority=30)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理用户消息"""
        if not self.enable:
            return True  # 禁用状态下，继续处理其他插件
            
        content = str(message.get("Content", "")).strip()
        chat_id = message.get("FromWxid", "")
        sender = message.get("SenderWxid", "")
        
        # 检查是否为群消息，如果不是则忽略
        is_group = message.get("IsGroup", False)
        if not is_group:
            return True
            
        # 检查群组白名单
        if self.whitelist_groups and chat_id not in self.whitelist_groups:
            return True
            
        # 定义用户缓存键（群ID+发送者ID）
        cache_key = f"{chat_id}_{sender}"
        
        # 清理过期缓存
        self._clean_expired_cache()
        
        # 检查是否为获取详情的请求（格式：TVS# 编号）
        if content.startswith(f"{self.command}#"):
            logger.info(f"[TVSSpider] 收到详情请求: {content}")
            
            # 提取编号
            index_str = content[len(self.command)+1:].strip()
            logger.info(f"[TVSSpider] 解析到编号: {index_str}")
            
            # 验证输入是否为数字
            if not index_str.isdigit():
                logger.warning(f"[TVSSpider] 无效的编号格式: {index_str}")
                await bot.send_at_message(chat_id, f"请输入正确的编号，如：{self.command}# 1", [sender])
                return False
                
            index = int(index_str)
            
            # 检查该用户是否有缓存的搜索结果
            if cache_key not in self.search_cache:
                logger.warning(f"[TVSSpider] 用户 {cache_key} 没有缓存的搜索结果")
                await bot.send_at_message(chat_id, "请先搜索影视剧，再获取详情", [sender])
                return False
                
            # 获取缓存结果
            cached_data = self.search_cache[cache_key]
            results = cached_data['results']
            keyword = cached_data['keyword']
            logger.info(f"[TVSSpider] 获取到缓存结果，关键词: {keyword}, 结果数: {len(results)}")
            
            # 验证编号是否有效
            if index < 1 or index > len(results):
                logger.warning(f"[TVSSpider] 编号超出范围: {index}, 有效范围: 1-{len(results)}")
                await bot.send_at_message(chat_id, f"无效的编号，请输入1-{len(results)}之间的数字", [sender])
                return False
                
            # 获取选定的结果
            selected_result = results[index-1]
            logger.info(f"[TVSSpider] 选择了结果: #{index}, 标题: {selected_result.get('标题', '未知')}")
            
            # 组装详情回复
            detail_response = await self.format_detail_result(index, selected_result)
            await bot.send_at_message(chat_id, detail_response, [sender])
            logger.info(f"[TVSSpider] 已发送详情结果")
            
            return False  # 阻止继续处理其他插件
            
        # 检查消息是否以命令开头
        elif content.startswith(self.command):
            # 提取关键词
            keyword = content[len(self.command):].strip()
            if not keyword:
                await bot.send_at_message(chat_id, "请输入要搜索的影视剧名称，如：TVS 滤镜", [sender])
                return False
                
            # 执行搜索
            try:
                logger.info(f"[TVSSpider] 收到搜索请求: {keyword}")
                results = await self.search_video(keyword)
                
                if not results:
                    await bot.send_at_message(chat_id, f"未找到与\"{keyword}\"相关的影视资源", [sender])
                    return False
                    
                # 缓存结果
                self.search_cache[cache_key] = {
                    'results': results,
                    'keyword': keyword,
                    'timestamp': asyncio.get_event_loop().time()
                }
                logger.info(f"[TVSSpider] 已缓存搜索结果，用户: {cache_key}, 结果数: {len(results)}")
                
                # 组装第一步回复内容（只包含编号、标题、演员、年份）
                response = await self.format_search_preview(keyword, results)
                await bot.send_at_message(chat_id, response, [sender])
                logger.info(f"[TVSSpider] 已发送搜索预览结果")
                
            except Exception as e:
                logger.error(f"[TVSSpider] 搜索异常: {str(e)}\n{traceback.format_exc()}")
                await bot.send_at_message(chat_id, f"搜索失败: {str(e)}", [sender])
                
            return False  # 阻止继续处理其他插件
            
        return True  # 继续处理其他插件
        
    def _clean_expired_cache(self):
        """清理过期的缓存"""
        current_time = asyncio.get_event_loop().time()
        expired_keys = []
        
        for key, cache_data in self.search_cache.items():
            if current_time - cache_data['timestamp'] > self.cache_expire_time:
                expired_keys.append(key)
                
        for key in expired_keys:
            del self.search_cache[key]
            
        if expired_keys:
            logger.info(f"[TVSSpider] 已清理 {len(expired_keys)} 条过期缓存")

    async def search_video(self, keyword: str) -> List[Dict]:
        """搜索视频资源"""
        # URL编码搜索关键词
        encoded_keyword = quote(keyword)
        search_url = f"{self.base_url}/index.php/vod/search.html?wd={encoded_keyword}"
        
        retry_count = 0
        while retry_count < self.retry_times:
            try:
                # 执行搜索请求
                logger.info(f"[TVSSpider] 正在搜索关键词: {keyword}, URL: {search_url}")
                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers, timeout=self.timeout) as response:
                        if response.status != 200:
                            logger.error(f"[TVSSpider] 搜索请求失败，状态码: {response.status}")
                            retry_count += 1
                            if retry_count < self.retry_times:
                                logger.info(f"[TVSSpider] 将在2秒后进行第{retry_count+1}次重试...")
                                await asyncio.sleep(2)
                                continue
                            else:
                                raise Exception(f"搜索请求失败，HTTP状态码: {response.status}")
                        
                        html = await response.text()
                
                # 解析HTML
                soup = BeautifulSoup(html, 'html.parser')
                
                # 查找所有搜索结果项
                search_items = soup.select('.module-search-item')
                
                if not search_items:
                    logger.info(f"[TVSSpider] 未找到结果: {keyword}")
                    return []
                
                logger.info(f"[TVSSpider] 找到 {len(search_items)} 条结果: {keyword}")
                
                results = []
                for item in search_items:
                    # 提取标题
                    title_element = item.select_one('h3 a')
                    title = title_element.get('title') if title_element else "未知标题"
                    
                    # 提取播放链接
                    play_element = item.select_one('.module-item-pic a')
                    play_url = play_element.get('href') if play_element else None
                    full_play_url = self.base_url + play_url if play_url else None
                    
                    # 提取封面图片
                    img_element = item.select_one('.module-item-pic img')
                    img_url = img_element.get('data-src') if img_element else None
                    
                    # 提取剧情简介 - 精确定位"剧情："后面的内容
                    plot = "无剧情简介"
                    try:
                        # 查找包含"剧情："的元素
                        plot_title_elements = item.select('.video-info-itemtitle')
                        plot_title_element = None
                        for title_elem in plot_title_elements:
                            if "剧情：" in title_elem.text:
                                plot_title_element = title_elem
                                break
                        
                        if plot_title_element:
                            # 找到剧情标题所在的父容器
                            plot_container = plot_title_element.parent
                            
                            # 从父容器中查找剧情内容
                            plot_element = plot_container.select_one('.video-info-item')
                            
                            if plot_element:
                                # 获取文本并清理
                                plot = plot_element.text.strip()
                                logger.info(f"[TVSSpider] 通过剧情标题找到剧情: {plot[:30]}..." if len(plot) > 30 else f"[TVSSpider] 通过剧情标题找到剧情: {plot}")
                        else:
                            # 直接查找所有video-info-items元素
                            info_items = item.select('.video-info-items')
                            
                            for info_item in info_items:
                                # 检查是否包含"剧情："文本
                                if "剧情：" in info_item.text:
                                    # 尝试找到剧情内容元素
                                    plot_element = info_item.select_one('.video-info-item')
                                    if plot_element:
                                        plot = plot_element.text.strip()
                                        logger.info(f"[TVSSpider] 通过文本匹配找到剧情: {plot[:30]}..." if len(plot) > 30 else f"[TVSSpider] 通过文本匹配找到剧情: {plot}")
                                    else:
                                        # 如果没有找到专门的元素，则提取整个文本并去除"剧情："前缀
                                        full_text = info_item.text.strip()
                                        if "剧情：" in full_text:
                                            plot = full_text.split("剧情：", 1)[1].strip()
                                            logger.info(f"[TVSSpider] 通过分割文本找到剧情: {plot[:30]}..." if len(plot) > 30 else f"[TVSSpider] 通过分割文本找到剧情: {plot}")
                        
                        # 清理剧情文本
                        if plot and plot != "无剧情简介":
                            # 去除开头的全角空格(　)和其他空白字符
                            plot = re.sub(r'^[\s　]+', '', plot)
                            # 替换多个空格为单个空格
                            plot = re.sub(r'\s+', ' ', plot)
                            # 如果简介超过一定长度，截断并添加省略号
                            if len(plot) > 200:
                                plot = plot[:197] + "..."
                    except Exception as e:
                        logger.error(f"[TVSSpider] 提取剧情简介时出错: {str(e)}")
                        plot = "无剧情简介"
                    
                    logger.info(f"[TVSSpider] 最终提取到的剧情简介: {plot[:50]}..." if len(plot) > 50 else f"[TVSSpider] 最终提取到的剧情简介: {plot}")
                    
                    # 提取主演信息
                    actors_elements = item.select('.video-info-actor a')
                    actors = [actor.text for actor in actors_elements] if actors_elements else ["未知"]
                    
                    # 提取年份和地区
                    year_element = item.select_one('.tag-link a[href*="year"]')
                    year = year_element.text.strip() if year_element else "未知年份"
                    
                    area_element = item.select_one('.tag-link a[href*="area"]')
                    area = area_element.text.strip() if area_element else "未知地区"
                    
                    # 组织结果
                    result = {
                        "标题": title,
                        "播放链接": full_play_url,
                        "播放路径": play_url,
                        "封面图片": img_url,
                        "剧情简介": plot,
                        "主演": actors,
                        "年份": year,
                        "地区": area
                    }
                    results.append(result)
                
                return results
                
            except Exception as e:
                logger.error(f"[TVSSpider] 搜索出错: {str(e)}")
                logger.error(traceback.format_exc())
                retry_count += 1
                if retry_count < self.retry_times:
                    logger.info(f"[TVSSpider] 将在2秒后进行第{retry_count+1}次重试...")
                    await asyncio.sleep(2)
                else:
                    raise Exception(f"搜索失败，已重试{self.retry_times}次: {str(e)}")

    async def format_search_preview(self, keyword: str, results: List[Dict]) -> str:
        """格式化搜索结果为简要回复消息（第一步）"""
        # 组装输出信息
        emoji_prefix = "🔍 " if self.enable_emoji else ""
        output = f"{emoji_prefix}找到 {len(results)} 条与\"{keyword}\"相关的内容\n\n"
        
        # 最多显示max_results条结果
        max_results = min(len(results), self.max_results)
        for i, result in enumerate(results[:max_results], 1):
            title = result["标题"]
            actors = "、".join(result["主演"][:3])  # 最多显示3个演员
            if len(result["主演"]) > 3:
                actors += "等"
            
            # 根据设置添加emoji
            if self.enable_emoji:
                output += f"【{i}】{title}\n"
                output += f"   👨‍👩‍👧‍👦 主演: {actors}\n"
                output += f"   📆 {result['年份']} | 🌍 {result['地区']}\n\n"
            else:
                output += f"【{i}】{title}\n"
                output += f"   主演: {actors}\n"
                output += f"   {result['年份']} | {result['地区']}\n\n"
        
        # 如果结果超过最大显示数，添加提示
        if len(results) > self.max_results:
            output += f"还有 {len(results) - self.max_results} 条结果未显示...\n"
            output += f"输入更精确的关键词可以获得更准确的结果\n\n"
        
        # 添加使用详情命令的提示
        command_tip = f"{self.command}# 编号"
        if self.enable_emoji:
            output += f"📌 获取链接请发送: {command_tip} (例如: {self.command}# 1)"
        else:
            output += f"获取链接请发送: {command_tip} (例如: {self.command}# 1)"
        
        return output.strip()

    async def format_detail_result(self, index: int, result: Dict) -> str:
        """格式化详细结果为回复消息（第二步）"""
        title = result["标题"]
        
        # 根据设置添加emoji前缀
        if self.enable_emoji:
            output = f"🎬 【{title}】\n\n"
            output += f"📺 播放链接: https://hadis898.github.io/qqfh/api/?url={result['播放链接']}\n\n"
            
            # 添加主演信息
            actors = "、".join(result["主演"][:3])  # 最多显示3个演员
            if len(result["主演"]) > 3:
                actors += "等"
            output += f"👨‍👩‍👧‍👦 主演: {actors}\n"
            
            # 添加年份和地区
            output += f"📆 年份: {result['年份']} | 🌍 地区: {result['地区']}\n"
            
            # 添加剧情简介（不限制长度）
            plot = result['剧情简介']
            if plot and plot != "无剧情简介":
                output += f"\n📝 简介: {plot}\n"
        else:
            output = f"【{title}】\n\n"
            output += f"播放链接: https://hadis898.github.io/qqfh/api/?url={result['播放链接']}\n\n"
            
            # 添加主演信息
            actors = "、".join(result["主演"][:3])
            if len(result["主演"]) > 3:
                actors += "等"
            output += f"主演: {actors}\n"
            
            # 添加年份和地区
            output += f"年份: {result['年份']} | 地区: {result['地区']}\n"
            
            # 添加剧情简介（不限制长度）
            plot = result['剧情简介']
            if plot and plot != "无剧情简介":
                output += f"\n简介: {plot}\n"
        
        return output.strip()

# 添加插件导出的接口
__plugin_name__ = "TVSSpider"
__plugin_version__ = "1.0.0"
__plugin_description__ = "TVS1网站视频搜索插件"
__plugin_author__ = "BEelzebub"
__plugin_usage__ = """
【TVS1网站视频搜索插件】

指令：
    TVS 关键词 - 搜索影视剧，显示基本信息
    TVS# 编号 - 获取指定编号的播放链接

使用示例：
    TVS 流浪地球  (搜索并显示基本信息)
    TVS# 1       (获取第1个结果的播放链接)
"""

def register():
    """注册插件"""
    return TVSSpider()

def on_message(wechat_instance, message):
    """消息处理接口，兼容性函数"""
    # 此函数仅为接口兼容，实际使用了 on_text_message 装饰器
    pass

# 测试代码 (仅在直接运行此文件时执行)
if __name__ == "__main__":
    # 模拟微信消息的测试代码
    async def test_search():
        plugin = TVSSpider()
        await plugin.async_init()
        
        # 存储测试用户的搜索结果
        test_cache_key = "test_user"
        
        # 模拟消息
        while True:
            msg_text = input("\n请输入消息(输入q退出): ")
            if msg_text.lower() == 'q':
                break
                
            # 处理URL测试 (格式: URL http://xxx)
            if msg_text.lower().startswith("url "):
                test_url = msg_text[4:].strip()
                if not test_url:
                    print("\n请输入有效的URL")
                    continue
                    
                print(f"\n正在测试URL: {test_url}")
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(test_url, headers=plugin.headers, timeout=plugin.timeout) as response:
                            if response.status != 200:
                                print(f"\n请求失败，状态码: {response.status}")
                                continue
                                
                            html = await response.text()
                            
                    # 解析HTML
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 尝试提取剧情描述
                    print("\n尝试提取剧情描述...")
                    plot = "无剧情简介"
                    
                    # 方法1: 查找包含"剧情："的元素
                    print("\n方法1: 查找包含'剧情：'的标题元素")
                    plot_title_elements = soup.select('.video-info-itemtitle')
                    plot_title_element = None
                    for title_elem in plot_title_elements:
                        if "剧情：" in title_elem.text:
                            plot_title_element = title_elem
                            print(f"找到剧情标题元素: {title_elem.text}")
                            break
                    
                    if plot_title_element:
                        # 找到剧情标题所在的父容器
                        plot_container = plot_title_element.parent
                        print(f"父容器HTML: {plot_container}")
                        
                        # 从父容器中查找剧情内容
                        plot_element = plot_container.select_one('.video-info-item')
                        
                        if plot_element:
                            # 获取文本并清理
                            plot = plot_element.text.strip()
                            print(f"找到剧情内容: {plot[:100]}...")
                            
                            # 清理全角空格
                            cleaned_plot = re.sub(r'^[\s　]+', '', plot)
                            cleaned_plot = re.sub(r'\s+', ' ', cleaned_plot)
                            print(f"清理后的剧情: {cleaned_plot[:100]}...")
                    else:
                        print("未找到剧情标题元素")
                        
                        # 方法2: 直接查找所有video-info-items元素
                        print("\n方法2: 查找包含'剧情：'的info-items元素")
                        info_items = soup.select('.video-info-items')
                        
                        for i, info_item in enumerate(info_items):
                            print(f"检查第{i+1}个info-items元素: {info_item.text[:50]}...")
                            # 检查是否包含"剧情："文本
                            if "剧情：" in info_item.text:
                                print(f"找到包含'剧情：'的元素: {info_item.text[:100]}...")
                                # 尝试找到剧情内容元素
                                plot_element = info_item.select_one('.video-info-item')
                                if plot_element:
                                    plot = plot_element.text.strip()
                                    print(f"找到剧情内容元素: {plot[:100]}...")
                                    
                                    # 清理全角空格
                                    cleaned_plot = re.sub(r'^[\s　]+', '', plot)
                                    cleaned_plot = re.sub(r'\s+', ' ', cleaned_plot)
                                    print(f"清理后的剧情: {cleaned_plot[:100]}...")
                                else:
                                    # 如果没有找到专门的元素，则提取整个文本并去除"剧情："前缀
                                    full_text = info_item.text.strip()
                                    if "剧情：" in full_text:
                                        plot = full_text.split("剧情：", 1)[1].strip()
                                        print(f"通过分割文本找到剧情: {plot[:100]}...")
                                        
                                        # 清理全角空格
                                        cleaned_plot = re.sub(r'^[\s　]+', '', plot)
                                        cleaned_plot = re.sub(r'\s+', ' ', cleaned_plot)
                                        print(f"清理后的剧情: {cleaned_plot[:100]}...")
                    
                    # 展示相关HTML结构
                    print("\n相关HTML结构预览:")
                    video_info_main = soup.select_one('.video-info-main')
                    if video_info_main:
                        print(video_info_main.prettify())
                    else:
                        print("未找到.video-info-main元素")
                    
                except Exception as e:
                    print(f"\n测试URL时出错: {str(e)}")
                    traceback.print_exc()
                
                continue
                
            # 处理获取详情命令
            if msg_text.startswith(f"{plugin.command}#"):
                # 提取编号
                index_str = msg_text[len(plugin.command)+1:].strip()
                
                # 验证输入是否为数字
                if not index_str.isdigit():
                    print(f"\n请输入正确的编号，如：{plugin.command}# 1")
                    continue
                    
                index = int(index_str)
                
                # 检查是否有缓存的搜索结果
                if test_cache_key not in plugin.search_cache:
                    print("\n请先搜索影视剧，再获取详情")
                    continue
                    
                # 获取缓存结果
                cached_data = plugin.search_cache[test_cache_key]
                results = cached_data['results']
                
                # 验证编号是否有效
                if index < 1 or index > len(results):
                    print(f"\n无效的编号，请输入1-{len(results)}之间的数字")
                    continue
                    
                # 获取选定的结果
                selected_result = results[index-1]
                
                # 显示详情结果
                detail_response = await plugin.format_detail_result(index, selected_result)
                print("\n" + detail_response)
                
            # 处理搜索命令
            elif msg_text.startswith(plugin.command):
                keyword = msg_text[len(plugin.command):].strip()
                if keyword:
                    try:
                        results = await plugin.search_video(keyword)
                        if results:
                            # 缓存搜索结果
                            plugin.search_cache[test_cache_key] = {
                                'results': results,
                                'keyword': keyword,
                                'timestamp': asyncio.get_event_loop().time()
                            }
                            
                            # 显示预览结果
                            response = await plugin.format_search_preview(keyword, results)
                            print("\n" + response)
                        else:
                            print(f"\n未找到与\"{keyword}\"相关的内容")
                    except Exception as e:
                        print(f"\n搜索出错: {str(e)}")
                else:
                    print("\n请输入要搜索的影视剧名称")
            
            else:
                print("\n未识别的命令。使用'TVS 关键词'进行搜索，使用'TVS# 编号'获取详情，或使用'URL 网址'测试剧情提取")
    
    try:
        asyncio.run(test_search())
    except KeyboardInterrupt:
        print("\n程序已退出") 