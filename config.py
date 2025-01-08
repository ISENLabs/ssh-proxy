import os

# Server configuration
BIND_ADDRESS = '0.0.0.0'
BIND_PORT = 32
MAX_CONNECTIONS = 100

# Proxy SSH key
SERVER_KEY_FILE = 'ssh_host_rsa_key'

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Database configuration
DB_HOST = '127.0.0.1'
DB_PORT = 3306
DB_USERNAME = 'cyriac'
DB_PASSWORD = ''
DB_NAME = "volumn"
MAX_COMMAND_LENGTH = 10000