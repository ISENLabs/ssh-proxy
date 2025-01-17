import paramiko
import threading
import logging
import mariadb
from time import sleep
from datetime import datetime
from config import *

class ProxySession(threading.Thread):
    def __init__(self, client_sock, client_ip):
        threading.Thread.__init__(self)
        self.client_sock = client_sock
        self.client_ip = client_ip
        self.term = None
        self.width = 80
        self.height = 24
        self.db_connection = mariadb.connect(
            host = DB_HOST,
            port = DB_PORT,
            user = DB_USERNAME,
            password = DB_PASSWORD,
            database = DB_NAME
        )
        
    def __del__(self):
        if self.db_connection:
            self.db_connection.close();

    def log_cmd(self, command):
        try:
            cursor = self.db_connection.cursor()
            request = "INSERT INTO volum_ssh_logs(vm_id, username, command) VALUES(?,?,?)";
            for i in range(0, len(command), MAX_COMMAND_LENGTH):
                chunk = command[i:i + MAX_COMMAND_LENGTH]
                cursor.execute(request, (self.client_vm_id, self.client_username, chunk))
            self.db_connection.commit()
        except Exception as e:
            logging.error(f"Error in database logging: {e}")

        
    def setup_session_logging(self, vm_id, username):
        # Setup logigng
        log_filename = f"logs/ssh_{vm_id}_{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.session_logger = logging.getLogger(f"ssh_session_{vm_id}_{username}")
        self.session_logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler(log_filename)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        self.session_logger.addHandler(handler)
        
        self.session_logger.info(f"New SSH session from {self.client_ip}")

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        self.term = term
        self.width = width
        self.height = height
        return True

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        self.width = width
        self.height = height
        if hasattr(self, 'target_chan'):
            self.target_chan.resize_pty(width=width, height=height)
        return True

    def run(self):
        from proxy import SSHProxy
        try:
            transport = paramiko.Transport(self.client_sock)
            
            server_key = paramiko.RSAKey.from_private_key_file(SERVER_KEY_FILE)
            transport.add_server_key(server_key)
            
            server = SSHProxy(self.client_ip, self.db_connection)
            server.check_channel_pty_request = self.check_channel_pty_request
            server.check_channel_window_change_request = self.check_channel_window_change_request
            
            try:
                transport.start_server(server=server)
            except paramiko.SSHException as e:
                logging.error(f"SSH negotiation failed: {e}")
                return
            
            server.event.wait(30)
            if not server.event.is_set():
                logging.error("Client never asked for a shell")
                transport.close()
                return

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                server.target_ip,
                username=server.target_username,
                password=server.target_password,
                port=22
            )

            self.client_username = server.target_username
            self.client_vm_id = server.target_vm_id

            chan = transport.accept(20)
            if chan is None:
                logging.error("No channel.")
                return
            
            self.target_chan = client.get_transport().open_session()
            self.target_chan.get_pty(
                term=self.term or 'xterm',
                width=self.width,
                height=self.height
            )
            self.target_chan.invoke_shell()

            vm_id = server.target_ip.split('.')[-1]
            self.setup_session_logging(vm_id, server.target_username)
            
            self.forward_streams(chan, self.target_chan)
            
        except Exception as e:
            logging.error(f"Error in proxy session: {e}")
            raise

    def forward_streams(self, chan, target_chan):
        """Forward data between client and target channels while logging commands"""
        def forward_to_target(source, destination):
            try:
                buff = ''
                while True:
                    data = source.recv(1024)
                    if not data:
                        break
                        
                    # Try to decode and log command when newline is detected
                    try:
                        char = data.decode('utf-8')
                        
                        # Handle Ctrl+C to clear buffer
                        if char == '\x03':  # ^C character
                            buff = ''
                            destination.send(data)
                            continue
                            
                        buff += char

                        if char == '\n' or char == '\r':
                            lines = buff.replace('\r', '\n').split('\n')
                            buff = "" # Clear buffer
                            for line in lines:
                                line = line.strip()
                                if line:  # Don't log empty lines
                                    self.log_cmd(line);
                                    self.session_logger.info(f"Command: {line}")
                                    # Hide this because of session_logger that already print cmd in terminal
                                    # print(f"\033[93m[{datetime.now()}] User command: {line}\033[0m")
                    except UnicodeDecodeError:
                        pass
                        
                    destination.send(data)
            finally:
                source.close()
                destination.close()

        def forward_to_client(source, destination):
            try:
                while True:
                    data = source.recv(1024)
                    if not data:
                        break
                    destination.send(data)
            finally:
                source.close()
                destination.close()

        # Start forwarding threads
        thread_c2t = threading.Thread(target=forward_to_target, args=(chan, target_chan))
        thread_t2c = threading.Thread(target=forward_to_client, args=(target_chan, chan))
        
        thread_c2t.start()
        thread_t2c.start()
        
        thread_c2t.join()
        thread_t2c.join()