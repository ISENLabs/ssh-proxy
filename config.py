import os

# Server configuration
BIND_ADDRESS = '0.0.0.0'
BIND_PORT = 32
MAX_CONNECTIONS = 100

# Proxy SSH key
SERVER_KEY_FILE = 'ssh_host_rsa_key'

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)
