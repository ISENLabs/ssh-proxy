import os

# Server configuration
BIND_ADDRESS = '0.0.0.0'
BIND_PORT = 32
MAX_CONNECTIONS = 100

# Proxy SSH key
SERVER_KEY_FILE = 'ssh_host_rsa_key'  # Chemin vers le fichier de clé privée

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Database configuration
DB_HOST = '127.0.0.1'
DB_PORT = 3306
DB_USERNAME = ''
DB_PASSWORD = ''
DB_NAME = ""
MAX_COMMAND_LENGTH = 10000

TARGET_SSH_PORT=22