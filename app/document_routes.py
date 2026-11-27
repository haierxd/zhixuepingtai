"""Material APIs using the existing single-class identity model."""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import auth, documents, store
from .config import get_settings

router = APIRouter()


def teacher(x_teacher_pass: str | None = Header(None)):
    if not x_teacher_pass or x_teacher_pass != get_settings().teacher_passcode:
        raise HTTPException(401, "教师口令无效")


def reader(request: Request, x_teacher_pass: str | None = Header(None), x_student_id: str | None = Header(None)):
    if x_teacher_pass and x_teacher_pass == get_settings().teacher_passcode:
        return "teacher"
    auth.student(request)
    return "student"


def visible(document_id, version_id, role):
    row = documents.version(document_id, version_id)
    if role != "teacher":
        if row["status"] not in documents.PUBLISHED:
            raise HTTPException(404, "课件版本不存在或尚未发布")


async def content(file, markdown):
    if file:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".md", ".pdf"}:
            raise HTTPException(400, "仅支持 .pdf 和 .md 文件")
        try:
            payload = await file.read(get_settings().document_max_bytes + 1)
        finally:
            await file.close()
        return payload, file.filename, "pdf" if suffix == ".pdf" else "markdown"
    return markdown.encode("utf-8"), "讲义.md", "markdown"


@router.get("/api/teacher/documents", dependencies=[Depends(teacher)])
def teacher_list():
    return {"documents": documents.list_documents()}


@router.get("/api/teacher/documents/{document_id}", dependencies=[Depends(teacher)])
def teacher_detail(document_id: str):
    return documents.detail(document_id)


@router.post("/api/teacher/documents", dependencies=[Depends(teacher)])
async def create(title: str = Form(...), topic_id: str = Form(...),
                 course_id: str = Form(documents.COURSE_ID), markdown: str = Form(""),
                 file: UploadFile | None = File(None)):
    if course_id != documents.COURSE_ID:
        raise HTTPException(400, "当前仅开放默认课程")
    payload, filename, kind = await content(file, markdown)
    return await run_in_threadpool(documents.save_draft, title=title, topic_id=topic_id,
                                  content=payload, filename=filename, kind=kind)


@router.post("/api/teacher/documents/{document_id}/versions", dependencies=[Depends(teacher)])
async def new_version(document_id: str, title: str = Form(...), markdown: str = Form(""),
                      file: UploadFile | None = File(None)):
    doc = documents.document(document_id)
    payload, filename, kind = await content(file, markdown)
    return await run_in_threadpool(documents.save_draft, title=title, topic_id=doc["topic_id"],
                                  content=payload, filename=filename, kind=kind, document_id=document_id)


@router.post("/api/teacher/documents/{document_id}/versions/{version_id}/publish", dependencies=[Depends(teacher)])
async def publish(document_id: str, version_id: str, tasks: BackgroundTasks):
    documents.request_publish(document_id, version_id)
    tasks.add_task(documents.publish, document_id, version_id)
    return {"status": "indexing", "version_id": version_id}


@router.get("/api/documents")
def student_list(role: str = Depends(reader)):
    return {"documents": documents.list_documents(published_only=role != "teacher")}


@router.get("/api/documents/{document_id}/versions/{version_id}")
def read_version(document_id: str, version_id: str, role: str = Depends(reader)):
    visible(document_id, version_id, role)
    return documents.version_detail(document_id, version_id)


@router.get("/api/documents/{document_id}/versions/{version_id}/file")
def pdf(document_id: str, version_id: str, role: str = Depends(reader)):
    visible(document_id, version_id, role)
    return FileResponse(documents.file_path(document_id, version_id), media_type="application/pdf",
                        headers={"Content-Disposition": "inline", "Cache-Control": "private, no-store"})


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    document_id: str | None = None


@router.post("/api/documents/search")
async def search(req: SearchRequest, _: str = Depends(reader)):
    return {"chunks": await documents.retrieve(req.query, document_id=req.document_id)}
