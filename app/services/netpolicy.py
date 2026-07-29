"""Сетевая политика для исходящих SSH-подключений."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_BLOCKED_V4 = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]

_BLOCKED_V6 = [
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("100::/64"),
    ipaddress.ip_network("2001:db8::/32"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


class TargetRejected(ValueError):
    """Адрес запрещён политикой."""


@dataclass(frozen=True)
class ResolvedTarget:
    hostname: str
    ip: str
    family: int

    @property
    def is_ipv6(self) -> bool:
        return self.family == socket.AF_INET6


def _classify(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Возвращает причину отказа либо None, если адрес разрешён."""
    networks = _BLOCKED_V6 if ip.version == 6 else _BLOCKED_V4
    for net in networks:
        if ip in net:
            if net.is_loopback or str(net) in {"::1/128", "127.0.0.0/8"}:
                return "loopback-адрес"
            if str(net) == "169.254.0.0/16":
                return "link-local / метаданные облака"
            if ip.is_private:
                return "адрес внутренней сети"
            return "зарезервированный диапазон"
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return "непубличный адрес"
    return None


async def resolve_target(
    hostname: str, port: int, allow_private: bool = False, timeout: float = 5.0
) -> ResolvedTarget:
    """Резолвит имя и проверяет адрес. Возвращает IP для подключения."""
    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                hostname, port, type=socket.SOCK_STREAM
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise TargetRejected(f"не удалось разрешить имя «{hostname}»: таймаут") from exc
    except socket.gaierror as exc:
        raise TargetRejected(f"не удалось разрешить имя «{hostname}»") from exc

    if not infos:
        raise TargetRejected(f"имя «{hostname}» никуда не разрешается")

    if allow_private:
        family, _, _, _, sockaddr = infos[0]
        return ResolvedTarget(hostname=hostname, ip=sockaddr[0], family=family)

    first_ok: ResolvedTarget | None = None
    for family, _type, _proto, _canon, sockaddr in infos:
        raw_ip = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(raw_ip.split("%")[0])
        except ValueError:
            raise TargetRejected(f"некорректный адрес: {raw_ip}") from None

        reason = _classify(ip_obj)
        if reason is not None:
            logger.warning(
                "Отклонён адрес %s (%s -> %s): %s", hostname, hostname, raw_ip, reason
            )
            raise TargetRejected(f"{raw_ip} — {reason}")

        if first_ok is None:
            first_ok = ResolvedTarget(hostname=hostname, ip=raw_ip, family=family)

    if first_ok is None:
        raise TargetRejected(f"для «{hostname}» не нашлось подходящего адреса")
    return first_ok
