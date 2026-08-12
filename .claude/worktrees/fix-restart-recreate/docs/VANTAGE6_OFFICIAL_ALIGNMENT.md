# Vantage6 Official Implementation Alignment

## Overview

This document describes how the Node Manager's container creation logic has been updated to match the official vantage6 CLI implementation (`v6 node start` command).

## Critical Differences Identified

### 1. Missing Container Command ⚠️ **CRITICAL**

**Problem**: The container was created without a command, causing it to exit immediately.

**Official Implementation** (`vantage6/cli/node/start.py`, lines 257-261):
```python
system_folders_option = "--system" if system_folders else ""
cmd = (
    f"vnode-local start --name {name} --config /mnt/config.yaml"
    f" --dockerized {system_folders_option}"
)
```

**Fix Applied**:
```python
system_folders_option = "--system" if config['type'] == 'system' else "--user"
cmd = f"vnode-local start --name {name} --config /mnt/config/{config_path.name} --dockerized {system_folders_option}"
```

### 2. Missing Docker Volumes ⚠️ **CRITICAL**

**Problem**: The official implementation uses Docker volumes for persistent storage, not bind mounts for `/mnt/data`.

**Official Implementation** (`vantage6/cli/node/start.py`, lines 138-141):
```python
data_volume = docker_client.volumes.create(ctx.docker_volume_name)
vpn_volume = docker_client.volumes.create(ctx.docker_vpn_volume_name)
ssh_volume = docker_client.volumes.create(ctx.docker_ssh_volume_name)
squid_volume = docker_client.volumes.create(ctx.docker_squid_volume_name)
```

**Fix Applied**:
```python
data_volume_name = f"{container_name}-vol"
vpn_volume_name = f"{container_name}-vpn-vol"
ssh_volume_name = f"{container_name}-ssh-vol"
squid_volume_name = f"{container_name}-squid-vol"

# Create volumes if they don't exist
data_volume = client.volumes.get_or_create(data_volume_name)
vpn_volume = client.volumes.get_or_create(vpn_volume_name)
ssh_volume = client.volumes.get_or_create(ssh_volume_name)
squid_volume = client.volumes.get_or_create(squid_volume_name)
```

### 3. Different Volume Mount Structure ⚠️ **HIGH**

**Problem**: Volume mounts didn't match the expected structure inside the node container.

**Official Implementation** (`vantage6/cli/node/start.py`, lines 145-155):
```python
mounts = [
    ("/mnt/log", str(ctx.log_dir)),
    ("/mnt/data", data_volume.name),       # Docker volume, not bind mount!
    ("/mnt/vpn", vpn_volume.name),
    ("/mnt/ssh", ssh_volume.name),
    ("/mnt/squid", squid_volume.name),
    ("/mnt/config", str(ctx.config_dir)),  # Directory, not single file!
    ("/var/run/docker.sock", "/var/run/docker.sock"),
]
```

**Fix Applied**:
```python
volumes = [
    f"{log_dir_host_path}:/mnt/log",
    f"{data_volume.name}:/mnt/data",          # Volume name, not path
    f"{vpn_volume.name}:/mnt/vpn",
    f"{ssh_volume.name}:/mnt/ssh",
    f"{squid_volume.name}:/mnt/squid",
    f"{config_dir_host_path}:/mnt/config",    # Config directory
    "/var/run/docker.sock:/var/run/docker.sock"
]
```

### 4. Missing Environment Variables ⚠️ **HIGH**

**Problem**: The node container needs specific environment variables to function correctly.

**Official Implementation** (`vantage6/cli/node/start.py`, lines 192-216):
```python
env = {
    'DATA_VOLUME_NAME': data_volume.name,
    'VPN_VOLUME_NAME': vpn_volume.name,
    'PRIVATE_KEY': '/mnt/private_key.pem',
}
```

**Fix Applied**:
```python
env = {
    'DATA_VOLUME_NAME': data_volume.name,
    'VPN_VOLUME_NAME': vpn_volume.name,
    'SSH_TUNNEL_VOLUME_NAME': ssh_volume.name,
    'SSH_SQUID_VOLUME_NAME': squid_volume.name,
    'PRIVATE_KEY': '/mnt/private_key.pem'
}
```

### 5. Missing TTY Flag ⚠️ **MEDIUM**

**Problem**: The `tty=True` flag wasn't set, which some applications need for proper I/O.

**Official Implementation** (`vantage6/cli/node/start.py`, line 321):
```python
container = docker_client.containers.run(
    # ... other params ...
    tty=True
)
```

