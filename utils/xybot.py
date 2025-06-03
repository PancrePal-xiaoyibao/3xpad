import tomllib
import xml.etree.ElementTree as ET
from typing import Dict, Any
import asyncio
import io

from loguru import logger

from WechatAPI import WechatAPIClient
from WechatAPI.Client.protect import protector
from database.messsagDB import MessageDB
from database.contacts_db import update_contact_in_db, get_contact_from_db
from utils.event_manager import EventManager


class XYBot:
    def __init__(self, bot_client: WechatAPIClient):
        self.bot = bot_client
        self.wxid = None
        self.nickname = None
        self.alias = None
        self.phone = None

        # 打印当前工作目录，便于调试
        import os
        logger.debug(f"当前工作目录: {os.getcwd()}")

        # 检查配置文件是否存在
        config_path = "main_config.toml"
        if not os.path.exists(config_path):
            logger.error(f"配置文件 {config_path} 不存在")
            main_config = {}
        else:
            logger.debug(f"配置文件 {config_path} 存在，大小: {os.path.getsize(config_path)} 字节")
            try:
                with open(config_path, "rb") as f:
                    main_config = tomllib.load(f)
                    # 打印配置文件的所有键
                    logger.debug(f"配置文件的所有键: {list(main_config.keys())}")
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
                main_config = {}

        self.ignore_protection = main_config.get("XYBot", {}).get("ignore-protection", False)

        # 从配置文件中读取消息过滤设置
        try:
            # 尝试从顶层读取设置
            if "ignore-mode" in main_config:
                self.ignore_mode = main_config["ignore-mode"]
                self.whitelist = main_config["whitelist"]
                self.blacklist = main_config["blacklist"]
            # 如果顶层没有，尝试从AutoRestart部分读取
            elif "AutoRestart" in main_config and "ignore-mode" in main_config["AutoRestart"]:
                self.ignore_mode = main_config["AutoRestart"]["ignore-mode"]
                self.whitelist = main_config["AutoRestart"]["whitelist"]
                self.blacklist = main_config["AutoRestart"]["blacklist"]
            else:
                # 如果都没有，使用默认值
                raise KeyError("ignore-mode not found in config")
        except KeyError as e:
            # 如果读取失败，使用默认值
            self.ignore_mode = "None"
            self.whitelist = []
            self.blacklist = []

        # 记录配置信息
        logger.info(f"消息过滤模式: {self.ignore_mode}")
        logger.info(f"白名单: {self.whitelist}")
        logger.info(f"黑名单: {self.blacklist}")

        self.msg_db = MessageDB()

    def update_profile(self, wxid: str, nickname: str, alias: str, phone: str):
        """更新机器人信息"""
        self.wxid = wxid
        self.nickname = nickname
        self.alias = alias
        self.phone = phone

    def is_logged_in(self):
        """检查机器人是否已登录

        Returns:
            bool: 如果已登录返回true，否则返回false
        """
        return self.wxid is not None

    async def get_chatroom_member_list(self, group_wxid: str):
        """获取群成员列表

        Args:
            group_wxid: 群聊的wxid

        Returns:
            list: 群成员列表
        """
        if not group_wxid.endswith("@chatroom"):
            logger.error(f"无效的群ID: {group_wxid}，只有群聊才能获取成员列表")
            return []

        try:
            logger.info(f"开始获取群 {group_wxid} 的成员列表")

            # 直接调用微信API获取群成员列表
            try:
                import aiohttp
                import json

                # 获取微信API的基本配置
                api_base = "http://127.0.0.1:9011"
                if hasattr(self.bot, 'ip') and hasattr(self.bot, 'port'):
                    api_base = f"http://{self.bot.ip}:{self.bot.port}"

                # 确定API路径前缀
                api_prefix = ""

                # 先检查是否有显式设置的前缀
                if hasattr(self.bot, 'api_prefix'):
                    api_prefix = self.bot.api_prefix
                elif hasattr(self.bot, '_api_prefix'):
                    api_prefix = self.bot._api_prefix

                # 如果没有显式设置，则根据协议版本确定
                if api_prefix == "":
                    # 读取协议版本配置
                    try:
                        import tomllib
                        with open("main_config.toml", "rb") as f:
                            config = tomllib.load(f)
                            protocol_version = config.get("Protocol", {}).get("version", "849")

                            # 根据协议版本选择前缀
                            if protocol_version == "849":
                                api_prefix = "/VXAPI"
                                logger.info(f"使用849协议前缀: {api_prefix}")
                            else:  # 855 或 ipad
                                api_prefix = "/api"
                                logger.info(f"使用{protocol_version}协议前缀: {api_prefix}")
                    except Exception as e:
                        logger.warning(f"读取协议版本失败，使用默认前缀: {e}")
                        # 默认使用 849 的前缀
                        api_prefix = "/VXAPI"
                        logger.info(f"使用默认协议前缀: {api_prefix}")

                # 获取当前登录的wxid
                wxid = ""
                if hasattr(self.bot, 'wxid'):
                    wxid = self.bot.wxid

                logger.info(f"使用API路径: {api_base}{api_prefix}/Group/GetChatRoomMemberDetail")

                # 直接调用API获取群成员
                async with aiohttp.ClientSession() as session:
                    json_param = {"QID": group_wxid, "Wxid": wxid}
                    logger.info(f"发送请求参数: {json.dumps(json_param)}")

                    response = await session.post(
                        f'{api_base}{api_prefix}/Group/GetChatRoomMemberDetail',
                        json=json_param,
                        headers={"Content-Type": "application/json"}
                    )

                    # 检查响应状态
                    if response.status != 200:
                        logger.error(f"获取群成员列表失败: HTTP状态码 {response.status}")
                        return []

                    # 解析响应数据
                    try:
                        json_resp = await response.json()
                        logger.info(f"收到API响应: {json.dumps(json_resp)[:200]}...")

                        if json_resp.get("Success"):
                            # 处理成功响应
                            members_data = []

                            # 根据实际响应结构提取成员列表
                            if json_resp.get("Data") and json_resp["Data"].get("NewChatroomData") and json_resp["Data"]["NewChatroomData"].get("ChatRoomMember"):
                                members_data = json_resp["Data"]["NewChatroomData"]["ChatRoomMember"]
                                logger.info(f"从 NewChatroomData.ChatRoomMember 获取到 {len(members_data)} 个成员")
                            elif json_resp.get("Data") and json_resp["Data"].get("ChatRoomMember"):
                                members_data = json_resp["Data"]["ChatRoomMember"]
                                logger.info(f"从 Data.ChatRoomMember 获取到 {len(members_data)} 个成员")
                            elif json_resp.get("Data") and isinstance(json_resp["Data"], list):
                                members_data = json_resp["Data"]
                                logger.info(f"从 Data 数组获取到 {len(members_data)} 个成员")

                            logger.info(f"成功获取群 {group_wxid} 的成员列表，共 {len(members_data)} 个成员")

                            # 处理成员信息，确保每个成员都有基本字段
                            members = []
                            for member in members_data:
                                # 确保每个成员都有wxid字段
                                if not member.get('wxid') and member.get('Wxid'):
                                    member['wxid'] = member['Wxid']

                                # 确保每个成员都有nickname字段
                                if not member.get('nickname'):
                                    if member.get('NickName'):
                                        member['nickname'] = member['NickName']
                                    else:
                                        member['nickname'] = member.get('wxid', 'Unknown')

                                # 处理头像字段
                                if not member.get('avatar'):
                                    if member.get('BigHeadImgUrl'):
                                        member['avatar'] = member['BigHeadImgUrl']
                                    elif member.get('SmallHeadImgUrl'):
                                        member['avatar'] = member['SmallHeadImgUrl']

                                members.append(member)

                            return members
                        else:
                            error_msg = json_resp.get("Message") or json_resp.get("message") or "未知错误"
                            logger.warning(f"获取群 {group_wxid} 成员列表失败: {error_msg}")
                            return []
                    except Exception as e:
                        logger.error(f"解析群成员响应数据失败: {str(e)}")
                        return []
            except Exception as e:
                logger.error(f"调用API获取群 {group_wxid} 成员列表失败: {str(e)}")
                return []
        except Exception as e:
            logger.error(f"获取群成员列表时发生异常: {str(e)}")
            return []

    async def update_contact_info(self, wxid: str):
        """更新联系人信息

        Args:
            wxid: 联系人的wxid
        """
        try:
            # 先检查数据库中是否已有该联系人的信息
            existing_contact = get_contact_from_db(wxid)

            # 如果数据库中没有该联系人的信息，或者信息不完整，则从 API 获取
            if not existing_contact or not existing_contact.get('nickname'):
                # 从 API 获取联系人信息
                try:
                    # 如果是群聊，不获取详细信息
                    if wxid.endswith("@chatroom"):
                        contact_info = {
                            'wxid': wxid,
                            'nickname': wxid,
                            'type': 'group'
                        }
                        # 更新到数据库
                        update_contact_in_db(contact_info)
                        logger.debug(f"已在消息处理中更新群聊 {wxid} 的基本信息")
                    else:
                        # 获取联系人详细信息
                        logger.debug(f"开始获取联系人 {wxid} 的详细信息")
                        try:
                            detail = await self.bot.get_contract_detail(wxid)
                            logger.debug(f"获取到联系人 {wxid} 的详细信息: {detail}")

                            if detail:
                                # 处理返回结果
                                if isinstance(detail, list) and len(detail) > 0:
                                    detail_item = detail[0]
                                    logger.debug(f"联系人 {wxid} 详情项类型: {type(detail_item)}")

                                    if isinstance(detail_item, dict):
                                        # 记录详细的字段信息，帮助调试
                                        logger.debug(f"联系人 {wxid} 详情字段: {list(detail_item.keys())}")

                                        # 检查nickname字段的类型和值
                                        nickname_value = detail_item.get('nickname')
                                        if nickname_value is None:
                                            # 尝试其他可能的字段名
                                            nickname_value = detail_item.get('NickName')
                                            if nickname_value is None:
                                                logger.warning(f"联系人 {wxid} 没有找到nickname或NickName字段")
                                            else:
                                                logger.debug(f"联系人 {wxid} 使用NickName字段: {nickname_value}")
                                        else:
                                            logger.debug(f"联系人 {wxid} 使用nickname字段: {nickname_value}")

                                        # 如果nickname是字典类型，尝试获取其中的string字段
                                        if isinstance(nickname_value, dict):
                                            logger.debug(f"联系人 {wxid} 的nickname是字典类型: {nickname_value}")
                                            nickname_string = nickname_value.get('string')
                                            if nickname_string:
                                                nickname_value = nickname_string
                                                logger.debug(f"从字典中提取nickname.string: {nickname_string}")

                                        # 处理头像字段 - 优先使用BigHeadImgUrl或SmallHeadImgUrl
                                        avatar_value = detail_item.get('BigHeadImgUrl', '')
                                        if not avatar_value:
                                            avatar_value = detail_item.get('SmallHeadImgUrl', '')
                                        if not avatar_value:
                                            # 如果没有直接的URL，尝试使用avatar字段
                                            avatar_value = detail_item.get('avatar', '')
                                            if isinstance(avatar_value, dict):
                                                avatar_value = avatar_value.get('string', '')

                                        logger.debug(f"联系人 {wxid} 的头像地址: {avatar_value}")

                                        # 处理备注字段
                                        remark_value = detail_item.get('remark', '')
                                        if remark_value is None or not remark_value:
                                            remark_value = detail_item.get('Remark', '')
                                        if isinstance(remark_value, dict):
                                            remark_value = remark_value.get('string', '')

                                        # 处理微信号字段
                                        alias_value = detail_item.get('alias', '')
                                        if alias_value is None or not alias_value:
                                            alias_value = detail_item.get('Alias', '')
                                        if isinstance(alias_value, dict):
                                            alias_value = alias_value.get('string', '')

                                        # 构建联系人信息
                                        contact_info = {
                                            'wxid': wxid,
                                            'nickname': nickname_value if nickname_value else wxid,
                                            'avatar': avatar_value,
                                            'remark': remark_value,
                                            'alias': alias_value
                                        }
                                        logger.debug(f"解析联系人 {wxid} 详情成功: {contact_info}")
                                    else:
                                        logger.warning(f"联系人 {wxid} 详情格式不是字典: {detail_item}")
                                        # 创建基本联系人信息
                                        contact_info = {
                                            'wxid': wxid,
                                            'nickname': wxid,
                                            'type': 'friend'
                                        }
                                elif isinstance(detail, dict):
                                    # 记录详细的字段信息，帮助调试
                                    logger.debug(f"联系人 {wxid} 详情字段(字典格式): {list(detail.keys())}")

                                    # 检查nickname字段的类型和值
                                    nickname_value = detail.get('nickname')
                                    if nickname_value is None:
                                        # 尝试其他可能的字段名
                                        nickname_value = detail.get('NickName')
                                        if nickname_value is None:
                                            logger.warning(f"联系人 {wxid} 没有找到nickname或NickName字段")
                                        else:
                                            logger.debug(f"联系人 {wxid} 使用NickName字段: {nickname_value}")
                                    else:
                                        logger.debug(f"联系人 {wxid} 使用nickname字段: {nickname_value}")

                                    # 如果nickname是字典类型，尝试获取其中的string字段
                                    if isinstance(nickname_value, dict):
                                        logger.debug(f"联系人 {wxid} 的nickname是字典类型: {nickname_value}")
                                        nickname_string = nickname_value.get('string')
                                        if nickname_string:
                                            nickname_value = nickname_string
                                            logger.debug(f"从字典中提取nickname.string: {nickname_string}")

                                    # 处理头像字段 - 优先使用BigHeadImgUrl或SmallHeadImgUrl
                                    avatar_value = detail.get('BigHeadImgUrl', '')
                                    if not avatar_value:
                                        avatar_value = detail.get('SmallHeadImgUrl', '')
                                    if not avatar_value:
                                        # 如果没有直接的URL，尝试使用avatar字段
                                        avatar_value = detail.get('avatar', '')
                                        if isinstance(avatar_value, dict):
                                            avatar_value = avatar_value.get('string', '')

                                    logger.debug(f"联系人 {wxid} 的头像地址(字典格式): {avatar_value}")

                                    # 处理备注字段
                                    remark_value = detail.get('remark', '')
                                    if remark_value is None or not remark_value:
                                        remark_value = detail.get('Remark', '')
                                    if isinstance(remark_value, dict):
                                        remark_value = remark_value.get('string', '')

                                    # 处理微信号字段
                                    alias_value = detail.get('alias', '')
                                    if alias_value is None or not alias_value:
                                        alias_value = detail.get('Alias', '')
                                    if isinstance(alias_value, dict):
                                        alias_value = alias_value.get('string', '')

                                    # 构建联系人信息
                                    contact_info = {
                                        'wxid': wxid,
                                        'nickname': nickname_value if nickname_value else wxid,
                                        'avatar': avatar_value,
                                        'remark': remark_value,
                                        'alias': alias_value
                                    }
                                    logger.debug(f"解析联系人 {wxid} 详情成功(字典格式): {contact_info}")
                                else:
                                    logger.warning(f"联系人 {wxid} 详情格式不支持: {type(detail)}")
                                    # 创建基本联系人信息
                                    contact_info = {
                                        'wxid': wxid,
                                        'nickname': wxid,
                                        'type': 'friend'
                                    }
                            else:
                                logger.warning(f"无法获取联系人 {wxid} 的详细信息，API返回空数据")
                                # 创建基本联系人信息
                                contact_info = {
                                    'wxid': wxid,
                                    'nickname': wxid,
                                    'type': 'friend'
                                }

                            # 更新到数据库
                            update_contact_in_db(contact_info)
                            logger.debug(f"已在消息处理中更新联系人 {wxid} 的信息")
                        except Exception as e:
                            logger.error(f"调用API获取联系人 {wxid} 详情失败: {str(e)}")
                            # 创建基本联系人信息
                            contact_info = {
                                'wxid': wxid,
                                'nickname': wxid,
                                'type': 'friend'
                            }
                            # 仍然更新到数据库，确保至少有基本信息
                            update_contact_in_db(contact_info)
                            logger.debug(f"已在消息处理中更新联系人 {wxid} 的基本信息")
                except Exception as e:
                    logger.error(f"在消息处理中获取联系人 {wxid} 信息失败: {str(e)}")
                    # 创建基本联系人信息并保存
                    contact_info = {
                        'wxid': wxid,
                        'nickname': wxid,
                        'type': 'friend' if not wxid.endswith("@chatroom") else 'group'
                    }
                    update_contact_in_db(contact_info)
                    logger.debug(f"已在消息处理中更新联系人 {wxid} 的基本信息(异常处理)")
        except Exception as e:
            logger.error(f"更新联系人信息时发生异常: {str(e)}")

    async def process_message(self, message: Dict[str, Any]):
        """处理接收到的消息"""

        msg_type = message.get("MsgType")

        # 预处理消息
        # 确保 FromWxid 始终是字符串，默认为空字符串
        from_user = message.get("FromUserName", {})
        if isinstance(from_user, dict):
            message["FromWxid"] = from_user.get("string", "")
        else:
            message["FromWxid"] = str(from_user) if from_user else ""
        message.pop("FromUserName", None)

        # 确保 ToWxid 始终是字符串，默认为空字符串
        to_wxid = message.get("ToWxid", {})
        if isinstance(to_wxid, dict):
            message["ToWxid"] = to_wxid.get("string", "")
        else:
            message["ToWxid"] = str(to_wxid) if to_wxid else ""

        # 处理一下自己发的消息
        to_wxid = message.get("ToWxid", "")
        if message.get("FromWxid") == self.wxid and isinstance(to_wxid, str) and to_wxid.endswith("@chatroom"):
            message["FromWxid"], message["ToWxid"] = message["ToWxid"], message["FromWxid"]

        # 异步更新发送者联系人信息
        from_wxid = message.get("FromWxid", "")
        if from_wxid and from_wxid != self.wxid:
            # 如果是群聊，只更新群聊本身信息
            if from_wxid.endswith("@chatroom"):
                logger.info(f"开始异步更新群聊信息: {from_wxid}")
                update_task = asyncio.create_task(self.update_contact_info(from_wxid))
                # 添加回调以记录完成状态
                update_task.add_done_callback(
                    lambda t: logger.info(f"完成群聊信息更新: {from_wxid}, 状态: {'success' if not t.exception() else f'error: {t.exception()}'}")
                )
            # 如果是私聊，更新发送者信息
            elif not from_wxid.endswith("@chatroom"):
                logger.info(f"开始异步更新发送者联系人信息: {from_wxid}")
                update_task = asyncio.create_task(self.update_contact_info(from_wxid))
                # 添加回调以记录完成状态
                update_task.add_done_callback(
                    lambda t: logger.info(f"完成发送者联系人信息更新: {from_wxid}, 状态: {'success' if not t.exception() else f'error: {t.exception()}'}")
                )

        # 根据消息类型触发不同的事件
        if msg_type == 1:  # 文本消息
            await self.process_text_message(message)
        elif msg_type == 3:  # 图片消息
            await self.process_image_message(message)
        elif msg_type == 34:  # 语音消息
            await self.process_voice_message(message)
        elif msg_type == 43:  # 视频消息
            await self.process_video_message(message)
        elif msg_type == 47:  # 表情消息
            await self.process_emoji_message(message)
        elif msg_type == 49:  # xml消息
            await self.process_xml_message(message)
        elif msg_type == 10002:  # 系统消息
            await self.process_system_message(message)
        elif msg_type == 37:  # 好友请求
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("friend_request", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")
        elif msg_type == 51:
            pass
        else:
            logger.info("未知的消息类型: {}", message)

    async def process_text_message(self, message: Dict[str, Any]):
        """处理文本消息"""
        message["Content"] = message.get("Content", {}).get("string", "")

        # ====== TVS 指令优先处理（无论单聊/群聊） ======
        content = message["Content"].strip()
        from_wxid = message["FromWxid"]
        sender_wxid = message.get("SenderWxid", from_wxid)
        is_group = message.get("IsGroup", False)
        chat_id = from_wxid
        sender = sender_wxid
        # 兼容单聊
        if not is_group:
            sender = from_wxid
            chat_id = from_wxid
        try:
            from plugins.TVSSpider.main import TVSSpider
            # 单例/全局缓存
            if not hasattr(self, "_tvs_spider"):
                self._tvs_spider = TVSSpider()
                await self._tvs_spider.async_init()
            tvs_spider = self._tvs_spider
            # 只要以TVS或TVS#开头就拦截
            if content.startswith("TVS#") or content.startswith("TVS #"):
                # 详情
                fake_msg = {
                    "Content": content,
                    "FromWxid": chat_id,
                    "SenderWxid": sender,
                    "IsGroup": is_group
                }
                await tvs_spider.handle_text(self.bot, fake_msg)
                return  # 不再分发
            elif content.startswith("TVS") or content.startswith("TVS "):
                # 搜索
                fake_msg = {
                    "Content": content,
                    "FromWxid": chat_id,
                    "SenderWxid": sender,
                    "IsGroup": is_group
                }
                await tvs_spider.handle_text(self.bot, fake_msg)
                return  # 不再分发
        except Exception as e:
            logger.error(f"[主程序TVS直通] 处理TVS指令异常: {e}")
        # ====== TVS 指令优先处理 END ======

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":\n", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]

                # 不更新群聊中发送者的联系人信息
                # 根据需求，只更新群聊本身信息，不更新群聊中发送者信息
            else:
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        try:
            root = ET.fromstring(message.get("MsgSource", ""))
            ats = root.find("atuserlist").text if root.find("atuserlist") is not None else ""
        except Exception as e:
            logger.error("解析文本消息失败: {}", e)
            ats = ""

        if ats:
            ats = ats.strip(",").split(",")
        else:
            ats = []
        message["Ats"] = ats if ats and ats[0] != "" else []

        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["SenderWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=message["Content"],
            is_group=message["IsGroup"]
        )

        if self.wxid in message.get("Ats", []):
            logger.info("收到被@消息: 消息ID:{} 来自:{} 发送人:{} @:{} 内容:{}",
                        message.get("MsgId", ""), message["FromWxid"],
                        message["SenderWxid"], message["Ats"], message["Content"])
            if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
                if self.ignore_protection or not protector.check(14400):
                    await EventManager.emit("at_message", self.bot, message)
                else:
                    logger.warning("风控保护: 新设备登录后4小时内请挂机")
            return

        logger.info("收到文本消息: 消息ID:{} 来自:{} 发送人:{} @:{} 内容:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["SenderWxid"], message["Ats"], message["Content"])

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("text_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_image_message(self, message: Dict[str, Any]):
        """处理图片消息"""
        message["Content"] = message.get("Content", {}).get("string", "").replace("\n", "").replace("\t", "")

        if message["FromWxid"].endswith("@chatroom"):
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]

                # 不更新群聊中发送者的联系人信息
                # 根据需求，只更新群聊本身信息，不更新群聊中发送者信息
            else:
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        logger.info("收到图片消息: 消息ID:{} 来自:{} 发送人:{} XML:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["SenderWxid"], message["Content"])

        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["SenderWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=message.get("MsgSource", ""),
            is_group=message["IsGroup"]
        )

        aeskey, cdnmidimgurl, length, md5 = None, None, None, None
        try:
            root = ET.fromstring(message["Content"])
            img_element = root.find('img')
            if img_element is not None:
                aeskey = img_element.get('aeskey')
                cdnmidimgurl = img_element.get('cdnmidimgurl')
                length = img_element.get('length')
                md5 = img_element.get('md5')
                logger.debug(f"解析图片XML成功: aeskey={aeskey}, length={length}, md5={md5}")
        except Exception as e:
            logger.error("解析图片消息失败: {}, 内容: {}", e, message["Content"])
            return

        # 尝试使用新的get_msg_image方法分段下载图片
        try:
            if length and length.isdigit():
                img_length = int(length)
                logger.debug(f"尝试使用get_msg_image下载图片: MsgId={message.get('MsgId')}, length={img_length}")

                # 分段下载图片
                chunk_size = 64 * 1024  # 64KB
                chunks = (img_length + chunk_size - 1) // chunk_size  # 向上取整
                full_image_data = bytearray()

                logger.info(f"开始分段下载图片，总大小: {img_length} 字节，分 {chunks} 段下载")

                download_success = True
                for i in range(chunks):
                    try:
                        # 下载当前段
                        start_pos = i * chunk_size
                        chunk_data = await self.bot.get_msg_image(message.get('MsgId'), message["FromWxid"], img_length, start_pos=start_pos)
                        if chunk_data and len(chunk_data) > 0:
                            full_image_data.extend(chunk_data)
                            logger.debug(f"第 {i+1}/{chunks} 段下载成功，大小: {len(chunk_data)} 字节")
                        else:
                            logger.error(f"第 {i+1}/{chunks} 段下载失败，数据为空")
                            download_success = False
                            break
                    except Exception as e:
                        logger.error(f"下载第 {i+1}/{chunks} 段时出错: {e}")
                        download_success = False
                        break

                if download_success and len(full_image_data) > 0:
                    # 验证图片数据
                    try:
                        import base64
                        from PIL import Image, ImageFile
                        ImageFile.LOAD_TRUNCATED_IMAGES = True  # 允许加载截断的图片

                        image_data = bytes(full_image_data)
                        # 验证图片数据
                        Image.open(io.BytesIO(image_data))
                        message["Content"] = base64.b64encode(image_data).decode('utf-8')
                        logger.info(f"分段下载图片成功，总大小: {len(image_data)} 字节")
                    except Exception as img_error:
                        logger.error(f"验证分段下载的图片数据失败: {img_error}")
                        # 如果验证失败，尝试使用download_image
                        if aeskey and cdnmidimgurl:
                            logger.warning("尝试使用download_image下载图片")
                            message["Content"] = await self.bot.download_image(aeskey, cdnmidimgurl)
                else:
                    logger.warning(f"分段下载图片失败，已下载: {len(full_image_data)}/{img_length} 字节")
                    # 如果分段下载失败，尝试使用download_image
                    if aeskey and cdnmidimgurl:
                        logger.warning("尝试使用download_image下载图片")
                        message["Content"] = await self.bot.download_image(aeskey, cdnmidimgurl)
            elif aeskey and cdnmidimgurl:
                logger.debug("使用download_image下载图片")
                message["Content"] = await self.bot.download_image(aeskey, cdnmidimgurl)
        except Exception as e:
            logger.error(f"下载图片失败: {e}")
            if aeskey and cdnmidimgurl:
                try:
                    message["Content"] = await self.bot.download_image(aeskey, cdnmidimgurl)
                except Exception as e2:
                    logger.error(f"备用方法下载图片也失败: {e2}")

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("image_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_voice_message(self, message: Dict[str, Any]):
        """处理语音消息"""
        message["Content"] = message.get("Content", {}).get("string", "").replace("\n", "").replace("\t", "")

        if message["FromWxid"].endswith("@chatroom"):
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]

                # 不更新群聊中发送者的联系人信息
                # 根据需求，只更新群聊本身信息，不更新群聊中发送者信息
            else:
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        logger.info("收到语音消息: 消息ID:{} 来自:{} 发送人:{} XML:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["SenderWxid"], message["Content"])

        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["SenderWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=message["Content"],
            is_group=message["IsGroup"]
        )

        if message["IsGroup"] or not message.get("ImgBuf", {}).get("buffer", ""):
            voiceurl, length = None, None
            try:
                root = ET.fromstring(message["Content"])
                voicemsg_element = root.find('voicemsg')
                if voicemsg_element is not None:
                    voiceurl = voicemsg_element.get('voiceurl')
                    length = int(voicemsg_element.get('length'))
            except Exception as e:
                logger.error("解析语音消息失败: {}, 内容: {}", e, message["Content"])
                return

            if voiceurl and length:
                silk_base64 = await self.bot.download_voice(message["MsgId"], voiceurl, length)
                message["Content"] = await self.bot.silk_base64_to_wav_byte(silk_base64)
        else:
            silk_base64 = message.get("ImgBuf", {}).get("buffer", "")
            message["Content"] = await self.bot.silk_base64_to_wav_byte(silk_base64)

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("voice_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_emoji_message(self, message: Dict[str, Any]):
        """处理表情消息"""
        message["Content"] = message.get("Content", {}).get("string", "").replace("\n", "").replace("\t", "")

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":\n", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["ActualUserWxid"] = split_content[0]

                # 不更新群聊中发送者的联系人信息
                # 根据需求，只更新群聊本身信息，不更新群聊中发送者信息
            else:
                message["Content"] = split_content[0]
                message["ActualUserWxid"] = self.wxid
        else:
            message["ActualUserWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        logger.info("收到表情消息: 消息ID:{} 来自:{} 发送人:{} XML:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["ActualUserWxid"], message["Content"])

        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["ActualUserWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=message["Content"],
            is_group=message["IsGroup"]
        )

        if self.ignore_check(message["FromWxid"], message["ActualUserWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("emoji_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_xml_message(self, message: Dict[str, Any]):
        """处理xml消息"""
        message["Content"] = message.get("Content", {}).get("string", "").replace("\n", "").replace("\t", "")

        if message["FromWxid"].endswith("@chatroom"):
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]

                # 不更新群聊中发送者的联系人信息
                # 根据需求，只更新群聊本身信息，不更新群聊中发送者信息
            else:
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        # 保存消息到数据库（即使解析失败也保存）
        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["SenderWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=message["Content"],
            is_group=message["IsGroup"]
        )

        try:
            root = ET.fromstring(message["Content"])
            appmsg = root.find("appmsg")
            if appmsg is None:
                logger.warning("XML 中未找到 appmsg 节点，内容: {}", message["Content"])
                return
            type_element = appmsg.find("type")
            if type_element is None:
                logger.warning("XML 中未找到 type 节点，内容: {}", message["Content"])
                return
            type_value = int(type_element.text)
            logger.debug("解析到的 XML 类型: {}, 完整内容: {}", type_value, message["Content"])
        except ET.ParseError as e:
            logger.error("解析 XML 失败: {}, 完整内容: {}", e, message["Content"])
            return
        except Exception as e:
            logger.error("处理 XML 时发生异常: {}, 完整内容: {}", e, message["Content"])
            return

        if type_value == 57:  # 引用消息
            await self.process_quote_message(message)
        elif type_value == 6:  # 文件消息
            # 先触发 xml_message 事件，再处理文件消息
            if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
                if self.ignore_protection or not protector.check(14400):
                    logger.debug("触发文件消息的 xml_message 事件: 消息ID: {}", message.get("MsgId", ""))
                    await EventManager.emit("xml_message", self.bot, message)
                else:
                    logger.warning("风控保护: 新设备登录后4小时内请挂机")

            # 然后处理文件消息
            await self.process_file_message(message)
        elif type_value == 5:  # 公众号文章或链接分享消息
            logger.info("收到链接分享消息: 消息ID:{} 来自:{} 发送人:{} XML:{}",
                        message.get("MsgId", ""), message["FromWxid"],
                        message["SenderWxid"], message["Content"])
            logger.debug("完整 XML 内容: {}", message["Content"])
            if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
                if self.ignore_protection or not protector.check(14400):
                    logger.debug("触发 article_message 事件: 消息ID: {}", message.get("MsgId", ""))
                    await EventManager.emit("article_message", self.bot, message)
                else:
                    logger.warning("风控保护: 新设备登录后4小时内请挂机")
        elif type_value == 74:  # 文件消息，但还在上传
            logger.debug("收到上传中文件消息: 消息ID:{} 来自:{}", message.get("MsgId", ""), message["FromWxid"])
        else:
            logger.info("未知的 XML 消息类型: {}, 完整内容: {}", type_value, message["Content"])

        # 触发 xml_message 事件，无论 XML 类型如何
        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                logger.debug("触发 xml_message 事件: 消息ID: {}", message.get("MsgId", ""))
                await EventManager.emit("xml_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_quote_message(self, message: Dict[str, Any]):
        """处理引用消息"""
        quote_message = {}
        try:
            root = ET.fromstring(message["Content"])
            appmsg = root.find("appmsg")
            text = appmsg.find("title").text
            refermsg = appmsg.find("refermsg")

            quote_message["MsgType"] = int(refermsg.find("type").text)

            if quote_message["MsgType"] == 1:  # 文本消息
                quote_message["NewMsgId"] = refermsg.find("svrid").text
                quote_message["ToWxid"] = refermsg.find("fromusr").text
                quote_message["FromWxid"] = refermsg.find("chatusr").text
                quote_message["Nickname"] = refermsg.find("displayname").text
                quote_message["MsgSource"] = refermsg.find("msgsource").text
                quote_message["Content"] = refermsg.find("content").text
                quote_message["Createtime"] = refermsg.find("createtime").text

            elif quote_message["MsgType"] == 49:  # 引用消息
                quote_message["NewMsgId"] = refermsg.find("svrid").text
                quote_message["ToWxid"] = refermsg.find("fromusr").text
                quote_message["FromWxid"] = refermsg.find("chatusr").text
                quote_message["Nickname"] = refermsg.find("displayname").text
                quote_message["MsgSource"] = refermsg.find("msgsource").text
                quote_message["Createtime"] = refermsg.find("createtime").text

                quote_message["Content"] = refermsg.find("content").text

                quote_root = ET.fromstring(quote_message["Content"])
                quote_appmsg = quote_root.find("appmsg")

                quote_message["Content"] = quote_appmsg.find("title").text if isinstance(quote_appmsg.find("title"), ET.Element) else ""
                quote_message["destination"] = quote_appmsg.find("des").text if isinstance(quote_appmsg.find("des"), ET.Element) else ""
                quote_message["action"] = quote_appmsg.find("action").text if isinstance(quote_appmsg.find("action"), ET.Element) else ""
                quote_message["XmlType"] = int(quote_appmsg.find("type").text) if isinstance(quote_appmsg.find("type"), ET.Element) else 0
                quote_message["showtype"] = int(quote_appmsg.find("showtype").text) if isinstance(quote_appmsg.find("showtype"), ET.Element) else 0
                quote_message["soundtype"] = int(quote_appmsg.find("soundtype").text) if isinstance(quote_appmsg.find("soundtype"), ET.Element) else 0
                quote_message["url"] = quote_appmsg.find("url").text if isinstance(quote_appmsg.find("url"), ET.Element) else ""
                quote_message["lowurl"] = quote_appmsg.find("lowurl").text if isinstance(quote_appmsg.find("lowurl"), ET.Element) else ""
                quote_message["dataurl"] = quote_appmsg.find("dataurl").text if isinstance(quote_appmsg.find("dataurl"), ET.Element) else ""
                quote_message["lowdataurl"] = quote_appmsg.find("lowdataurl").text if isinstance(quote_appmsg.find("lowdataurl"), ET.Element) else ""
                quote_message["songlyric"] = quote_appmsg.find("songlyric").text if isinstance(quote_appmsg.find("songlyric"), ET.Element) else ""
                quote_message["appattach"] = {}
                quote_message["appattach"]["totallen"] = int(quote_appmsg.find("appattach").find("totallen").text) if isinstance(quote_appmsg.find("appattach").find("totallen"), ET.Element) else 0
                quote_message["appattach"]["attachid"] = quote_appmsg.find("appattach").find("attachid").text if isinstance(quote_appmsg.find("appattach").find("attachid"), ET.Element) else ""
                quote_message["appattach"]["emoticonmd5"] = quote_appmsg.find("appattach").find("emoticonmd5").text if isinstance(quote_appmsg.find("appattach").find("emoticonmd5"), ET.Element) else ""
                quote_message["appattach"]["fileext"] = quote_appmsg.find("appattach").find("fileext").text if isinstance(quote_appmsg.find("appattach").find("fileext"), ET.Element) else ""
                quote_message["appattach"]["cdnthumbaeskey"] = quote_appmsg.find("appattach").find("cdnthumbaeskey").text if isinstance(quote_appmsg.find("appattach").find("cdnthumbaeskey"), ET.Element) else ""
                quote_message["appattach"]["aeskey"] = quote_appmsg.find("appattach").find("aeskey").text if isinstance(quote_appmsg.find("appattach").find("aeskey"), ET.Element) else ""
                quote_message["extinfo"] = quote_appmsg.find("extinfo").text if isinstance(quote_appmsg.find("extinfo"), ET.Element) else ""
                quote_message["sourceusername"] = quote_appmsg.find("sourceusername").text if isinstance(quote_appmsg.find("sourceusername"), ET.Element) else ""
                quote_message["sourcedisplayname"] = quote_appmsg.find("sourcedisplayname").text if isinstance(quote_appmsg.find("sourcedisplayname"), ET.Element) else ""
                quote_message["thumburl"] = quote_appmsg.find("thumburl").text if isinstance(quote_appmsg.find("thumburl"), ET.Element) else ""
                quote_message["md5"] = quote_appmsg.find("md5").text if isinstance(quote_appmsg.find("md5"), ET.Element) else ""
                quote_message["statextstr"] = quote_appmsg.find("statextstr").text if isinstance(quote_appmsg.find("statextstr"), ET.Element) else ""
                quote_message["directshare"] = int(quote_appmsg.find("directshare").text) if isinstance(quote_appmsg.find("directshare"), ET.Element) else 0

        except Exception as e:
            logger.error("解析引用消息失败: {}, 完整内容: {}", e, message["Content"])
            return

        message["Content"] = text
        message["Quote"] = quote_message

        logger.info("收到引用消息: 消息ID:{} 来自:{} 发送人:{} 内容:{} 引用:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["SenderWxid"], message["Content"], message["Quote"])

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("quote_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_video_message(self, message):
        message["Content"] = message.get("Content", {}).get("string", "")

        if message["FromWxid"].endswith("@chatroom"):
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]

                # 不更新群聊中发送者的联系人信息
                # 根据需求，只更新群聊本身信息，不更新群聊中发送者信息
            else:
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        logger.info("收到视频消息: 消息ID:{} 来自:{} 发送人:{} XML:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["SenderWxid"], message["Content"])

        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["SenderWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=message["Content"],
            is_group=message["IsGroup"]
        )

        message["Video"] = await self.bot.download_video(message.get("MsgId", 0))

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("video_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_file_message(self, message: Dict[str, Any]):
        """处理文件消息"""
        try:
            root = ET.fromstring(message["Content"])
            filename = root.find("appmsg").find("title").text
            attach_id = root.find("appmsg").find("appattach").find("attachid").text
            file_extend = root.find("appmsg").find("appattach").find("fileext").text
        except Exception as e:
            logger.error("解析文件消息失败: {}, 内容: {}", e, message["Content"])
            return

        message["Filename"] = filename
        message["FileExtend"] = file_extend

        logger.info("收到文件消息: 消息ID:{} 来自:{} 发送人:{} XML:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["SenderWxid"], message["Content"])

        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["SenderWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=message["Content"],
            is_group=message["IsGroup"]
        )

        message["File"] = await self.bot.download_attach(attach_id)

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("file_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_system_message(self, message: Dict[str, Any]):
        """处理系统消息"""
        message["Content"] = message.get("Content", {}).get("string", "")

        if message["FromWxid"].endswith("@chatroom"):
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]

                # 不更新群聊中发送者的联系人信息
                # 根据需求，只更新群聊本身信息，不更新群聊中发送者信息
            else:
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        try:
            root = ET.fromstring(message["Content"])
            msg_type = root.attrib["type"]
        except Exception as e:
            logger.error("解析系统消息失败: {}, 内容: {}", e, message["Content"])
            return

        if msg_type == "pat":
            await self.process_pat_message(message)
        elif msg_type == "ClientCheckGetExtInfo":
            pass
        else:
            logger.info("收到系统消息: {}, 完整内容: {}", message, message["Content"])
            if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
                if self.ignore_protection or not protector.check(14400):
                    await EventManager.emit("system_message", self.bot, message)
                else:
                    logger.warning("风控保护: 新设备登录后4小时内请挂机")

    async def process_pat_message(self, message: Dict[str, Any]):
        """处理拍一拍请求消息"""
        try:
            root = ET.fromstring(message["Content"])
            pat = root.find("pat")
            patter = pat.find("fromusername").text
            patted = pat.find("pattedusername").text
            pat_suffix = pat.find("patsuffix").text
        except Exception as e:
            logger.error("解析拍一拍消息失败: {}, 内容: {}", e, message["Content"])
            return

        message["Patter"] = patter
        message["Patted"] = patted
        message["PatSuffix"] = pat_suffix

        logger.info("收到拍一拍消息: 消息ID:{} 来自:{} 发送人:{} 拍者:{} 被拍:{} 后缀:{}",
                    message.get("MsgId", ""), message["FromWxid"],
                    message["SenderWxid"], message["Patter"],
                    message["Patted"], message["PatSuffix"])

        await self.msg_db.save_message(
            msg_id=int(message.get("MsgId", 0)),
            sender_wxid=message["SenderWxid"],
            from_wxid=message["FromWxid"],
            msg_type=int(message.get("MsgType", 0)),
            content=f"{message['Patter']} 拍了拍 {message['Patted']} {message['PatSuffix']}",
            is_group=message["IsGroup"]
        )

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            if self.ignore_protection or not protector.check(14400):
                await EventManager.emit("pat_message", self.bot, message)
            else:
                logger.warning("风控保护: 新设备登录后4小时内请挂机")

    def ignore_check(self, FromWxid: str, SenderWxid: str):
        # 过滤公众号消息（公众号wxid通常以gh_开头）
        if SenderWxid and isinstance(SenderWxid, str) and SenderWxid.startswith('gh_'):
            logger.debug(f"忽略公众号消息: {SenderWxid}")
            return False
        if FromWxid and isinstance(FromWxid, str) and FromWxid.startswith('gh_'):
            logger.debug(f"忽略公众号消息: {FromWxid}")
            return False

        # 过滤微信团队和系统通知
        system_accounts = [
            'weixin', # 微信团队
            'filehelper', # 文件传输助手
            'fmessage', # 朋友推荐通知
            'medianote', # 语音记事本
            'floatbottle', # 漂流瓶
            'qmessage', # QQ离线消息
            'qqmail', # QQ邮箱提醒
            'tmessage', # 腾讯新闻
            'weibo', # 微博推送
            'newsapp', # 新闻推送
            'notification_messages', # 服务通知
            'helper_entry', # 新版微信运动
            'mphelper', # 公众号助手
            'brandsessionholder', # 公众号消息
            'weixinreminder', # 微信提醒
            'officialaccounts', # 公众平台
        ]

        # 检查是否是系统账号
        for account in system_accounts:
            if (SenderWxid and isinstance(SenderWxid, str) and SenderWxid == account) or \
               (FromWxid and isinstance(FromWxid, str) and FromWxid == account):
                logger.debug(f"忽略系统账号消息: {SenderWxid or FromWxid}")
                return False

        # 检测其他特殊账号特征
        # 微信支付相关通知
        if (SenderWxid and isinstance(SenderWxid, str) and 'wxpay' in SenderWxid) or \
           (FromWxid and isinstance(FromWxid, str) and 'wxpay' in FromWxid):
            logger.debug(f"忽略微信支付相关消息: {SenderWxid or FromWxid}")
            return False

        # 腾讯游戏相关通知
        if (SenderWxid and isinstance(SenderWxid, str) and ('tencent' in SenderWxid.lower() or 'game' in SenderWxid.lower())) or \
           (FromWxid and isinstance(FromWxid, str) and ('tencent' in FromWxid.lower() or 'game' in FromWxid.lower())):
            logger.debug(f"忽略腾讯游戏相关消息: {SenderWxid or FromWxid}")
            return False

        # 其他特殊账号特征
        # 微信官方账号通常包含"service"或"official"
        if (SenderWxid and isinstance(SenderWxid, str) and ('service' in SenderWxid.lower() or 'official' in SenderWxid.lower())) or \
           (FromWxid and isinstance(FromWxid, str) and ('service' in FromWxid.lower() or 'official' in FromWxid.lower())):
            logger.debug(f"忽略官方服务账号消息: {SenderWxid or FromWxid}")
            return False

        # 先检查是否是群聊消息
        is_group = FromWxid and isinstance(FromWxid, str) and FromWxid.endswith("@chatroom")

        if self.ignore_mode == "Whitelist":
            if is_group:
                # 群聊消息：有两种情况
                # 1. 群聊ID在白名单中（处理该群中的所有消息）
                # 2. 发送者ID在白名单中（无论群聊ID是否在白名单中）

                # 当发送者ID在白名单中，或者群聊ID在白名单中时，才处理消息
                # 修改逻辑，允许处理白名单群聊中的所有消息，而不仅仅是机器人自己发送的消息
                logger.debug(f"白名单检查: 群聊ID={FromWxid}, 发送者ID={SenderWxid}, 群聊ID在白名单中={FromWxid in self.whitelist}, 发送者ID在白名单中={SenderWxid in self.whitelist}")
                return SenderWxid in self.whitelist or FromWxid in self.whitelist
            else:
                # 私聊消息：发送者ID在白名单中
                return SenderWxid in self.whitelist
        elif self.ignore_mode == "Blacklist":
            if is_group:
                # 群聊消息：群聊ID不在黑名单中且发送者ID不在黑名单中
                return (FromWxid not in self.blacklist) and (SenderWxid not in self.blacklist)
            else:
                # 私聊消息：发送者ID不在黑名单中
                return SenderWxid not in self.blacklist
        else:
            # 默认处理所有消息
            return True

    # 朋友圈相关方法
    async def get_friend_circle_list(self, max_id: int = 0) -> dict:
        """获取自己的朋友圈列表

        Args:
            max_id: 朋友圈ID，用于分页获取

        Returns:
            dict: 朋友圈数据
        """
        return await self.bot.get_pyq_list(self.wxid, max_id)

    async def get_user_friend_circle(self, wxid: str, max_id: int = 0) -> dict:
        """获取特定用户的朋友圈

        Args:
            wxid: 用户wxid
            max_id: 朋友圈ID，用于分页获取

        Returns:
            dict: 朋友圈数据
        """
        return await self.bot.get_pyq_detail(wxid=self.wxid, Towxid=wxid, max_id=max_id)

    async def like_friend_circle(self, id: str) -> dict:
        """点赞朋友圈

        Args:
            id: 朋友圈ID

        Returns:
            dict: 点赞结果
        """
        return await self.bot.put_pyq_comment(wxid=self.wxid, id=id, type=1)

    async def comment_friend_circle(self, id: str, content: str) -> dict:
        """评论朋友圈

        Args:
            id: 朋友圈ID
            content: 评论内容

        Returns:
            dict: 评论结果
        """
        return await self.bot.put_pyq_comment(wxid=self.wxid, id=id, Content=content, type=2)