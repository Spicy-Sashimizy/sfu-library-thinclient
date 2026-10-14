# TrueNAS Setup Guide — SFU Library MCP Server

One-time setup for deploying the SFU Library MCP server on TrueNAS SCALE 25.04.1.

## Prerequisites

- TrueNAS SCALE 25.04.1 at <nas-ip>
- Docker v27.5.0 + Compose v2.32.3
- SSH user `<SSH_USER>` (key-based auth, ProxyJump via Windows host)
- `<SSH_USER>` sudo restricted to `/usr/bin/docker` only

## 1. ZFS Dataset Creation (Admin — TrueNAS Web Shell)

**These commands must be run by an admin user via TrueNAS Web Shell or SSH as `truenas_admin`.
The `<SSH_USER>` user cannot create ZFS datasets.**

```bash
zfs create MAIN/sfu-library-mcp
mkdir -p /mnt/MAIN/sfu-library-mcp/{app,secrets,logs,data}
chown -R <nas-user>:<nas-user> /mnt/MAIN/sfu-library-mcp
chmod 700 /mnt/MAIN/sfu-library-mcp/secrets
```

Resulting layout:
```
/mnt/MAIN/sfu-library-mcp/
├── app/          # Git clone or rsync target
├── secrets/      # chmod 700 credential files
├── logs/         # Persistent log volume
└── data/         # Server data volume
```

## 2. Create Secret Files (Admin — TrueNAS Web Shell)

```bash
echo -n "YOUR_ZOTERO_API_KEY" > /mnt/MAIN/sfu-library-mcp/secrets/zotero_api_key
echo -n "YOUR_ZOTERO_USER_ID" > /mnt/MAIN/sfu-library-mcp/secrets/zotero_user_id

chown <nas-user>:<nas-user> /mnt/MAIN/sfu-library-mcp/secrets/*
chmod 600 /mnt/MAIN/sfu-library-mcp/secrets/*
```

## 3. SSH Config (Dev Container)

Already configured in `~/.ssh/config`:
```
Host truenas
    HostName <nas-ip>
    User <nas-user>
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump windows-host

Host windows-host
    HostName host.docker.internal
    User <user>
    IdentityFile ~/.ssh/id_ed25519
```

## 4. First Deployment

From the dev container:
```bash
bash scripts/archive/deploy_opensearch_era/deploy.sh
```

## 5. Docker Cleanup (Optional)

Free ~54GB of unused images on TrueNAS:
```bash
# Run from TrueNAS Web Shell
sudo docker image prune -a --filter "until=720h"
```

## 6. Verification

```bash
bash scripts/archive/deploy_opensearch_era/healthcheck.sh
```
