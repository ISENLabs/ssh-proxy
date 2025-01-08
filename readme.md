# ISENLabs's SSH-Proxy
This software is designed to forward connections to the right SSH host, based on the username provided by the user. We also want to log the commands, in order to store them.

## How it works
At end-user connection, the proxy will act as an SSH Server. It's needed to obtain informations about the user (and the commands). This way, the user will send the informations to the proxy, that will forward them to the real host. 

## Installation
- `pip3 install -r requirements.txt`
- Create the DB and put basic informations innit
- Edit the config.py
- Run the proxy: `python3 proxy.py`
- Connect to the proxy: `ssh <id>-<user>@proxyip`. Example: `ssh 8-debian@127.0.0.1`