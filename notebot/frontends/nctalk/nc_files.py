"""Attach a real image file to a Talk conversation.

A Talk *bot* (HMAC secret) can only send text and reactions — it cannot upload
files. To post an actual image (like the Telegram bot's send_photo), the file must
be uploaded to Nextcloud Files and shared into the room, which needs a Nextcloud
user account + app password. So this uses WebDAV (upload) + the Files Sharing OCS
API (shareType 10 = Talk conversation).
"""

import os
import requests


def share_image_to_room(base_url, token, local_path, remote_name, user, password, timeout=30):
    """Upload `local_path` to the user's Files and share it into conversation `token`.
    Returns True if the share was created (i.e. the image is now in the chat)."""
    base = base_url.rstrip("/")
    dav = f"{base}/remote.php/dav/files/{user}"
    folder = "Talk Bot"
    remote_path = f"{folder}/{remote_name}"

    s = requests.Session()
    s.trust_env = False           # ignore HTTP(S)_PROXY env — Nextcloud is local
    s.auth = (user, password)

    # ensure the folder exists (MKCOL is fine to fail if it already does)
    s.request("MKCOL", f"{dav}/{folder}", timeout=timeout)
    with open(local_path, "rb") as f:
        put = s.put(f"{dav}/{remote_path}", data=f, timeout=timeout)
    if put.status_code not in (200, 201, 204):
        raise RuntimeError(f"WebDAV upload failed: HTTP {put.status_code}")

    share = s.post(
        f"{base}/ocs/v2.php/apps/files_sharing/api/v1/shares",
        headers={"OCS-APIRequest": "true", "Accept": "application/json"},
        data={"path": remote_path, "shareType": 10, "shareWith": token},
        timeout=timeout,
    )
    if not share.ok:
        raise RuntimeError(f"share failed: HTTP {share.status_code} {share.text[:200]}")
    return True
