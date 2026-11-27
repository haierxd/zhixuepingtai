"""Phase-two acceptance journeys and session/ownership regressions."""
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter

from .conftest import TEACHER_PASS


def upload(client, text=None):
    response = client.post('/api/learning/materials', data={
        'title': '过拟合与正则化',
        'markdown': text or '# 过拟合\n\n训练误差下降而验证误差上升，可能是模型过拟合。\n\n## 正则化\n\n正则化通过约束模型复杂度改善泛化。',
    })
    assert response.status_code == 200, response.text
    mid = response.json()['id']
    return client.get('/api/learning/materials/' + mid).json()


def test_selected_source_chat_citation_quiz_retry_and_resume(client):
    doc = upload(client)
    assert doc['can_ask'] and len(doc['blocks']) == 2
    block = doc['blocks'][0]
    source = {'material_id': doc['id'], 'anchor': block['anchor'],
              'selection': '训练误差下降而验证误差上升，可能是模型过拟合。'}
    first = client.post('/api/learning/ask', json={**source, 'question': '这说明什么？'})
    assert first.status_code == 200, first.text
    assert source['selection'] in first.json()['answer']
    assert first.json()['citation']['anchor'] == block['anchor']
    second_block = doc['blocks'][1]
    second = client.post('/api/learning/ask', json={
        'material_id': doc['id'], 'anchor': second_block['anchor'],
        'selection': '正则化通过约束模型复杂度改善泛化。', 'question': '解释这句话',
    })
    assert second.status_code == 200
    assert second.json()['citation']['anchor'] != first.json()['citation']['anchor']
    assert '正则化通过约束模型复杂度改善泛化。' in second.json()['answer']
    assert client.post('/api/learning/bookmarks', json=source).status_code == 200
    assert client.put('/api/learning/position', json={
        'material_id': doc['id'], 'anchor': second_block['anchor'], 'scroll': 0.7, 'page': 1,
    }).status_code == 200
    quiz = client.post('/api/learning/quiz', json=source)
    assert quiz.status_code == 200, quiz.text
    quiz = quiz.json()
    assert 'answer' not in quiz['question'] and 'explanation' not in quiz['question']
    assert not [r for r in client.get('/api/learning/records').json()['records'] if r['kind'] == 'quiz']
    result = client.post('/api/learning/grade', json={'quiz_id': quiz['quiz_id'], 'answer': 'A'})
    assert result.status_code == 200
    assert result.json()['score'] == 0 and result.json()['diagnosis']
    assert result.json()['citation']['anchor'] == block['anchor']
    retry = client.post('/api/learning/quiz', json={**source, 'retry_id': quiz['quiz_id']})
    assert retry.status_code == 200, retry.text
    assert retry.json()['question']['stem'] != quiz['question']['stem']
    assert retry.json()['question']['concept'] == quiz['question']['concept']
    assert client.post('/api/learning/grade', json={'quiz_id': retry.json()['quiz_id'], 'answer': 'B'}).json()['score'] == 100
    client.post('/api/logout')
    assert client.get('/api/learning/records').status_code == 401
    client.post('/api/login', json={'username': 'demo', 'password': '888888'})
    records = client.get('/api/learning/materials/' + doc['id']).json()['records']
    assert len([r for r in records if r['kind'] == 'position']) == 1
    assert next(r for r in records if r['kind'] == 'position')['payload']['scroll'] == 0.7
    assert next(r for r in records if r['kind'] == 'bookmark')['payload']['excerpt'] == source['selection']
    assert len([r for r in records if r['kind'] == 'quiz']) == 2


