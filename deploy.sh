#!/usr/bin/env bash
# 在服务器上运行：bash deploy.sh
set -e
DIR=/opt/stock-monitor
REPO=https://github.com/wdnmd2716/-.git
BRANCH=${BRANCH:-claude/bold-davinci-cf29y0}

command -v git >/dev/null || (apt-get update && apt-get install -y git python3-venv) || yum install -y git python3
[ -d $DIR/.git ] || git clone -b $BRANCH $REPO $DIR
cd $DIR && git pull
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cat > .env <<'ENV'
ANTHROPIC_API_KEY=
PUSHPLUS_TOKEN=
SERVERCHAN_KEY=
ENV
  chmod 600 .env
  echo ">>> 请编辑 $DIR/.env 填入密钥"
fi

# 每 10 分钟运行一次，脚本内部按纽约时间判断是否开盘
LINE="*/10 * * * * cd $DIR && set -a && . ./.env && set +a && .venv/bin/python monitor.py auto >> monitor.log 2>&1"
(crontab -l 2>/dev/null | grep -v stock-monitor; echo "$LINE") | crontab -
echo ">>> 已安装定时任务；测试：cd $DIR && set -a && . ./.env && .venv/bin/python monitor.py summary"
