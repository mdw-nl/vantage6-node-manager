# Paths and Volume Mounts - Production Guide

This document explains how paths are mapped between your host system, the Node Manager container, and the Vantage6 node containers.

## Overview

When running in production with Docker, there are three layers of path mappings to understand:

1. **Host System** - Your physical machine
2. **Node Manager Container** - The web application container
3. **Vantage6 Node Containers** - The actual node containers managed by the Node Manager

**Important**: When the Node Manager creates vantage6 node containers, it must mount volumes using **host paths**, not container paths. The Node Manager automatically converts its internal container paths to host paths for volume mounting.

## Volume Mounts

### Docker Compose Configuration

The following volumes are mounted in the Node Manager container:

```yaml
volumes:
  # Docker socket - allows Node Manager to control Docker
  - /var/run/docker.sock:/var/run/docker.sock
  
  # User configuration directory
  - ${HOME}/.config/vantage6:/root/.config/vantage6
  
  # System configuration directory (optional)
  - ${HOME}/.config/vantage6-system:/etc/vantage6/node
  
  # Data directory for datasets
  - ${HOME}/vantage6-data:/data
```

## Path Mappings

### Configuration Files

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `${HOME}/.config/vantage6/node/*.yaml` | `/root/.config/vantage6/node/*.yaml` | User node configurations |
| `${HOME}/.config/vantage6/node/private_keys/` | `/root/.config/vantage6/node/private_keys/` | Encryption private keys |
| `${HOME}/.config/vantage6-system/` | `/etc/vantage6/node/` | System-wide configurations |

### Data Files

| Host Path | Node Manager Container | Node Container | Purpose |
|-----------|----------------------|----------------|---------|
| `${HOME}/vantage6-data/mydata.csv` | `/data/mydata.csv` | `/mnt/data/default` | Dataset files |
| `${HOME}/vantage6-data/tasks/` | `/data/tasks/` | `/mnt/data/tasks/` | Task output directory |

## Environment Variables

The following environment variables control path behavior:

| Variable | Default | Description |
|----------|---------|-------------|
| `VANTAGE6_CONFIG_DIR` | `/root/.config/vantage6/node` | User config directory |
| `VANTAGE6_SYSTEM_CONFIG_DIR` | `/etc/vantage6/node` | System config directory |
| `VANTAGE6_DATA_DIR` | `/data` | Data files directory |

## Best Practices

### 1. Database File Paths

When creating a node configuration, specify database paths in one of these formats:

#### Option A: Absolute path in container (Recommended)
```yaml
databases:
  - label: default
    uri: /data/mydata.csv
    type: csv
```

This assumes the file exists at `${HOME}/vantage6-data/mydata.csv` on the host.

#### Option B: Relative path
```yaml
databases:
  - label: default
    uri: mydata.csv  # Will look in /data/mydata.csv
    type: csv
```

#### Option C: Full host path (Works if file is accessible)
```yaml
databases:
  - label: default
    uri: /home/user/datasets/mydata.csv
    type: csv
```

⚠️ **Warning**: This only works if the path exists inside the Node Manager container or is in a mounted volume.

### 2. Task Directory

The default task directory is now `/mnt/data/tasks` instead of `/tmp/vantage6` to ensure:
- Task outputs persist across container restarts
- Outputs are accessible on the host at `${HOME}/vantage6-data/tasks/`

### 3. Private Keys

Private keys are stored in:
- Host: `${HOME}/.config/vantage6/node/private_keys/`
- Container: `/root/.config/vantage6/node/private_keys/`

They persist across container restarts and are automatically mounted to node containers when needed.

## Troubleshooting

### "Database file not found" warning

If you see this warning when starting a node:
1. Check that the file exists on your host at `${HOME}/vantage6-data/yourfile.csv`
2. Verify the path in your node configuration matches the container path
3. Ensure the volume mount is active: `docker inspect vantage6-node-manager | grep Mounts`

### Configurations not persisting

