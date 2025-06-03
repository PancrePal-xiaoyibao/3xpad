import requests
import random
import string
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from colorama import init, Fore
import re

# 初始化 colorama
init()

VALID_CODES_FILE = "valid_codes.txt"  # 有效兑换码文件
CHECKED_CODES_FILE = "checked_codes.txt"  # 已检测兑换码文件
LAST_CODE_FILE = "last_code.txt"  # 记录最后一个检测的兑换码

# 用于线程同步
lock = threading.Lock()
checked_codes = set()  # 已检测的兑换码集合
total_checks = 0  # 检测总数
valid_count = 0  # 有效兑换码数量

def extract_code_from_url(url):
    """从URL中提取邀请码"""
    try:
        code = url.split('code=')[1].split(')')[0].split(']')[0]
        return code
    except:
        return None

def load_checked_codes():
    """加载已检测的兑换码"""
    global checked_codes
    if os.path.exists(CHECKED_CODES_FILE):
        with open(CHECKED_CODES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                code = line.strip()
                if code:
                    checked_codes.add(code)
    print(f"已加载 {len(checked_codes)} 个已检测的兑换码")

def save_checked_code(code, is_valid, result=None):
    """保存已检测的兑换码"""
    with lock:
        # 添加到内存集合
        checked_codes.add(code)
        # 添加到已检测文件
        with open(CHECKED_CODES_FILE, "a", encoding="utf-8") as f:
            f.write(f"{code}\n")
        # 保存最后检测的兑换码
        with open(LAST_CODE_FILE, "w", encoding="utf-8") as f:
            f.write(code)
        # 如果有效，保存到有效兑换码文件
        if is_valid and result:
            save_valid_code(code, result)

def save_valid_code(code, result):
    """保存有效的兑换码"""
    with open(VALID_CODES_FILE, "a", encoding="utf-8") as f:
        f.write(f"优惠码: {code}\n")
        f.write(f"结果: {json.dumps(result, indent=2, ensure_ascii=False)}\n")
        f.write("-" * 50 + "\n")

def check_code(code):
    """检测优惠码是否有效"""
    global total_checks, valid_count

    # 如果已检测过，跳过
    if code in checked_codes:
        return False, code, None

    # 模拟浏览器访问邀请链接
    url = f"https://cursor.com/cn/referral?code={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    try:
        # 访问邀请链接
        response = requests.get(url, headers=headers, allow_redirects=True)
        
        # 检查响应内容
        content = response.text.lower()  # 转换为小写以进行不区分大小写的检查
        
        # 检查是否包含无效标记
        is_invalid = any([
            "invalid referral code" in content,
            "referral code is invalid" in content,
            "referral code has expired" in content,
            "referral code not found" in content
        ])
        
        is_valid = not is_invalid
        
        result = {
            "status_code": response.status_code,
            "url": response.url,
            "is_valid": is_valid,
            "content_check": "包含无效标记" if is_invalid else "未发现无效标记"
        }

        with lock:
            total_checks += 1
            if is_valid:
                valid_count += 1

        color = Fore.GREEN if is_valid else Fore.RED
        print(f"[{total_checks}] 优惠码 ---- {code} ---- 状态码 {response.status_code} ---- 有效性: {color}{is_valid}{Fore.RESET}")

        # 保存检测结果
        save_checked_code(code, is_valid, result)
        return is_valid, code, result
    except Exception as e:
        print(f"优惠码 ---- {code} ---- 检测失败: {str(e)}")
        return False, code, None

def check_codes_from_file(file_path):
    """从文件中读取并检查邀请码"""
    print("开始从文件中检查邀请码...")
    print("=" * 60)
    
    # 确保输出文件存在
    if not os.path.exists(VALID_CODES_FILE):
        with open(VALID_CODES_FILE, "w", encoding="utf-8") as f:
            f.write("有效的优惠码列表:\n")
    
    # 加载已检测的兑换码
    load_checked_codes()
    
    # 读取文件中的邀请码
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        # 使用正则表达式匹配所有邀请码
        urls = re.findall(r'https://cursor\.com/referral\?code=[A-Z0-9]+', content)
        
        total_codes = len(urls)
        print(f"从文件中找到 {total_codes} 个邀请码")
        
        for url in urls:
            code = extract_code_from_url(url)
            if code:
                check_code(code)
                time.sleep(random.uniform(0.3, 0.8))  # 添加随机延迟
    
    print(f"\n检测完成。共检查了 {total_checks} 个兑换码，找到 {valid_count} 个有效码")
    print(f"有效推荐码保存在: {VALID_CODES_FILE}")
    print(f"已检测兑换码保存在: {CHECKED_CODES_FILE}")
    print(f"最后检测的兑换码保存在: {LAST_CODE_FILE}")

if __name__ == "__main__":
    check_codes_from_file("/Users/qinxiaoqiang/Downloads/cursor.txt")