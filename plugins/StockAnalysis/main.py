import asyncio
import json
import re
import tomllib
from datetime import datetime, timedelta
from typing import Dict, Optional
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import io

from loguru import logger
import aiohttp

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message, on_at_message, schedule
from utils.plugin_base import PluginBase

class StockAnalysis(PluginBase):
    """
    一个用于分析股票数据的插件，通过调用股票分析API获取股票信息，
    将分析结果返回到微信。
    """

    description = "股票分析与投资建议"
    author = "老夏的金库"
    version = "1.0.0"

    # 分析命令的正则表达式
    STOCK_COMMAND_PATTERN = r'^(分析股票|股票分析|分析|analyze)\s*([0-9A-Za-z]{4,8})$'
    
    # 响应等待消息
    ANALYSIS_IN_PROGRESS_PROMPT = """
    正在分析股票数据，请稍候...
    """

    def __init__(self):
        super().__init__()
        self.name = "StockAnalysis"
        self.description = "股票分析插件"
        self.version = "1.0.0"
        self.author = "Claude"
        
        # 添加logger
        self.logger = logger  # 从loguru导入的logger
        
        # 初始化akshare
        try:
            import akshare as ak
            self.ak = ak
        except ImportError:
            self.logger.error("未安装akshare包，请先安装: pip install akshare")
            raise
            
        # 加载配置
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
            
        self.config = config.get("StockAnalysis", {})
        
        self.enable = self.config.get("enable", False)
        self.commands = self.config.get("commands", ["分析股票", "股票分析", "analyze"])
        
        # 获取设置
        settings = self.config.get("Settings", {})
        self.default_market = settings.get("default_market", "A")
        self.data_cache_days = settings.get("data_cache_days", 30)
        
        # 获取 Dify 配置
        dify_config = self.config.get("Dify", {})
        self.dify_enable = dify_config.get("enable", False)
        self.dify_api_key = dify_config.get("api-key", "")
        self.dify_base_url = dify_config.get("base-url", "")
        self.http_proxy = dify_config.get("http-proxy", "")
        
        if not self.dify_enable or not self.dify_api_key or not self.dify_base_url:
            logger.warning("Dify配置不完整，AI分析功能将被禁用")
            self.dify_enable = False
        
        if not self.enable:
            logger.warning("股票分析插件未启用，请检查config.toml文件")
        
        self.analysis_tasks = {}  # 存储正在进行的分析任务
        self.http_session = aiohttp.ClientSession()

        # 初始化字体路径
        self.font_path = os.path.join(os.path.dirname(__file__), "fonts", "msyh.ttc")
        if not os.path.exists(self.font_path):
            os.makedirs(os.path.dirname(self.font_path), exist_ok=True)
            # 如果字体文件不存在，需要下载或复制微软雅黑字体到该位置
            self.logger.warning(f"字体文件不存在: {self.font_path}")
            self.font_path = None

    async def close(self):
        """插件关闭时，取消所有未完成的分析任务并关闭会话。"""
        logger.info("正在关闭 StockAnalysis 插件")
        
        # 取消所有未完成的分析任务
        for chat_id, task in self.analysis_tasks.items():
            if not task.done():
                logger.info(f"取消 {chat_id} 的股票分析任务")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"{chat_id} 的股票分析任务已取消")
                except Exception as e:
                    logger.exception(f"取消 {chat_id} 的股票分析任务时出错: {e}")
        
        # 关闭HTTP会话
        if self.http_session:
            await self.http_session.close()
            logger.info("HTTP会话已关闭")
        
        logger.info("StockAnalysis 插件已关闭")

    @on_text_message
    async def handle_text_message(self, bot: WechatAPIClient, message: Dict) -> bool:
        """处理文本消息，检查是否是股票分析命令。"""
        if not self.enable:
            return True  # 插件未启用，允许其他插件处理
        
        chat_id = message["FromWxid"]
        content = message["Content"]
        
        # 检查是否为股票分析命令
        match = re.match(self.STOCK_COMMAND_PATTERN, content)
        if match:
            command, stock_code = match.groups()
            
            # 检查是否正在进行分析
            if chat_id in self.analysis_tasks and not self.analysis_tasks[chat_id].done():
                try:
                    await bot.send_text_message(chat_id, "已有一个分析任务正在进行，请稍后再试。")
                except Exception as e:
                    logger.exception(f"发送消息失败: {e}")
                return False  # 阻止其他插件处理
            
            # 发送等待消息
            try:
                await bot.send_text_message(chat_id, self.ANALYSIS_IN_PROGRESS_PROMPT)
            except Exception as e:
                logger.exception(f"发送等待消息失败: {e}")
            
            # 创建分析任务
            self.analysis_tasks[chat_id] = asyncio.create_task(
                self._analyze_stock(bot, chat_id, stock_code)
            )
            logger.info(f"创建股票 {stock_code} 的分析任务")
            return False  # 阻止其他插件处理
            
        return True  # 不是分析命令，允许其他插件处理

    @on_at_message
    async def handle_at_message(self, bot: WechatAPIClient, message: Dict) -> bool:
        """处理@消息，检查是否包含股票分析命令。"""
        if not self.enable:
            return True  # 插件未启用，允许其他插件处理
            
        chat_id = message["FromWxid"]
        content = message["Content"]
        
        # 移除@标记和特殊字符，仅保留实际文本内容
        # 注意：这里可能需要根据实际的@消息格式进行调整
        content = re.sub(r'@\S+\s+', '', content).strip()
        
        # 检查是否为股票分析命令
        match = re.match(self.STOCK_COMMAND_PATTERN, content)
        if match:
            command, stock_code = match.groups()
            
            # 检查是否正在进行分析
            if chat_id in self.analysis_tasks and not self.analysis_tasks[chat_id].done():
                try:
                    await bot.send_text_message(chat_id, "已有一个分析任务正在进行，请稍后再试。")
                except Exception as e:
                    logger.exception(f"发送消息失败: {e}")
                return False  # 阻止其他插件处理
            
            # 发送等待消息
            try:
                await bot.send_text_message(chat_id, self.ANALYSIS_IN_PROGRESS_PROMPT)
            except Exception as e:
                logger.exception(f"发送等待消息失败: {e}")
            
            # 创建分析任务
            self.analysis_tasks[chat_id] = asyncio.create_task(
                self._analyze_stock(bot, chat_id, stock_code)
            )
            logger.info(f"创建股票 {stock_code} 的分析任务")
            return False  # 阻止其他插件处理
            
        return True  # 不是分析命令，允许其他插件处理

    async def _get_stock_data(self, stock_code: str, market_type: str = "A"):
        """获取股票数据"""
        try:
            if market_type == "A":
                self.logger.info(f"正在获取A股数据: {stock_code}")
                
                # 获取更长时间的历史数据
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
                
                try:
                    # 尝试获取股票名称和状态
                    stock_info = self.ak.stock_zh_a_spot_em()
                    stock_name = ""  # 初始化股票名称变量
                    actual_code = stock_code  # 默认使用原始代码
                    
                    if not stock_info.empty:
                        # 确保股票代码格式一致（补齐前导零）
                        padded_code = stock_code.zfill(6)
                        self.logger.info(f"查询股票信息，原始代码: {stock_code}, 补齐后代码: {padded_code}")
                        
                        # 打印所有可用的股票代码用于调试
                        available_codes = stock_info['代码'].tolist()
                        self.logger.info(f"数据源中包含的部分股票代码: {available_codes[:10]}...")
                        
                        # 检查股票代码是否存在
                        stock_match = stock_info[stock_info['代码'] == padded_code]
                        if stock_match.empty:
                            # 尝试直接使用原始代码
                            stock_match = stock_info[stock_info['代码'] == stock_code]
                            if stock_match.empty:
                                self.logger.error(f"股票代码 {stock_code} 不存在于数据源中")
                                return None
                            
                        stock_name = stock_match.iloc[0]['名称']
                        self.logger.info(f"找到股票: {stock_name}")
                        
                        if '退市' in stock_name or 'ST' in stock_name:
                            self.logger.error(f"股票 {stock_code} ({stock_name}) 可能已退市或被ST")
                            return None
                            
                        # 使用找到的实际代码
                        actual_code = stock_match.iloc[0]['代码']
                        self.logger.info(f"使用实际代码获取数据: {actual_code}")
                    
                    # 使用东方财富数据源
                    self.logger.info(f"使用东方财富数据源获取数据... 时间范围: {start_date} 至 {end_date}")
                    df = self.ak.stock_zh_a_hist(
                        symbol=actual_code,  # 使用实际代码
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq"
                    )
                    
                    if df.empty:
                        self.logger.error(f"无法获取股票数据: {actual_code}")
                        return None
                        
                    # 检查数据量是否足够
                    if len(df) < 60:  # 如果数据少于60天，尝试获取更长时间的数据
                        self.logger.info("数据量不足，尝试获取更长时间的数据...")
                        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")  # 扩展到一年
                        df = self.ak.stock_zh_a_hist(
                            symbol=actual_code,
                            period="daily",
                            start_date=start_date,
                            end_date=end_date,
                            adjust="qfq"
                        )
                    
                    # 确保必要的列存在并重命名
                    column_map = {
                        '日期': 'date',
                        '开盘': 'open',
                        '收盘': 'close',
                        '最高': 'high',
                        '最低': 'low',
                        '成交量': 'volume',
                        '成交额': 'amount',
                        '振幅': 'amplitude',
                        '涨跌幅': 'change_pct',
                        '涨跌额': 'change_amount',
                        '换手率': 'turnover_rate'
                    }
                    
                    # 检查列名并打印用于调试
                    self.logger.info(f"数据列名: {list(df.columns)}")
                    
                    # 重命名列
                    df = df.rename(columns=column_map)
                    
                    # 确保所有必要的列都存在
                    required_columns = ['date', 'open', 'close', 'high', 'low', 'volume']
                    if not all(col in df.columns for col in required_columns):
                        missing_cols = [col for col in required_columns if col not in df.columns]
                        self.logger.error(f"缺少必要的列: {missing_cols}")
                        return None
                    
                    self.logger.info(f"成功获取股票数据，数据条数: {len(df)}")
                    
                    # 添加最近的涨跌幅信息
                    latest_change = df['change_pct'].iloc[-1] if 'change_pct' in df.columns else 0
                    latest_price = df['close'].iloc[-1]
                    latest_turnover = df['turnover_rate'].iloc[-1] if 'turnover_rate' in df.columns else 0
                    
                    # 将额外信息添加到DataFrame的属性中
                    df.attrs['stock_name'] = stock_name  # 添加股票名称到属性
                    df.attrs['market_type'] = market_type  # 添加市场类型到属性
                    df.attrs['latest_change'] = latest_change
                    df.attrs['latest_price'] = latest_price
                    df.attrs['latest_turnover'] = latest_turnover
                    
                    return df
                    
                except Exception as e:
                    self.logger.error(f"获取股票数据失败: {str(e)}")
                    # 尝试使用备用数据源
                    try:
                        self.logger.info("尝试使用新浪财经数据源...")
                        df = self.ak.stock_zh_a_daily(symbol=stock_code, adjust="qfq")
                        if not df.empty:
                            # 在备用数据源中也添加股票信息
                            df.attrs['stock_name'] = "未知"  # 备用数据源可能无法获取股票名称
                            df.attrs['market_type'] = market_type
                            return df
                    except Exception as e2:
                        self.logger.error(f"备用数据源也获取失败: {str(e2)}")
                    return None
                
        except Exception as e:
            self.logger.error(f"获取股票数据时发生错误: {str(e)}")
            return None
            
    def _calculate_indicators(self, df):
        """计算技术指标"""
        try:
            # 计算RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # 计算MACD
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            
            # 计算MA
            df['MA5'] = df['close'].rolling(window=5).mean()
            df['MA10'] = df['close'].rolling(window=10).mean()
            df['MA20'] = df['close'].rolling(window=20).mean()
            
            # 计算波动率
            df['Volatility'] = df['close'].pct_change().rolling(window=20).std() * np.sqrt(252) * 100
            
            return df
            
        except Exception as e:
            self.logger.error(f"计算技术指标失败: {str(e)}")
            return None
            
    def _analyze_indicators(self, df):
        """分析技术指标生成报告"""
        try:
            latest = df.iloc[-1]
            
            # 趋势分析
            trend = "上升" if latest['MA5'] > latest['MA20'] else "下降"
            
            # 波动性分析
            volatility = float(latest['Volatility'])
            
            # RSI分析
            rsi = float(latest['RSI'])
            rsi_signal = "超买" if rsi > 70 else "超卖" if rsi < 30 else "中性"
            
            # MACD分析
            macd_signal = "买入" if latest['MACD'] > latest['Signal'] else "卖出"
            
            # 成交量分析
            volume_trend = "放量" if df['volume'].iloc[-5:].mean() > df['volume'].iloc[-20:].mean() else "缩量"
            
            # 获取最新市场数据
            latest_price = float(latest['close'])
            latest_change = float(df['change_pct'].iloc[-1]) if 'change_pct' in df.columns else 0.0
            latest_turnover = float(df['turnover_rate'].iloc[-1]) if 'turnover_rate' in df.columns else 0.0
            
            # 获取均线数据
            ma5 = float(latest['MA5'])
            ma10 = float(latest['MA10'])
            ma20 = float(latest['MA20'])
            
            # 计算综合得分(0-100)
            score = 0
            score += 30 if trend == "上升" else 0
            score += 20 if 30 < rsi < 70 else 0
            score += 20 if macd_signal == "买入" else 0
            score += 15 if volume_trend == "放量" else 0
            score += 15 if volatility < 30 else 0
            
            return {
                "trend": trend,
                "volatility": volatility,
                "rsi": rsi,
                "rsi_signal": rsi_signal,
                "macd_signal": macd_signal,
                "volume_trend": volume_trend,
                "score": score,
                "latest_price": latest_price,
                "latest_change": latest_change,
                "latest_turnover": latest_turnover,
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20
            }
            
        except Exception as e:
            self.logger.error(f"生成分析报告失败: {str(e)}")
            return None

    async def _send_to_dify(self, data: Dict) -> None:
        """
        发送数据到 dify 进行 AI 分析
        
        Args:
            data: 包含股票数据的字典，包括技术指标和历史数据
        """
        if not self.dify_enable:
            self.logger.warning("Dify功能未启用")
            return None
                
        try:
            headers = {
                "Authorization": f"Bearer {self.dify_api_key}",
                "Content-Type": "application/json"
            }
            
            # 获取格式化的分析结果
            formatted_analysis = self._format_analysis_result(data['analysis'])
            
            # 将原始数据转换为文本格式
            raw_data_text = f"""
【股票数据分析请求】

1. 基本信息：
代码：{data['code']}
名称：{data['name']}
市场类型：{data['market_type']}
货币单位：{data['currency']}

2. 市场数据：
最新价格：{data['analysis']['latest_price']:.4f}
涨跌幅：{data['analysis']['latest_change']:.2f}%
换手率：{data['analysis'].get('latest_turnover', 0):.2f}%
趋势：{data['analysis']['trend']}
波动率：{data['analysis']['volatility']:.2f}%
成交量趋势：{data['analysis']['volume_trend']}

3. 技术指标：
RSI(14)：{data['analysis']['rsi']:.2f}
RSI信号：{data['analysis']['rsi_signal']}
MACD信号：{data['analysis']['macd_signal']}
MA5：{data['analysis']['ma5']:.2f}
MA10：{data['analysis']['ma10']:.2f}
MA20：{data['analysis']['ma20']:.2f}

4. 技术指标趋势（最近20个交易日）：
RSI趋势：{', '.join([f'{x:.2f}' for x in data['indicators']['RSI'][-20:]])}
MACD趋势：{', '.join([f'{x:.2f}' for x in data['indicators']['MACD'][-20:]])}
MACD信号线：{', '.join([f'{x:.2f}' for x in data['indicators']['Signal'][-20:]])}
MA5趋势：{', '.join([f'{x:.2f}' for x in data['indicators']['MA5'][-20:]])}
MA10趋势：{', '.join([f'{x:.2f}' for x in data['indicators']['MA10'][-20:]])}
MA20趋势：{', '.join([f'{x:.2f}' for x in data['indicators']['MA20'][-20:]])}
波动率趋势：{', '.join([f'{x:.2f}' for x in data['indicators']['Volatility'][-20:]])}

5. 历史数据（近一个月交易日）：
"""
            # 添加近一个月的历史数据
            for record in data['historical_data'][-20:]:
                raw_data_text += f"日期：{record['date']}, 开盘：{record['open']:.4f}, 收盘：{record['close']:.4f}, "
                raw_data_text += f"最高：{record['high']:.4f}, 最低：{record['low']:.4f}, "
                raw_data_text += f"成交量：{record['volume']}, 涨跌幅：{record.get('change_pct', 0):.2f}%\n"
            
            # 准备发送给 dify 的数据
            payload = {
                "inputs": {},
                "query": f"""{raw_data_text}

请根据以上数据进行深度分析，重点关注：

1. 技术面分析：
   - 结合K线形态和技术指标（RSI、MACD、均线系统）分析当前趋势
   - 分析成交量与价格的关系，判断趋势的可信度
   - 通过均线系统判断多空头排列情况

2. 趋势研判：
   - 基于历史数据分析近期支撑位和压力位
   - 结合RSI和MACD指标判断可能的趋势反转点
   - 评估趋势的强度和持续性

3. 投资风险提示：
   - 基于波动率和换手率分析当前风险水平
   - 结合技术指标给出风险预警信号
   - 评估当前价格位置的风险收益比

4. 具体操作建议：
   - 给出明确的操作方向（买入/卖出/观望）
   - 建议具体的买卖价格区间
   - 设置合理的止损位和目标价位

请结合所有数据，给出专业、具体且可操作的建议。""",
                "response_mode": "blocking",
                "conversation_id": None,
                "user": "stock_analysis"
            }
            
            url = f"{self.dify_base_url}/chat-messages"
            async with self.http_session.post(
                url=url,
                headers=headers,
                json=payload,
                proxy=self.http_proxy if self.http_proxy else None
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    answer = result.get("answer", "")
                    self.logger.info("成功从 Dify API 获取分析结果")
                    return result
                else:
                    error_msg = await response.text()
                    self.logger.error(f"调用 Dify API 失败: {response.status} - {error_msg}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"与 Dify 通信时发生错误: {e}")
            return None

    def _text_to_image(self, text: str, title: str = "") -> bytes:
        """
        将文本转换为图片
        
        Args:
            text: 要转换的文本
            title: 标题
            
        Returns:
            图片的二进制数据
        """
        try:
            # 设置字体
            if self.font_path and os.path.exists(self.font_path):
                title_font = ImageFont.truetype(self.font_path, 40)
                content_font = ImageFont.truetype(self.font_path, 30)
            else:
                # 使用默认字体
                title_font = ImageFont.load_default()
                content_font = ImageFont.load_default()
            
            # 计算图片大小
            padding = 50
            line_spacing = 10
            
            # 分割文本为行
            lines = text.split('\n')
            
            # 创建临时图片来计算文本大小
            temp_img = Image.new('RGB', (1, 1), color='white')
            temp_draw = ImageDraw.Draw(temp_img)
            
            # 计算标题大小
            if title:
                title_bbox = temp_draw.textbbox((0, 0), title, font=title_font)
                title_w = title_bbox[2] - title_bbox[0]
                title_h = title_bbox[3] - title_bbox[1]
            else:
                title_w, title_h = 0, 0
            
            # 计算每行文本的大小
            max_line_width = 0
            total_height = title_h + padding if title else padding
            
            for line in lines:
                if line.strip():
                    bbox = temp_draw.textbbox((0, 0), line, font=content_font)
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                    max_line_width = max(max_line_width, w)
                    total_height += h + line_spacing
            
            # 设置图片大小
            width = max(max_line_width + padding * 2, title_w + padding * 2)
            height = total_height + padding
            
            # 创建图片
            img = Image.new('RGB', (width, height), color='white')
            draw = ImageDraw.Draw(img)
            
            # 绘制标题
            if title:
                title_x = (width - title_w) // 2
                draw.text((title_x, padding//2), title, font=title_font, fill='black')
                current_y = title_h + padding
            else:
                current_y = padding
            
            # 绘制正文
            for line in lines:
                if line.strip():
                    bbox = draw.textbbox((0, 0), line, font=content_font)
                    h = bbox[3] - bbox[1]
                    draw.text((padding, current_y), line, font=content_font, fill='black')
                    current_y += h + line_spacing
            
            # 添加水印
            watermark = "老夏的金库"
            watermark_font = ImageFont.truetype(self.font_path, 20) if self.font_path else ImageFont.load_default()
            watermark_bbox = draw.textbbox((0, 0), watermark, font=watermark_font)
            w = watermark_bbox[2] - watermark_bbox[0]
            h = watermark_bbox[3] - watermark_bbox[1]
            draw.text((width - w - padding, height - h - padding//2), 
                     watermark, font=watermark_font, fill='gray')
            
            # 转换为字节流
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            
            return img_byte_arr
            
        except Exception as e:
            self.logger.exception(f"生成图片失败: {e}")
            return None

    async def _analyze_stock(self, bot: WechatAPIClient, chat_id: str, code: str) -> None:
        try:
            logger.info(f"开始分析 {code}")
            
            # 判断代码类型
            market_type = self._determine_market_type(code)
            
            # 获取数据
            df = None
            if market_type == 'A':
                df = await self._get_stock_data(code, market_type)
            elif market_type == 'HK':
                df = await self._get_hk_stock_data(code)
            elif market_type == 'US':
                df = await self._get_us_stock_data(code)
            elif market_type in ['ETF', 'LOF']:
                df = await self._get_fund_data(code, market_type)
                
            if df is None:
                await bot.send_text_message(chat_id, f"无法获取 {code} 的数据，请确认代码是否正确。")
                return
                
            # 计算指标
            df = self._calculate_indicators(df)
            if df is None:
                await bot.send_text_message(chat_id, f"无法计算 {code} 的技术指标。")
                return
                
            # 生成分析报告
            analysis = self._analyze_indicators(df)
            if analysis is None:
                await bot.send_text_message(chat_id, f"无法生成 {code} 的分析报告。")
                return
                
            # 添加代码和名称到分析结果
            analysis['code'] = code
            
            # 获取并记录股票名称
            stock_name = df.attrs.get('stock_name', '')
            fund_name = df.attrs.get('fund_name', '')
            self.logger.info(f"DataFrameattrs中的名称信息: stock_name='{stock_name}', fund_name='{fund_name}'")
            
            analysis['name'] = df.attrs.get('stock_name', '') or df.attrs.get('fund_name', '')
            analysis['type'] = df.attrs.get('market_type', market_type)
            analysis['currency'] = self._get_currency_by_market(market_type)
            
            self.logger.info(f"最终使用的股票名称: '{analysis['name']}'")
            
            # 准备发送给 Dify 的数据
            stock_data = {
                'code': code,
                'market_type': market_type,
                'name': analysis['name'],
                'currency': analysis['currency'],
                'analysis': analysis,
                'indicators': {
                    'RSI': df['RSI'].tail(20).tolist(),
                    'MACD': df['MACD'].tail(20).tolist(),
                    'Signal': df['Signal'].tail(20).tolist(),
                    'MA5': df['MA5'].tail(20).tolist(),
                    'MA10': df['MA10'].tail(20).tolist(),
                    'MA20': df['MA20'].tail(20).tolist(),
                    'Volatility': df['Volatility'].tail(20).tolist()
                },
                'historical_data': df[['date', 'open', 'close', 'high', 'low', 'volume', 'change_pct']].tail(60).to_dict('records')
            }
            
            # 异步发送数据到 dify
            dify_task = asyncio.create_task(self._send_to_dify(stock_data))
            
            # 格式化分析结果
            formatted_result = self._format_analysis_result(analysis)
            
            # 将分析结果转换为图片
            stock_name = analysis['name'] if analysis['name'] else code
            title = f"{stock_name}({code}) 分析报告"
            img_data = self._text_to_image(formatted_result, title)
            
            if img_data:
                # 发送图片
                await bot.send_image_message(chat_id, img_data)
            else:
                # 如果图片生成失败，退回到发送文本
                await bot.send_text_message(chat_id, formatted_result)
            
            # 等待 dify 分析结果
            try:
                dify_result = await dify_task
                if dify_result and 'answer' in dify_result:
                    # 将AI分析结果也转换为图片
                    ai_analysis_img = self._text_to_image(
                        dify_result['answer'],
                        f"{stock_name}({code}) AI深度分析"
                    )
                    if ai_analysis_img:
                        await bot.send_image_message(chat_id, ai_analysis_img)
                    else:
                        await bot.send_text_message(chat_id, f"\n\n【AI 深度分析】\n{dify_result['answer']}")
            except Exception as e:
                self.logger.error(f"获取 Dify 分析结果失败: {e}")
            
            logger.info(f"{code} 的分析已完成并发送")
            
        except Exception as e:
            logger.exception(f"分析 {code} 时出错: {e}")
            try:
                await bot.send_text_message(chat_id, f"分析时发生错误: {str(e)}")
            except Exception as send_error:
                logger.exception(f"发送错误消息失败: {send_error}")
        finally:
            if chat_id in self.analysis_tasks:
                del self.analysis_tasks[chat_id]

    def _determine_market_type(self, stock_code: str) -> str:
        """
        根据股票代码确定市场类型
        
        Args:
            stock_code: 股票代码
            
        Returns:
            市场类型: 'A'(A股), 'HK'(港股), 'US'(美股), 'ETF', 'LOF', 'FUND'(其他基金)
        """
        try:
            # 首先尝试从基金列表中查找
            try:
                # 检查是否为普通基金
                fund_info = self.ak.fund_open_fund_info_em(fund=stock_code)
                if not fund_info.empty:
                    return 'FUND'
                    
                # 检查是否为ETF
                etf_info = self.ak.fund_etf_spot_em()
                if not etf_info.empty and stock_code in etf_info['代码'].values:
                    return 'ETF'
                    
                # 检查是否为LOF
                lof_info = self.ak.fund_lof_spot_em()
                if not lof_info.empty and stock_code in lof_info['代码'].values:
                    return 'LOF'
            except Exception as e:
                self.logger.warning(f"基金类型检查失败: {e}")
        
            # 如果不是基金，则按照股票代码规则判断
            if (
                stock_code.startswith('60') or  # 上海主板
                stock_code.startswith('00') or  # 深圳主板
                stock_code.startswith('30') or  # 创业板
                stock_code.startswith('68') or  # 科创板
                stock_code.startswith('002') or # 中小板
                stock_code.startswith('003') or # 深圳主板
                stock_code.startswith('001') or # 深圳主板
                stock_code.startswith('004') or # 深圳主板
                stock_code.startswith('005')    # 深圳主板
            ):
                # 进一步验证A股
                try:
                    stock_info = self.ak.stock_zh_a_spot_em()
                    if not stock_info.empty and stock_code in stock_info['代码'].values:
                        return 'A'
                except Exception as e:
                    self.logger.warning(f"A股验证失败: {e}")
                
            # 基金代码规则
            if (
                stock_code.startswith('51') or  # 上海ETF
                stock_code.startswith('56') or  # 上海ETF
                stock_code.startswith('58') or  # 上海ETF
                stock_code.startswith('15') or  # 深圳ETF
                stock_code.startswith('159')    # 深圳ETF
            ):
                return 'ETF'
            elif (
                stock_code.startswith('16') or  # 深圳LOF
                stock_code.startswith('50') or  # 上海LOF
                stock_code.startswith('501')    # 上海LOF
            ):
                return 'LOF'
            
            # 港股市场
            elif len(stock_code) == 5 and stock_code.isdigit():
                return 'HK'
            
            # 美股市场
            else:
                return 'US'
                
        except Exception as e:
            self.logger.error(f"市场类型判断失败: {e}")
            return 'A'  # 默认返回A股类型

    def _format_analysis_result(self, analysis: Dict) -> str:
        """
        格式化股票分析结果为易读的文本
        """
        try:
            # 构建分析结果文本
            market_type = analysis.get('type', '')
            if market_type == 'FUND':
                analysis_text = "【混合型基金分析报告】\n\n"
            elif market_type in ['ETF', 'LOF']:
                analysis_text = f"【{market_type}基金分析报告】\n\n"
            else:
                market_name = {
                    'A': 'A股',
                    'HK': '港股',
                    'US': '美股'
                }.get(market_type, '')
                analysis_text = f"【{market_name}分析报告】\n\n"
            
            # 基本信息
            analysis_text += f"代码: {analysis.get('code', '')}\n"
            if analysis.get('name'):
                analysis_text += f"名称: {analysis.get('name')}\n"
            analysis_text += f"分析日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            
            # 市场数据
            currency = analysis.get('currency', 'CNY')
            currency_symbol = {
                'CNY': '¥',
                'HKD': 'HK$',
                'USD': '$'
            }.get(currency, '')
            
            latest_price = float(analysis.get('latest_price', 0))
            latest_change = float(analysis.get('latest_change', 0))
            latest_turnover = float(analysis.get('latest_turnover', 0))
            
            if market_type in ['ETF', 'LOF']:
                analysis_text += f"最新净值: {currency_symbol}{latest_price:.4f}\n"
            else:
                analysis_text += f"最新价格: {currency_symbol}{latest_price:.2f}\n"
            
            analysis_text += f"涨跌幅: {latest_change:.2f}%\n"
            if 'latest_turnover' in analysis:
                analysis_text += f"换手率: {latest_turnover:.2f}%\n"
            analysis_text += "\n"
            
            # 技术指标概要
            analysis_text += "【技术指标概要】\n"
            analysis_text += f"趋势: {analysis.get('trend', '未知')}\n"
            
            # 确保波动率是数值类型
            volatility = float(analysis.get('volatility', 0))
            analysis_text += f"波动率: {volatility:.2f}%\n"
            
            analysis_text += f"成交量趋势: {analysis.get('volume_trend', '未知')}\n"
            
            # 确保RSI是数值类型
            rsi = float(analysis.get('rsi', 0))
            analysis_text += f"RSI指标: {rsi:.2f}\n"
            analysis_text += f"RSI信号: {analysis.get('rsi_signal', '未知')}\n"
            analysis_text += f"MACD信号: {analysis.get('macd_signal', '未知')}\n\n"
            
            # 均线分析
            analysis_text += "【均线分析】\n"
            # 确保均线值是数值类型
            ma5 = float(analysis.get('ma5', 0))
            ma10 = float(analysis.get('ma10', 0))
            ma20 = float(analysis.get('ma20', 0))
            
            analysis_text += f"5日均线: {ma5:.2f}\n"
            analysis_text += f"10日均线: {ma10:.2f}\n"
            analysis_text += f"20日均线: {ma20:.2f}\n\n"
            
            # 投资建议
            analysis_text += "【投资建议】\n"
            score = int(analysis.get('score', 0))
            analysis_text += f"综合评分: {score}/100\n"
            
            # 根据得分给出建议
            if score >= 80:
                recommendation = "强烈推荐买入"
            elif score >= 60:
                recommendation = "建议买入"
            elif score >= 40:
                recommendation = "建议观望"
            elif score >= 20:
                recommendation = "建议减持"
            else:
                recommendation = "建议卖出"
            
            analysis_text += f"建议: {recommendation}\n\n"
            
            # 风险提示
            analysis_text += "【风险提示】\n"
            analysis_text += "以上分析仅供参考，投资有风险，入市需谨慎。"
            
            return analysis_text
            
        except Exception as e:
            self.logger.exception(f"格式化分析结果时出错: {e}")
            return "分析结果格式化失败，请稍后重试。"

    @schedule('cron', hour=15, minute=30)
    async def daily_market_summary(self, bot):
        """每个交易日收盘后发送市场总结"""
        try:
            # 这里可以实现获取大盘指数的逻辑
            # 例如分析上证指数、深证成指、创业板指等
            
            # 示例实现
            index_codes = ["000001", "399001", "399006"]  # 上证指数、深证成指、创业板指
            market_summary = "【今日市场总结】\n\n"
            
            for code in index_codes:
                try:
                    analysis = await self._analyze_stock(None, None, code)
                    if analysis:
                        # 修改这行，避免在f-string中使用反斜杠
                        lines = analysis.split('\n')
                        if len(lines) > 1:
                            info = lines[1].split(': ')
                            if len(info) > 1:
                                market_summary += f"{code}: {info[1]}\n"
                except Exception as e:
                    logger.exception(f"获取指数 {code} 数据失败: {e}")
            
            # 这里可以配置需要发送的群组或个人
            target_groups = ["12345678@chatroom"]  # 示例群聊ID
            
            for group_id in target_groups:
                await bot.send_text_message(group_id, market_summary)
                
        except Exception as e:
            logger.exception(f"发送每日市场总结失败: {e}")

    async def _get_fund_data(self, fund_code: str, fund_type: str = "FUND"):
        """获取基金数据"""
        try:
            self.logger.info(f"正在获取{fund_type}基金数据: {fund_code}")
            
            # 获取历史数据
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
            
            try:
                if fund_type == "FUND":
                    self.logger.info(f"获取普通基金数据... 时间范围: {start_date} 至 {end_date}")
                    # 获取基金净值数据
                    df = self.ak.fund_open_fund_info_em(fund=fund_code, indicator="单位净值走势")
                    
                    # 重命名列
                    column_map = {
                        '净值日期': 'date',
                        '单位净值': 'close',
                        '日增长率': 'change_pct'
                    }
                    df = df.rename(columns=column_map)
                    
                    # 获取基金信息
                    fund_info = self.ak.fund_em_fund_name()
                    fund_name = ""
                    if not fund_info.empty:
                        fund_match = fund_info[fund_info['基金代码'] == fund_code]
                        if not fund_match.empty:
                            fund_name = fund_match.iloc[0]['基金简称']
                    
                    # 添加基金信息到DataFrame的属性中
                    df.attrs['fund_name'] = fund_name
                    df.attrs['fund_type'] = 'FUND'
                    df.attrs['latest_price'] = float(df['close'].iloc[-1])
                    df.attrs['latest_change'] = float(df['change_pct'].iloc[-1]) if 'change_pct' in df.columns else 0.0
                    
                    return df
                    
                elif fund_type == "ETF":
                    self.logger.info(f"获取ETF基金数据... 时间范围: {start_date} 至 {end_date}")
                    df = self.ak.fund_etf_hist_em(
                        symbol=fund_code,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq"
                    )
                else:  # LOF
                    self.logger.info(f"获取LOF基金数据... 时间范围: {start_date} 至 {end_date}")
                    df = self.ak.fund_lof_hist_em(
                        symbol=fund_code,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq"
                    )
                
                if df.empty:
                    self.logger.error(f"无法获取基金数据: {fund_code}")
                    return None
                    
                # 重命名列
                column_map = {
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '振幅': 'amplitude',
                    '涨跌幅': 'change_pct',
                    '涨跌额': 'change_amount',
                    '换手率': 'turnover_rate'
                }
                
                # 检查列名并打印用于调试
                self.logger.info(f"数据列名: {list(df.columns)}")
                
                # 重命名列
                df = df.rename(columns=column_map)
                
                # 获取基金名称和类型
                if fund_type == "ETF":
                    fund_info = self.ak.fund_etf_spot_em()
                else:
                    fund_info = self.ak.fund_lof_spot_em()
                    
                fund_name = ""
                if not fund_info.empty:
                    fund_match = fund_info[fund_info['代码'] == fund_code]
                    if not fund_match.empty:
                        fund_name = fund_match.iloc[0]['名称']
                
                # 添加基金信息到DataFrame的属性中
                df.attrs['fund_name'] = fund_name
                df.attrs['fund_type'] = fund_type
                df.attrs['latest_price'] = float(df['close'].iloc[-1])
                df.attrs['latest_change'] = float(df['change_pct'].iloc[-1]) if 'change_pct' in df.columns else 0.0
                df.attrs['latest_turnover'] = float(df['turnover_rate'].iloc[-1]) if 'turnover_rate' in df.columns else 0.0
                
                return df
                
            except Exception as e:
                self.logger.error(f"获取基金数据失败: {str(e)}")
                return None
            
        except Exception as e:
            self.logger.error(f"获取基金数据时发生错误: {str(e)}")
            return None

    async def _get_hk_stock_data(self, stock_code: str):
        """获取港股数据"""
        try:
            self.logger.info(f"正在获取港股数据: {stock_code}")
            
            # 确保是5位数字代码
            stock_code = stock_code.zfill(5)
            
            # 获取历史数据
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
            
            try:
                self.logger.info(f"获取港股数据... 时间范围: {start_date} 至 {end_date}")
                df = self.ak.stock_hk_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"
                )
                
                if df.empty:
                    self.logger.error(f"无法获取港股数据: {stock_code}")
                    return None
                    
                # 获取港股名称
                stock_info = self.ak.stock_hk_spot_em()
                stock_name = ""
                if not stock_info.empty:
                    stock_match = stock_info[stock_info['代码'] == stock_code]
                    if not stock_match.empty:
                        stock_name = stock_match.iloc[0]['名称']
                
                # 重命名列
                column_map = {
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '涨跌幅': 'change_pct',
                    '涨跌额': 'change_amount',
                    '换手率': 'turnover_rate'
                }
                
                df = df.rename(columns=column_map)
                
                # 添加股票信息
                df.attrs['stock_name'] = stock_name
                df.attrs['market_type'] = 'HK'
                df.attrs['latest_price'] = float(df['close'].iloc[-1])
                df.attrs['latest_change'] = float(df['change_pct'].iloc[-1]) if 'change_pct' in df.columns else 0.0
                df.attrs['latest_turnover'] = float(df['turnover_rate'].iloc[-1]) if 'turnover_rate' in df.columns else 0.0
                
                return df
                
            except Exception as e:
                self.logger.error(f"获取港股数据失败: {str(e)}")
                return None
            
        except Exception as e:
            self.logger.error(f"获取港股数据时发生错误: {str(e)}")
            return None

    async def _get_us_stock_data(self, stock_code: str):
        """获取美股数据"""
        try:
            self.logger.info(f"正在获取美股数据: {stock_code}")
            
            try:
                # 获取历史数据
                df = self.ak.stock_us_daily(
                    symbol=stock_code,
                    adjust="qfq"
                )
                
                if df.empty:
                    self.logger.error(f"无法获取美股数据: {stock_code}")
                    return None
                    
                # 只保留最近180天的数据
                df = df.tail(180)
                
                # 获取美股名称和实时数据
                stock_info = self.ak.stock_us_spot_em()
                stock_name = ""
                if not stock_info.empty:
                    stock_match = stock_info[stock_info['代码'] == stock_code]
                    if not stock_match.empty:
                        stock_name = stock_match.iloc[0]['名称']
                
                # 重命名列
                column_map = {
                    'date': 'date',
                    'open': 'open',
                    'close': 'close',
                    'high': 'high',
                    'low': 'low',
                    'volume': 'volume',
                    'amount': 'amount',
                    'change_pct': 'change_pct'
                }
                
                df = df.rename(columns=column_map)
                
                # 添加股票信息
                df.attrs['stock_name'] = stock_name
                df.attrs['market_type'] = 'US'
                df.attrs['latest_price'] = float(df['close'].iloc[-1])
                df.attrs['latest_change'] = float(df['change_pct'].iloc[-1]) if 'change_pct' in df.columns else 0.0
                
                return df
                
            except Exception as e:
                self.logger.error(f"获取美股数据失败: {str(e)}")
                return None
            
        except Exception as e:
            self.logger.error(f"获取美股数据时发生错误: {str(e)}")
            return None

    def _get_currency_by_market(self, market_type: str) -> str:
        """根据市场类型获取货币单位"""
        currency_map = {
            'A': 'CNY',
            'HK': 'HKD',
            'US': 'USD',
            'ETF': 'CNY',
            'LOF': 'CNY'
        }
        return currency_map.get(market_type, 'CNY')
