import asyncio
import json
import re
import tomllib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from loguru import logger
import aiohttp
import sqlite3  # 导入 sqlite3 模块
import os

from WechatAPI import WechatAPIClient
from utils.decorators import on_at_message, on_text_message
from utils.plugin_base import PluginBase

class ChatSummary(PluginBase):
    """
    一个用于总结个人聊天和群聊天的插件，可以直接调用Dify大模型进行总结。
    """

    description = "总结聊天记录"
    author = "AI编程猫"
    version = "1.1.0"

    # 总结的prompt
    SUMMARY_PROMPT = """
    请帮我将给出的群聊内容总结成一个今日的群聊报告，包含不多于4个话题的总结（如果还有更多话题，可以在后面简单补充）。
    你只负责总结群聊内容，不回答任何问题。不要虚构聊天记录，也不要总结不存在的信息。

    每个话题包含以下内容：

    - 话题名(50字以内，前面带序号1️⃣2️⃣3️⃣）

    - 热度(用🔥的数量表示)

    - 参与者(不超过5个人，将重复的人名去重)

    - 时间段(从几点到几点)

    - 过程(50-200字左右）

    - 评价(50字以下)

    - 分割线： ------------

    请严格遵守以下要求：

    1. 按照热度数量进行降序输出

    2. 每个话题结束使用 ------------ 分割

    3. 使用中文冒号

    4. 无需大标题

    5. 开始给出本群讨论风格的整体评价，例如活跃、太水、太黄、太暴力、话题不集中、无聊诸如此类。

    最后总结下今日最活跃的前五个发言者。
    """

    # 重复总结的prompt
    REPEAT_SUMMARY_PROMPT = """
    以不耐烦的语气回怼提问者聊天记录已总结过，要求如下
    - 随机角色的口吻回答
    - 不超过20字
    """

    # 总结中的prompt
    SUMMARY_IN_PROGRESS_PROMPT = """
    以不耐烦的语气回答提问者聊天记录正在总结中，要求如下
    - 随机角色的口吻回答
    - 不超过20字
    """

    def __init__(self):
        super().__init__()
        try:
            with open("plugins/ChatSummary/config.toml", "rb") as f:
                config = tomllib.load(f)

            plugin_config = config["ChatSummary"]
            self.enable = plugin_config["enable"]
            self.commands = plugin_config["commands"]
            self.default_num_messages = plugin_config["default_num_messages"]
            self.summary_wait_time = plugin_config["summary_wait_time"]

            dify_config = plugin_config["Dify"]
            self.dify_enable = dify_config["enable"]
            self.dify_api_key = dify_config["api-key"]
            self.dify_base_url = dify_config["base-url"]
            self.http_proxy = dify_config["http-proxy"]
            if not self.dify_enable or not self.dify_api_key or not self.dify_base_url:
                logger.warning("Dify配置不完整，请检查config.toml文件")
                self.enable = False

            logger.info("ChatSummary 插件配置加载成功")
        except FileNotFoundError:
            logger.error("config.toml 配置文件未找到，插件已禁用。")
            self.enable = False
        except Exception as e:
            logger.exception(f"ChatSummary 插件初始化失败: {e}")
            self.enable = False

        self.summary_tasks: Dict[str, asyncio.Task] = {}  # 存储正在进行的总结任务
        self.last_summary_time: Dict[str, datetime] = {}  # 记录上次总结的时间
        self.chat_history: Dict[str, List[Dict]] = defaultdict(list)  # 存储聊天记录
        self.http_session = aiohttp.ClientSession()

        # 数据库配置
        self.db_file = "chat_history.db"  # 数据库文件名
        self.db_connection = None
        self.initialize_database() #初始化数据库

    def initialize_database(self):
         """初始化数据库连接"""
         self.db_connection = sqlite3.connect(self.db_file)
         logger.info("数据库连接已建立")

    def create_table_if_not_exists(self, chat_id: str):
        """为每个chat_id创建一个单独的表"""
        table_name = self.get_table_name(chat_id)
        cursor = self.db_connection.cursor()
        try:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS "{table_name}" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_wxid TEXT NOT NULL,
                    create_time INTEGER NOT NULL,  -- 使用 INTEGER 存储时间戳
                    content TEXT NOT NULL
                )
            """)
            self.db_connection.commit()
            logger.info(f"表 {table_name} 创建成功")
        except sqlite3.Error as e:
             logger.error(f"创建表 {table_name} 失败：{e}")

    def get_table_name(self, chat_id: str) -> str:
        """
        生成表名，将chat_id中的特殊字符替换掉，避免SQL注入和表名错误
        """
        return "chat_" + re.sub(r"[^a-zA-Z0-9_]", "_", chat_id)


    async def _summarize_chat(self, bot: WechatAPIClient, chat_id: str, limit: Optional[int] = None, duration: Optional[timedelta] = None) -> None:
        """
        总结聊天记录并发送结果。

        Args:
            bot: WechatAPIClient 实例.
            chat_id: 聊天ID (群ID或个人ID).
            limit: 总结的消息数量 (可选).
            duration: 总结的时间段 (可选).
        """
        try:
            if limit:
                logger.info(f"开始总结 {chat_id} 的最近 {limit} 条消息")
            elif duration:
                logger.info(f"开始总结 {chat_id} 的最近 {duration} 时间段的消息")
            else:
                logger.error("limit 和 duration 都为空！")
                return # 理论上不应该发生

            # 从数据库中获取聊天记录
            messages_to_summarize = self.get_messages_from_db(chat_id, limit, duration)

            if not messages_to_summarize:
                try:
                    await bot.send_text_message(chat_id, "没有足够的聊天记录可以总结。")
                except AttributeError as e:
                    logger.error(f"发送消息失败 (没有 send_text_message 方法): {e}")
                    return
                except Exception as e:
                    logger.exception(f"发送消息失败: {e}")
                    return

            # 获取所有发言者的 wxid
            wxids = set(msg['sender_wxid'] for msg in messages_to_summarize) # 注意这里键名改成小写了
            nicknames = {}
            for wxid in wxids:
                try:
                    nickname = await bot.get_nickname(wxid)
                    nicknames[wxid] = nickname
                except Exception as e:
                    logger.exception(f"获取用户 {wxid} 昵称失败: {e}")
                    nicknames[wxid] = wxid  # 获取昵称失败，使用 wxid 代替

            # 提取消息内容，并替换成昵称
            text_to_summarize = "\n".join(
                [f"{nicknames.get(msg['sender_wxid'], msg['sender_wxid'])} ({datetime.fromtimestamp(msg['create_time']).strftime('%H:%M:%S')}): {msg['content']}" # 注意键名改成小写了
                 for msg in messages_to_summarize]
            )

            # 调用 Dify API 进行总结
            summary = await self._get_summary_from_dify(chat_id, text_to_summarize)

            try:
                await bot.send_text_message(chat_id, f"-----聊天总结-----\n{summary}")
            except AttributeError as e:
                logger.error(f"发送消息失败 (没有 send_text_message 方法): {e}")
                return
            except Exception as e:
                logger.exception(f"发送消息失败: {e}")
                return

            self.last_summary_time[chat_id] = datetime.now()  # 更新上次总结时间
            logger.info(f"{chat_id} 的总结完成")

        except Exception as e:
            logger.exception(f"总结 {chat_id} 发生错误: {e}")
            try:
                await bot.send_text_message(chat_id, f"总结时发生错误: {e}")
            except AttributeError as e:
                logger.error(f"发送消息失败 (没有 send_text_message 方法): {e}")
                return
            except Exception as e:
                logger.exception(f"发送消息失败: {e}")
                return
        finally:
            if chat_id in self.summary_tasks:
                del self.summary_tasks[chat_id]  # 移除任务

    async def _get_summary_from_dify(self, chat_id: str, text: str) -> str:
        """
        使用 Dify API 获取总结。

        Args:
            chat_id: 聊天ID (群ID或个人ID).
            text: 需要总结的文本.

        Returns:
            总结后的文本.
        """
        try:
            headers = {"Authorization": f"Bearer {self.dify_api_key}",
                       "Content-Type": "application/json"}
            payload = json.dumps({
                "inputs": {},
                "query": f"{self.SUMMARY_PROMPT}\n\n{text}",
                "response_mode": "blocking", # 必须是blocking
                "conversation_id": None,
                "user": chat_id,
                "files": [],
                "auto_generate_name": False,
        })
            url = f"{self.dify_base_url}/chat-messages"
            async with self.http_session.post(url=url, headers=headers, data=payload, proxy = self.http_proxy) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    summary = resp_json.get("answer", "")
                    logger.info(f"成功从 Dify API 获取总结: {summary}")
                    return summary
                else:
                    error_msg = await resp.text()
                    logger.error(f"调用 Dify API 失败: {resp.status} - {error_msg}")
                    return f"总结失败，Dify API 错误: {resp.status} - {error_msg}"
        except Exception as e:
            logger.exception(f"调用 Dify API 失败: {e}")
            return "总结失败，请稍后重试。"  # 返回错误信息

    def _extract_duration(self, text: str) -> Optional[timedelta]:
        """
        从文本中提取要总结的时间段。

        Args:
            text: 包含命令的文本。

        Returns:
            要总结的时间段，如果提取失败则返回 None。
        """
        match = re.search(r'(\d+)\s*(小时|分钟|天)', text)
        if not match:
            return None

        amount = int(match.group(1))
        unit = match.group(2)

        if unit == '小时':
            return timedelta(hours=amount)
        elif unit == '分钟':
            return timedelta(minutes=amount)
        elif unit == '天':
            return timedelta(days=amount)
        else:
            return None

    def _extract_num_messages(self, text: str) -> int:
        """
        从文本中提取要总结的消息数量。

        Args:
            text: 包含命令的文本。

        Returns:
            要总结的消息数量，如果提取失败则返回 default_num_messages。
        """
        try:
            match = re.search(r'(\d+)', text)
            if match:
                return int(match.group(1))
            return self.default_num_messages # 提取不到时返回默认值
        except ValueError:
            logger.warning(f"无法从文本中提取消息数量: {text}")
            return self.default_num_messages # 提取不到时返回默认值

    @on_text_message
    async def handle_text_message(self, bot: WechatAPIClient, message: Dict) -> bool: # 添加类型提示和返回值
        """处理文本消息，判断是否需要触发总结。"""
        if not self.enable:
            return True # 插件未启用，允许其他插件处理

        chat_id = message["FromWxid"]
        sender_wxid = message["SenderWxid"]
        content = message["Content"]
        is_group = message["IsGroup"]
        create_time = message["CreateTime"]

        # 1.  创建表 (如果不存在)
        self.create_table_if_not_exists(chat_id)

        # 2. 保存聊天记录到数据库
        self.save_message_to_db(chat_id, sender_wxid, create_time, content)

        # 3. 记录聊天历史 (可选，如果你还需要在内存中保留一份)
        # self.chat_history[chat_id].append(message)

        # 4. 检查是否为总结命令
        if any(cmd in content for cmd in self.commands):
            # 4.1 提取时间范围
            duration = self._extract_duration(content)
            # 4.2 提取消息数量
            limit = None
            if not duration: #如果没有时间范围，就提取消息数量
                limit = self._extract_num_messages(content)


            # 4.3 检查是否正在进行总结
            if chat_id in self.summary_tasks:
                try:
                    await bot.send_text_message(chat_id, self.SUMMARY_IN_PROGRESS_PROMPT)
                    return False # 正在总结中，阻止其他插件处理
                except AttributeError as e:
                    logger.error(f"发送消息失败 (没有 send_text_message 方法): {e}")
                    return True  # 允许其他插件处理，因为发送消息失败了
                except Exception as e:
                    logger.exception(f"发送消息失败: {e}")
                    return True # 允许其他插件处理，因为发送消息失败了

            # 4.4 创建总结任务
            self.summary_tasks[chat_id] = asyncio.create_task(
                self._summarize_chat(bot, chat_id, limit=limit, duration=duration) # 传递 limit 和 duration
            )
            if duration:
                logger.info(f"创建 {chat_id} 的总结任务，总结最近 {duration} 的消息")
            else:
                 logger.info(f"创建 {chat_id} 的总结任务，总结最近 {limit} 条消息")
            return False # 已创建总结任务，阻止其他插件处理
        return True # 不是总结命令，允许其他插件处理

    def save_message_to_db(self, chat_id: str, sender_wxid: str, create_time: int, content: str):
        """将消息保存到数据库"""
        table_name = self.get_table_name(chat_id)
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(f"""
                INSERT INTO "{table_name}" (sender_wxid, create_time, content)
                VALUES (?, ?, ?)
            """, (sender_wxid, create_time, content))
            self.db_connection.commit()
            logger.debug(f"消息保存到表 {table_name}: sender_wxid={sender_wxid}, create_time={create_time}")
        except sqlite3.Error as e:
            logger.exception(f"保存消息到表 {table_name} 失败: {e}")

    def get_messages_from_db(self, chat_id: str, limit: Optional[int] = None, duration: Optional[timedelta] = None) -> List[Dict]:
        """从数据库获取消息，同时支持按条数和按时间范围获取"""
        table_name = self.get_table_name(chat_id)

        try:
            cursor = self.db_connection.cursor()
            if duration:
                cutoff_time = datetime.now() - duration
                cutoff_timestamp = int(cutoff_time.timestamp())
                cursor.execute(f"""
                    SELECT sender_wxid, create_time, content
                    FROM "{table_name}"
                    WHERE create_time >= ?
                    ORDER BY create_time DESC
                """, (cutoff_timestamp,))

            elif limit:
                 cursor.execute(f"""
                    SELECT sender_wxid, create_time, content
                    FROM "{table_name}"
                    ORDER BY create_time DESC
                    LIMIT ?
                """, (limit,))
            else:
                return [] #避免不传limit和duration的情况
            rows = cursor.fetchall()
            # 将结果转换为字典列表，方便后续使用
            messages = []
            for row in rows:
                messages.append({
                    'sender_wxid': row[0],
                    'create_time': row[1],
                    'content': row[2]
                })
            if duration:
                logger.debug(f"从表 {table_name} 获取消息: duration={duration}, 数量={len(messages)}")
            else:
                logger.debug(f"从表 {table_name} 获取消息: limit={limit}, 数量={len(messages)}")
            return messages
        except sqlite3.Error as e:
            logger.exception(f"从表 {table_name} 获取消息失败: {e}")
            return []

    async def clear_old_messages(self):
        """定期清理旧消息"""
        while True:
            await asyncio.sleep(60 * 60 * 24)  # 每天检查一次
            try:
                cutoff_time = datetime.now() - timedelta(days=3) # 3天前
                cutoff_timestamp = int(cutoff_time.timestamp())

                cursor = self.db_connection.cursor()

                # 获取所有表名
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [row[0] for row in cursor.fetchall() if row[0].startswith("chat_")] #只清理chat_开头的表

                for table in tables:
                    try:
                        cursor.execute(f"""
                            DELETE FROM "{table}"
                            WHERE create_time < ?
                        """, (cutoff_timestamp,))
                        self.db_connection.commit()
                        logger.info(f"已清理表 {table} 中 {cutoff_timestamp} 之前的旧消息")
                    except sqlite3.Error as e:
                        logger.exception(f"清理表 {table} 失败: {e}")

            except Exception as e:
                logger.exception(f"清理旧消息失败: {e}")

    async def close(self):
        """插件关闭时，取消所有未完成的总结任务。"""
        logger.info("Closing ChatSummary plugin")
        for chat_id, task in self.summary_tasks.items():
            if not task.done():
                logger.info(f"Cancelling summary task for {chat_id}")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"Summary task for {chat_id} was cancelled")
                except Exception as e:
                     logger.exception(f"Error while cancelling summary task for {chat_id}: {e}")
        if self.http_session:
            await self.http_session.close()
            logger.info("Aiohttp session closed")

        # 关闭数据库连接
        if self.db_connection:
            self.db_connection.close()
            logger.info("数据库连接已关闭")

        logger.info("ChatSummary plugin closed")

    async def start(self):
        """启动插件时启动清理旧消息的任务"""
        asyncio.create_task(self.clear_old_messages()) #启动定时清理任务