from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

from fastapi.testclient import TestClient

from google_docs_emulator.app import DOCX_MIME, create_app


def create(client, text=""):
    identifier = client.post("/v1/documents", json={"title": "Test"}).json()["documentId"]
    if text:
        assert update(client, identifier, [{"insertText": {"location": {"index": 1}, "text": text}}]).status_code == 200
    return identifier


def update(client, identifier, requests, **extra):
    return client.post(f"/v1/documents/{identifier}:batchUpdate", json={"requests": requests, **extra})


def text(client, identifier):
    return client.get(f"/drive/v3/files/{identifier}/export", params={"mimeType": "text/plain"}).text


def test_utf16_structure_styles_and_edits(client):
    identifier = create(client, "A😀B\nSecond")
    doc = client.get("/v1/documents/" + identifier).json()
    assert doc["body"]["content"][0]["endIndex"] == 1
    assert doc["body"]["content"][1]["endIndex"] == 6
    assert doc["body"]["content"][2]["endIndex"] == 13
    response = update(
        client,
        identifier,
        [
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": 1, "endIndex": 5},
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    "fields": "namedStyleType",
                }
            },
            {
                "updateTextStyle": {
                    "range": {"startIndex": 2, "endIndex": 4},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            },
            {"deleteContentRange": {"range": {"startIndex": 4, "endIndex": 5}}},
            {"insertText": {"location": {"index": 4}, "text": "!"}},
        ],
    )
    assert response.status_code == 200
    assert text(client, identifier) == "A😀!\nSecond\n"
    doc = client.get("/v1/documents/" + identifier).json()
    paragraph = doc["body"]["content"][1]["paragraph"]
    assert paragraph["paragraphStyle"]["namedStyleType"] == "HEADING_1"
    assert paragraph["elements"][1]["textRun"]["textStyle"]["bold"]
    assert client.get(f"/drive/v3/files/{identifier}/export", params={"mimeType": "text/markdown"}).text.startswith(
        "# A😀!"
    )


def test_batch_rollback_surrogates_final_newline_and_revision(client):
    identifier = create(client, "😀")
    before = client.get("/v1/documents/" + identifier).json()
    for requests in [
        [{"insertText": {"location": {"index": 2}, "text": "bad"}}],
        [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 4}}}],
        [{"insertText": {"location": {"index": 1}, "text": "changed"}}, {"unsupported": {}}],
        [{"updateTextStyle": {"range": {"startIndex": 1, "endIndex": 3}, "textStyle": {}, "fields": "font.x"}}],
    ]:
        assert update(client, identifier, requests).status_code == 400
        assert client.get("/v1/documents/" + identifier).json() == before
    assert update(client, identifier, [], writeControl={"requiredRevisionId": "old"}).status_code == 400
    assert update(client, identifier, [], writeControl={"requiredRevisionId": before["revisionId"]}).status_code == 200


def test_replace_and_style_reset(client):
    identifier = create(client, "One one ONE")
    response = update(
        client,
        identifier,
        [{"replaceAllText": {"containsText": {"text": "one", "matchCase": False}, "replaceText": "two"}}],
    )
    assert response.json()["replies"] == [{"replaceAllText": {"occurrencesChanged": 3}}]
    assert text(client, identifier) == "two two two\n"
    for style in [{"italic": True}, {}]:
        assert (
            update(
                client,
                identifier,
                [
                    {
                        "updateTextStyle": {
                            "range": {"startIndex": 1, "endIndex": 4},
                            "textStyle": style,
                            "fields": "italic",
                        }
                    }
                ],
            ).status_code
            == 200
        )
    run = client.get("/v1/documents/" + identifier).json()["body"]["content"][1]["paragraph"]["elements"][0]
    assert run["textRun"]["textStyle"] == {}


def test_drive_lifecycle_pagination_queries_permissions_exports(client):
    identifier = create(client, "Hello <world>")
    copied = client.post(f"/drive/v3/files/{identifier}/copy", json={"name": "Copy"}).json()["id"]
    assert copied != identifier
    assert text(client, copied) == "Hello <world>\n"
    client.patch("/drive/v3/files/" + identifier, json={"trashed": True, "name": "Changed"})
    result = client.get(
        "/drive/v3/files", params={"q": "trashed = false and name contains 'Cop'", "fields": "files(id,name)"}
    ).json()
    assert result == {"files": [{"id": copied, "name": "Copy"}]}
    page = client.get("/drive/v3/files", params={"pageSize": 1, "orderBy": "name"}).json()
    assert page["nextPageToken"] == "1"
    assert len(client.get("/drive/v3/files", params={"pageSize": 1, "pageToken": "1"}).json()["files"]) == 1
    for params in [{"q": "unsupported = true"}, {"pageToken": "-1"}, {"pageSize": 0}, {"orderBy": "size"}]:
        assert client.get("/drive/v3/files", params=params).status_code == 400
    permission = client.post(f"/drive/v3/files/{copied}/permissions", json={"type": "anyone", "role": "reader"}).json()
    assert client.get(f"/drive/v3/files/{copied}/permissions").json()["permissions"] == [permission]
    assert client.delete(f"/drive/v3/files/{copied}/permissions/" + permission["id"]).status_code == 204
    data = client.get(f"/drive/v3/files/{copied}/export", params={"mimeType": DOCX_MIME}).content
    with ZipFile(BytesIO(data)) as archive:
        tree = ElementTree.fromstring(archive.read("word/document.xml"))
        assert "Hello <world>" in "".join(tree.itertext())
    assert client.get(f"/drive/v3/files/{copied}/export", params={"mimeType": "application/pdf"}).status_code == 400
    assert client.delete("/drive/v3/files/" + copied).status_code == 204
    assert client.get("/v1/documents/" + copied).status_code == 404


