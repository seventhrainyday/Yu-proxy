# Yu-proxy Docker 部署
# 需要 TUN 设备与 NET_ADMIN 权限（OpenVPN 拨号必需）
FROM python:3.12-alpine

RUN apk add --no-cache openvpn iproute2 iptables

WORKDIR /opt/Yu-proxy
COPY *.py ./
COPY config.json /etc/Yu-proxy/config.json

# 数据目录（节点缓存、统计、事件、自定义节点、出口配置）
VOLUME ["/var/lib/Yu-proxy", "/etc/Yu-proxy"]

EXPOSE 52051 52052

CMD ["python3", "/opt/Yu-proxy/main.py", "-c", "/etc/Yu-proxy/config.json", "daemon"]
