# Node Container Startup: Before vs After

## Quick Comparison

| Aspect | Before (Broken) | After (Fixed) |
|--------|----------------|---------------|
| **Container Status** | Exits immediately | Running |
| **Command** | None ❌ | `vnode-local start ...` ✅ |
| **Data Mount** | Bind mount | Docker volume ✅ |
| **Config Mount** | Single file | Directory ✅ |
| **Volumes Created** | 0 | 4 (data, vpn, ssh, squid) ✅ |
| **Environment Variables** | 1 | 5 ✅ |
| **TTY Mode** | False | True ✅ |

## Container Creation Comparison

### Before (Broken)

```python
container = client.containers.run(
    image,
    name=container_name,
    detach=True,
    volumes={
        config_host_path: {'bind': '/mnt/config.yaml', 'mode': 'ro'}
    },
    environment={
        'VANTAGE6_CONFIG_FILE': '/mnt/config.yaml'
    },
    labels={
        'vantage6-type': 'node',
        'vantage6-name': name
    }
)
```

**Problems**:
- ❌ No `command` - container has nothing to run, exits immediately
- ❌ Only config file mounted, no data directory
- ❌ No Docker volumes created
- ❌ Missing critical environment variables
- ❌ Config mounted as single file instead of directory
- ❌ No TTY mode

### After (Fixed)

```python
# Create Docker volumes first
data_volume = client.volumes.create(f"{container_name}-vol")
vpn_volume = client.volumes.create(f"{container_name}-vpn-vol")
ssh_volume = client.volumes.create(f"{container_name}-ssh-vol")
squid_volume = client.volumes.create(f"{container_name}-squid-vol")

# Build command
cmd = f"vnode-local start --name {name} --config /mnt/config/{config_file} --dockerized --system"

# Build volumes list
volumes = [
    f"{log_dir_host_path}:/mnt/log",
    f"{data_volume.name}:/mnt/data",
    f"{vpn_volume.name}:/mnt/vpn",
    f"{ssh_volume.name}:/mnt/ssh",
    f"{squid_volume.name}:/mnt/squid",
    f"{config_dir_host_path}:/mnt/config",
    "/var/run/docker.sock:/var/run/docker.sock"
]

# Build environment
env = {
    'DATA_VOLUME_NAME': data_volume.name,
    'VPN_VOLUME_NAME': vpn_volume.name,
    'SSH_TUNNEL_VOLUME_NAME': ssh_volume.name,
    'SSH_SQUID_VOLUME_NAME': squid_volume.name,
    'PRIVATE_KEY': '/mnt/private_key.pem'
}

# Create container
container = client.containers.run(
    image,
    command=cmd,
    volumes=volumes,
    detach=True,
    labels={
        f'{APPNAME}-type': 'node',
        'system': 'True',
        'name': name
    },
    environment=env,
    name=container_name,
    auto_remove=False,
    tty=True
)
```

**Fixes**:
- ✅ Command specified - container runs `vnode-local start`
- ✅ 7 mount points including data volume
- ✅ 4 Docker volumes created for persistence
- ✅ 5 environment variables for proper configuration
- ✅ Config directory mounted (not just single file)
- ✅ TTY enabled for proper I/O

## Why Each Change Matters

### 1. Command Parameter

**Why it's needed**: Without a command, the container starts and immediately exits because there's nothing to run.

**What it does**: 
- Runs `vnode-local start` inside the container
- Loads configuration from `/mnt/config/<name>.yaml`
- Connects to the vantage6 server
- Starts listening for tasks

### 2. Docker Volumes

**Why they're needed**: The node creates algorithm containers that need shared access to data.

**What they do**:
- **Data volume**: Stores task input/output, algorithm results
- **VPN volume**: Stores VPN configuration for node-to-node communication
- **SSH volume**: Stores SSH tunnel configuration for secure data access
- **Squid volume**: Stores proxy configuration for whitelisting

### 3. Environment Variables

**Why they're needed**: The node container needs to know which volumes to use when creating algorithm containers.

