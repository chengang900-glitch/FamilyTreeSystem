"""网络工具：受信代理下的真实客户端 IP 解析

安全约定：只有请求来自受信代理（默认仅本机回环）时才读取 X-Forwarded-For，
否则一律使用 TCP 连接的对端地址。这样外部请求无法通过伪造 XFF 绕过限流/审计。
"""
import ipaddress
import os

from flask import request

from server.service import settings

DEFAULT_TRUSTED = '127.0.0.1,::1'


def _networks(text: str):
    out = []
    for raw in (text or '').split(','):
        item = raw.strip()
        if not item:
            continue
        try:
            out.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return out


def trusted_networks():
    # 环境变量优先，便于容器编排一次性注入（无需先改数据库设置）
    raw = os.environ.get('FTS_TRUSTED_PROXIES') \
        or settings.get_str('security.trusted_proxies', DEFAULT_TRUSTED)
    return _networks(raw)


def is_trusted(ip: str, networks=None) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    nets = networks if networks is not None else trusted_networks()
    return any(addr in net for net in nets)


def client_ip() -> str:
    """返回可信的客户端 IP；非受信代理的 XFF 头一律忽略"""
    remote = request.remote_addr or ''
    if is_trusted(remote):
        forwarded = request.headers.get('X-Forwarded-For', '')
        for part in forwarded.split(','):
            candidate = part.strip()
            if candidate:
                return candidate
    return remote or 'unknown'
