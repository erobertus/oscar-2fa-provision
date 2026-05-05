"""Database connection helpers — direct or via SSH tunnel.

Adapted from the Oscar_Auto_Billing project so this script's connection
behaviour matches the rest of the toolchain on Helium.
"""

from __future__ import annotations

from typing import Optional, Tuple

import mariadb
import paramiko
from sshtunnel import SSHTunnelForwarder


def _log(msg: str, verbose: int = 1) -> None:
    if verbose:
        print(msg)


def attempt_direct_connection(config: dict) -> Optional[mariadb.Connection]:
    """Open a direct (no-tunnel) DB connection. Returns None on failure."""
    try:
        _log(
            f"Connecting directly to {config['db_host']}:{config['db_port']}/"
            f"{config['db_database']} as {config['db_user']}",
            config.get("verbose", 1),
        )
        return mariadb.connect(
            user=config["db_user"],
            password=config["db_secret"],
            host=config["db_host"],
            port=config["db_port"],
            database=config["db_database"],
            compress=config.get("db_compress", True),
        )
    except mariadb.Error as e:
        print(f"Direct DB connection failed: {e}")
        return None


def connect_to_database(
    use_ssh: bool, config: dict
) -> Tuple[Optional[mariadb.Connection], Optional[SSHTunnelForwarder]]:
    """Connect either directly or via an SSH tunnel.

    Returns (connection, tunnel). Tunnel is None for direct connections.
    Caller is responsible for closing both.
    """
    if not use_ssh:
        return attempt_direct_connection(config), None

    tunnel: Optional[SSHTunnelForwarder] = None
    try:
        if not config.get("pkey_file"):
            raise RuntimeError(
                "SSH_ENABLED=true but PKEY_FILE is not set in the environment."
            )

        pkey = paramiko.RSAKey.from_private_key_file(
            config["pkey_file"], password=config.get("cert_secret")
        )

        tunnel = SSHTunnelForwarder(
            (config["db_host"], config["ssh_port"]),
            ssh_username=config["ssh_user"],
            ssh_pkey=pkey,
            ssh_private_key_password=config.get("cert_secret"),
            remote_bind_address=(config["ssh_db_host"], config["db_port"]),
        )
        tunnel.start()

        if not tunnel.is_active:
            print("SSH tunnel failed to start; falling back to direct.")
            tunnel.close()
            return attempt_direct_connection(config), None

        _log(
            f"SSH tunnel up: {config['ssh_user']}@{config['db_host']}:{config['ssh_port']} "
            f"-> {config['ssh_db_host']}:{config['db_port']} "
            f"(local 127.0.0.1:{tunnel.local_bind_port})",
            config.get("verbose", 1),
        )

        connection = mariadb.connect(
            user=config["db_user"],
            password=config["db_secret"],
            host=config["ssh_db_host"],
            port=tunnel.local_bind_port,
            database=config["db_database"],
            compress=config.get("db_compress", True),
        )
        return connection, tunnel

    except (mariadb.Error, paramiko.SSHException, OSError, RuntimeError) as e:
        print(f"SSH tunnel connection failed: {e}")
        if tunnel is not None and tunnel.is_active:
            tunnel.close()
        return attempt_direct_connection(config), None
