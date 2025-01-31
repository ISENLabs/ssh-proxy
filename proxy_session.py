import paramiko
import threading
import logging
import mariadb
from datetime import datetime
from config import *

class ProxySession(threading.Thread):
    """Handles SSH proxy sessions including regular SSH, SCP, and SFTP."""

    BUFFER_SIZE = 32768
    SHELL_BUFFER_SIZE = 1024
    TIMEOUT = 30
    CTRL_C = '\x03'

    def __init__(self, client_sock, client_ip):
        """Initialize the proxy session.
        
        Args:
            client_sock: Socket for the client connection
            client_ip: IP address of the client
        """
        threading.Thread.__init__(self)
        self.client_sock = client_sock
        self.client_ip = client_ip
        self.term = None
        self.width = 80
        self.height = 24
        self.db_connection = mariadb.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USERNAME,
            password=DB_PASSWORD,
            database=DB_NAME
        )

    def __del__(self):
        """Cleanup database connection on deletion."""
        if hasattr(self, 'db_connection') and self.db_connection:
            self.db_connection.close()

    def log_cmd(self, command):
        """Log command to database.
        
        Args:
            command: Command string to log
        """
        try:
            cursor = self.db_connection.cursor()
            request = "INSERT INTO volum_ssh_logs(vm_id, username, command) VALUES(?,?,?)"
            cursor.execute(request, (self.client_vm_id, self.client_username, command))
            self.db_connection.commit()
        except Exception as e:
            logging.error(f"Error in database logging: {e}")

    def setup_session_logging(self, vm_id, username):
        """Setup file logging for the session.
        
        Args:
            vm_id: Virtual machine ID
            username: Username for the session
        """
        log_filename = f"logs/ssh_{vm_id}_{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.session_logger = logging.getLogger(f"ssh_session_{vm_id}_{username}")
        self.session_logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler(log_filename)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        self.session_logger.addHandler(handler)
        
        self.session_logger.info(f"New SSH session from {self.client_ip}")

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        """Handle PTY request from client.
        
        Args:
            channel: SSH channel
            term: Terminal type
            width: Terminal width
            height: Terminal height
            pixelwidth: Terminal pixel width
            pixelheight: Terminal pixel height
            modes: Terminal modes
        """
        self.term = term
        self.width = width
        self.height = height
        return True

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        """Handle window change request from client.
        
        Args:
            channel: SSH channel
            width: New terminal width
            height: New terminal height
            pixelwidth: New terminal pixel width
            pixelheight: New terminal pixel height
        """
        self.width = width
        self.height = height
        if hasattr(self, 'target_chan'):
            self.target_chan.resize_pty(width=width, height=height)
        return True

    def setup_transport(self):
        """Initialize and configure the SSH transport."""
        transport = paramiko.Transport(self.client_sock)
        transport.set_keepalive(60)
        
        server_key = paramiko.RSAKey.from_private_key_file(SERVER_KEY_FILE)
        transport.add_server_key(server_key)
        
        return transport

    def create_client_connection(self, server):
        """Create and configure the SSH client for the target server.
        
        Args:
            server: SSHProxy instance containing target server details
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=server.target_ip,
            username=server.target_username,
            password=server.target_password,
            port=TARGET_SSH_PORT,
            look_for_keys=False,
            allow_agent=False,
            timeout=self.TIMEOUT
        )
        return client

    def handle_file_transfer(self, chan, target_chan):
        """Handle SCP/SFTP file transfer between channels.
        
        Args:
            chan: Source channel
            target_chan: Target channel
        """
        import select
        while True:
            r, _, _ = select.select([chan, target_chan], [], [], 0.1)
            
            if chan in r:
                data = chan.recv(self.BUFFER_SIZE)
                if not data:
                    break
                target_chan.sendall(data)

            if target_chan in r:
                data = target_chan.recv(self.BUFFER_SIZE)
                if not data:
                    break
                chan.sendall(data)

            if target_chan.exit_status_ready():
                status = target_chan.recv_exit_status()
                chan.send_exit_status(status)
                break

            if chan.exit_status_ready():
                break

    def create_shell_forwarder(self, chan, target_chan):
        """Create data forwarders for shell session.
        
        Args:
            chan: Client channel
            target_chan: Target server channel
        """
        def forward_to_target():
            """Forward data from client to target and log commands."""
            try:
                buff = ''
                while True:
                    if chan.closed or target_chan.closed:
                        break
                    
                    if not chan.recv_ready():
                        if chan.exit_status_ready():
                            break
                        continue
                        
                    data = chan.recv(self.SHELL_BUFFER_SIZE)
                    if not data:
                        break
                    
                    try:
                        char = data.decode('utf-8')
                        if char == self.CTRL_C:
                            target_chan.send(data)
                            buff = ''
                            continue
                        
                        buff += char
                        if char in '\r\n':
                            command = buff.strip()
                            if command:
                                self.log_cmd(command)
                            buff = ''
                    except UnicodeDecodeError:
                        pass
                        
                    target_chan.send(data)
            except Exception as e:
                logging.error(f"Forward to target error: {e}")
            finally:
                chan.close()
                target_chan.close()

        def forward_to_client():
            """Forward data from target to client."""
            try:
                while True:
                    if chan.closed or target_chan.closed:
                        break
                        
                    if not target_chan.recv_ready():
                        if target_chan.exit_status_ready():
                            break
                        continue
                        
                    data = target_chan.recv(self.SHELL_BUFFER_SIZE)
                    if not data:
                        break
                        
                    chan.send(data)
                    
                    if target_chan.exit_status_ready():
                        break
            except Exception as e:
                logging.error(f"Forward to client error: {e}")
            finally:
                chan.close()
                target_chan.close()

        return forward_to_target, forward_to_client

    def handle_shell_session(self, chan, target_chan, server):
        """Handle interactive shell session.
        
        Args:
            chan: Client channel
            target_chan: Target server channel
            server: SSHProxy instance
        """
        target_chan.get_pty(
            term=self.term or 'xterm',
            width=self.width,
            height=self.height
        )
        target_chan.invoke_shell()

        vm_id = server.target_ip.split('.')[-1]
        self.setup_session_logging(vm_id, server.target_username)

        forward_to_target, forward_to_client = self.create_shell_forwarder(chan, target_chan)

        thread_c2t = threading.Thread(target=forward_to_target)
        thread_t2c = threading.Thread(target=forward_to_client)
        
        thread_c2t.start()
        thread_t2c.start()
        
        thread_c2t.join()
        thread_t2c.join()

    def run(self):
        """Main method to handle the proxy session."""
        transport = None
        client = None
        
        try:
            from proxy import SSHProxy
            transport = self.setup_transport()

            server = SSHProxy(self.client_ip, self.db_connection)
            server.check_channel_pty_request = self.check_channel_pty_request
            server.check_channel_window_change_request = self.check_channel_window_change_request

            try:
                transport.start_server(server=server)
            except paramiko.SSHException as e:
                logging.error(f"SSH negotiation failed: {e}")
                return

            if not server.event.wait(self.TIMEOUT):
                logging.error("Client never asked for a shell")
                return

            chan = transport.accept(20)
            if chan is None:
                logging.error("No channel.")
                return

            client = self.create_client_connection(server)
            self.client_username = server.target_username
            self.client_vm_id = server.target_vm_id

            session_command = getattr(server, 'command', None)
            logging.info(f"Session type: {'file_transfer' if session_command else 'shell'}")

            if session_command:
                target_chan = client.get_transport().open_session()
                if session_command == "sftp":
                    target_chan.invoke_subsystem('sftp')
                else:
                    target_chan.exec_command(session_command)
                self.handle_file_transfer(chan, target_chan)
            else:
                target_chan = client.get_transport().open_session()
                self.handle_shell_session(chan, target_chan, server)

        except Exception as e:
            logging.error(f"Error in proxy session: {e}")
            if 'chan' in locals() and chan and not chan.exit_status_ready():
                try:
                    chan.send_exit_status(1)
                except:
                    pass
        finally:
            for resource in (transport, client):
                if resource:
                    try:
                        resource.close()
                    except:
                        pass
                    
