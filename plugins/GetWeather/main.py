import sys
import subprocess
import importlib.util
import asyncio
import logging
import time
import os
import tomllib
import aiohttp
import jwt
import jieba

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase

# 检查并安装必要的依赖
def check_and_install_dependencies():
    """检查并安装必要的依赖"""
    required_packages = {
        'aiohttp': 'aiohttp',
        'PyJWT': 'PyJWT',
        'cryptography': 'cryptography', # PyJWT[crypto] often pulls this
        'jieba': 'jieba'
    }

    for package, import_name in required_packages.items():
        if importlib.util.find_spec(import_name) is None:
            print(f"正在安装依赖: {package}")
            try:
                subprocess.check_call([
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    package,
                    "-i",
                    "https://pypi.tuna.tsinghua.edu.cn/simple",
                    "--trusted-host",
                    "pypi.tuna.tsinghua.edu.cn"
                ])
                print(f"成功安装 {package}")
            except subprocess.CalledProcessError as e:
                print(f"安装 {package} 失败: {str(e)}")
                raise RuntimeError(f"无法安装必要的依赖: {package}")

# 安装依赖
check_and_install_dependencies()

class GetWeather(PluginBase):
    """天气查询插件"""

    name = "GetWeather"
    description = "获取实时天气和天气预报"
    author = "samqin-小x宝社区-服务癌症和罕见病患者的开源公益社区欢迎加入！"
    version = "1.0.11" # Incremented version

    # Change Log
    changes = [
        "1.0.11: 实现JWT token缓存和提前5分钟自动刷新机制",
        "1.0.10: 更新JWT生成逻辑，使用新的API认证方式",
        "1.0.9: 添加依赖版本检查",
        "1.0.8: 优化依赖安装逻辑",
        "1.0.7: 修复依赖导入顺序问题",
        "1.0.6: 更新JWT生成方法",
        "1.0.5: 添加JWT生成功能",
        "1.0.4: 添加自动安装依赖功能",
        "1.0.3: 添加天气API调用",
        "1.0.2: 添加城市查询功能",
        "1.0.1: 添加基础命令解析",
        "1.0.0: 初始版本"
    ]

    def __init__(self):
        """初始化插件"""
        super().__init__()

        # 加载配置
        config_path = "plugins/GetWeather/config.toml"


        with open(config_path, "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config.get("GetWeather", {})
        if not config:
            raise ValueError("配置文件中缺少GetWeather节")

        # 验证必要的配置项
        required_configs = ["api-host", "api-key", "jwt-kid", "jwt-sub"]
        missing_configs = [key for key in required_configs if key not in config]
        if missing_configs:
            raise ValueError(f"配置文件缺少必要的配置项: {', '.join(missing_configs)}")

        # 设置配置
        self.api_host = config["api-host"]
        self.private_key = config["api-key"] # This should be the actual private key string
        self.jwt_kid = config["jwt-kid"]
        self.jwt_sub = config["jwt-sub"]

        # Token caching attributes
        self.cached_token = None
        self.token_expiry_time = 0  # Unix timestamp (seconds)
        self.token_refresh_lead_time = 5 * 60  # 5 minutes in seconds
        self.token_default_lifespan = 24* 15 * 60 # 15 minutes in seconds, as per example (900s)
                                             # If API allows 24h, this could be 24 * 60 * 60

        # 设置日志
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        self.logger.info(f"插件 {self.name} v{self.version} 初始化完成")

    def generate_jwt_token(self):
        """
        生成JWT token.
        如果存在有效的缓存token,则返回缓存token。
        否则,生成新token,缓存并返回。
        """
        current_time_unix = int(time.time())

        # 检查缓存的token是否仍然有效且不需要刷新
        if self.cached_token and current_time_unix < (self.token_expiry_time - self.token_refresh_lead_time):
            self.logger.info(f"使用缓存的JWT token: {self.cached_token}")
            return self.cached_token

        self.logger.info("生成新的JWT token（缓存未命中或需要刷新）。")
        try:
            # 构建payload
            # iat (Issued At) Claim: Time at which the JWT was issued.
            # We set it slightly in the past to account for potential clock skew.
            iat_time = current_time_unix - 30

            # exp (过期时间) 声明：JWT 的过期时间。
            # 示例中使用的是 +900 秒（15 分钟）。
            # 如果您的 API 提供商允许更长的有效期（例如 24 小时），请调整 token_default_lifespan。
            exp_time = current_time_unix + self.token_default_lifespan

            payload = {
                'iat': iat_time,
                'exp': exp_time,
                'sub': self.jwt_sub
            }

            # 构建headers
            headers = {
                'kid': self.jwt_kid
            }

            self.logger.info("JWT Generation Details:")
            self.logger.info(f"  Current Timestamp: {current_time_unix}")
            self.logger.info(f"  iat (Issued At):   {payload['iat']}")
            self.logger.info(f"  exp (Expires At):  {payload['exp']}")
            self.logger.info(f"  Headers: {headers}")
            self.logger.info(f"  Payload: {payload}")

            # 生成token
            # Ensure self.private_key is the raw private key string, not a path to a file
            token = jwt.encode(payload, self.private_key, algorithm='EdDSA', headers=headers)
            self.logger.info(f"成功生成新的JWT token: {token}")

            # 缓存新token和其过期时间
            self.cached_token = token
            self.token_expiry_time = exp_time # Store the calculated expiry time

            return token

        except Exception as e:
            self.logger.error(f"生成JWT token失败: {str(e)}", exc_info=True)
            # Invalidate cache on error to force regeneration next time
            self.cached_token = None
            self.token_expiry_time = 0
            raise

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if "天气" not in message["Content"]:
            return

        if message.get("_processed", False):
            return

        message["_processed"] = True

        command_segments = list(jieba.cut(message["Content"]))

        if len(command_segments) == 1 and "天气" in command_segments:
            await bot.send_at_message(message["FromWxid"], "\n请指定城市名称，例如：天气 北京", [message["SenderWxid"]])
            return
        
        # 移除"天气"关键词并组合城市名
        city_name_parts = [word for word in command_segments if word != "天气"]
        if not city_name_parts: # e.g. "天气" alone was handled, but "天气 " might lead here
            await bot.send_at_message(message["FromWxid"], "\n请指定城市名称，例如：天气 北京", [message["SenderWxid"]])
            return

        request_loc = "".join(city_name_parts)
        
        # 简单校验一下，避免过长的无效请求
        if len(request_loc) > 20: # Arbitrary length limit
            self.logger.info(f"Request location too long: {request_loc}")
            await bot.send_at_message(message["FromWxid"], "\n城市名称过长，请检查。", [message["SenderWxid"]])
            return


        try:
            token = self.generate_jwt_token() # This will now use caching
            api_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate, br" # Common accept encoding
            }

            geo_api_url = f'{self.api_host}/geo/v2/city/lookup?location={request_loc}'
            self.logger.info(f"请求城市查询API: {geo_api_url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(geo_api_url, headers=api_headers) as response:
                    response_text = await response.text() # Get raw text for better debugging
                    if response.status != 200:
                        self.logger.error(f"城市查询API请求失败: {response.status}, Body: {response_text}")
                        await bot.send_at_message(message["FromWxid"], "\n⚠️城市查询服务暂时不可用，请稍后重试", [message["SenderWxid"]])
                        return
                    try:
                        geoapi_json = await response.json(content_type=None) # Allow any content type for json parsing
                    except aiohttp.ContentTypeError as json_err:
                        self.logger.error(f"城市查询API响应非JSON: {response.status}, Body: {response_text}. Error: {json_err}")
                        await bot.send_at_message(message["FromWxid"], "\n⚠️城市查询服务响应格式错误", [message["SenderWxid"]])
                        return


            self.logger.debug(f"城市查询API响应: {geoapi_json}")

            if geoapi_json.get('code') == '404' or not geoapi_json.get("location"):
                self.logger.info(f"未找到城市: {request_loc}. API Response: {geoapi_json}")
                await bot.send_at_message(message["FromWxid"], f"\n⚠️未查询到“{request_loc}”的信息，请检查城市名称。", [message["SenderWxid"]])
                return
            elif geoapi_json.get('code') != '200':
                self.logger.error(f"城市查询API业务错误: {geoapi_json}")
                error_msg = geoapi_json.get('message', '未知错误')
                await bot.send_at_message(message["FromWxid"], f"\n⚠️城市查询失败: {error_msg}", [message["SenderWxid"]])
                return

            location_info = geoapi_json["location"][0]
            country = location_info.get("country", "")
            adm1 = location_info.get("adm1", "")
            adm2 = location_info.get("adm2", "")
            city_id = location_info["id"]

            now_weather_api_url = f'{self.api_host}/v7/weather/now?location={city_id}'
            self.logger.info(f"请求实时天气API: {now_weather_api_url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(now_weather_api_url, headers=api_headers) as response:
                    response_text_now = await response.text()
                    if response.status != 200:
                        self.logger.error(f"实时天气API请求失败: {response.status}, Body: {response_text_now}")
                        await bot.send_at_message(message["FromWxid"], "\n⚠️获取实时天气失败，请稍后重试", [message["SenderWxid"]])
                        return
                    try:
                        now_weather_api_json = await response.json(content_type=None)
                    except aiohttp.ContentTypeError as json_err:
                        self.logger.error(f"实时天气API响应非JSON: {response.status}, Body: {response_text_now}. Error: {json_err}")
                        await bot.send_at_message(message["FromWxid"], "\n⚠️实时天气服务响应格式错误", [message["SenderWxid"]])
                        return


            weather_forecast_api_url = f'{self.api_host}/v7/weather/7d?location={city_id}'
            self.logger.info(f"请求天气预报API: {weather_forecast_api_url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(weather_forecast_api_url, headers=api_headers) as response:
                    response_text_forecast = await response.text()
                    if response.status != 200:
                        self.logger.error(f"天气预报API请求失败: {response.status}, Body: {response_text_forecast}")
                        await bot.send_at_message(message["FromWxid"], "\n⚠️获取天气预报失败，请稍后重试", [message["SenderWxid"]])
                        return
                    try:
                        weather_forecast_api_json = await response.json(content_type=None)
                    except aiohttp.ContentTypeError as json_err:
                        self.logger.error(f"天气预报API响应非JSON: {response.status}, Body: {response_text_forecast}. Error: {json_err}")
                        await bot.send_at_message(message["FromWxid"], "\n⚠️天气预报服务响应格式错误", [message["SenderWxid"]])
                        return


            if now_weather_api_json.get("code") != "200" or weather_forecast_api_json.get("code") != "200":
                 self.logger.error(f"天气API业务错误. Now: {now_weather_api_json.get('code')}, Forecast: {weather_forecast_api_json.get('code')}")
                 await bot.send_at_message(message["FromWxid"], "\n⚠️获取天气数据时出错，请稍后再试。", [message["SenderWxid"]])
                 return


            out_message = self.compose_weather_message(country, adm1, adm2, now_weather_api_json, weather_forecast_api_json)
            await bot.send_at_message(message["FromWxid"], "\n" + out_message, [message["SenderWxid"]])

        except jwt.exceptions.InvalidKeyError as e:
            self.logger.error(f"JWT密钥无效，请检查config.toml中的api-key格式: {str(e)}", exc_info=True)
            await bot.send_at_message(message["FromWxid"], f"\n⚠️天气服务认证配置错误，请联系管理员。", [message["SenderWxid"]])
        except aiohttp.ClientError as e:
            self.logger.error(f"网络请求错误: {str(e)}", exc_info=True)
            await bot.send_at_message(message["FromWxid"], f"\n⚠️网络连接超时或错误，请稍后重试。", [message["SenderWxid"]])
        except Exception as e:
            self.logger.error(f"处理天气查询时发生未知错误: {str(e)}", exc_info=True)
            await bot.send_at_message(message["FromWxid"], f"\n⚠️处理天气查询时发生内部错误，请稍后重试。", [message["SenderWxid"]])

        return False # Message handled

    @staticmethod
    def compose_weather_message(country, adm1, adm2, now_weather_api_json, weather_forecast_api_json):
        """构建天气信息消息"""
        update_time_str = now_weather_api_json.get('updateTime', '未知')
        now_data = now_weather_api_json.get('now', {})
        daily_forecast = weather_forecast_api_json.get('daily', [])

        # Format update time if possible
        try:
            # Example: 2023-10-26T10:35+08:00 -> 10-26 10:35
            dt_obj = datetime.fromisoformat(update_time_str)
            formatted_update_time = dt_obj.strftime("%m-%d %H:%M")
        except:
            formatted_update_time = update_time_str # Fallback

        message = (
            f"----- 小胰宝助手提醒您关注天气 -----\n"
            f"{country}{adm1}{adm2} 实时天气☁️\n"
            f"⏰更新时间：{formatted_update_time}\n\n"
            f"🌡️当前温度：{now_data.get('temp','N/A')}℃\n"
            f"🌡️体感温度：{now_data.get('feelsLike','N/A')}℃\n"
            f"☁️天气：{now_data.get('text','N/A')}\n"
        )
        
        # UV Index might be in today's forecast (index 0 of daily)
        if daily_forecast:
            message += f"☀️紫外线指数：{daily_forecast[0].get('uvIndex','N/A')}\n"
        
        message += (
            f"🌬️风向：{now_data.get('windDir','N/A')}\n"
            f"🌬️风力：{now_data.get('windScale','N/A')}级\n"
            f"💦湿度：{now_data.get('humidity','N/A')}%\n"
            f"🌧️降水量：{now_data.get('precip','N/A')}mm/h\n"
            f"👀能见度：{now_data.get('vis','N/A')}km\n\n"
        )

        if adm2: # Use specific district/city name if available for forecast title
            message += f"☁️未来3天 {adm2} 天气：\n"
        elif adm1:
             message += f"☁️未来3天 {adm1} 天气：\n"
        else:
            message += f"☁️未来3天天气：\n"


        # Iterate through the next 3 days of forecast (index 1, 2, 3 of daily array)
        # API usually gives today as index 0, then next days
        for day_forecast in daily_forecast[1:4]: # Slicing handles cases where fewer than 3 days are returned
            date_str = day_forecast.get('fxDate', 'N/A')
            # Format date if possible: 2023-10-27 -> 10.27
            try:
                formatted_date = '.'.join([d.lstrip('0') for d in date_str.split('-')[1:]])
            except:
                formatted_date = date_str

            weather_text = day_forecast.get('textDay', 'N/A')
            max_temp = day_forecast.get('tempMax', 'N/A')
            min_temp = day_forecast.get('tempMin', 'N/A')
            uv_index = day_forecast.get('uvIndex', 'N/A')
            message += f'{formatted_date} {weather_text} 最高🌡️{max_temp}℃ 最低🌡️{min_temp}℃ ☀️紫外线:{uv_index}\n'
        
        if not daily_forecast or len(daily_forecast) < 2:
            message += "未来几天天气预报数据暂缺。\n"

        return message.strip()
