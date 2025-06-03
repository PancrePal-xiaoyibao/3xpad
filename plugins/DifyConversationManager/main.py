import tomllib
import aiohttp
import traceback
from loguru import logger
from typing import List, Dict, Optional
from datetime import datetime
from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message
from utils.plugin_base import PluginBase
from database.XYBotDB import XYBotDB

class DifyConversationManager(PluginBase):
    description = "Dify对话管理插件"
    author = "xxxbot"
    version = "1.2.0"

    def __init__(self):
        super().__init__()
        # 加载配置
        with open("plugins/DifyConversationManager/config.toml", "rb") as f:
            config = tomllib.load(f)

        plugin_config = config["DifyConversationManager"]

        # 基础配置
        self.enable = plugin_config["enable"]
        self.api_key = plugin_config["api-key"]
        self.base_url = plugin_config["base-url"]
        self.http_proxy = plugin_config.get("http-proxy", "")

        # 命令配置
        self.command_prefix = plugin_config.get("command-prefix", "/dify")
        self.commands = plugin_config.get("commands", ["列表", "历史", "删除", "重命名", "帮助"])
        self.command_tip = plugin_config.get("command-tip", "使用 /dify 帮助 查看使用说明")

        # 权限配置
        self.price = plugin_config.get("price", 0)
        self.admin_ignore = plugin_config.get("admin_ignore", True)
        self.whitelist_ignore = plugin_config.get("whitelist_ignore", True)

        # 分页配置
        self.default_page_size = plugin_config.get("default-page-size", 20)
        self.max_page_size = plugin_config.get("max-page-size", 100)

        # 加载管理员列表
        try:
            with open("main_config.toml", "rb") as f:
                main_config = tomllib.load(f)
            self.admins = main_config["XYBot"]["admins"]
            logger.info(f"已加载管理员列表: {self.admins}")
        except Exception as e:
            logger.error(f"加载管理员列表失败: {e}")
            self.admins = []

        # 初始化数据库
        self.db = XYBotDB()

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict) -> bool:
        if not self.enable:
            return True

        content = message["Content"].strip()

        # 只响应 /dify 开头的命令
        if not content.startswith(self.command_prefix):
            return True

        # 提取命令部分
        cmd_content = content[len(self.command_prefix):].strip()

        # 如果只输入 /dify，显示帮助菜单
        if not cmd_content:
            await bot.send_text_message(message["FromWxid"], self.command_tip)
            return False

        # 处理删除所有对话的命令
        if cmd_content == "删除对话":
            await self.handle_delete_all_conversations(bot, message)
            return False

        # 处理删除所有用户所有对话的命令（仅管理员可用）
        if cmd_content == "删除所有对话":
            await self.handle_delete_all_users_conversations(bot, message)
            return False

        # 处理具体命令
        if cmd_content == "列表":
            await self.handle_list_command(bot, message)
        elif cmd_content.startswith("历史 "):
            conv_id = cmd_content[3:].strip()
            await self.handle_history_command(bot, message, conv_id)
        elif cmd_content.startswith("删除 "):
            conv_id = cmd_content[3:].strip()
            await self.handle_delete_command(bot, message, conv_id)
        elif cmd_content.startswith("重命名 "):
            params = cmd_content[3:].strip()
            await self.handle_rename_command(bot, message, params)
        else:
            # 无效命令也显示帮助菜单
            await bot.send_text_message(message["FromWxid"], self.command_tip)

        return False

    async def handle_help_command(self, bot: WechatAPIClient, message: dict):
        """处理帮助命令"""
        help_text = (
            "📝 Dify对话管理助手\n\n"
            "支持的命令：\n"
            f"1. {self.command_prefix} {self.commands[0]}\n"
            "   查看所有对话列表\n\n"
            f"2. {self.command_prefix} {self.commands[1]} <对话ID>\n"
            "   查看指定对话的历史记录\n\n"
            f"3. {self.command_prefix} {self.commands[2]} <对话ID>\n"
            "   删除指定的对话\n\n"
            f"4. {self.command_prefix} {self.commands[3]} <对话ID> <新名称>\n"
            "   重命名指定的对话\n\n"
            f"5. {self.command_prefix} 删除对话\n"
            "   删除当前用户或群聊的所有对话\n\n"
        )

        # 如果是管理员，显示管理员命令
        if message["SenderWxid"] in self.admins:
            help_text += (
                "🔐 管理员命令：\n"
                f"6. {self.command_prefix} 删除所有对话\n"
                "   ⚠️ 删除系统中所有用户的所有对话\n\n"
            )

        help_text += (
            "示例：\n"
            f"{self.command_prefix} {self.commands[0]}\n"
            f"{self.command_prefix} {self.commands[1]} abc-123\n"
            f"{self.command_prefix} {self.commands[3]} abc-123 测试对话"
        )
        await bot.send_text_message(message["FromWxid"], help_text)

    async def handle_list_command(self, bot: WechatAPIClient, message: dict):
        """处理列表命令"""
        try:
            wxid = message["SenderWxid"]
            chat_id = message["FromWxid"]
            is_group = message["IsGroup"]

            # 确定要查询的用户ID
            target_user = chat_id if is_group else wxid

            logger.info(f"获取对话列表 - 用户: {wxid}, 群聊: {chat_id}, 是否群聊: {is_group}, 目标用户: {target_user}")

            conversations = await self.get_conversations(target_user)
            if not conversations:
                msg = "当前群聊没有任何对话记录" if is_group else "您没有任何对话记录"
                logger.info(f"没有找到对话记录 - 目标用户: {target_user}")

                if is_group:
                    await bot.send_at_message(chat_id, msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, msg)
                return

            output = "📝 对话列表：\n\n"
            for conv in conversations:
                created_time = datetime.fromtimestamp(conv["created_at"]).strftime("%Y-%m-%d %H:%M")
                output += f"🆔 ID: {conv['id']}\n"
                output += f"📌 名称: {conv['name']}\n"
                output += f"⏰ 创建时间: {created_time}\n"
                output += "---------------\n"

            logger.info(f"成功获取对话列表 - 数量: {len(conversations)}")

            if is_group:
                await bot.send_at_message(chat_id, output, [wxid])
            else:
                await bot.send_text_message(chat_id, output)

        except Exception as e:
            logger.error(f"获取对话列表失败: {e}")
            logger.error(traceback.format_exc())

            error_msg = "获取对话列表失败，请稍后重试"
            if message.get("IsGroup", False):
                await bot.send_at_message(message["FromWxid"], error_msg, [message["SenderWxid"]])
            else:
                await bot.send_text_message(message["FromWxid"], error_msg)

    async def handle_history_command(self, bot: WechatAPIClient, message: dict, conversation_id: str):
        """处理历史记录命令"""
        try:
            wxid = message["SenderWxid"]
            chat_id = message["FromWxid"]
            is_group = message["IsGroup"]

            # 确定要查询的用户ID
            target_user = chat_id if is_group else wxid

            logger.info(f"获取对话历史 - 用户: {wxid}, 群聊: {chat_id}, 是否群聊: {is_group}, 目标用户: {target_user}, 对话ID: {conversation_id}")

            messages = await self.get_messages(target_user, conversation_id)
            if not messages:
                msg = f"没有找到对话 {conversation_id} 的历史记录"
                logger.info(f"没有找到对话历史 - 目标用户: {target_user}, 对话ID: {conversation_id}")

                if is_group:
                    await bot.send_at_message(chat_id, msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, msg)
                return

            output = f"📝 对话 {conversation_id} 的历史记录：\n\n"
            for msg in messages:
                created_time = datetime.fromtimestamp(msg["created_at"]).strftime("%Y-%m-%d %H:%M")
                output += f"⏰ {created_time}\n"
                output += f"❓ 问：{msg['query']}\n"
                output += f"💡 答：{msg['answer']}\n"
                output += "---------------\n"

            logger.info(f"成功获取对话历史 - 对话ID: {conversation_id}, 消息数量: {len(messages)}")

            if is_group:
                await bot.send_at_message(chat_id, output, [wxid])
            else:
                await bot.send_text_message(chat_id, output)

        except Exception as e:
            logger.error(f"获取对话历史失败: {e}")
            logger.error(traceback.format_exc())

            error_msg = "获取对话历史失败，请稍后重试"
            if message.get("IsGroup", False):
                await bot.send_at_message(message["FromWxid"], error_msg, [message["SenderWxid"]])
            else:
                await bot.send_text_message(message["FromWxid"], error_msg)

    async def handle_delete_command(self, bot: WechatAPIClient, message: dict, conversation_id: str):
        """处理删除命令"""
        try:
            wxid = message["SenderWxid"]
            chat_id = message["FromWxid"]
            is_group = message["IsGroup"]

            # 确定要删除的用户ID
            target_user = chat_id if is_group else wxid

            logger.info(f"删除单个对话 - 用户: {wxid}, 群聊: {chat_id}, 是否群聊: {is_group}, 目标用户: {target_user}, 对话ID: {conversation_id}")

            if await self.delete_conversation(target_user, conversation_id):
                success_msg = f"✅ 成功删除对话 {conversation_id}"
                logger.info(f"成功删除对话 - 目标用户: {target_user}, 对话ID: {conversation_id}")

                if is_group:
                    await bot.send_at_message(chat_id, success_msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, success_msg)
            else:
                fail_msg = f"❌ 删除对话 {conversation_id} 失败"
                logger.warning(f"删除对话失败 - 目标用户: {target_user}, 对话ID: {conversation_id}")

                if is_group:
                    await bot.send_at_message(chat_id, fail_msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, fail_msg)
        except Exception as e:
            logger.error(f"删除对话失败: {e}")
            logger.error(traceback.format_exc())

            error_msg = "删除对话失败，请稍后重试"
            if message.get("IsGroup", False):
                await bot.send_at_message(message["FromWxid"], error_msg, [message["SenderWxid"]])
            else:
                await bot.send_text_message(message["FromWxid"], error_msg)

    async def handle_rename_command(self, bot: WechatAPIClient, message: dict, params: str):
        """处理重命名命令"""
        try:
            wxid = message["SenderWxid"]
            chat_id = message["FromWxid"]
            is_group = message["IsGroup"]

            # 确定要操作的用户ID
            target_user = chat_id if is_group else wxid

            parts = params.split(maxsplit=1)
            if len(parts) != 2:
                format_error_msg = f"格式错误！正确格式：{self.command_prefix} {self.commands[3]} <对话ID> <新名称>"
                logger.warning(f"重命名命令格式错误 - 用户: {wxid}, 参数: {params}")

                if is_group:
                    await bot.send_at_message(chat_id, format_error_msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, format_error_msg)
                return

            conversation_id, new_name = parts
            logger.info(f"重命名对话 - 用户: {wxid}, 群聊: {chat_id}, 是否群聊: {is_group}, 目标用户: {target_user}, 对话ID: {conversation_id}, 新名称: {new_name}")

            if await self.rename_conversation(target_user, conversation_id, new_name):
                success_msg = f"✅ 成功将对话 {conversation_id} 重命名为「{new_name}」"
                logger.info(f"成功重命名对话 - 目标用户: {target_user}, 对话ID: {conversation_id}, 新名称: {new_name}")

                if is_group:
                    await bot.send_at_message(chat_id, success_msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, success_msg)
            else:
                fail_msg = f"❌ 重命名对话 {conversation_id} 失败"
                logger.warning(f"重命名对话失败 - 目标用户: {target_user}, 对话ID: {conversation_id}, 新名称: {new_name}")

                if is_group:
                    await bot.send_at_message(chat_id, fail_msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, fail_msg)
        except Exception as e:
            logger.error(f"重命名对话失败: {e}")
            logger.error(traceback.format_exc())

            error_msg = "重命名对话失败，请稍后重试"
            if message.get("IsGroup", False):
                await bot.send_at_message(message["FromWxid"], error_msg, [message["SenderWxid"]])
            else:
                await bot.send_text_message(message["FromWxid"], error_msg)

    async def handle_delete_all_users_conversations(self, bot: WechatAPIClient, message: dict):
        """处理删除所有用户所有对话的命令（仅管理员可用）"""
        try:
            wxid = message["SenderWxid"]
            chat_id = message["FromWxid"]

            # 检查权限
            if wxid not in self.admins:
                logger.warning(f"非管理员用户 {wxid} 尝试执行删除所有对话命令")
                await bot.send_text_message(chat_id, "⚠️ 您没有权限执行此操作，此命令仅限管理员使用。")
                return

            logger.info(f"管理员 {wxid} 执行删除所有用户所有对话命令")

            # 通知用户操作已开始
            await bot.send_text_message(chat_id, "🔄 正在删除所有用户的所有对话，请稍候...")

            # 这里应该实现删除所有用户所有对话的逻辑
            # 由于Dify API可能没有提供直接删除所有对话的接口，我们暂时返回一个提示信息

            await bot.send_text_message(chat_id, "⚠️ 此功能尚未实现。请联系开发者添加此功能。")

        except Exception as e:
            logger.error(f"删除所有用户所有对话时发生错误: {e}")
            logger.error(traceback.format_exc())
            await bot.send_text_message(chat_id, "❌ 删除所有用户所有对话时发生错误，请稍后重试。")

    async def handle_delete_all_conversations(self, bot: WechatAPIClient, message: dict):
        """处理删除所有对话的命令"""
        try:
            wxid = message["SenderWxid"]
            chat_id = message["FromWxid"]
            is_group = message["IsGroup"]

            # 确定要删除的用户ID
            target_user = chat_id if is_group else wxid

            # 记录操作日志
            logger.info(f"删除对话操作 - 用户: {wxid}, 群聊: {chat_id}, 是否群聊: {is_group}, 目标用户: {target_user}")

            # 记录消息内容
            logger.debug(f"消息内容: {message}")

            # 获取对话列表
            logger.info(f"开始获取对话列表 - 目标用户: {target_user}")
            conversations = await self.get_conversations(target_user)
            logger.info(f"获取到 {len(conversations)} 个对话")

            if not conversations:
                msg = "当前群聊没有任何对话记录" if is_group else "您没有任何对话记录"
                logger.info(f"没有找到对话记录 - 目标用户: {target_user}")
                if is_group:
                    await bot.send_at_message(chat_id, msg, [wxid])
                else:
                    await bot.send_text_message(chat_id, msg)
                return

            # 记录删除结果
            success_count = 0
            failed_count = 0
            failed_ids = []

            # 逐个删除对话
            for i, conv in enumerate(conversations):
                try:
                    conv_id = conv.get('id', 'unknown')
                    logger.info(f"[{i+1}/{len(conversations)}] 尝试删除对话 - ID: {conv_id}, 用户: {target_user}")

                    # 记录对话详情
                    logger.debug(f"对话详情: {conv}")

                    if await self.delete_conversation(target_user, conv_id):
                        success_count += 1
                        logger.info(f"[{i+1}/{len(conversations)}] 成功删除对话 - ID: {conv_id}")
                    else:
                        failed_count += 1
                        failed_ids.append(conv_id)
                        logger.warning(f"[{i+1}/{len(conversations)}] 删除对话失败 - ID: {conv_id}")
                except Exception as e:
                    logger.error(f"[{i+1}/{len(conversations)}] 删除对话 {conv.get('id', 'unknown')} 失败: {e}")
                    logger.error(traceback.format_exc())
                    failed_count += 1
                    failed_ids.append(conv.get('id', 'unknown'))

            # 生成结果报告
            output = "📝 删除对话结果：\n\n"
            if is_group:
                output += f"🔹 群聊: {chat_id}\n"
            else:
                output += f"🔹 用户: {wxid}\n"

            output += f"✅ 成功删除: {success_count} 个对话\n"
            if failed_count > 0:
                output += f"❌ 删除失败: {failed_count} 个对话\n"
                if failed_ids:
                    output += "失败的对话ID：\n"
                    for failed_id in failed_ids:
                        output += f"- {failed_id}\n"

            # 记录结果
            logger.info(f"删除对话结果 - 成功: {success_count}, 失败: {failed_count}")

            # 发送结果
            if is_group:
                logger.info(f"发送结果到群聊 - 群聊: {chat_id}, 用户: {wxid}")
                await bot.send_at_message(chat_id, output, [wxid])
            else:
                logger.info(f"发送结果到私聊 - 用户: {wxid}")
                await bot.send_text_message(chat_id, output)

        except Exception as e:
            logger.error(f"删除所有对话时发生错误: {e}")
            error_msg = "删除对话时发生错误，请稍后重试"
            if is_group:
                await bot.send_at_message(chat_id, error_msg, [wxid])
            else:
                await bot.send_text_message(chat_id, error_msg)

    async def get_conversations(self, user: str, last_id: str = "", limit: int = 100) -> List[Dict]:
        """获取对话列表"""
        try:
            logger.info(f"开始获取对话列表 - 用户: {user}, 上一个ID: {last_id}, 限制: {limit}")

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            params = {
                "user": user,
                "last_id": last_id,
                "limit": limit,
                "sort_by": "-updated_at"
            }

            url = f"{self.base_url}/conversations"
            logger.debug(f"请求URL: {url}, 参数: {params}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, proxy=self.http_proxy) as resp:
                    status_code = resp.status
                    logger.debug(f"响应状态码: {status_code}")

                    if status_code == 200:
                        result = await resp.json()
                        conversations = result.get("data", [])
                        logger.info(f"成功获取对话列表 - 数量: {len(conversations)}")

                        # 记录前几个对话的ID，便于调试
                        if conversations:
                            sample_ids = [conv.get('id', 'unknown') for conv in conversations[:3]]
                            logger.debug(f"对话ID示例: {sample_ids}")

                        return conversations
                    else:
                        response_text = await resp.text()
                        logger.error(f"获取对话列表失败: 状态码 {status_code} - {response_text}")
                        return []

        except Exception as e:
            logger.error(f"获取对话列表异常: {e}")
            logger.error(traceback.format_exc())
            return []

    async def delete_conversation(self, user: str, conversation_id: str) -> bool:
        """删除对话"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            # 记录请求信息
            logger.info(f"删除对话 - 用户: {user}, 对话ID: {conversation_id}")

            # 构建请求数据
            data = {"user": user}
            url = f"{self.base_url}/conversations/{conversation_id}"

            # 记录完整请求信息
            logger.debug(f"删除对话请求 - URL: {url}, 数据: {data}")

            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers, json=data, proxy=self.http_proxy) as resp:
                    response_text = await resp.text()
                    logger.debug(f"删除对话响应 - 状态码: {resp.status}, 响应: {response_text}")

                    if resp.status == 200:
                        try:
                            result = await resp.json()
                            success = result.get("result") == "success"
                            logger.info(f"删除对话结果 - 成功: {success}")
                            return success
                        except Exception as json_error:
                            logger.error(f"解析删除对话响应JSON失败: {json_error}")
                            # 如果无法解析JSON，但状态码是200，我们认为删除成功
                            return True
                    else:
                        logger.error(f"删除对话失败: {resp.status} - {response_text}")
                        return False

        except Exception as e:
            logger.error(f"删除对话异常: {e}")
            logger.error(traceback.format_exc())
            return False

    async def get_messages(self, user: str, conversation_id: str, first_id: str = "", limit: int = 20) -> List[Dict]:
        """获取对话历史消息"""
        try:
            logger.info(f"开始获取对话历史消息 - 用户: {user}, 对话ID: {conversation_id}, 首条消息ID: {first_id}, 限制: {limit}")

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            params = {
                "conversation_id": conversation_id,
                "user": user,
                "first_id": first_id,
                "limit": limit
            }

            url = f"{self.base_url}/messages"
            logger.debug(f"请求URL: {url}, 参数: {params}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, proxy=self.http_proxy) as resp:
                    status_code = resp.status
                    logger.debug(f"响应状态码: {status_code}")

                    if status_code == 200:
                        result = await resp.json()
                        messages = result.get("data", [])
                        logger.info(f"成功获取对话历史消息 - 数量: {len(messages)}")

                        # 记录前几条消息的内容，便于调试
                        if messages:
                            sample_messages = [f"{msg.get('query', '无问题')}..." for msg in messages[:2]]
                            logger.debug(f"消息示例: {sample_messages}")

                        return messages
                    else:
                        response_text = await resp.text()
                        logger.error(f"获取对话历史失败: 状态码 {status_code} - {response_text}")
                        return []

        except Exception as e:
            logger.error(f"获取对话历史异常: {e}")
            logger.error(traceback.format_exc())
            return []

    async def rename_conversation(self, user: str, conversation_id: str, new_name: str) -> bool:
        """重命名对话"""
        try:
            logger.info(f"开始重命名对话 - 用户: {user}, 对话ID: {conversation_id}, 新名称: {new_name}")

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "name": new_name,
                "auto_generate": False,
                "user": user
            }

            url = f"{self.base_url}/conversations/{conversation_id}/name"
            logger.debug(f"请求URL: {url}, 数据: {data}")

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data, proxy=self.http_proxy) as resp:
                    status_code = resp.status
                    logger.debug(f"响应状态码: {status_code}")

                    if status_code == 200:
                        result = await resp.json()
                        success = bool(result.get("name") == new_name)
                        logger.info(f"重命名对话结果 - 成功: {success}, 返回名称: {result.get('name', '无名称')}")
                        return success
                    else:
                        response_text = await resp.text()
                        logger.error(f"重命名对话失败: 状态码 {status_code} - {response_text}")
                        return False

        except Exception as e:
            logger.error(f"重命名对话异常: {e}")
            logger.error(traceback.format_exc())
            return False