def test_fixtures_reset_persistence_and_escaping(tmp_path):
    path = str(tmp_path / "data.sqlite")
    with TestClient(create_app(database=path)) as client:
        assert client.post(
            "/api/admin/seed", json={"documents": [{"documentId": "seed", "title": "<script>", "text": "Hello"}]}
        ).json() == {"loaded": 1}
        assert "&lt;script&gt;" in client.get("/").text
        assert "<script>" not in client.get("/ui/documents/seed").text
        structural = client.get("/v1/documents/seed").json()
        structural["documentId"] = "structural"
        assert client.post("/api/admin/seed", json={"documents": [structural]}).status_code == 200
        assert text(client, "structural") == "Hello\n"
        assert (
            client.post(
                "/api/admin/seed", json={"documents": [{"documentId": "rollback"}, {"documentId": "seed"}]}
            ).status_code
            == 400
        )
        assert client.get("/v1/documents/rollback").status_code == 404
    with TestClient(create_app(database=path)) as client:
        assert text(client, "seed") == "Hello\n"
        assert client.post("/api/admin/reset").status_code == 200
    with TestClient(create_app(database=path)) as client:
        assert client.get("/drive/v3/files").json()["files"] == []


def test_markdown_startup_seed(tmp_path):
    path = tmp_path / "fixture.md"
    path.write_text("# Hello\n")
    with TestClient(create_app(seed=str(path))) as client:
        assert text(client, "fixture") == "# Hello\n"


def test_fake_auth():
    with TestClient(create_app(auth_mode="strict")) as client:
        assert client.post("/v1/documents", json={}).status_code == 401
        assert client.post("/v1/documents", json={}, headers={"Authorization": "Bearer fake-local"}).status_code == 200
        assert (
            client.post("/token", data={"grant_type": "refresh_token", "refresh_token": "fake"}).json()["token_type"]
            == "Bearer"
        )
        assert client.post("/token", data={"grant_type": "bad"}).status_code == 400


def test_concurrent_updates_are_not_lost(client):
    identifier = create(client)

    def insert(_):
        return update(client, identifier, [{"insertText": {"location": {"index": 1}, "text": "x"}}]).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(insert, range(30))) == [200] * 30
    assert text(client, identifier) == "x" * 30 + "\n"


def test_empty_document_end_location_and_projection(client):
    identifier = create(client)
    empty = client.get("/v1/documents/" + identifier).json()
    assert empty["body"]["content"][1]["paragraph"]["elements"][0]["textRun"]["content"] == "\n"
    assert update(client, identifier, [{"insertText": {"endOfSegmentLocation": {}, "text": "tail"}}]).status_code == 200
    assert text(client, identifier) == "tail\n"
    assert client.get(
        "/v1/documents/" + identifier, params={"fields": "body/content(paragraph/elements/textRun/content)"}
    ).json() == {"body": {"content": [{}, {"paragraph": {"elements": [{"textRun": {"content": "tail\n"}}]}}]}}


def test_malformed_batches_are_errors_and_atomic(client):
    identifier = create(client, "unchanged")
    for requests in [
        None,
        {},
        [None],
        [{"insertText": None}],
        [{"insertText": {"text": "bad"}}],
        [{"insertText": {"location": {"index": True}, "text": "bad"}}],
        [{"insertText": {"location": {"index": 1}, "text": 123}}],
    ]:
        assert update(client, identifier, requests).status_code == 400
        assert text(client, identifier) == "unchanged\n"


def test_parent_search_and_copy_isolation(client):
    parent = client.post(
        "/drive/v3/files", json={"name": "Folder", "mimeType": "application/vnd.google-apps.folder"}
    ).json()["id"]
    identifier = client.post("/drive/v3/files", json={"name": "Agent's doc", "parents": [parent]}).json()["id"]
    assert client.get("/drive/v3/files", params={"q": f"'{parent}' in parents", "fields": "files(id)"}).json() == {
        "files": [{"id": identifier}]
    }
    assert client.get("/drive/v3/files", params={"q": "name = 'Agent\\'s doc'"}).json()["files"][0]["id"] == identifier
    copied = client.post(f"/drive/v3/files/{identifier}/copy", json={}).json()["id"]
    assert update(client, copied, [{"insertText": {"location": {"index": 1}, "text": "copy only"}}]).status_code == 200
    assert text(client, identifier) == "\n"
    assert text(client, copied) == "copy only\n"