If node configurations disappear after container restart:
1. Verify the volume mount: `${HOME}/.config/vantage6:/root/.config/vantage6`
2. Check directory exists: `ls -la ${HOME}/.config/vantage6/node/`
3. Ensure the Node Manager has write permissions

### Node cannot access database

If a node container starts but cannot read the database:
1. The Node Manager must mount the database file to the node container
2. Check the database path is accessible to the Node Manager container
3. Verify file permissions allow read access

## Migration from Development

If you were running the Node Manager directly (not in Docker), you'll need to:

1. Move your configurations:
```bash
# Your configs are already at the right place
ls ~/.config/vantage6/node/
```

2. Move your data files:
```bash
mkdir -p ~/vantage6-data
# Copy your data files
cp /path/to/your/data/*.csv ~/vantage6-data/
```

3. Update node configurations to use the new data paths:
```bash
# Edit each .yaml file in ~/.config/vantage6/node/
# Change database uri to: /data/yourfile.csv
```

## Example Setup

Complete example for a production deployment:

```bash
# 1. Create necessary directories on host
mkdir -p ~/.config/vantage6/node
mkdir -p ~/.config/vantage6-system
mkdir -p ~/vantage6-data

# 2. Place your data files
cp mydata.csv ~/vantage6-data/

# 3. Start the Node Manager
docker-compose -f docker-compose.prod.yml up -d

# 4. Access web interface
# http://localhost:5000

# 5. Create node configuration via web UI:
#    - Database URI: /data/mydata.csv
#    - Task Dir: /mnt/data/tasks (default)
```

## Security Considerations

1. **Private Keys**: Stored with 0600 permissions, only readable by the container user
2. **Docker Socket**: Mounted to allow container management - ensure Node Manager is not publicly accessible
3. **Data Directory**: Use read-only mounts (`mode: ro`) when possible for database files
4. **Configuration Files**: Contain API keys - keep volumes secure

## Technical Details

### Path Conversion for Volume Mounting

When the Node Manager runs in a container and creates vantage6 node containers, it faces a unique challenge: it must mount volumes using **host paths**, not its own container paths.

For example:
- Config file location inside Node Manager: `/root/.config/vantage6/node/mynode.yaml`
- Host location: `${HOME}/.config/vantage6/node/mynode.yaml`
- The node container needs the **host path** for mounting

The `container_path_to_host_path()` function handles this conversion automatically:

```python
# Container path -> Host path conversions
/root/.config/vantage6/node/file.yaml  -> ${HOME}/.config/vantage6/node/file.yaml
/etc/vantage6/node/file.yaml           -> ${HOME}/.config/vantage6-system/file.yaml
/data/mydata.csv                       -> ${HOME}/vantage6-data/mydata.csv
```

This ensures that when starting node containers, the correct host paths are used for Docker volume mounts.

## Advanced Configuration

### Custom Volume Mounts

You can customize volume mounts in `docker-compose.yml`:

```yaml
volumes:
  # Use a different data directory
  - /mnt/storage/vantage6:/data
  
  # Use NFS for shared storage
  - type: volume
    source: vantage6-data
    target: /data
    volume:
      nocopy: true
      driver_opts:
        type: nfs
        o: addr=nfs-server,rw
        device: ":/path/on/nfs"
```

### Running with Docker Run

For direct `docker run` command:

```bash
docker run -d \
  --name vantage6-node-manager \
  -p 5000:5000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ${HOME}/.config/vantage6:/root/.config/vantage6 \
  -v ${HOME}/.config/vantage6-system:/etc/vantage6/node \
  -v ${HOME}/vantage6-data:/data \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e VANTAGE6_CONFIG_DIR=/root/.config/vantage6/node \
  -e VANTAGE6_SYSTEM_CONFIG_DIR=/etc/vantage6/node \
  -e VANTAGE6_DATA_DIR=/data \
  ghcr.io/mdw-nl/vantage6-node-manager:latest
```
