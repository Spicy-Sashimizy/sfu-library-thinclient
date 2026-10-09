#!/bin/bash
# One-shot trigger: rebuild the serve instance as soon as the tenancy can launch
# paid shapes (i.e. the pay-as-you-go upgrade has landed). Run every few minutes
# by systemd/sfu-rebuild-trigger.timer on the broker box. Until then the rebuild
# script's preflight exits 2 without changing anything. After a launch it writes
# rebuild.launched and this trigger disables itself, success or not.
cd /home/ubuntu/demo_broker || exit 1
PY=/home/ubuntu/broker-venv/bin/python3
exec 9>rebuild_trigger.lock
flock -n 9 || exit 0
if [ ! -f rebuild.launched ]; then
  "$PY" rebuild_serve_instance.py --execute --hand-to-broker --notify \
      --ssh-authorized-key "$(head -1 /home/ubuntu/.ssh/authorized_keys)" \
      > rebuild_trigger.last.log 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) rc=$rc $(grep -m1 -E 'PREFLIGHT FAIL|launched|-> [0-9]{3}:' rebuild_trigger.last.log | cut -c1-160)" >> rebuild_trigger.log
  [ -f rebuild.launched ] && cp rebuild_trigger.last.log "rebuild_trigger.launch-$(date -u +%Y%m%dT%H%M%SZ).log"
fi
if [ -f rebuild.launched ]; then
  sudo -n systemctl disable --now sfu-rebuild-trigger.timer
fi
exit 0
