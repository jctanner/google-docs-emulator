import os
import subprocess
from pathlib import Path

import pytest
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def test_python_official_clients(live_url):
    credentials = Credentials(
        token=None,
        refresh_token="fake-refresh",
        token_uri=live_url + "/token",
        client_id="local",
        client_secret="local",
    )
    credentials.refresh(Request())
    assert credentials.token == "emulator-local-token"
    docs = build(
        "docs",
        "v1",
        credentials=credentials,
        static_discovery=True,
        cache_discovery=False,
        client_options={"api_endpoint": live_url + "/"},
    )
    drive = build(
        "drive",
        "v3",
        credentials=credentials,
        static_discovery=True,
        cache_discovery=False,
        client_options={"api_endpoint": live_url + "/drive/v3/"},
    )
    identifier = docs.documents().create(body={"title": "Python contract"}).execute()["documentId"]
    docs.documents().batchUpdate(
        documentId=identifier,
        body={
            "requests": [
                {"insertText": {"location": {"index": 1}, "text": "Hello 😀 Python"}},
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": 1, "endIndex": 6},
                        "paragraphStyle": {"namedStyleType": "HEADING_2"},
                        "fields": "namedStyleType",
                    }
                },
                {"replaceAllText": {"containsText": {"text": "Python", "matchCase": True}, "replaceText": "client"}},
            ]
        },
    ).execute()
    result = docs.documents().get(documentId=identifier, fields="documentId,body").execute()
    assert result["body"]["content"][1]["paragraph"]["elements"][0]["textRun"]["content"] == "Hello 😀 client\n"
    assert drive.files().get(fileId=identifier, fields="id,name").execute()["name"] == "Python contract"
    assert drive.files().export(fileId=identifier, mimeType="text/plain").execute() == "Hello 😀 client\n".encode()
    assert drive.files().list(q="trashed = false", fields="files(id)").execute() == {"files": [{"id": identifier}]}
    copied = drive.files().copy(fileId=identifier, body={"name": "Copy"}).execute()["id"]
    permission = drive.permissions().create(fileId=copied, body={"type": "anyone", "role": "reader"}).execute()
    assert drive.permissions().list(fileId=copied).execute()["permissions"][0]["id"] == permission["id"]
    drive.permissions().delete(fileId=copied, permissionId=permission["id"]).execute()
    drive.files().delete(fileId=copied).execute()
    created = (
        drive.files().create(body={"name": "From Drive", "mimeType": "application/vnd.google-apps.document"}).execute()
    )
    assert docs.documents().get(documentId=created["id"]).execute()["title"] == "From Drive"
    docs.close()
    drive.close()


def test_node_official_clients(live_url):
    root = Path(__file__).resolve().parents[1]
    if not (root / "node_modules/googleapis").exists():
        if os.getenv("REQUIRE_NODE_CONTRACT") == "1":
            pytest.fail("Run npm ci to install Node contract dependency")
        pytest.skip("Run npm ci for official Node contracts")
    subprocess.run(["node", "tests/node-contract.cjs", live_url], cwd=root, check=True, timeout=60)


def test_service_account_jwt_exchange(live_url):
    # Generate a disposable signing key in memory, never read any auth store.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.oauth2 import service_account

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    credentials = service_account.Credentials.from_service_account_info(
        {
            "type": "service_account",
            "client_email": "synthetic@emulator.invalid",
            "token_uri": live_url + "/token",
            "private_key": pem,
        },
        scopes=["emulator-local"],
    )
    credentials.refresh(Request())
    assert credentials.token == "emulator-local-token"
    docs = build(
        "docs",
        "v1",
        credentials=credentials,
        static_discovery=True,
        cache_discovery=False,
        client_options={"api_endpoint": live_url + "/"},
    )
    assert docs.documents().create(body={"title": "Synthetic account"}).execute()["title"] == "Synthetic account"
    docs.close()


def test_browser_editor(live_url):
    root = Path(__file__).resolve().parents[1]
    if not (root / "node_modules/@playwright/test").exists():
        if os.getenv("REQUIRE_BROWSER_TEST") == "1":
            pytest.fail("Run npm ci for browser editor tests")
        pytest.skip("Run npm ci and install Chromium for browser editor tests")
    if not os.getenv("CHROMIUM_PATH") and not Path("/usr/bin/chromium-browser").exists():
        if os.getenv("REQUIRE_BROWSER_TEST") == "1":
            pytest.fail("Set CHROMIUM_PATH to the installed Chromium executable")
        pytest.skip("Set CHROMIUM_PATH for browser editor tests")
    (root / "data").mkdir(exist_ok=True)
    subprocess.run(["node", "tests/browser-editor.cjs", live_url], cwd=root, check=True, timeout=90)
