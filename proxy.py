import paramiko
import socket
import threading
import logging
import mariadb
from proxy_session import ProxySession
from config import *

class SSHProxy(paramiko.ServerInterface):
    def __init__(self, client_ip, db_connection):
        self.client_ip = client_ip
        self.event = threading.Event()
        self.db_connection = db_connection

    def check_auth_password(self, username, password):
        print(f"Checking auth for {username}")
        try:
            vm_id, real_username = username.split('-', 1)
            vm_id = int(vm_id)

            try:
                cursor = self.db_connection.cursor()
                request = "SELECT internal_ip FROM volum_vms WHERE ctid=?"
                cursor.execute(request, (vm_id,))
                row = cursor.fetchone()

                if row is None:
                    logging.error(f"Error in getting internal ip: ip for vm {vm_id} is null")
                    return paramiko.AUTH_FAILED

                self.target_ip = row[0]
            except Exception as e:
                logging.error(f"Error in getting internal ip: {e}")
                return paramiko.AUTH_FAILED

            self.target_username = real_username
            self.target_password = password
            self.target_vm_id = vm_id
            
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