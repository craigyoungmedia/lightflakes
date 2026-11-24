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
files = {
    "sitemap.xml": Path("production/sitemap.xml").read_bytes(),
    "robots.txt": Path("production/robots.txt").read_bytes(),
    "index.html": page,
}
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
                for scheme in ("https", "http"):
                    try:
                        with urlopen(f"{scheme}://lightflakes.com/{probe}", timeout=12) as response:
                            if response.read(128) == token:
                                break
                    except OSError as error:
                        print(f"{scheme} folder check: {error}")
                else:
                    continue
                print(f"Verified the Lightflakes folder over {scheme.upper()}.")
                break
            finally:
                sftp.remove(probe)
        else:
            raise SystemExit("Login succeeded, but no accessible folder served the domain check. Verify the IONOS domain target and SSL certificate.")
        for name, content in files.items():
            staging = ".lightflakes-" + run + "-" + name
            try:
                with sftp.open(staging, "wb") as target:
                    target.write(content)
                with sftp.open(staging, "rb") as uploaded:
                    if uploaded.read() != content:
                        raise SystemExit("Uploaded file failed verification.")
                sftp.chmod(staging, 0o644)
                sftp.posix_rename(staging, name)
                print(f"Published {name} over SFTP.")
            finally:
                try:
                    sftp.remove(staging)
                except FileNotFoundError:
                    pass

for name, content in files.items():
    path = "" if name == "index.html" else name
    url = "https://lightflakes.com/" + path
    for attempt in range(4):
        try:
            with urlopen(url, timeout=15) as response:
                if response.status == 200 and response.read() == content:
                    print(f"Verified {url}")
                    break
        except OSError as error:
            print(f"HTTPS verification: {error}")
        time.sleep(3)
    else:
        raise SystemExit(f"Public verification failed for {url}.")