def test_student_sessions_prevent_header_forgery_and_cross_account_access(client, teacher):
    doc = upload(client)
    token = client.post('/api/login', json={'username': 'demo', 'password': '888888'}).json()['token']
    client.cookies.clear()
    assert client.get('/api/profile', headers={'X-Student-Id': 'demo-student'}).status_code == 401
    assert client.get('/api/learning/materials', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    assert client.get('/api/learning/materials', headers={'Authorization': 'Bearer ' + token}).status_code == 200
    stu = client.post('/api/teacher/students', headers=teacher, json={'name': '其他同学', 'username': 'other'}).json()
    client.post('/api/login', json={'username': 'other', 'password': '888888'})
    other_header = {'X-Student-Id': 'demo-student'}
    assert client.get('/api/profile', headers=other_header).status_code == 403
    assert client.get('/api/learning/materials/' + doc['id']).status_code == 404
    assert doc['id'] not in [d['id'] for d in client.get('/api/learning/materials').json()['materials']]
    assert client.post('/api/learning/ask', json={'material_id': doc['id'], 'question': '读一下'}).status_code == 404
    assert client.get('/api/teacher/overview').status_code == 401
    assert client.get('/api/learning/records').json()['records'] == []
    # Course-wide legacy retrieval never contains personal uploads.
    from app import documents
    hits = client.portal.call(documents.retrieve, '过拟合', 50)
    assert not any(hit.get('document_id') == doc['id'] for hit in hits)
    client.post('/api/logout')
    assert client.get('/api/session').status_code == 401


def test_markdown_selection_can_span_formatting_and_keeps_its_source(client):
    doc = upload(client, '# 正则化\n\n**正则化**通过[限制复杂度](/reference)改善泛化。')
    source = {'material_id': doc['id'], 'anchor': doc['blocks'][0]['anchor'],
              'selection': '正则化通过限制复杂度改善泛化。'}
    for route, extra in [('ask', {'question': '这句话是什么意思？'}), ('bookmarks', {}), ('quiz', {})]:
        response = client.post('/api/learning/' + route, json={**source, **extra})
        assert response.status_code == 200, response.text
        data = response.json()
        cite = data['payload'] if route == 'bookmarks' else data['citation']
        assert cite['excerpt'] == source['selection']
        assert cite['anchor'] == source['anchor']

    hidden_link = {**source, 'selection': '/reference', 'question': '解释这段文字。'}
    assert client.post('/api/learning/ask', json=hidden_link).status_code == 400


def test_pdf_retry_uses_original_citation_after_turning_to_a_scan(client):
    fixture = Path(__file__).parent / 'fixtures' / 'learning-reader.pdf'
    with fixture.open('rb') as pdf:
        upload = client.post('/api/learning/materials', data={'title': '混合 PDF'},
                             files={'file': ('reader.pdf', pdf, 'application/pdf')})
    assert upload.status_code == 200, upload.text
    mid = upload.json()['id']
    original = client.post('/api/learning/quiz', json={'material_id': mid, 'anchor': 'page-1'}).json()
    wrong = client.post('/api/learning/grade', json={'quiz_id': original['quiz_id'], 'answer': 'A'}).json()
    assert wrong['diagnosis']

    scan = {'material_id': mid, 'anchor': 'page-3'}
    assert client.post('/api/learning/quiz', json=scan).status_code == 400
    retry = client.post('/api/learning/quiz', json={**scan, 'retry_id': original['quiz_id']})
    assert retry.status_code == 200, retry.text
    assert retry.json()['citation'] == original['citation']
    assert retry.json()['question']['concept'] == original['question']['concept']
    assert retry.json()['question']['stem'] != original['question']['stem']


def test_pdf_scan_upload_validation_and_no_text_behavior(client):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO(); writer.write(buffer)
    created = client.post('/api/learning/materials', data={'title': '扫描资料'},
                          files={'file': ('scan.pdf', buffer.getvalue(), 'application/pdf')})
    assert created.status_code == 200
    assert created.json()['status'] == 'read_only' and not created.json()['can_ask']
    mid = created.json()['id']
    assert client.get('/api/learning/materials/' + mid + '/file').content.startswith(b'%PDF-')
    for path in ('ask', 'quiz', 'bookmarks'):
        response = client.post('/api/learning/' + path, json={
            'material_id': mid, 'anchor': 'page-1', 'question': '读一下', 'selection': '没有这段文字',
        })
        assert response.status_code == 400
    assert client.put('/api/learning/position', json={'material_id': mid, 'page': 1, 'anchor': 'page-1'}).status_code == 200
    assert client.post('/api/learning/materials', data={'title': '假 PDF'},
                       files={'file': ('fake.pdf', b'bad file', 'application/pdf')}).status_code == 400
    assert client.post('/api/learning/materials', data={'title': '不支持'},
                       files={'file': ('fake.exe', b'bad file', 'application/octet-stream')}).status_code == 400


def test_teacher_materials_and_textbook_are_readable_and_drafts_are_hidden(client, teacher):
    draft = client.post('/api/teacher/documents', headers=teacher, data={
        'title': '教师发布资料', 'topic_id': 'overfitting-regularization', 'markdown': '# 课程资料\n\n这是已发布的共享课件。',
    }).json()
    mid = f"course:{draft['id']}:{draft['latest_version_id']}"
    assert client.get('/api/learning/materials/' + mid).status_code == 404
    assert client.post(f"/api/teacher/documents/{draft['id']}/versions/{draft['latest_version_id']}/publish", headers=teacher).status_code == 200
    materials = client.get('/api/learning/materials').json()['materials']
    assert any(d['id'] == mid and d['source'] == 'course' for d in materials)
    assert len([d for d in materials if d['source'] == 'textbook']) == 16
    assert client.get('/api/learning/materials/topic:overfitting-regularization').json()['blocks']


def test_invalid_selection_rejected_and_diagnosis_requires_evidence(client, monkeypatch):
    doc = upload(client)
    source = {'material_id': doc['id'], 'anchor': doc['blocks'][0]['anchor'], 'selection': '伪造的资料内容'}
    assert client.post('/api/learning/ask', json={**source, 'question': '解释'}).status_code == 400
    source['selection'] = ''
    async def no_evidence(*args, **kwargs):
        return {'question': {'stem': '哪个正确？', 'options': ['A. 不正确', 'B. 正确', 'C. 不正确', 'D. 不正确'],
                             'answer': 'B', 'explanation': '查看原文解析', 'concept': '泛化',
                             'misconceptions': {'A': '未经证实的错因'}, 'evidence': '不在资料中的原文证据'}}
    from app import gemini
    monkeypatch.setattr(gemini, 'generate_json', no_evidence)
    quiz = client.post('/api/learning/quiz', json=source).json()
    result = client.post('/api/learning/grade', json={'quiz_id': quiz['quiz_id'], 'answer': 'A'}).json()
    assert not result['diagnosis']
    assert client.post('/api/learning/quiz', json={**source, 'retry_id': quiz['quiz_id']}).status_code == 400


def test_role_entry_pages_have_shared_assets(client):
    for url in ('/', '/student/', '/teacher/'):
        assert client.get(url).status_code == 200


def test_teacher_cannot_write_as_a_student_without_a_student_session(client, teacher):
    doc = upload(client)
    client.cookies.clear()
    assert client.post('/api/chat', headers=teacher, json={'message': '问题'}).status_code == 401
    assert client.post('/api/quiz/generate', headers=teacher, json={'topic_id': 'cnn'}).status_code == 401
    assert client.get('/api/learning/materials', headers=teacher).status_code == 401
    assert client.get('/api/learning/materials/' + doc['id'], headers=teacher).status_code == 401
    assert client.get('/api/learning/records', headers=teacher).status_code == 401
    assert client.post('/api/learning/ask', headers=teacher,
                       json={'material_id': doc['id'], 'question': '解释一下'}).status_code == 401
    assert client.get('/api/teacher/overview', headers=teacher).status_code == 200


def test_teacher_can_read_selected_student_learning_without_student_login(client, teacher):
    from app import store
    stu = client.post('/api/teacher/students', headers=teacher,
                      json={'name': '只读学情学生', 'username': 'read-only'}).json()
    store.update_mastery(stu['id'], 'cnn', observed=75)
    client.cookies.clear()
    query = {'student_id': stu['id']}
    profile = client.get('/api/profile', headers=teacher, params=query)
    assert profile.status_code == 200
    assert profile.json()['student']['id'] == stu['id']
    for endpoint in ('state', 'topics', 'graph', 'path', 'history', 'quizzes', 'mistakes', 'assignments'):
        response = client.get('/api/' + endpoint, headers=teacher, params=query)
        assert response.status_code == 200, (endpoint, response.text)
    for endpoint, body in [('quiz/grade', {'quiz_id': 'missing', 'answers': {}}),
                           ('emotion/frame', {}), ('learning/quiz', {'material_id': 'topic:cnn'})]:
        assert client.post('/api/' + endpoint, headers=teacher, params=query, json=body).status_code == 401


def test_reset_retains_personal_files_delete_removes_them(client, teacher, settings):
    stu = client.post('/api/teacher/students', headers=teacher,
                      json={'name': '删除测试', 'username': 'cleanup'}).json()
    client.post('/api/login', json={'username': 'cleanup', 'password': '888888'})
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    buffer = BytesIO(); writer.write(buffer)
    doc = client.post('/api/learning/materials', data={'title': '私有 PDF'},
                      files={'file': ('scan.pdf', buffer.getvalue(), 'application/pdf')}).json()
    path = settings.document_dir / 'personal' / (doc['id'] + '.pdf')
    assert path.exists()
    assert client.put('/api/learning/position', json={'material_id': doc['id'], 'anchor': 'page-1'}).status_code == 200
    assert client.post(f"/api/teacher/student/{stu['id']}/reset", headers=teacher).status_code == 200
    assert path.exists() and not client.get('/api/learning/records').json()['records']
    assert client.delete(f"/api/teacher/student/{stu['id']}", headers=teacher).status_code == 200
    assert not path.exists()
    assert client.get('/api/session').status_code == 401


def test_grading_without_diagnosis_service_still_returns_explanation(client, monkeypatch):
    from app import gemini
    doc = upload(client)
    quiz = client.post('/api/learning/quiz', json={'material_id': doc['id']}).json()
    async def fail_diagnosis(*args, **kwargs):
        raise gemini.GeminiError('unavailable')
    monkeypatch.setattr(gemini, 'generate_json', fail_diagnosis)
    grade = client.post('/api/learning/grade', json={'quiz_id': quiz['quiz_id'], 'answer': 'A'})
    assert grade.status_code == 200
    assert grade.json()['score'] == 0 and grade.json()['explanation'] and not grade.json()['diagnosis']
