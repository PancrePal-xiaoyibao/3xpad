import aiohttp
import base64
from .base import WechatAPIClientBase
from ..errors import UserLoggedOut
from loguru import logger

class ToolExtensionMixin(WechatAPIClientBase):
    async def get_msg_image(self, msg_id: str, to_wxid: str = None, data_len: int = 0, start_pos: int = 0) -> bytes:
        """获取消息中的图片内容。

        Args:
            msg_id (str): 消息ID
            to_wxid (str, optional): 接收人的wxid，如果不提供则使用自己的wxid
            data_len (int, optional): 图片大小，从图片XML中获取
            start_pos (int, optional): 开始位置，用于分段下载

        Returns:
            bytes: 图片的二进制数据

        Raises:
            UserLoggedOut: 未登录时调用
            根据error_handler处理错误
        """
        logger.debug(f"ToolExtension: get_msg_image called with msg_id={msg_id}, to_wxid={to_wxid}, data_len={data_len}, start_pos={start_pos}") # <--- 添加日志
        
        if not self.wxid:
            raise UserLoggedOut("请先登录")

        # 如果没有提供接收人的wxid，则使用自己的wxid
        if not to_wxid:
            to_wxid = self.wxid

        # 计算当前段的大小
        chunk_size = 64 * 1024  # 64KB
        current_chunk_size = min(chunk_size, data_len - start_pos)

        if current_chunk_size <= 0:
            logger.warning(f"无效的分段下载参数: start_pos={start_pos}, data_len={data_len}")
            return b""

        async with aiohttp.ClientSession() as session:
            # 根据提供的API文档构造请求参数
            json_param = {
                "Wxid": self.wxid,
                "ToWxid": to_wxid,
                "MsgId": int(msg_id),
                "DataLen": data_len,
                "CompressType": 0,
                "Section": {
                    "StartPos": start_pos,
                    "DataLen": current_chunk_size
                }
            }

            logger.debug(f"尝试下载图片分段: MsgId={msg_id}, ToWxid={to_wxid}, DataLen={data_len}, StartPos={start_pos}, ChunkSize={current_chunk_size}")
            response = await session.post(f'http://{self.ip}:{self.port}/VXAPI/Tools/DownloadImg', json=json_param)

            try:
                json_resp = await response.json()

                if json_resp.get("Success"):
                    logger.info(f"获取消息图片分段成功: MsgId={msg_id}, StartPos={start_pos}, ChunkSize={current_chunk_size}")
                    # 尝试从不同的响应格式中获取图片数据
                    data = json_resp.get("Data")

                    if isinstance(data, dict):
                        # 如果是字典，尝试获取buffer字段
                        if "buffer" in data:
                            return base64.b64decode(data["buffer"])
                        elif "data" in data and isinstance(data["data"], dict) and "buffer" in data["data"]:
                            return base64.b64decode(data["data"]["buffer"])
                        else:
                            # 如果没有buffer字段，尝试直接解码整个data
                            try:
                                return base64.b64decode(str(data))
                            except:
                                logger.error(f"无法解析图片数据字典: {data}")
                    elif isinstance(data, str):
                        # 如果是字符串，直接解码
                        try:
                            return base64.b64decode(data)
                        except:
                            logger.error(f"无法解析图片数据字符串: {data[:100]}...")
                    else:
                        logger.error(f"无法解析图片数据类型: {type(data)}")
                else:
                    error_msg = json_resp.get("Message", "Unknown error")
                    logger.error(f"下载图片分段失败: {error_msg}, StartPos={start_pos}")
                    # 如果是分段下载，不调用error_handler，避免中断下载过程
                    if start_pos == 0:
                        self.error_handler(json_resp)
            except Exception as e:
                logger.error(f"解析图片分段响应失败: {e}, StartPos={start_pos}")
                # 尝试直接获取二进制数据
                try:
                    raw_data = await response.read()
                    if raw_data and len(raw_data) > 100:  # 确保有足够的数据
                        logger.info(f"成功获取图片分段二进制数据: {len(raw_data)} 字节, StartPos={start_pos}")
                        return raw_data
                except Exception as bin_err:
                    logger.error(f"获取图片分段二进制数据失败: {bin_err}, StartPos={start_pos}")

            # 如果是第一段且失败，尝试使用备用API端点
            if start_pos == 0:
                try:
                    logger.debug(f"尝试使用备用API端点下载图片: MsgId={msg_id}")
                    simple_param = {"Wxid": self.wxid, "MsgId": int(msg_id)}
                    response = await session.post(f'http://{self.ip}:{self.port}/VXAPI/Msg/GetMsgImage', json=simple_param)
                    json_resp = await response.json()

                    if json_resp.get("Success"):
                        data = json_resp.get("Data")
                        if isinstance(data, str):
                            return base64.b64decode(data)
                        elif isinstance(data, dict) and "buffer" in data:
                            return base64.b64decode(data["buffer"])
                except Exception as e:
                    logger.error(f"备用API端点下载图片失败: {e}")

            return b""
