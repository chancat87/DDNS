# coding=utf-8
"""
HuaweiDNS API
华为DNS解析操作库
https://support.huaweicloud.com/api-dns/zh-cn_topic_0037134406.html
@author: cybmp3
"""


from hashlib import sha256
from hmac import new as hmac
from binascii import hexlify
from json import loads as jsondecode, dumps as jsonencode
from logging import debug, info, warning
from datetime import datetime

try:  # python 3
    from http.client import HTTPSConnection
    from urllib.parse import urlencode
except ImportError:  # python 2
    from httplib import HTTPSConnection
    from urllib import urlencode


__author__ = 'New Future'
BasicDateFormat = "%Y%m%dT%H%M%SZ"
Algorithm = "SDK-HMAC-SHA256"


# __all__ = ["request", "ID", "TOKEN", "PROXY"]


class Config:
    ID = "id"  # AK
    TOKEN = "TOKEN"  # AS
    PROXY = None  # 代理设置
    TTL = None


class API:
    # API 配置
    SCHEME = 'https'
    SITE = 'dns.myhuaweicloud.com'  # API endpoint


def HexEncodeSHA256Hash(data):
    sha = sha256()
    sha.update(data)
    return sha.hexdigest()


def StringToSign(canonical_request, t):
    b = HexEncodeSHA256Hash(canonical_request)
    return "%s\n%s\n%s" % (Algorithm, datetime.strftime(t, BasicDateFormat), b)


def CanonicalHeaders(headers, signed_headers):
    a = []
    __headers = {}
    for key in headers:
        key_encoded = key.lower()
        value = headers[key]
        value_encoded = value.strip()
        __headers[key_encoded] = value_encoded
    for key in signed_headers:
        a.append(key + ":" + __headers[key])
    return '\n'.join(a) + "\n"


def request(method, path, param=None, body=None, **params):
    # path 是不带host但是 前面需要带 / , body json 字符串或者自己从dict转换下
    # 也可以自己改成 判断下是不是post 是post params就是body
    if param:
        params.update(param)

    query = urlencode(sorted(params.items()))
    headers = {"content-type": "application/json"}  # 初始化header
    headers["X-Sdk-Date"] = datetime.strftime(
        datetime.utcnow(), BasicDateFormat)
    headers["host"] = API.SITE
    # 如何后来有需要把header头 key转换为小写 value 删除前导空格和尾随空格
    sign_headers = []
    for key in headers:
        sign_headers.append(key.lower())
    # 先排序
    sign_headers.sort()

    if body is None:
        body = ""

    hex_encode = HexEncodeSHA256Hash(body.encode('utf-8'))
    # 生成文档中的CanonicalRequest
    canonical_headers = CanonicalHeaders(headers, sign_headers)

    # 签名中的path 必须 / 结尾
    if path[-1] != '/':
        sign_path = path + "/"
    else:
        sign_path = path

    canonical_request = "%s\n%s\n%s\n%s\n%s\n%s" % (method.upper(), sign_path, query,
                                                    canonical_headers, ";".join(sign_headers), hex_encode)

    hashed_canonical_request = HexEncodeSHA256Hash(
        canonical_request.encode('utf-8'))

    # StringToSign
    str_to_sign = "%s\n%s\n%s" % (
        Algorithm, headers['X-Sdk-Date'], hashed_canonical_request)

    secret = Config.TOKEN
    # 计算签名  HexEncode(HMAC(Access Secret Key, string to sign))
    signature = hmac(secret.encode(
        'utf-8'), str_to_sign.encode('utf-8'), digestmod=sha256).digest()
    signature = hexlify(signature).decode()
    # 添加签名信息到请求头
    auth_header = "%s Access=%s, SignedHeaders=%s, Signature=%s" % (
        Algorithm, Config.ID, ";".join(sign_headers), signature)
    headers['Authorization'] = auth_header
    # 创建Http请求

    if Config.PROXY:
        conn = HTTPSConnection(Config.PROXY)
        conn.set_tunnel(API.SITE, 443)
    else:
        conn = HTTPSConnection(API.SITE)
    conn.request(method, API.SCHEME + "://" + API.SITE +
                 path + '?' + query, body, headers)
    info(API.SCHEME + "://" + API.SITE + path + '?' + query, body)
    resp = conn.getresponse()
    data = resp.read().decode('utf8')
    resp.close()
    if resp.status < 200 or resp.status >= 300:

        warning('%s : error[%d]: %s', path, resp.status, data)
        raise Exception(data)
    else:
        data = jsondecode(data)
        debug('%s : result:%s', path, data)
        return data


