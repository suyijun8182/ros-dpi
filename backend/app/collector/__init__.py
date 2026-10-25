"""UDP 监听：IPFIX/NetFlow（默认 2055）与 TZSP DNS 镜像（默认 37008）。"""
import asyncio
import socket


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, handler):
        self.handler = handler

    def datagram_received(self, data, addr):
        try:
            self.handler(data, addr[0].removeprefix("::ffff:"))
        except Exception as e:  # noqa: BLE001  单个坏包不能影响监听
            print(f"[collector] 处理数据包出错 {addr[0]}: {e!r}")


def _udp_socket(port: int) -> socket.socket:
    """优先建 IPv6 双栈 socket（显式关闭 IPV6_V6ONLY，Windows 默认是开的），不支持 IPv6 时退回 IPv4。"""
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        s.bind(("::", port))
    except OSError:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", port))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    s.setblocking(False)
    return s


async def start_listeners(engine, ipfix_port: int, tzsp_port: int):
    loop = asyncio.get_running_loop()
    transports = []
    for port, handler, name in (
        (ipfix_port, lambda d, a: engine.on_ipfix(d, a), "IPFIX/NetFlow"),
        (tzsp_port, lambda d, a: engine.on_tzsp(d, a), "TZSP-DNS"),
    ):
        try:
            sock = _udp_socket(port)
            t, _ = await loop.create_datagram_endpoint(lambda h=handler: _Proto(h), sock=sock)
            transports.append(t)
            print(f"[collector] {name} 监听 udp/{sock.getsockname()[1]}", flush=True)
        except OSError as e:
            print(f"[collector] {name} 无法监听 udp/{port}: {e}", flush=True)
    return transports
