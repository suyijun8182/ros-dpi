# RouterOS 配置说明

下文以容器主机 IP `192.168.88.10`、路由器 LAN `192.168.88.1` 为例。命令适用于 RouterOS 7。

## 1. 流量采集（必需）

```routeros
/ip traffic-flow set enabled=yes interfaces=all active-flow-timeout=1m inactive-flow-timeout=15s
/ip traffic-flow target add dst-address=192.168.88.10 port=2055 version=ipfix
```

- `interfaces=all`：上行包在 LAN 口入方向采集，下行包在 WAN 口入方向采集，两者合起来才完整。ROS-DPI 会按 LAN 网段判断方向，并自动丢弃内网互访和路由器自身的流量，不会重复计数。
- `active-flow-timeout=1m`：长连接每分钟上报一次，统计和速率才能接近实时。
- 也可用 `version=9`（NetFlow v9），两者都支持。

**FastTrack**：被 FastTrack 的连接可能不经过 Traffic Flow，导致统计偏少。对比概览页的“WAN 实时速率”（来自接口计数）和“采集速率”可以判断。如果差距明显，可以缩小 FastTrack 范围，或者关闭它（会增加 CPU 占用）。

## 2. DNS 嗅探（应用识别，强烈建议）

```routeros
/ip firewall mangle add chain=output  protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ip firewall mangle add chain=forward protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
```

- `output`：路由器自己作为 DNS 服务器时，发给终端的应答。
- `forward`：终端直连外部 DNS（如 223.5.5.5）时的应答；内网自建 DNS 服务器向上游查询时的应答也走这里。
- 只镜像 DNS 应答，数据量很小。

**作用**：流量记录里只有 IP 和端口。DNS 嗅探记下“这个 IP 是哪个域名解析出来的”，ROS-DPI 才能把发往该 IP 的流量认成抖音、微信等具体应用。它不影响流量字节数统计；没有它时，流量只能按 IP 段、端口识别为 HTTPS / QUIC 等通用协议。

**内网有自己的 DNS 服务器**（例如 AdGuard Home / Pi-hole 在 192.168.88.248，DHCP 下发的 DNS 是它）：

- 终端 → 内网 DNS 在同一网段，走交换机，路由器看不到，这一段嗅探不到。这没关系：ROS-DPI 的“IP → 域名”表是全网共用的，不需要知道是哪台终端查的。
- 内网 DNS → 上游 DNS（如 223.5.5.5）的应答要经过路由器，会被上面的 `forward` 规则嗅探到，效果和终端直接查询一样。
- 前提是内网 DNS 的**上游用普通 DNS（udp/53）**。上游设成 DoH / DoT（AdGuard Home 默认的 `https://dns10.quad9.net/dns-query` 之类）时，路由器只看到加密流量，DNS 应答数会一直是 0。解决方法二选一：把上游改成普通 DNS（如 `223.5.5.5`、`119.29.29.29`）；或者把上游改成路由器地址，并在路由器上开启 `/ip dns set allow-remote-requests=yes`，这样应答由 `output` 规则嗅探。
- 内网 DNS 有缓存，缓存命中时不会再向上游查询。ROS-DPI 会把每条对应关系保留 6 到 48 小时，一般够用。
- 可以在 **系统设置 → DNS 嗅探 → 应答来源** 确认：看到 223.5.5.5 等外网地址（标为“外网”）说明上游应答已经嗅探到了。

提高识别率：

- 在 DHCP 里把 DNS 下发为路由器地址，并开启 `/ip dns set allow-remote-requests=yes`。
- 浏览器 / 系统里的“安全 DNS（DoH）”会绕过嗅探，可以在终端上关闭，或用防火墙拦截常见 DoH 地址。

## 3. 只读 API 账号（可选）

```routeros
/user group add name=rosdpi policy=read,rest-api,api,!write,!policy,!sensitive
/user add name=rosdpi group=rosdpi password=<强密码> address=192.168.88.10
/ip service set www-ssl disabled=no   # REST API 走 HTTPS（或用 www 的 HTTP）
```

然后在 `.env` 设置：

```
ROS_URL=https://192.168.88.1
ROS_USER=rosdpi
ROS_PASSWORD=<强密码>
```

用于：DHCP 主机名、ARP / IPv6 邻居（IP↔MAC）、WAN 口实时速率、路由器 CPU / 内存，以及自动发现 LAN 的 IPv6 公网前缀。ROS-DPI 只发 GET 请求，不会修改路由器配置。

> 修改了这个用户组的权限后，已登录的会话仍沿用旧权限，需要重启容器或执行 `/user active request-logout [find name=rosdpi]`。

## 4. LAN 网段

ROS-DPI 用 LAN 网段判断哪一端是终端。默认是三个私网段，以下情况需要手动修改（`.env` 的 `LAN_CIDRS`，或 **系统设置 → 网络**）：

- **双 NAT**（WAN 口也是 192.168.x.x 等私网地址）：只填内网实际网段，否则 WAN 侧地址会被当成终端。
- **IPv6**：配置了 ROS API 时会自动加入 LAN 接口上的公网前缀；否则需要手动填写。

## 排错

**系统设置 → 运行状态** 会显示：

| 现象 | 检查 |
|---|---|
| 流量采集一直“等待数据” | 容器的 udp/2055 是否映射；主机防火墙；`/ip traffic-flow target print` |
| 已处理流很多，但全部“丢弃” | LAN 网段填错 |
| DNS 应答为 0 | mangle 规则是否命中（`/ip firewall mangle print stats`）；udp/37008 是否映射 |
| 识别率低 | 终端是否在用 DoH；在 **识别规则 → 未识别域名 Top** 里补规则 |
| 统计明显偏少 | FastTrack，见上文 |