**Fix Applied**:
```python
container = client.containers.run(
    # ... other params ...
    tty=True
)
```

## How It Works Now

### Container Creation Flow

1. **Volume Creation**: Create 4 Docker volumes if they don't exist:
   - Data volume: Stores task data and algorithm results
   - VPN volume: Stores VPN configuration
   - SSH volume: Stores SSH tunnel configuration
   - Squid volume: Stores proxy configuration

2. **Path Conversion**: Convert container paths to host paths for bind mounts:
   - Config directory: `/root/.config/vantage6/node/` → `${HOME}/.config/vantage6/node/`
   - Log directory: `/data/...` → `${HOME}/.local/share/vantage6/node/...`

3. **Volume Mounting**:
   - Bind mounts: Log directory, config directory, Docker socket
   - Docker volumes: Data, VPN, SSH, Squid (persist independently of host filesystem)

4. **Command Execution**: Run `vnode-local start` inside the container with proper flags:
   ```bash
   vnode-local start --name <name> --config /mnt/config/<config>.yaml --dockerized --system
   ```

5. **Container Start**: Start in detached mode with TTY enabled

## Key Insights from Official Implementation

### Why Docker Volumes for Data?

The official implementation uses Docker volumes (not bind mounts) for the data directory because:

1. **Nested Container Creation**: The node creates algorithm containers. These need access to the data volume.
2. **Cross-Container Sharing**: Using a named volume allows multiple containers to access the same data.
3. **Docker-in-Docker**: When running dockerized, bind mounts from the container don't work for nested containers.

### Why Config Directory Instead of Single File?

Mounting the config directory instead of a single file because:

1. **Additional Files**: Nodes may need private keys, SSL certificates, etc. in the same directory
2. **File Updates**: Directory mounts handle file updates better than single file mounts
3. **Consistency**: The node code expects `/mnt/config/<name>.yaml`, not `/mnt/config.yaml`

### Why These Environment Variables?

- `DATA_VOLUME_NAME`: Tells the node container which volume to use for algorithm containers
- `VPN_VOLUME_NAME`: Required for VPN client container setup
- `SSH_TUNNEL_VOLUME_NAME`: Required for SSH tunnel functionality
- `SSH_SQUID_VOLUME_NAME`: Required for Squid proxy functionality
- `PRIVATE_KEY`: Path to encryption key inside the container

## Testing the Fix

To verify the node starts correctly:

1. **Check Container Status**:
   ```bash
   docker ps -a | grep vantage6
   ```
   Should show container as "Up" not "Exited"

2. **View Container Logs**:
   ```bash
   docker logs vantage6-<node-name>-system
   ```
   Should show node initialization and connection to server

3. **Inspect Volumes**:
   ```bash
   docker volume ls | grep <node-name>
   ```
   Should show 4 volumes created

4. **Check Mounts**:
   ```bash
   docker inspect vantage6-<node-name>-system | jq '.[0].Mounts'
   ```
   Should show all 7 mount points

## References

- Official vantage6 CLI: `vantage6/cli/node/start.py`
- Node container context: `vantage6-node/vantage6/node/context.py`
- Docker node context: `vantage6-node/vantage6/node/context.py` (DockerNodeContext class)
- Volume name properties: `vantage6/cli/context/node.py` (lines 173-231)

## Migration Notes

### For Existing Deployments

If you have nodes running with the old implementation:

1. **Stop Old Containers**: `docker stop <container-name>`
2. **Remove Old Containers**: `docker rm <container-name>`
3. **Volumes Will Be Created**: New volumes will be created automatically on first start
4. **Data Migration**: If you need to preserve existing data, copy it into the new data volume

### Volume Persistence

The new Docker volumes persist even when containers are removed. To fully clean up:

```bash
# Remove container
docker rm vantage6-<node-name>-system

# Remove volumes
docker volume rm vantage6-<node-name>-system-vol
docker volume rm vantage6-<node-name>-system-vpn-vol
docker volume rm vantage6-<node-name>-system-ssh-vol
docker volume rm vantage6-<node-name>-system-squid-vol
```

## Future Enhancements

Consider implementing:

1. **Database Mounting**: The official implementation has sophisticated database file detection and mounting
2. **Private Key Mounting**: Support for encryption private keys
3. **SSH Tunnel Keys**: Support for SSH identity files
4. **Extra Mounts**: Support for `node_extra_mounts` configuration
5. **Extra Environment**: Support for `node_extra_env` configuration
6. **Extra Hosts**: Support for `node_extra_hosts` configuration
