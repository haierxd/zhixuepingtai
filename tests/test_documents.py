from io import BytesIO

from pypdf import PdfWriter


def _topic_id(client):
    return client.get("/api/topics").json()["topics"][0]["id"]


def _draft(client, teacher, *, title="版本管理讲义", markdown=None):
    return client.post("/api/teacher/documents", headers=teacher, data={
        "title": title,
        "topic_id": _topic_id(client),
        "markdown": markdown or "# 版本管理\n\n明确区分草稿与当前生效的学习资料。\n\n## 发布顺序\n\n先完整建立检索索引，再切换课件版本。",
    })


def test_markdown_draft_publish_search_and_student_access(client, teacher):
    created = _draft(client, teacher)
    assert created.status_code == 200, created.text
    doc = created.json()
    version = doc["versions"][0]
    assert version["status"] == "draft"
    assert client.get("/api/documents", headers={"X-Student-Id": "demo-student"}).json()["documents"] == []
    assert client.get(f"/api/documents/{doc['id']}/versions/{version['id']}",
                      headers={"X-Student-Id": "demo-student"}).status_code == 404

    published = client.post(f"/api/teacher/documents/{doc['id']}/versions/{version['id']}/publish",
                            headers=teacher)
    assert published.status_code == 200
    state = client.get(f"/api/teacher/documents/{doc['id']}", headers=teacher).json()
    assert state["active_version_id"] == version["id"]
    assert state["versions"][0]["status"] == "published"

    visible = client.get("/api/documents", headers={"X-Student-Id": "demo-student"})
    assert visible.status_code == 200
    assert len(visible.json()["documents"]) == 1
    search = client.post("/api/documents/search", headers={"X-Student-Id": "demo-student"},
                         json={"query": "课件索引发布顺序"})
    assert search.status_code == 200
    assert search.json()["chunks"]
    assert search.json()["chunks"][0]["document_id"] == doc["id"]
    # The ordinary RAG entry point must include published materials as well.
    from app.rag import get_index
    hits = client.portal.call(get_index().retrieve, "课件索引发布顺序", 200)
    assert any(hit.get("document_id") == doc["id"] for hit in hits)


def test_failed_new_version_keeps_previous_active_version(client, teacher, monkeypatch):
    first = _draft(client, teacher, title="稳定版本").json()
    first_version = first["versions"][0]["id"]
    client.post(f"/api/teacher/documents/{first['id']}/versions/{first_version}/publish", headers=teacher)
    second = client.post(f"/api/teacher/documents/{first['id']}/versions", headers=teacher, data={
        "title": "待发布新版", "markdown": "# 新版\n\n新内容等待建立向量索引。",
    }).json()
    second_version = second["versions"][0]["id"]

    from app import gemini
    original_embedding = gemini.embed_batch
    async def fail_embedding(*args, **kwargs):
        raise RuntimeError("test failure")
    monkeypatch.setattr(gemini, "embed_batch", fail_embedding)
    response = client.post(f"/api/teacher/documents/{first['id']}/versions/{second_version}/publish",
                           headers=teacher)
    assert response.status_code == 200
    current = client.get(f"/api/teacher/documents/{first['id']}", headers=teacher).json()
    assert current["active_version_id"] == first_version
    assert next(v for v in current["versions"] if v["id"] == second_version)["status"] == "failed"
    visible = client.get("/api/documents", headers={"X-Student-Id": "demo-student"}).json()["documents"]
    assert visible[0]["title"] == "稳定版本"
    assert visible[0]["version_id"] == first_version
    monkeypatch.setattr(gemini, "embed_batch", original_embedding)
    assert client.post(f"/api/teacher/documents/{first['id']}/versions/{second_version}/publish", headers=teacher).status_code == 200
    retried = client.get(f"/api/teacher/documents/{first['id']}", headers=teacher).json()
    assert retried["active_version_id"] == second_version
    assert client.get(f"/api/documents/{first['id']}/versions/{first_version}",
                      headers={"X-Student-Id": "demo-student"}).status_code == 200
    older = client.post(f"/api/teacher/documents/{first['id']}/versions", headers=teacher, data={
        "title": "旧草稿", "markdown": "# 旧草稿\n\n此版本没有发布。",
    }).json()["latest_version_id"]
    assert client.get(f"/api/documents/{first['id']}/versions/{first_version}",
                      headers={"X-Student-Id": "demo-student"}).status_code == 200
    assert client.get(f"/api/documents/{first['id']}/versions/{older}",
                      headers={"X-Student-Id": "demo-student"}).status_code == 404


