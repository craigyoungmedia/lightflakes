import base64
import hashlib
import os
import posixpath
import secrets
import socket
import time
from pathlib import Path
from urllib.request import urlopen

import paramiko

# IONOS publishes this Ed25519 fingerprint in its Web Hosting SSH fingerprint guide.
FINGERPRINT = "SHA256:1gx2w8Rtv3wCgi7Jh8myf/KVd72cRQbow03UP8P095Q"
host, user, password = (os.environ.get(key) for key in ("IONOS_HOST", "IONOS_USER", "IONOS_PASSWORD"))
if not all((host, user, password)):
    raise SystemExit("Set the IONOS_HOST and IONOS_USER repository variables and IONOS_PASSWORD Actions secret.")

page = Path("production/index.html").read_bytes()
if b"noindex" in page.lower() or b"https://sidedoorreview.com/maps" not in page:
    raise SystemExit("Expected the indexable production homepage.")
run = os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
with socket.create_connection((host, 22), timeout=20) as sock, paramiko.Transport(sock) as transport:
    transport.get_security_options().key_types = ("ssh-ed25519",)
    transport.start_client(timeout=20)
    key = transport.get_remote_server_key()
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    if fingerprint != FINGERPRINT:
        raise SystemExit("Server key differs from the published IONOS fingerprint.")
    transport.auth_password(user, password)
    with paramiko.SFTPClient.from_transport(transport) as sftp:
        sftp.get_channel().settimeout(25)
        home = sftp.normalize(".")
        candidates = [posixpath.join(home, "lightflakes"), "/lightflakes",
                      "/kunden/homepages/37/d353520313/htdocs/lightflakes", home]
        for folder in dict.fromkeys(candidates):
            try:
                sftp.chdir(folder)
            except (FileNotFoundError, PermissionError):
                continue
            probe = "lightflakes-check-" + secrets.token_hex(12) + ".txt"
            token = secrets.token_hex(24).encode()
            with sftp.open(probe, "wx") as target:
                target.write(token)
            try:
                sftp.chmod(probe, 0o644)
                with urlopen("https://lightflakes.com/" + probe, timeout=12) as response:
                    if response.read(128) == token:
                        print("Verified the SFTP folder for lightflakes.com.")
                        break
            except OSError as error:
                print("Domain check:", type(error).__name__, getattr(error, "code", ""))
            finally:
                sftp.remove(probe)
        else:
            raise SystemExit("Login succeeded, but no accessible folder served the HTTPS domain check. Verify the IONOS domain target and SSL certificate.")
        staging = ".lightflakes-" + run + ".html"
        try:
            with sftp.open(staging, "wb") as target:
                target.write(page)
            with sftp.open(staging, "rb") as uploaded:
                if uploaded.read() != page:
                    raise SystemExit("Uploaded file failed verification.")
            sftp.chmod(staging, 0o644)
            sftp.posix_rename(staging, "index.html")
        finally:
            try:
                sftp.remove(staging)
            except FileNotFoundError:
                pass

for attempt in range(4):
    try:
        with urlopen("https://lightflakes.com/?release=" + run, timeout=15) as result:
            if result.read() == page:
                print("Verified the published homepage at https://lightflakes.com/")
                break
    except OSError:
        pass
    time.sleep(3)
else:
    raise SystemExit("SFTP upload succeeded, but the public domain did not serve the matching homepage.")
