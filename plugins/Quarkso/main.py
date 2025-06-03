import tomllib
import os
import asyncio
import aiohttp
from loguru import logger

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase
from database.XYBotDB import XYBotDB

from .quark import QURAK
from concurrent.futures import ThreadPoolExecutor
from typing import List, Any
import time
import logging
from datetime import datetime


class Quarkso(PluginBase):
    description = "夸克资源搜索"
    author = "BEelzebub"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        try:
            logger.info("[Quarkso] 初始化插件...")
            
            # 读取主配置
            main_config_path = "main_config.toml"
            if not os.path.exists(main_config_path):
                logger.error(f"[Quarkso] 主配置文件不存在: {main_config_path}")
                raise FileNotFoundError(f"主配置文件不存在: {main_config_path}")
                
            with open(main_config_path, "rb") as f:
                config = tomllib.load(f)
            
            if "XYBot" not in config or "admins" not in config["XYBot"]:
                logger.error("[Quarkso] 主配置文件中缺少 XYBot.admins 配置")
                self.admins = []
            else:
                self.admins = config["XYBot"]["admins"]
            
            # 读取插件配置
            plugin_config_path = "plugins/Quarkso/config.toml"
            if not os.path.exists(plugin_config_path):
                logger.error(f"[Quarkso] 插件配置文件不存在: {plugin_config_path}")
                raise FileNotFoundError(f"插件配置文件不存在: {plugin_config_path}")
                
            with open(plugin_config_path, "rb") as f:
                plugin_config = tomllib.load(f)
            
            if "Quarkso" not in plugin_config:
                logger.error("[Quarkso] 插件配置文件中缺少 Quarkso 配置")
                raise KeyError("插件配置文件中缺少 Quarkso 配置")
                
            config = plugin_config["Quarkso"]
            self.enable = config.get("enable", True)
            filtered_commandAll = [item for item in config.get("commandAll", []) if item and item.strip()]
            self.command = config.get("command", ["外部搜索"]) + filtered_commandAll
            self.commandAll = 1 if filtered_commandAll else 0
            self.command_format = config.get("command-format", "搜索指令：\n外部搜索+资源名称")
            
            self.price = config.get("price", 0)
            self.admin_ignore = config.get("admin_ignore", False)
            self.whitelist_ignore = config.get("whitelist_ignore", False)
            self.default_type = config.get("default_type", "QUARK")  # 新增默认资源类型配置
            
            try:
                self.db = XYBotDB()
            except Exception as e:
                logger.error(f"[Quarkso] 数据库初始化失败: {e}")
                self.db = None
                
            logger.info(f"[Quarkso] 插件初始化完成, 命令列表: {self.command}")
        except Exception as e:
            logger.error(f"[Quarkso] 插件初始化异常: {e}")
            # 设置默认值，确保不会完全崩溃
            self.enable = False
            self.command = []
            self.commandAll = 0
            self.command_format = ""
            self.price = 0
            self.admin_ignore = False
            self.whitelist_ignore = False
            self.db = None
            self.admins = []

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        try:
            if not self.enable:
                return
                
            content = str(message["Content"]).strip()
            logger.debug(f"[Quarkso] 收到消息: {content}")
            
            # 按命令长度从长到短排序
            self.command.sort(key=len, reverse=True)
            
            # 检查消息是否以 command 中的任意一个开头
            matched_command = None
            for cmd in self.command:
                if content.startswith(cmd):
                    matched_command = cmd
                    break
            
            # 如果不以 command 中的任意一个开头，直接 return
            if not matched_command:
                return
                
            logger.info(f"[Quarkso] 匹配到命令: {matched_command}")
            
            # 去掉开头的命令字符
            processed_content = content[len(matched_command):].strip()
            
            # 确定搜索类型
            search_type = "QUARK"  # 默认夸克
            if "百度云搜索" in matched_command:
                search_type = "BDY"
            elif "夸克搜索" in matched_command:
                search_type = "QUARK"
            else:
                search_type = self.default_type
                
            logger.info(f"[Quarkso] 搜索类型: {search_type}")
            
            # 如果 processed_content 为空，直接 return
            if not processed_content:
                await bot.send_at_message(message["FromWxid"], f"\n{self.command_format}", [message["SenderWxid"]])
                return
            
            if await self._check_point(bot, message):
                await bot.send_text_message(message["FromWxid"], f"正在搜索，请稍等...", [message["SenderWxid"]])
                response_data = self.merge_qry_data(processed_content, search_type)
                await self.send_final_reply(bot, message, response_data, search_type)
        except Exception as e:
            logger.error(f"[Quarkso] 处理消息异常: {e}")
            try:
                await bot.send_at_message(message["FromWxid"], f"\n处理请求时出现错误，请稍后再试。", [message["SenderWxid"]])
            except Exception as send_err:
                logger.error(f"[Quarkso] 发送错误消息失败: {send_err}")

    async def send_final_reply(self, bot: WechatAPIClient, message: dict, response_text: str, search_type="QUARK"):
        try:
            search_type_text = "百度云" if search_type == "BDY" else "夸克"
            
            if not response_text or response_text == f'【{message["Content"].strip()}】{search_type_text}资源搜索结果：\n':
                reply_text_final = f"未找到，可换个关键词尝试哦~"
                reply_text_final += "\n⚠️宁少写，不多写、错写~"

                if self.db is not None and not (message["SenderWxid"] in self.admins and self.admin_ignore):
                    try:
                        is_whitelist = self.db.get_whitelist(message["SenderWxid"]) and self.whitelist_ignore
                        if not is_whitelist:
                            self.db.add_points(message["SenderWxid"], self.price)
                    except Exception as e:
                        logger.error(f"[Quarkso] 补偿积分异常: {e}")
            else:
                reply_text_final = response_text
                reply_text_final += "\n\n欢迎使用！如果喜欢可以喊你的朋友一起来哦"

            await bot.send_at_message(message["FromWxid"], "\n" + reply_text_final, [message["SenderWxid"]])
            logger.info(f"[Quarkso] 发送搜索结果成功")
        except Exception as e:
            logger.error(f"[Quarkso] 发送搜索结果异常: {e}")
            try:
                # 尝试发送简单的消息
                await bot.send_text_message(message["FromWxid"], "抱歉，在发送搜索结果时遇到问题。", [message["SenderWxid"]])
            except Exception as send_err:
                logger.error(f"[Quarkso] 发送错误消息失败: {send_err}")

    def merge_qry_data(self, qry_key: str, search_type="QUARK"):
        try:
            def fetch_data(method_name: str, qry_key: str, search_type="QUARK") -> Any:
                try:
                    quark = QURAK()
                    method = getattr(quark, method_name, None)
                    if method is not None:
                        # 如果是瓦力搜索方法，传入搜索类型参数
                        if method_name in ["get_waliso_search", "get_qry_external_4"]:
                            return method(qry_key, search_type)
                        # 如果搜索百度云且有对应方法，使用百度云搜索方法
                        elif search_type == "BDY" and method_name == "get_baidu_search":
                            return method(qry_key)
                        # 如果搜索夸克，使用夸克相关方法
                        elif search_type == "QUARK":
                            return method(qry_key)
                        return None
                    return None
                except Exception as e:
                    logger.error(f"[Quarkso] 执行方法 {method_name} 异常: {e}")
                    return None

            logger.info(f'[Quarkso] 查询关键字: {qry_key}, 搜索类型: {search_type}')
            
            search_type_text = "百度云" if search_type == "BDY" else "夸克"
            msg = f'【{qry_key}】{search_type_text}资源搜索结果：\n'
            start_time = time.time()

            # 首先尝试使用瓦力搜索
            try:
                logger.info(f'[Quarkso] 尝试使用瓦力搜索，类型: {search_type}...')
                quark = QURAK()
                
                if search_type == "BDY":
                    waliso_results = quark.get_baidu_search(qry_key)
                else:
                    waliso_results = quark.get_waliso_search(qry_key)
                
                # 如果瓦力搜索找到了结果，直接返回
                if waliso_results and len(waliso_results) > 0:
                    logger.info(f'[Quarkso] 瓦力搜索成功，找到 {len(waliso_results)} 个结果')
                    
                    # 构建返回消息
                    i = 1
                    for item in waliso_results:
                        if i > 5:
                            break
                        item['sno'] = i
                        msg += '========== \n'
                        title = item.get('title', '未知标题')
                        url = item.get('url', '')
                        msg += f"{i}.{title}\n{url}\n"
                        i += 1
                        
                    end_time = time.time()
                    execution_time = end_time - start_time
                    logger.info(f"[Quarkso] 瓦力搜索耗时: {execution_time:.6f} seconds")
                    return msg
                
                logger.info(f'[Quarkso] 瓦力搜索未找到结果，尝试其他来源...')
            except Exception as e:
                logger.error(f'[Quarkso] 瓦力搜索异常: {e}')
            
            # 百度云搜索只使用瓦力搜索，如果未找到结果则直接返回
            if search_type == "BDY":
                end_time = time.time()
                execution_time = end_time - start_time
                logger.info(f"[Quarkso] 百度云搜索耗时: {execution_time:.6f} seconds")
                return msg
            
            # 如果是夸克搜索且瓦力搜索失败或未找到结果，尝试使用其他搜索源
            try:
                with ThreadPoolExecutor() as executor:
                    futures = [
                        executor.submit(fetch_data, method_name, qry_key)
                        for method_name in [
                            'qry_kkkob',
                            'get_qry_external',
                            'get_qry_external_2',
                            'get_qry_external_3',
                            'get_qry_external_5'
                        ]
                    ]

                # 使用列表推导式来获取每个 Future 的结果
                seen_url = set()
                # 创建一个新的列表来存储去重后的数据
                unique_data = []

                i = 1
                # 遍历合并后的数据，按链接去重
                for future in futures:
                    future_data = future.result()
                    if future_data is not None:
                        for item in future_data:
                            if i > 5:
                                break
                            if 'url' not in item:
                                logger.warning(f"[Quarkso] 数据项缺少 url 字段: {item}")
                                continue
                                
                            url = item['url']
                            if not url:
                                continue
                                
                            if url not in seen_url:
                                item['sno'] = i
                                seen_url.add(url)
                                unique_data.append(item)

                                msg += '========== \n'
                                title = item.get('title', '未知标题')
                                msg += f"{item['sno']}.{title}\n{url}\n"

                                i += 1
            except Exception as e:
                logger.error(f"[Quarkso] 合并查询结果异常: {e}")
                
            end_time = time.time()
            execution_time = end_time - start_time
            logger.info(f"[Quarkso] 查询执行耗时: {execution_time:.6f} seconds")
            
            if i > 1:  # 表示找到了结果
                logger.info(f"[Quarkso] 查询找到 {i-1} 个结果")
                return msg
            else:
                logger.info(f"[Quarkso] 未找到搜索结果")
                return ""
        except Exception as e:
            logger.error(f"[Quarkso] merge_qry_data 方法异常: {e}")
            return ""

    async def _check_point(self, bot: WechatAPIClient, message: dict) -> bool:
        try:
            wxid = message["SenderWxid"]
            
            # 如果数据库未初始化，直接返回True
            if self.db is None:
                logger.warning("[Quarkso] 数据库未初始化，跳过积分检查")
                return True
                
            # 管理员检查
            if wxid in self.admins and self.admin_ignore:
                return True
                
            # 白名单检查
            try:
                is_whitelist = self.db.get_whitelist(wxid) and self.whitelist_ignore
                if is_whitelist:
                    return True
            except Exception as e:
                logger.error(f"[Quarkso] 检查白名单异常: {e}")
                # 遇到白名单检查错误时，继续检查积分
            
            # 价格为0时直接返回True
            if self.price <= 0:
                return True
                
            # 积分检查
            try:
                user_points = self.db.get_points(wxid)
                if user_points < self.price:
                    await bot.send_at_message(message["FromWxid"], f"😭你的积分不够啦！需要 {self.price} 积分", [wxid])
                    await bot.send_text_message(message["FromWxid"], "你可以通过签到获取积分哦。", [wxid])
                    return False
                    
                # 扣除积分
                self.db.add_points(wxid, -self.price)
                return True
            except Exception as e:
                logger.error(f"[Quarkso] 检查或扣除积分异常: {e}")
                # 遇到积分检查错误时，为用户提供便利，返回True
                return True
        except Exception as e:
            logger.error(f"[Quarkso] _check_point 方法异常: {e}")
            return True  # 出现异常时，默认允许使用 