def test_scanned_pdf_is_read_only_and_original_is_served(client, teacher):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    response = client.post("/api/teacher/documents", headers=teacher, data={
        "title": "扫描讲义", "topic_id": _topic_id(client),
    }, files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")})
    assert response.status_code == 200, response.text
    doc = response.json()
    version_id = doc["versions"][0]["id"]
    assert doc["versions"][0]["status"] == "draft"
    client.post(f"/api/teacher/documents/{doc['id']}/versions/{version_id}/publish", headers=teacher)
    detail = client.get(f"/api/documents/{doc['id']}/versions/{version_id}",
                        headers={"X-Student-Id": "demo-student"}).json()
    assert detail["status"] == "read_only"
    assert detail["pages"] == [{"version_id": version_id, "page_number": 1, "text": "", "status": "no_text"}]
    pdf = client.get(f"/api/documents/{doc['id']}/versions/{version_id}/file",
                     headers={"X-Student-Id": "demo-student"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")


def test_upload_validation_and_authorization(client, teacher, settings, monkeypatch):
    assert _draft(client, {}).status_code == 401
    client.cookies.clear()
    assert client.get("/api/documents").status_code == 401
    assert client.post("/api/login", json={"username": "missing", "password": "wrong"}).status_code == 401
    student = client.post("/api/login", json={"username": "demo", "password": "888888"})
    assert student.status_code == 200
    assert client.get("/api/documents", headers={"X-Student-Id": student.json()["id"]}).status_code == 200
    assert client.post("/api/teacher/documents", headers=teacher,
                       data={"title": "", "topic_id": _topic_id(client), "markdown": "正文"}).status_code in (400, 422)
    assert client.post("/api/teacher/documents", headers=teacher,
                       data={"title": "未知知识点", "topic_id": "nonexistent", "markdown": "正文"}).status_code == 400
    data = {"title": "非法文件", "topic_id": _topic_id(client)}
    assert client.post("/api/teacher/documents", headers=teacher, data=data,
                       files={"file": ("fake.pdf", b"not a PDF", "application/pdf")}).status_code == 400
    assert client.post("/api/teacher/documents", headers=teacher, data=data,
                       files={"file": ("file.exe", b"content", "application/octet-stream")}).status_code == 400
    monkeypatch.setattr(settings, "document_max_bytes", 16)
    assert _draft(client, teacher, markdown="a" * 17).status_code == 413


def test_corrupt_and_encrypted_pdf_cannot_publish(client, teacher):
    encrypted = PdfWriter()
    encrypted.add_blank_page(width=100, height=100)
    encrypted.encrypt("not-a-real-password")
    buffer = BytesIO()
    encrypted.write(buffer)
    for payload in (b"%PDF-1.4\ntruncated", buffer.getvalue()):
        response = client.post("/api/teacher/documents", headers=teacher, data={
            "title": "不可解析课件", "topic_id": _topic_id(client),
        }, files={"file": ("file.pdf", payload, "application/pdf")})
        assert response.status_code == 200
        doc = response.json()
        assert doc["versions"][0]["status"] == "parse_failed"
        assert client.post(f"/api/teacher/documents/{doc['id']}/versions/{doc['latest_version_id']}/publish",
                           headers=teacher).status_code == 400


def test_pdf_pages_and_source_positions(client, teacher, monkeypatch, settings):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    for text in ("Regularization reduces overfitting.", "Validation error differs from training error."):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    def upload():
        return client.post("/api/teacher/documents", headers=teacher, data={
            "title": "Text PDF", "topic_id": _topic_id(client),
        }, files={"file": ("lesson.pdf", buffer.getvalue(), "application/pdf")})
    response = upload()
    assert response.status_code == 200
    doc = response.json()
    assert doc["versions"][0]["text_pages"] == 2
    vid = doc["latest_version_id"]
    client.post(f"/api/teacher/documents/{doc['id']}/versions/{vid}/publish", headers=teacher)
    hits = client.post("/api/documents/search", headers=teacher,
                       json={"query": "validation error", "document_id": doc["id"]}).json()["chunks"]
    assert {hit["page_number"] for hit in hits} == {1, 2}
    assert all(hit["version_id"] == vid for hit in hits)
    monkeypatch.setattr(settings, "document_max_pages", 1)
    assert upload().status_code == 413


def test_markdown_fences_and_formulas_remain_whole():
    from app.documents import markdown_chunks
    body = "# 内容\n\n```python\n## not a heading\n" + "code\n" * 250 + "```\n\n$$\nx^2 + y^2 = 1\n$$\n\n## 小节\n\n段落"
    chunks = markdown_chunks(body)
    fenced = [chunk for chunk in chunks if "```python" in chunk["text"]]
    assert len(fenced) == 1
    assert fenced[0]["text"].count("```") == 2
    assert any("$$\nx^2 + y^2 = 1\n$$" in chunk["text"] for chunk in chunks)
    assert len({chunk["section_anchor"] for chunk in chunks}) == 2
