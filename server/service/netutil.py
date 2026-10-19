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


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def client_ip() -> str:
    """返回可信的客户端 IP；非受信代理的 XFF 头一律忽略。

    注意：受信代理通常把客户端真实地址追加到 XFF 末尾，而客户端可以自己
    伪造最左边的值。因此必须从右往左取第一个「非受信代理」地址，不能取首段。
    """
    remote = request.remote_addr or ''
    if not is_trusted(remote):
        return remote or 'unknown'
    forwarded = request.headers.get('X-Forwarded-For', '')
    chain = [part.strip() for part in forwarded.split(',') if part.strip()]
    for candidate in reversed(chain):
        if not _valid_ip(candidate):
            continue
        if not is_trusted(candidate):
            return candidate
    for candidate in reversed(chain):
        if _valid_ip(candidate):
            return candidate
    return remote or 'unknown'
