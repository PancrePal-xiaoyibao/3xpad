import requests
import re
import logging
from loguru import logger

quark_headers = {
    'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'accept': 'application/json, text/plain, */*',
    'content-type': 'application/json',
    'sec-ch-ua-mobile': '?0',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'sec-ch-ua-platform': '"Windows"',
    'origin': 'https://pan.quark.cn',
    'sec-fetch-site': 'same-site',
    'sec-fetch-mode': 'cors',
    'sec-fetch-dest': 'empty',
    'referer': 'https://pan.quark.cn/',
    'accept-encoding': 'gzip, deflate, br',
    'accept-language': 'zh-CN,zh;q=0.9'
}

waliso_headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-encoding': 'gzip, deflate, br, zstd',
    'accept-language': 'zh-CN,zh;q=0.9',
    'content-type': 'application/json',
    'origin': 'https://waliso.com',
    'referer': 'https://waliso.com/search',
    'sec-ch-ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
}

kkkob_headers = {
    'accept': '*/*',
    'accept-encoding': 'gzip, deflate',
    'accept-language': 'zh-CN,zh;q=0.9',
    'content-length': '68',
    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'sec-ch-ua-platform': '"Windows"',
    'origin': 'http://z.kkkob.com',
    'referer': 'http://z.kkkob.com/app/',
    'Proxy-Connection': 'keep-alive',
    'X-Requested-With': 'XMLHttpRequest'
}