**What they configure**:
- `DATA_VOLUME_NAME`: Which volume to mount in algorithm containers
- `VPN_VOLUME_NAME`: Which volume contains VPN config
- `SSH_TUNNEL_VOLUME_NAME`: Which volume contains SSH config
- `SSH_SQUID_VOLUME_NAME`: Which volume contains proxy config
- `PRIVATE_KEY`: Path to encryption key

### 4. Config Directory Mount

**Why it's needed**: The node may need additional files (private keys, certificates) from the config directory.

**Before**: `/path/to/node.yaml` → `/mnt/config.yaml` (single file)
**After**: `/path/to/config/` → `/mnt/config/` (entire directory)

### 5. Volume Mount Format

**Why it changed**: Docker SDK accepts different formats for bind mounts vs volume mounts.

**Before** (dict format):
```python
volumes = {
    '/host/path': {'bind': '/container/path', 'mode': 'ro'}
}
```

**After** (list format):
```python
volumes = [
    '/host/path:/container/path',           # Bind mount
    'volume-name:/container/path'           # Volume mount
]
```

## Verification Steps

### Check Container is Running

```bash
docker ps | grep vantage6
```

Expected output:
```
CONTAINER ID   IMAGE                                          STATUS
abc123def456   harbor2.vantage6.ai/infrastructure/node:4.x.x  Up 2 minutes
```

### Check Container Logs

```bash
docker logs vantage6-<node-name>-system
```

Expected output should include:
```
INFO - Node package version '4.x.x'
INFO - Connecting server: http://your-server:5000/api
INFO - Successfully authenticated
INFO - Node connected to server
```

### Check Volumes Created

```bash
docker volume ls | grep <node-name>
```

Expected output:
```
vantage6-<node-name>-system-vol
vantage6-<node-name>-system-vpn-vol
vantage6-<node-name>-system-ssh-vol
vantage6-<node-name>-system-squid-vol
```

### Check Mounts

```bash
docker inspect vantage6-<node-name>-system | jq '.[0].Mounts[] | {Type, Source, Destination}'
```

Expected output:
```json
[
  {"Type": "bind", "Source": "/Users/johan/.config/vantage6/node/<name>/log", "Destination": "/mnt/log"},
  {"Type": "volume", "Source": "vantage6-<name>-system-vol", "Destination": "/mnt/data"},
  {"Type": "volume", "Source": "vantage6-<name>-system-vpn-vol", "Destination": "/mnt/vpn"},
  {"Type": "volume", "Source": "vantage6-<name>-system-ssh-vol", "Destination": "/mnt/ssh"},
  {"Type": "volume", "Source": "vantage6-<name>-system-squid-vol", "Destination": "/mnt/squid"},
  {"Type": "bind", "Source": "/Users/johan/.config/vantage6/node/<name>", "Destination": "/mnt/config"},
  {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock"}
]
```

## Troubleshooting

### Container Still Exits

1. Check logs: `docker logs vantage6-<name>-system`
2. Look for error messages about missing config or connectivity
3. Verify config file exists at: `${HOME}/.config/vantage6/node/<name>/<name>.yaml`
4. Verify server URL is accessible

### "Config file not found" Error

- Ensure config directory is mounted, not just the file
- Check that config file name matches in command: `/mnt/config/<name>.yaml`
- Verify host path exists: `ls -la ${HOME}/.config/vantage6/node/<name>/`

### "Cannot connect to server" Error

- Check `server_url` in config file
- Verify server is running and accessible
- Check firewall/network settings
- Ensure `api_path` matches server configuration

### Volume Permission Issues

- Check volume ownership: `docker volume inspect <volume-name>`
- Verify container runs with correct user
- Check host directory permissions if using bind mounts

## References

- Official vantage6 implementation: `vantage6/cli/node/start.py`
- Full comparison: `docs/VANTAGE6_OFFICIAL_ALIGNMENT.md`
- Path configuration: `docs/PATHS_AND_VOLUMES.md`
