# -*- coding: utf-8 -*-
import json
import os
import time
import aiohttp
from loguru import logger
import asyncio
import requests
import toml

# 改为使用TOML配置文件
CONFIG_FILE = 'config.toml'

class LoginHandler:
    def __init__(self, config):
        try:
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
            self.config = config
            self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
            self._plugin = None
            # 移除httpx客户端
            # self.client = httpx.Client(http2=True, timeout=30.0)
            self.http_session = None  # 将由主插件设置
            self._last_token_refresh = 0
        except Exception as e:
            logger.error(f"[Yuewen] LoginHandler初始化失败: {str(e)}")
            raise e

    def set_http_session(self, session):
        """设置HTTP会话"""
        self.http_session = session

    def save_config(self):
        """保存配置到文件"""
        try:
            # 如果有插件实例引用，使用插件的update_config方法保存配置
            if self._plugin is not None and hasattr(self._plugin, 'update_config'):
                logger.info(f"[Yuewen] LoginHandler保存配置到: {os.path.join(os.path.dirname(__file__), CONFIG_FILE)}")
                return self._plugin.update_config(self.config)
            
            # 直接保存方式：使用TOML格式
            config_file_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE)
            
            # 最多尝试3次保存
            for attempt in range(3):
                try:
                    # 确保目录存在
                    os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
                    
                    # 先保存到临时文件，然后重命名，避免文件被部分写入
                    temp_file_path = f"{config_file_path}.tmp"
                    
                    # 构建TOML格式（嵌套结构）
                    toml_config = {"yuewen": {k: v for k, v in self.config.items() if k != "image_config"}}
                    
                    # 添加image_config子项
                    if "image_config" in self.config:
                        toml_config["yuewen"]["image_config"] = self.config.get("image_config", {})
                    
                    # 保存到临时TOML文件
                    with open(temp_file_path, "w", encoding="utf-8") as f:
                        toml.dump(toml_config, f)
                    
                    # 如果文件已存在，先尝试备份
                    if os.path.exists(config_file_path):
                        backup_path = f"{config_file_path}.bak"
                        try:
                            if os.path.exists(backup_path):
                                os.remove(backup_path)
                            os.rename(config_file_path, backup_path)
                        except Exception as e:
                            logger.warning(f"[Yuewen] 创建配置备份失败 (非致命): {e}")
                    
                    # 重命名临时文件为正式文件
                    os.rename(temp_file_path, config_file_path)
                    
                    logger.info(f"[Yuewen] 配置已保存到TOML文件: {config_file_path}")
                    logger.debug(f"[Yuewen] 配置已更新: {list(self.config.keys())}")
                    return True
                    
                except PermissionError as pe:
                    # 文件可能被另一个进程锁定
                    if attempt < 2:  # 只在前两次尝试时记录警告
                        logger.warning(f"[Yuewen] 保存配置时遇到权限错误 (尝试 {attempt+1}/3): {pe}")
                        time.sleep(0.2 * (attempt + 1))  # 递增延迟
                    else:
                        logger.error(f"[Yuewen] 保存配置权限错误，已达最大重试次数: {pe}")
                        return False
                        
                except Exception as inner_e:
                    # 其他异常，记录错误并继续尝试
                    if attempt < 2:
                        logger.warning(f"[Yuewen] 保存TOML配置失败 (尝试 {attempt+1}/3): {inner_e}")
                        time.sleep(0.1 * (attempt + 1))
                    else:
                        logger.error(f"[Yuewen] 保存TOML配置失败，已达最大重试次数: {inner_e}")
                        return False
            
            return False  # 如果所有尝试都失败
                
        except Exception as e:
            logger.error(f"[Yuewen] LoginHandler保存配置失败: {e}")
            return False

    async def register_device(self):
        """注册设备获取初始 token（异步版本）"""
        try:
            # 确保会话已设置
            if not self.http_session:
                logger.error("[Yuewen] HTTP会话未设置")
                return False
                
            # 使用硬编码的URL，不使用动态URL以确保与原代码完全一致
            url = 'https://yuewen.cn/passport/proto.api.passport.v1.PassportService/RegisterDevice'
            
            # 复制原始代码的header设置，确保完全一致
            headers = self.base_headers.copy()
            headers.update({
                'Content-Type': 'application/json',
                'oasis-mode': '1',
                'oasis-webid': '8e2223012fadbac04d9cc1fcdc1d8b4eb8cc75a9',
                'oasis-appid': '10200',
                'oasis-platform': 'web',
                'origin': 'https://yuewen.cn',
                'referer': 'https://yuewen.cn/',
                'connect-protocol-version': '1',
                'x-waf-client-type': 'fetch_sdk'
            })
            
            # 发送异步请求
            async with self.http_session.post(url, headers=headers, json={}) as response:
                if response.status == 200:
                    data = await response.json()
                    self.config.update({
                        'oasis_webid': data['device']['deviceID'],
                        'oasis_token': f"{data['accessToken']['raw']}...{data['refreshToken']['raw']}"
                    })
                    self.save_config()
                    logger.info(f"[Yuewen] 设备注册成功: {self.config['oasis_webid']}")
                    return True
                
                error_text = await response.text()
                logger.error(f"[Yuewen] 设备注册失败: HTTP {response.status}, {error_text}")
                return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 设备注册异常: {e}")
            return False

    async def send_sms(self, phone_number):
        """发送验证码短信（异步版本）
        @param phone_number: 手机号
        @return: 成功返回True，失败返回False
        """
        try:
            if not self.http_session:
                logger.error("[Yuewen] HTTP会话未设置")
                return False
                
            # 使用旧项目代码中完全一样的URL和数据结构
            url = 'https://yuewen.cn/passport/proto.api.passport.v1.PassportService/SendVerifyCode'
            
            # 构建完整的请求头 - 与register_device保持一致
            headers = self.base_headers.copy()
            headers.update({
                'Content-Type': 'application/json',
                'oasis-mode': '1',
                'oasis-webid': self.config['oasis_webid'],
                'oasis-appid': '10200',
                'oasis-platform': 'web',
                'origin': 'https://yuewen.cn',
                'referer': 'https://yuewen.cn/',
                'connect-protocol-version': '1',
                'x-waf-client-type': 'fetch_sdk'
            })
            
            # 构造完整的Cookie字符串，包含在请求头中
            cookie_str = f"Oasis-Webid={self.config['oasis_webid']}"
            if self.config.get('oasis_token'):
                token = self.config['oasis_token'].split('...')[0] if '...' in self.config['oasis_token'] else self.config['oasis_token']
                cookie_str += f"; Oasis-Token={token}"
            headers['Cookie'] = cookie_str
            
            # 使用旧项目代码一样的请求体结构
            data = {'mobileCc': '86', 'mobileNum': phone_number}
            
            # 发送异步请求
            async with self.http_session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    logger.info(f"[Yuewen] 验证码发送成功: {phone_number}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"[Yuewen] 验证码发送失败: {response.status}, {error_text}")
                    return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 发送验证码异常: {e}")
            return False
            
    # 保留send_verify_code方法作为兼容性别名
    async def send_verify_code(self, mobile_num):
        """旧项目代码兼容方法（异步版本）"""
        return await self.send_sms(mobile_num)

    async def sign_in(self, mobile_num, auth_code):
        """登录进行验证（异步版本）
        @param mobile_num: 手机号
        @param auth_code: 验证码
        @return: 成功返回True，失败返回False
        """
        try:
            if not self.http_session:
                logger.error("[Yuewen] HTTP会话未设置")
                return False
                
            # 使用旧项目代码中完全一样的URL和数据结构
            url = 'https://yuewen.cn/passport/proto.api.passport.v1.PassportService/SignIn'
            
            # 构建完整的请求头 - 与register_device和send_sms保持一致
            headers = self.base_headers.copy()
            headers.update({
                'Content-Type': 'application/json',
                'oasis-mode': '1',
                'oasis-webid': self.config['oasis_webid'],
                'oasis-appid': '10200',
                'oasis-platform': 'web',
                'origin': 'https://yuewen.cn',
                'referer': 'https://yuewen.cn/',
                'connect-protocol-version': '1',
                'x-waf-client-type': 'fetch_sdk'
            })
            
            # 构造完整的Cookie字符串，包含在请求头中
            cookie_str = f"Oasis-Webid={self.config['oasis_webid']}"
            if self.config.get('oasis_token'):
                token = self.config['oasis_token'].split('...')[0] if '...' in self.config['oasis_token'] else self.config['oasis_token']
                cookie_str += f"; Oasis-Token={token}"
            headers['Cookie'] = cookie_str
            
            data = {
                'authCode': auth_code,
                'mobileCc': '86',
                'mobileNum': mobile_num
            }
            
            async with self.http_session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    data = await response.json()
                    # 确保按照原始实现的方式构造token字符串
                    # 原始方式: f"{data['accessToken']['raw']}...{data['refreshToken']['raw']}"
                    if 'accessToken' in data and 'refreshToken' in data:
                        access_token = data['accessToken'].get('raw')
                        refresh_token = data['refreshToken'].get('raw')
                        
                        if access_token and refresh_token:
                            # 使用...作为分隔符连接accessToken和refreshToken
                            self.config['oasis_token'] = f"{access_token}...{refresh_token}"
                            self.config['need_login'] = False
                            self.save_config()
                            logger.info(f"[Yuewen] 登录验证成功: {mobile_num}")
                            return True
                        else:
                            logger.error(f"[Yuewen] 登录验证失败: 响应中缺少token字段值")
                            return False
                    else:
                        logger.error(f"[Yuewen] 登录验证失败: 响应中缺少token字段 - {data}")
                        return False
                else:
                    error_text = await response.text()
                    logger.error(f"[Yuewen] 登录验证失败: {response.status}, {error_text}")
                    return False
                
        except Exception as e:
            logger.error(f"[Yuewen] 登录验证异常: {e}")
            return False

    async def verify_login(self, mobile_num, verify_code):
        """验证码登录（sign_in的异步别名）"""
        return await self.sign_in(mobile_num, verify_code)

    async def refresh_token(self, force=False):
        """刷新令牌 (更新oasis_token)（异步版本）
        
        Args:
            force (bool, optional): 是否强制刷新令牌，忽略刷新频率限制。默认为False。
            
        Returns:
            bool: 刷新成功返回True，失败返回False
        """
        # 限制刷新频率，除非强制刷新
        current_time = time.time()
        if not force and hasattr(self, '_last_token_refresh') and current_time - self._last_token_refresh < 60:
            logger.warning("[Yuewen] Token刷新太频繁，跳过")
            # 虽然跳过，但如果已经有token，认为token仍有效
            return bool(self.config.get('oasis_token'))
        
        if force:
            logger.info("[Yuewen] 强制刷新令牌，忽略刷新频率限制")

        # 检查webid是否存在
        if not self.config.get('oasis_webid'):
            logger.error("[Yuewen] webid不存在，无法刷新令牌")
            return False

        # 开始刷新令牌流程
        logger.debug("[Yuewen] 开始刷新令牌")
        
        # 确定当前使用的API版本
        current_api_version = self.config.get('api_version', 'old')
        
        # 与原始项目保持一致的URL
        refresh_url = 'https://yuewen.cn/passport/proto.api.passport.v1.PassportService/RefreshToken'
        
        # 如果是新版API，则使用新版的域名
        if current_api_version == 'new':
            refresh_url = 'https://www.stepfun.com/passport/proto.api.passport.v1.PassportService/RefreshToken'
        
        logger.debug(f"[Yuewen] 刷新令牌URL: {refresh_url}")

        # 完全按照curl命令构建请求头
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            'Origin': 'https://www.stepfun.com',
            'Referer': 'https://www.stepfun.com/chats/new',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
            'connect-protocol-version': '1',
            'content-type': 'application/json',
            'oasis-appid': '10200',
            'oasis-language': 'zh',
            'oasis-platform': 'web',
            'priority': 'u=1, i',
            'sec-ch-ua': '"Chromium";v="136", "Microsoft Edge";v="136", "Not.A/Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'x-waf-client-type': 'fetch_sdk'
        }

        # 设置Cookie - 使用完全符合curl示例的格式
        cookies = {}
        
        # 添加webid
        if self.config.get('oasis_webid'):
            cookies['Oasis-Webid'] = self.config.get('oasis_webid')
        
        # 添加token (使用原始完整的复合token，不分割)
        if self.config.get('oasis_token'):
            # 使用完整token，不分割
            token = self.config.get('oasis_token', '')
            cookies['Oasis-Token'] = token
            logger.debug(f"[Yuewen] 使用完整令牌，长度: {len(token)}")
        
        # 添加curl命令中的其他Cookie
        cookies['i18next'] = 'zh'
        cookies['_tea_utm_cache_20002086'] = '{%22utm_source%22:%22share%22%2C%22utm_content%22:%22web_image_share%22}'
        cookies['sidebar_state'] = 'false'
        
        # 构建请求体 - 与curl命令一致的空对象
        payload = {}
        
        # 准备开始发送请求，详细记录信息
        logger.debug(f"[Yuewen] 刷新令牌请求URL: {refresh_url}")
        logger.debug(f"[Yuewen] 刷新令牌请求Cookie: {list(cookies.keys())}")
        
        # 发送请求
        try:
            # 确保存在HTTP会话
            if not self.http_session:
                logger.error("[Yuewen] HTTP会话未初始化，无法刷新令牌")
                return False
                
            # 尝试使用requests库发送请求
            try:
                import requests
                
                # 转换headers和cookies为requests格式
                req_headers = dict(headers)
                req_cookies = dict(cookies)
                
                logger.debug("[Yuewen] 使用requests库刷新令牌")
                
                # 同步发送请求
                response = requests.post(
                    refresh_url,
                    headers=req_headers,
                    cookies=req_cookies,
                    json=payload,
                    timeout=30
                )
                
                response_status = response.status_code
                logger.debug(f"[Yuewen] 刷新令牌响应状态: {response_status}")
                
                if response_status == 200:
                    try:
                        # 获取完整响应
                        response_text = response.text
                        logger.debug(f"[Yuewen] 令牌刷新原始响应: {response_text[:200]}...")
                        
                        # 解析响应JSON
                        data = json.loads(response_text)
                        
                        # 按照curl命令响应格式提取token
                        access_token = data.get('accessToken', {}).get('raw')
                        refresh_token = data.get('refreshToken', {}).get('raw')
                        
                        # 添加详细日志
                        if access_token:
                            logger.debug(f"[Yuewen] 获取到新的访问令牌，长度: {len(access_token)}")
                        else:
                            logger.error("[Yuewen] 响应中未找到访问令牌")
                            
                        if refresh_token:
                            logger.debug(f"[Yuewen] 获取到新的刷新令牌，长度: {len(refresh_token)}")
                        else:
                            logger.error("[Yuewen] 响应中未找到刷新令牌")
                        
                        if access_token and refresh_token:
                            # 按照原始项目格式构造token
                            token_value = f"{access_token}...{refresh_token}"
                            
                            # 临时保存旧token，以便在保存失败时恢复
                            old_token = self.config.get('oasis_token')
                            
                            # 更新config
                            self.config['oasis_token'] = token_value
                            self.config['need_login'] = False
                            
                            # 记录刷新时间
                            self._last_token_refresh = current_time
                            
                            # 保存到配置前先验证数据
                            try:
                                # 确保token存在且格式正确
                                if not isinstance(token_value, str) or not token_value:
                                    logger.error("[Yuewen] 刷新令牌后token无效，恢复旧token")
                                    self.config['oasis_token'] = old_token
                                    return False
                                
                                # 保存配置
                                saved = self.save_config()
                                if not saved:
                                    logger.warning("[Yuewen] 令牌刷新后保存配置失败")
                                    # 尝试第二次保存
                                    time.sleep(0.5)  # 短暂延迟
                                    saved = self.save_config()
                                    if not saved:
                                        logger.error("[Yuewen] 令牌刷新后第二次保存仍然失败")
                                        
                                logger.info("[Yuewen] ✅ 令牌刷新成功，已保存新令牌")
                                return True
                            except Exception as cfg_e:
                                logger.error(f"[Yuewen] 刷新令牌后保存配置异常: {cfg_e}")
                                # 即使保存失败，我们仍然有内存中的令牌
                                logger.debug("[Yuewen] 令牌刷新成功，但配置保存失败")
                                return True
                        else:
                            logger.error("[Yuewen] 令牌刷新失败: 响应中未找到完整令牌")
                            return False
                    except Exception as parse_err:
                        logger.error(f"[Yuewen] 令牌刷新处理响应异常: {parse_err}")
                        return False
                
                # 处理错误情况
                error_text = response.text
                logger.debug(f"[Yuewen] 刷新令牌错误响应: {error_text[:200]}...")
                logger.error(f"[Yuewen] 令牌刷新失败: HTTP {response_status}")
                
                # 判断是否需要重新登录
                if response_status == 401 or (error_text and ("unauthorized" in error_text.lower() or "token is illegal" in error_text.lower())):
                    logger.warning("[Yuewen] 令牌已过期或无效，需要重新登录")
                    self.config['need_login'] = True
                    return False
                
                return False
                
            except ImportError:
                # 回退到 aiohttp
                logger.warning("[Yuewen] requests库未安装，使用aiohttp")
                
                # 发送异步请求
                async with self.http_session.post(
                    refresh_url,
                    headers=headers,
                    cookies=cookies,
                    json=payload,
                    timeout=30
                ) as response:
                    response_status = response.status
                    logger.debug(f"[Yuewen] 刷新令牌响应状态: {response_status}")
                    
                    if response_status == 200:
                        try:
                            # 获取完整响应
                            response_text = await response.text()
                            logger.debug(f"[Yuewen] 令牌刷新原始响应: {response_text[:200]}...")
                            
                            # 解析响应JSON
                            data = json.loads(response_text)
                            
                            # 按照curl命令响应格式提取token
                            access_token = data.get('accessToken', {}).get('raw')
                            refresh_token = data.get('refreshToken', {}).get('raw')
                            
                            # 添加详细日志
                            if access_token:
                                logger.debug(f"[Yuewen] 获取到新的访问令牌，长度: {len(access_token)}")
                            else:
                                logger.error("[Yuewen] 响应中未找到访问令牌")
                                
                            if refresh_token:
                                logger.debug(f"[Yuewen] 获取到新的刷新令牌，长度: {len(refresh_token)}")
                            else:
                                logger.error("[Yuewen] 响应中未找到刷新令牌")
                            
                            if access_token and refresh_token:
                                # 按照原始项目格式构造token
                                token_value = f"{access_token}...{refresh_token}"
                                
                                # 临时保存旧token，以便在保存失败时恢复
                                old_token = self.config.get('oasis_token')
                                
                                # 更新config
                                self.config['oasis_token'] = token_value
                                self.config['need_login'] = False
                                
                                # 记录刷新时间
                                self._last_token_refresh = current_time
                                
                                # 保存到配置前先验证数据
                                try:
                                    # 确保token存在且格式正确
                                    if not isinstance(token_value, str) or not token_value:
                                        logger.error("[Yuewen] 刷新令牌后token无效，恢复旧token")
                                        self.config['oasis_token'] = old_token
                                        return False
                                    
                                    # 保存配置
                                    saved = self.save_config()
                                    if not saved:
                                        logger.warning("[Yuewen] 令牌刷新后保存配置失败")
                                        # 尝试第二次保存
                                        time.sleep(0.5)  # 短暂延迟
                                        saved = self.save_config()
                                        if not saved:
                                            logger.error("[Yuewen] 令牌刷新后第二次保存仍然失败")
                                            
                                    logger.info("[Yuewen] ✅ 令牌刷新成功，已保存新令牌")
                                    return True
                                except Exception as cfg_e:
                                    logger.error(f"[Yuewen] 刷新令牌后保存配置异常: {cfg_e}")
                                    # 即使保存失败，我们仍然有内存中的令牌
                                    logger.debug("[Yuewen] 令牌刷新成功，但配置保存失败")
                                    return True
                            else:
                                logger.error("[Yuewen] 令牌刷新失败: 响应中未找到完整令牌")
                                return False
                        except json.JSONDecodeError as json_err:
                            logger.error(f"[Yuewen] 令牌刷新解析JSON响应失败: {json_err}")
                            # 打印原始响应内容以便调试
                            raw_text = await response.text()
                            logger.debug(f"[Yuewen] 令牌刷新原始响应: {raw_text[:200]}...")
                            return False
                        except Exception as parse_err:
                            logger.error(f"[Yuewen] 令牌刷新处理响应异常: {parse_err}")
                            return False
                            
                    # 处理错误情况
                    error_text = await response.text()
                    logger.debug(f"[Yuewen] 刷新令牌错误响应: {error_text[:200]}...")
                    
                    try:
                        # 尝试解析错误JSON
                        error_data = json.loads(error_text) if error_text else {"error": {"message": "未知错误"}}
                        error_msg = error_data.get('error', {}).get('message', '未知错误')
                    except json.JSONDecodeError:
                        # 如果不是JSON，使用原始文本
                        error_msg = error_text if error_text else "未知错误"
                            
                    logger.error(f"[Yuewen] 令牌刷新失败: HTTP {response.status}, {error_msg}")
                    
                    # 判断是否需要重新登录
                    if response.status == 401 or (error_text and ("unauthorized" in error_text.lower() or "token is illegal" in error_text.lower())):
                        logger.warning("[Yuewen] 令牌已过期或无效，需要重新登录")
                        self.config['need_login'] = True
                        return False
                        
                    return False
                        
        except Exception as e:
            logger.error(f"[Yuewen] 令牌刷新异常: {e}")
            logger.debug(f"[Yuewen] 令牌刷新异常栈: {traceback.format_exc()}")
            return False

    async def login_flow(self):
        """登录流程（异步版本）"""
        try:
            # 1. 注册设备
            if not await self.register_device():
                logger.error("[Yuewen] 设备注册失败")
                return False, "设备注册失败"
                
            # 2. 等待用户输入手机号
            # 这一步通常在外部UI交互中处理
            
            # 3. 发送验证码
            # phone_number = "用户输入的手机号"
            # if not await self.send_sms(phone_number):
            #     return False, "验证码发送失败"
            
            # 4. 等待用户输入验证码
            # 这一步通常在外部UI交互中处理
            
            # 5. 验证登录
            # verify_code = "用户输入的验证码"
            # if not await self.sign_in(phone_number, verify_code):
            #     return False, "登录验证失败"
            
            # 登录流程在外部由UI交互驱动，这里只是流程示意
            return True, "登录流程就绪"
            
        except Exception as e:
            logger.error(f"[Yuewen] 登录流程异常: {e}")
            return False, f"登录流程异常: {str(e)}"