def get_zone_id(domain):
    """
    切割域名获取主域名和对应ID https://support.huaweicloud.com/api-dns/dns_api_62003.html
    优先匹配级数最长的主域名
    """
    zoneid = None
    domain_slice = domain.split('.')
    index = len(domain_slice)
    root_domain = '.'.join(domain_slice[-2:])
    zones = request('GET', '/v2/zones', limit=500, name=root_domain)['zones']
    while (not zoneid) and (index >= 2):
        domain = '.'.join(domain_slice[-index:]) + '.'
        zone = next((z for z in zones if domain == (z.get('name'))), None)
        zoneid = zone and zone['id']
        index -= 1
    return zoneid


def get_records(zoneid, **conditions):
    """
        获取记录ID
        返回满足条件的所有记录[]
        https://support.huaweicloud.com/api-dns/dns_api_64004.html
        TODO 大于500翻页
    """
    cache_key = zoneid + "_" + \
        conditions.get('name', "") + "_" + conditions.get('type', "")
    if not hasattr(get_records, 'records'):
        get_records.records = {}  # "静态变量"存储已查询过的id
        get_records.keys = ('id', 'type', 'name', 'records', 'ttl')

    if zoneid not in get_records.records:
        get_records.records[cache_key] = {}

        data = request('GET', '/v2/zones/' + zoneid + '/recordsets',
                       limit=500, **conditions)

        # https://{DNS_Endpoint}/v2/zones/2c9eb155587194ec01587224c9f90149/recordsets?limit=&offset=
        if data:
            for record in data['recordsets']:
                info(record)
                get_records.records[cache_key][record['id']] = {
                    k: v for (k, v) in record.items() if k in get_records.keys}
    records = {}
    for (zid, record) in get_records.records[cache_key].items():
        for (k, value) in conditions.items():
            if record.get(k) != value:
                break
        else:  # for else push
            records[zid] = record
    return records


def update_record(domain, value, record_type='A'):
    """
        更新记录
        update
        https://support.huaweicloud.com/api-dns/UpdateRecordSet.html
        add
        https://support.huaweicloud.com/api-dns/dns_api_64001.html
    """
    info(">>>>>%s(%s)", domain, record_type)
    zoneid = get_zone_id(domain)
    if not zoneid:
        raise Exception("invalid domain: [ %s ] " % domain)
    domain += '.'
    records = get_records(zoneid, name=domain, type=record_type)
    cache_key = zoneid + "_" + domain + "_" + record_type
    result = {}
    if records:  # update
        for (rid, record) in records.items():
            if record['records'] != value:
                """
                PUT https://{endpoint}/v2/zones/{zone_id}/recordsets/{recordset_id}

                {
                    "name" : "www.example.com.",
                    "description" : "This is an example record set.",
                    "type" : "A",
                    "ttl" : 3600,
                    "records" : [ "192.168.10.1", "192.168.10.2" ]
                }
                """
                body = {
                    "name": domain,
                    "description": "Managed by DDNS.",
                    "type": record_type,
                    "records": [
                        value
                    ]
                }
                # 如果TTL不为空，则添加到字典中
                if Config.TTL is not None:
                    body['ttl'] = Config.TTL
                res = request('PUT', '/v2/zones/' + zoneid + '/recordsets/' + record['id'],
                              body=str(jsonencode(body)))
                if res:
                    get_records.records[cache_key][rid]['records'] = value
                    result[rid] = res.get("name")
                else:
                    result[rid] = "Update fail!\n" + str(res)
            else:
                result[rid] = domain
    else:  # create
        body = {
            "name": domain,
            "description": "Managed by DDNS.",
            "type": record_type,
            "records": [
                value
            ]
        }
        # 如果TTL不为空，则添加到字典中
        if Config.TTL is not None:
            body['ttl'] = Config.TTL
        res = request('POST', '/v2/zones/' + zoneid + '/recordsets',
                      body=str(jsonencode(body)))
        if res:
            get_records.records[cache_key][res['id']] = res
            result = res
        else:
            result = domain + " created fail!"
    return result
