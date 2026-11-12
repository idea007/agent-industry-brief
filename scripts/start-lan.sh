#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
server_dir="$project_dir/server"
client_dir="$project_dir/client"

lan_host="${RADAR_LAN_HOST:-0.0.0.0}"
lan_port="${RADAR_LAN_PORT:-80}"
web_port="${RADAR_WEB_PORT:-13000}"
api_port="${RADAR_API_PORT:-18000}"
lan_ip="${INTEL_RADAR_LAN_IP:-}"

if [[ -z "$lan_ip" ]]; then
  default_interface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}' || true)"
  if [[ -n "$default_interface" ]]; then
    lan_ip="$(ipconfig getifaddr "$default_interface" 2>/dev/null || true)"
  fi
fi

if [[ -z "$lan_ip" ]]; then
  echo "无法识别局域网 IP。请设置 INTEL_RADAR_LAN_IP 后重试。"
  exit 1
fi

if [[ ! -x "$server_dir/.venv/bin/python" ]]; then
  echo "服务端虚拟环境不存在，请先按 README 完成服务端安装。"
  exit 1
fi

if [[ ! -d "$client_dir/node_modules" ]]; then
  echo "客户端依赖不存在，请先在 client 目录执行 npm ci。"
  exit 1
fi

for port in "$lan_port" "$web_port" "$api_port"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "端口 $port 已被占用，请停止占用进程或通过 RADAR_*_PORT 指定其他端口。"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN
    exit 1
  fi
done

runtime_dir="$(mktemp -d)"
server_log="$runtime_dir/server.log"
client_log="$runtime_dir/client.log"
gateway_log="$runtime_dir/gateway.log"
server_pid=""
client_pid=""
gateway_pid=""

cleanup() {
  trap - INT TERM EXIT
  for pid in "$gateway_pid" "$client_pid" "$server_pid"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  wait >/dev/null 2>&1 || true
}

trap cleanup INT TERM EXIT

echo "正在构建手机客户端页面…"
(
  cd "$client_dir"
  NEXT_PUBLIC_API_BASE_URL="" RADAR_API_URL="http://127.0.0.1:$api_port" npm run build
)

(
  cd "$server_dir"
  exec .venv/bin/python -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "$api_port"
) >"$server_log" 2>&1 &
server_pid="$!"

(
  cd "$client_dir"
  exec node ./node_modules/next/dist/bin/next start \
    --hostname 127.0.0.1 \
    --port "$web_port"
) >"$client_log" 2>&1 &
client_pid="$!"

wait_for_url() {
  local label="$1"
  local url="$2"
  local log_file="$3"
  local pid="$4"
  local attempt
  for attempt in $(seq 1 60); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      echo "$label 启动失败："
      tail -40 "$log_file"
      exit 1
    fi
    if curl --noproxy "*" --silent --show-error --fail "$url" >/dev/null 2>&1; then
      return
    fi
    sleep 0.5
  done
  echo "$label 启动超时："
  tail -40 "$log_file"
  exit 1
}

wait_for_url "情报服务" "http://127.0.0.1:$api_port/health" "$server_log" "$server_pid"
wait_for_url "页面服务" "http://127.0.0.1:$web_port/" "$client_log" "$client_pid"

RADAR_LAN_HOST="$lan_host" \
RADAR_LAN_PORT="$lan_port" \
RADAR_WEB_PORT="$web_port" \
RADAR_API_PORT="$api_port" \
node "$script_dir/lan-gateway.mjs" >"$gateway_log" 2>&1 &
gateway_pid="$!"

wait_for_url "局域网入口" "http://127.0.0.1:$lan_port/health" "$gateway_log" "$gateway_pid"

echo "行业新闻简报已启动。"
if [[ "$lan_port" == "80" ]]; then
  echo "手机与电脑连接同一 Wi-Fi 后，请打开：http://$lan_ip/"
else
  echo "手机与电脑连接同一 Wi-Fi 后，请打开：http://$lan_ip:$lan_port/"
fi
echo "按 Ctrl+C 停止服务。"
echo "运行日志：$runtime_dir"

while
  kill -0 "$server_pid" >/dev/null 2>&1 &&
    kill -0 "$client_pid" >/dev/null 2>&1 &&
    kill -0 "$gateway_pid" >/dev/null 2>&1
do
  sleep 1
done

echo "有服务意外退出，最近日志如下："
tail -20 "$server_log" "$client_log" "$gateway_log"
exit 1
