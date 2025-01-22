import paramiko
import threading
import logging
import mariadb
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
            self.db_connection.close()

    def log_cmd(self, command):
        try:
            cursor = self.db_connection.cursor()
            request = "INSERT INTO volum_ssh_logs(vm_id, username, command) VALUES(?,?,?)"
            cursor.execute(request, (self.client_vm_id, self.client_username, command))
            self.db_connection.commit()
        except Exception as e:
            logging.error(f"Error in database logging: {e}")

    def setup_session_logging(self, vm_id, username):
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

    def handle_sftp_session(self, channel, server):
        try:
            target_client = paramiko.SSHClient()
            target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            target_client.connect(
                hostname=server.target_ip,
                username=server.target_username,
                password=server.target_password,
                port=TARGET_SSH_PORT,
                look_for_keys=False,
                allow_agent=False
            )

            target_channel = target_client.get_transport().open_session()
            target_channel.invoke_subsystem('sftp')

            while True:
                if channel.recv_ready():
                    data = channel.recv(32768)
                    if not data:
                        break
                    target_channel.send(data)

                if target_channel.recv_ready():
                    data = target_channel.recv(32768)
                    if not data:
                        break
                    channel.send(data)

                if target_channel.recv_stderr_ready():
                    data = target_channel.recv_stderr(32768)
                    if data:
                        channel.send_stderr(data)

                if channel.exit_status_ready():
                    break

                

        except Exception as e:
            if not channel.exit_status_ready():
                channel.send_exit_status(1)
        finally:
            if target_client:
                target_client.close()
            return True

    def handle_scp_session(self, channel, command, server):
        target_client = None
        try:
            
            target_client = paramiko.SSHClient()
            target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            target_client.connect(
                hostname=server.target_ip,
                username=server.target_username,
                password=server.target_password,
                port=TARGET_SSH_PORT,
                look_for_keys=False,
                allow_agent=False,
                timeout=10
            )

            
            target_channel = target_client.get_transport().open_session()
            target_channel.exec_command(command)

            # transfert petit a petit
            while True:
                # client -> serv
                if channel.recv_ready():
                    data = channel.recv(32768)
                    if not data:
                        break
                    target_channel.sendall(data)

                # serv -> client
                if target_channel.recv_ready():
                    data = target_channel.recv(32768)
                    if not data:
                        break
                    channel.sendall(data)

                # si erreur
                if target_channel.recv_stderr_ready():
                    data = target_channel.recv_stderr(32768)
                    if data:
                        channel.sendall_stderr(data)

                
                if target_channel.exit_status_ready():
                    status = target_channel.recv_exit_status()
                    channel.send_exit_status(status)
                    
                    target_channel.close()
                    channel.close()
                    break



            if channel.get_transport():
                channel.get_transport().close()
            return True

        except Exception as e:
            if channel and not channel.exit_status_ready():
                try:
                    channel.send_exit_status(1)
                except:
                    pass
            return True
            
        finally:
            # cleanup
            try:
                if target_client:
                    target_client.close()
                if channel.get_transport():
                    channel.get_transport().close()
            except:
                pass
            return True

    def run(self):

        try:
            
            from proxy import SSHProxy
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
                port=TARGET_SSH_PORT
            )

            self.client_username = server.target_username
            self.client_vm_id = server.target_vm_id

            chan = transport.accept(20)
            if chan is None:
                logging.error("No channel.")
                return
            
            if hasattr(server, 'command'):
                if server.command == "sftp":
                    if self.handle_sftp_session(chan, server):
                        transport.close()
                        return
                elif server.command and server.command.startswith('scp'):
                    if self.handle_scp_session(chan, server.command, server):
                        transport.close()
                        return
                else:
                    if self.handle_scp_session(chan, server.command, server):
                        transport.close()
                        return
            else:
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
        finally:
            if transport:
                transport.close()

    def forward_streams(self, chan, target_chan):
        def forward_to_target(source, destination):
            try:
                buff = ''
                while True:
                    data = source.recv(1024)
                    if not data:
                        break
                        
                    try:
                        char = data.decode('utf-8')
                        if char == '\x03':  # ^C character
                            buff = ''
                            destination.send(data)
                            continue
                            
                        buff += char

                        if char == '\n' or char == '\r':
                            lines = buff.replace('\r', '\n').split('\n')
                            buff = ""
                            for line in lines:
                                line = line.strip()
                                if line:
                                    self.log_cmd(line)
                                    self.session_logger.info(f"Command: {line}")
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

        thread_c2t = threading.Thread(target=forward_to_target, args=(chan, target_chan))
        thread_t2c = threading.Thread(target=forward_to_client, args=(target_chan, chan))
        
        thread_c2t.start()
        thread_t2c.start()
        
        thread_c2t.join()
        thread_t2c.join()