class QURAK:
    def get_id_from_url(self, url):
        try:
            url = url.replace("https://pan.quark.cn/s/", "")
            pattern = r"(\w+)(#/list/share.*/(\w+))?"
            match = re.search(pattern, url)
            if match:
                pwd_id = match.group(1)
                if match.group(2):
                    pdir_fid = match.group(3)
                else:
                    pdir_fid = 0
                return pwd_id, pdir_fid
            else:
                return None, None
        except Exception as e:
            logger.error(f"[QURAK] 解析URL异常: {e}")
            return None, None

    # 可验证资源是否失效
    def get_stoken(self, pwd_id):
        if not pwd_id:
            return False, "Invalid URL"
            
        try:
            url = "https://drive-m.quark.cn/1/clouddrive/share/sharepage/token"
            querystring = {"pr": "ucpro", "fr": "h5"}
            payload = {"pwd_id": pwd_id, "passcode": ""}
            response = requests.request(
                "POST", url, json=payload, headers=quark_headers, params=querystring, timeout=3
            ).json()
            if response.get("data"):
                return True, response["data"]["stoken"]
            else:
                return False, response["message"]
        except Exception as e:
            logger.error(f"[QURAK] 验证资源异常: {e}")
            return False, str(e)

    # 新增瓦力搜索方法
    def get_waliso_search(self, qry_key: str, resource_type="QUARK"):
        """
        使用瓦力搜索API进行资源搜索
        支持夸克网盘(QUARK)和百度云(BDY)
        """
        # 使用v1接口
        url = "https://waliso.com/v1/search/disk"
        headers = waliso_headers.copy()
        
        # 搜索参数 - 更新为正确的格式
        params = {
            "page": 1,
            "q": qry_key,
            "user": "",
            "exact": False,
            "format": [],
            "share_time": "",
            "size": 15,
            "type": resource_type,
            "exclude_user": [],
            "adv_params": {"wechat_pwd": ""}
        }
        
        result_json = []
        try:
            logger.info(f"[QURAK] 开始瓦力搜索: {qry_key}, 资源类型: {resource_type}")
            
            # 禁用SSL警告
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # 使用不验证SSL证书的方式访问API
            response = requests.post(
                url, 
                json=params, 
                headers=headers, 
                timeout=15,
                verify=False,  # 不验证SSL证书
                allow_redirects=True  # 允许重定向
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    if data.get("code") == 200 and data.get("data") and data["data"].get("list"):
                        items = data["data"]["list"]
                        logger.info(f"[QURAK] 瓦力搜索找到 {len(items)} 个结果")
                        
                        i = 1
                        for item in items:
                            if i > 5:  # 最多返回5个结果
                                break
                                
                            title = item.get("disk_name", "未知标题").replace("<em>", "").replace("</em>", "")
                            url = item.get("link", "")
                            
                            if not url:
                                continue
                                
                            # 验证资源有效性
                            if resource_type == "QUARK" and "quark" in url:
                                pwd_id, _ = self.get_id_from_url(url)
                                is_sharing, _ = self.get_stoken(pwd_id)
                                
                                if is_sharing:
                                    item_dict = {
                                        'title': title,
                                        'url': url
                                    }
                                    result_json.append(item_dict)
                                    i += 1
                            # 百度云资源不做验证，直接返回
                            elif resource_type == "BDY" and ("baidu" in url or "pan.baidu" in url):
                                item_dict = {
                                    'title': title,
                                    'url': url
                                }
                                result_json.append(item_dict)
                                i += 1
                        
                        logger.info(f"[QURAK] 瓦力搜索验证后有效结果: {len(result_json)} 个")
                    else:
                        logger.warning(f"[QURAK] 瓦力搜索结果为空或API返回错误: {data.get('msg')}")
                except ValueError as json_err:
                    logger.error(f"[QURAK] 瓦力搜索JSON解析错误: {json_err}")
            else:
                logger.error(f"[QURAK] 瓦力搜索请求失败，状态码: {response.status_code}")
                
        except Exception as e:
            logger.error(f"[QURAK] 瓦力搜索异常: {e}")
            
        return result_json
        
    # 更新为使用新API的方法
    def get_qry_external_4(self, qry_key: str, resource_type="QUARK"):
        """
        使用waliso.com的新API搜索资源，支持夸克网盘和百度云
        """
        return self.get_waliso_search(qry_key, resource_type)

    # 百度云搜索功能
    def get_baidu_search(self, qry_key: str):
        """
        使用瓦力搜索API搜索百度云资源
        """
        return self.get_waliso_search(qry_key, "BDY")

    # 查询资源1
    def get_qry_external(self, qry_key: str):
        url = f"http://www.662688.xyz/api/get_zy"
        params = {
            "keyword": qry_key,
        }
        items_json = []
        msg = '外部资源1查询结果：\n'
        try:
            response = requests.get(url, params=params, timeout=1)
            # 检查请求是否成功
            if response.status_code == 200:
                # 解析返回的JSON数据
                data = response.json()
                # 打印返回的数据，或者进行其他处理

                i = 1
                if data.get("data"):
                    first_three_items = data['data']
                    # 打印结果
                    for item in first_three_items:
                        item_str = str(item)  # 将item转换为字符串
                        if 'quark' in item_str and i <=5:
                            # 判断夸克资源是否失效
                            pwd_id, pdir_fid = self.get_id_from_url(item['url'])
                            is_sharing, stoken = self.get_stoken(pwd_id)
                            if is_sharing:
                                # msg += str(i) + '.' + f"{item['title']}\n{item['url']}\n"
                                # 创建一个字典，包含标题和URL
                                item_dict = {
                                    'title': item['title'],
                                    'url': item['url']
                                }
                                # 将字典添加到列表中
                                items_json.append(item_dict)
                                i += 1
                else:
                    msg += '未查询到数据1'
            else:
                msg += '查询请求失败1'
        except Exception:
            msg += f"查询请求失败1"

        return items_json

    # 查询资源2
    def get_qry_external_2(self, qry_key: str):
        url = f"https://www.hhlqilongzhu.cn/api/ziyuan_nanfeng.php"
        params = {
            "keysearch": qry_key,
        }
        items_json = []
        msg = '外部资源2查询结果：\n'

        try:
            response = requests.get(url, params=params, timeout=1)
            # 检查请求是否成功
            if response.status_code == 200:
                # 解析返回的JSON数据
                data = response.json()

                i = 1
                if data.get("data"):
                    first_three_items = data['data']
                    # 打印结果
                    for item in first_three_items:
                        item_str = str(item)  # 将item转换为字符串
                        if 'quark' in item_str and i <=5:
                            url = item['data_url'].split("链接：")[1]
                            title = item['title']
                            # 判断夸克资源是否失效
                            pwd_id, pdir_fid = self.get_id_from_url(url)
                            is_sharing, stoken = self.get_stoken(pwd_id)
                            if is_sharing:
                                # msg += str(i) + '.' + f"{item['title']}\r\n{url}\n"
                                # 创建一个字典，包含标题和URL
                                item_dict = {
                                    'title': title,
                                    'url': url
                                }
                                # 将字典添加到列表中
                                items_json.append(item_dict)
                                i += 1
                else:
                    msg += '未查询到数据2'
                    print(msg)
            else:
                msg += '查询请求失败2'
                print(msg)
        except Exception:
            msg += f"查询请求失败2"
            print(msg)

        return items_json

    # 查询资源3
    def get_qry_external_3(self, qry_key: str):
        url = f"https://v.funletu.com/search"
        headers = quark_headers.copy()
        headers['origin'] = 'https://pan.funletu.com'
        headers['referer'] = 'https://pan.funletu.com/'
        params = {
                    "style": "get",
                    "datasrc": "search",
                    "query": {
                        "id": "",
                        "datetime": "",
                        "commonid": 1,
                        "parmid": "",
                        "fileid": "",
                        "reportid": "",
                        "validid": "",
                        "searchtext": qry_key
                    },
                    "page": {
                        "pageSize": 10,
                        "pageIndex": 1
                    },
                    "order": {
                        "prop": "id",
                        "order": "desc"
                    },
                    "message": "请求资源列表数据"
                }

        msg = '外部资源3查询结果：\n'
        result_json = []
        try:
            response = requests.post(url, json=params, headers=headers, timeout=1).json()
            print(response)

            # 检查请求是否成功
            if response['status'] == 200:  # 假设0表示成功
                i = 1
                if response['data']:
                    first_three_items = response['data']
                    # 打印结果
                    for item in first_three_items:
                        item_str = str(item)  # 将item转换为字符串
                        if 'quark' in item_str and i <= 5:
                            url = item['url'].replace("?entry=funletu", "", 1)
                            title = item['title']
                            # 判断夸克资源是否失效
                            pwd_id, pdir_fid = self.get_id_from_url(url)
                            is_sharing, stoken = self.get_stoken(pwd_id)
                            if is_sharing:
                                # msg += str(i) + '.' + f"{item['title']}\r\n{url}\n"
                                item_dict = {
                                    'url': url,
                                    'title': title
                                }
                                # 将字典添加到列表中
                                result_json.append(item_dict)
                                i += 1
                else:
                    msg += '未查询到数据3'
                    print(msg)
            else:
                msg += '查询请求失败3'
                print(msg)
        except Exception:
            msg += f"查询请求失败3"
            print(msg)

        return result_json
        
    def get_qry_external_5(self, qry_key: str):
        url = f"https://api.cloudpan.cn/index/search"
        headers = quark_headers.copy()
        headers['origin'] = 'https://cloudpan.cn'
        headers['referer'] = 'https://cloudpan.cn/'
        params = {"page": 1, "pageSize": 20, "searchText": qry_key, "fileType": 0}

        result_json = []
        msg = '外部资源5查询结果：\n'

        try:
            response = requests.post(url, json=params, headers=headers, timeout=1).json()
            print(response)

            # 检查请求是否成功
            if response['code'] == 200:  # 假设0表示成功
                i = 1
                if response['data']:
                    first_three_items = response['data']['records']
                    # 打印结果
                    for item in first_three_items:
                        item_str = str(item)  # 将item转换为字符串
                        if i <= 5:
                            title = item['title']
                            url = 'https://pan.quark.cn/s/' + item['shareUrl']
                            # 判断夸克资源是否失效
                            pwd_id, pdir_fid = self.get_id_from_url(url)
                            is_sharing, stoken = self.get_stoken(pwd_id)
                            if is_sharing:
                                # msg += str(i) + '.' + f"{title}\r\n{url}\n"
                                item_dict = {
                                    'url': url,
                                    'title': title.encode('utf-8').decode('utf-8')
                                }
                                # 将字典添加到列表中
                                result_json.append(item_dict)
                                i += 1
                else:
                    msg += '未查询到数据'
            else:
                msg += '查询请求失败'
        except Exception:
            msg += f"查询请求失败"

        return result_json

    def get_kkkob_token(self):
        try:
            url = 'http://z.kkkob.com/v/api/getToken'
            # 使用 requests 获取网页内容
            response = requests.get(url)
            if response.status_code == 200:
                return response.json().get('token')
        except Exception as e:
            print(e)
        return ''

    def get_kkkob_result(self, qry: str, url: str, token: str):
        result_json = []
        msg = '查询结果kk：\n'
        try:
            headers = kkkob_headers.copy()
            params = {"name": qry, "token": token}
            response = requests.post(url, data=params, headers=headers, timeout=1)
            # print(response)
            # 检查请求是否成功
            if response.status_code == 200:
                response = response.json()
                i = 1
                if response['list']:
                    first_three_items = response['list']
                    # 打印结果
                    for item in first_three_items:
                        item_str = str(item)  # 将item转换为字符串
                        if 'quark' in item_str and i <= 3:
                            title = item['question']

                            # 正则表达式，用于匹配以https://开头，包含pan.quark.cn的链接
                            pattern = r'https?://pan\.quark\.cn/[^ ]+'

                            # 使用re.search查找匹配的链接
                            match = re.search(pattern, item['answer'])
                            url = match.group(0)
                            # url = item['answer'].replace(title + "链接：", "", 1)
                            # 判断夸克资源是否失效
                            pwd_id, pdir_fid = self.get_id_from_url(url)
                            is_sharing, stoken = self.get_stoken(pwd_id)
                            if is_sharing:
                                # msg += str(i) + '.' + f"{item['title']}\r\n{url}\n"
                                item_dict = {
                                    'url': url,
                                    'title': title
                                }
                                # 将字典添加到列表中
                                result_json.append(item_dict)
                                i += 1
                else:
                    msg += '未查询到数据kk'
            else:
                msg += '查询请求失败kk'
        except Exception as e:
            print(e)
        return result_json

    def qry_kkkob(self, qry: str):

        result_json = []

        # 获取token
        token = self.get_kkkob_token()
        if token == '':
            return result_json

        result_json += self.get_kkkob_result(qry, 'http://z.kkkob.com/v/api/getJuzi', token)
        result_json += self.get_kkkob_result(qry, 'http://z.kkkob.com/v/api/search', token)
        result_json += self.get_kkkob_result(qry, 'http://z.kkkob.com/v/api/getDJ', token)
        result_json += self.get_kkkob_result(qry, 'http://z.kkkob.com/v/api/getXiaoyu', token)
        result_json += self.get_kkkob_result(qry, 'http://z.kkkob.com/v/api/getSearchX', token)

        return result_json