import paramiko
import socket
import threading
import logging
from proxy_session import ProxySession
from config import *

class SSHProxy(paramiko.ServerInterface):
    def __init__(self, client_ip):
        self.client_ip = client_ip
        self.event = threading.Event()

    def check_auth_password(self, username, password):
        print(f"Checking auth for {username}")
        try:
            vm_id, real_username = username.split('-', 1)
            vm_id = int(vm_id)
            # TODO: Get VM IP from DB
            # but poc, so hardcoded IP
            if vm_id == 22:
                self.target_ip = "127.0.0.1"
                self.target_username = real_username
                self.target_password = password
                return paramiko.AUTH_SUCCESSFUL
        except ValueError:
            pass
        return paramiko.AUTH_FAILED

    # needed functions for paramiko.ServerInterface. But we don't need them, so just return True
    def check_channel_request(self, kind, chanid): 
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True

    def check_channel_pty_request(self, _, _2, _3, _4, _5, _6, _7):
        return True

def start_server():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((BIND_ADDRESS, BIND_PORT))
        sock.listen(MAX_CONNECTIONS)
        
        logging.info(f"Listening for SSH connections on {BIND_ADDRESS}:{BIND_PORT}...")

        while True:
            client, addr = sock.accept()
            logging.info(f"Got connection from {addr[0]}:{addr[1]}")

            ProxySession(client, addr[0]).start()

    except Exception as e:
        logging.error(f"Error starting server: {e}")
        sock.close()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    start_server()