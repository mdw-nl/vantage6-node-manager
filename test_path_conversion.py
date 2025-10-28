#!/usr/bin/env python3
"""
Test script to verify container path to host path conversion
Run this to test the path conversion logic
"""
from pathlib import Path
import os

def container_path_to_host_path(container_path):
    """
    Convert a path inside the Node Manager container to the corresponding host path.
    This is needed when the Node Manager creates volumes for node containers.
    
    Args:
        container_path: Path as seen inside the Node Manager container
    
    Returns:
        Host path that Docker can mount, or None if conversion not possible
    """
    container_path_str = str(container_path)
    
    # Check if path is in the user config directory
    if container_path_str.startswith('/root/.config/vantage6'):
        # /root/.config/vantage6 is mounted from ${HOME}/.config/vantage6 on host
        # Convert: /root/.config/vantage6/node/file.yaml -> ${HOME}/.config/vantage6/node/file.yaml
        relative_path = container_path_str.replace('/root/.config/vantage6/', '')
        host_path = Path.home() / '.config' / 'vantage6' / relative_path
        return str(host_path)
    
    # Check if path is in the system config directory
    elif container_path_str.startswith('/etc/vantage6/node'):
        # /etc/vantage6/node is mounted from ${HOME}/.config/vantage6-system on host
        relative_path = container_path_str.replace('/etc/vantage6/node/', '')
        host_path = Path.home() / '.config' / 'vantage6-system' / relative_path
        return str(host_path)
    
    # Check if path is in the data directory
    elif container_path_str.startswith('/data/'):
        # /data is mounted from ${HOME}/vantage6-data on host
        relative_path = container_path_str.replace('/data/', '')
        host_path = Path.home() / 'vantage6-data' / relative_path
        return str(host_path)
    
    # Path is not in a known mounted volume
    else:
        return None


def test_path_conversions():
    """Test the path conversion function"""
    test_cases = [
        ('/root/.config/vantage6/node/mynode.yaml', 'User config'),
        ('/root/.config/vantage6/node/private_keys/key.pem', 'User private key'),
        ('/etc/vantage6/node/system.yaml', 'System config'),
        ('/data/mydata.csv', 'Data file'),
        ('/data/subdir/file.csv', 'Data subdirectory'),
        ('/tmp/something.txt', 'Non-mounted path (should return None)'),
    ]
    
    print("Testing container path to host path conversions:")
    print("=" * 80)
    
    for container_path, description in test_cases:
        host_path = container_path_to_host_path(container_path)
        status = "✅" if host_path else "❌"
        
        print(f"\n{status} {description}")
        print(f"   Container: {container_path}")
        print(f"   Host:      {host_path if host_path else 'None (not in mounted volume)'}")
    
    print("\n" + "=" * 80)
    print("\nExpected results:")
    print("✅ All mounted paths should convert to ${HOME}/... paths")
    print("❌ Non-mounted paths should return None")


if __name__ == '__main__':
    test_path_conversions()
