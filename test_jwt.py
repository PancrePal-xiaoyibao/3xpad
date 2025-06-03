#!/usr/bin/env python3
import sys
import time
import jwt
import logging

# 尝试导入 tomllib，如果失败则使用 tomli
try:
    import tomllib
except ImportError:
    import tomli as tomllib

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def load_config():
    """加载配置文件"""
    try:
        with open("plugins/GetWeather/config.toml", "rb") as f:
            plugin_config = tomllib.load(f)
            config = plugin_config["GetWeather"]
            logger.info("成功加载配置文件")
            return config
    except Exception as e:
        logger.error(f"加载配置文件失败: {str(e)}")
        raise

def generate_jwt_token(config):
    """生成JWT token"""
    try:
        logger.info("开始生成JWT token...")
        logger.debug(f"使用的配置: kid={config['jwt-kid']}, sub={config['jwt-sub']}")
        
        # 设置过期时间为15分钟
        now = int(time.time())
        payload = {
            'iat': now - 30,  # 提前30秒
            'exp': now + 900,  # 15分钟后过期
            'sub': config['jwt-sub']
        }
        
        headers = {
            'alg': 'EdDSA',
            'kid': config['jwt-kid']
        }
        
        logger.debug(f"JWT payload: {payload}")
        logger.debug(f"JWT headers: {headers}")
        
        # 生成JWT
        token = jwt.encode(
            payload, 
            config['api-key'],
            algorithm='EdDSA', 
            headers=headers
        )
        
        logger.info("JWT token生成成功")
        logger.debug(f"生成的JWT token: {token}")
        return token
        
    except Exception as e:
        logger.error(f"生成JWT token时发生错误: {str(e)}")
        logger.exception("详细错误信息:")
        raise

def main():
    try:
        # 加载配置
        config = load_config()
        
        # 生成JWT token
        token = generate_jwt_token(config)
        
        # 打印结果
        print("\n=== JWT Token ===")
        print(token)
        print("\n=== 配置信息 ===")
        print(f"API Host: {config['api-host']}")
        print(f"JWT KID: {config['jwt-kid']}")
        print(f"JWT SUB: {config['jwt-sub']}")
        
    except Exception as e:
        logger.error(f"测试失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 