"""추천 자료 준비 전 목록·원문·DB를 읽기 전용으로 대조한다."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from backend.db.connection import database_connection

ROOT = Path(__file__).resolve().parents[1]
PREPARATION = ROOT / 'research' / 'preparation'
OUTPUT = PREPARATION / 'recommendation'


def read_json(name):
    """기존 준비 JSON을 수정하지 않고 읽는다."""
    return json.loads((PREPARATION / name).read_text(encoding='utf-8'))


def audit_recommendation_inventory():
    """현재 DB와 로컬 원문을 비교하고 감사 결과만 로컬에 저장한다."""
    catalog = read_json('catalog.json')
    technical = read_json('technical_exam_information.json')
    manifest = read_json('source_manifest.json')
    professional = read_json('professional_sources.json')
    documents = [json.loads(line) for line in (PREPARATION / 'official_documents.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    local_counts = Counter(item['qnet_code'] for item in catalog)
    local_by_code = {item['qnet_code']: item for item in catalog}
    technical_by_code = {item['qnet_code']: item for item in technical}
    documents_by_code = defaultdict(list)
    for document in documents:
        documents_by_code[str(document.get('qnet_code', ''))].append(document)

    with database_connection() as connection:
        # 읽기 전용 트랜잭션으로 의도하지 않은 변경을 DB에서도 차단한다.
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout = '20s'")
        certificates = connection.execute('SELECT id,qnet_code,name,category,description,career_tags,source_url,last_synced_at FROM certificates ORDER BY qnet_code').fetchall()
        exam_rows = connection.execute('SELECT certificate_id,subjects,pass_criteria,fees,raw_acquisition_text,raw_fee_text FROM exam_information').fetchall()
        schedules = connection.execute('SELECT certificate_id,count(*) AS count FROM schedules GROUP BY certificate_id').fetchall()
        source_history = connection.execute('SELECT count(*) AS total FROM sources').fetchone()['total']
        sources = connection.execute('SELECT DISTINCT ON (source_key) source_key,certificate_id,kind,collection_status,payload,retrieved_at FROM sources ORDER BY source_key,retrieved_at DESC').fetchall()

    db_by_code = {row['qnet_code']: row for row in certificates}
    exam_by_id = {str(row['certificate_id']): row for row in exam_rows}
    schedule_by_id = {str(row['certificate_id']): row['count'] for row in schedules}
    sources_by_id = defaultdict(list)
    for source in sources:
        if source['certificate_id'] is not None:
            sources_by_id[str(source['certificate_id'])].append(source)

    manifest_issues = []
    matched = 0
    for item in manifest:
        path = (ROOT / item['path']).resolve()
        if not path.is_relative_to(ROOT):
            manifest_issues.append({'path': item['path'], 'status': 'outside_workspace'})
            continue
        if not path.is_file():
            manifest_issues.append({'path': item['path'], 'status': 'missing'})
            continue
        data = path.read_bytes()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            manifest_issues.append({'path': item['path'], 'status': 'changed_since_manifest'})
        else:
            matched += 1

    keyword_candidates = []
    rows = []
    missing_fields = Counter()
    mismatches = []
    for code, certificate in db_by_code.items():
        identifier = str(certificate['id'])
        local = local_by_code.get(code, {})
        exam = exam_by_id.get(identifier)
        if local and (local['name'] != certificate['name'] or local['category'] != certificate['category']):
            mismatches.append({'qnet_code': code, 'local_name': local['name'], 'db_name': certificate['name'], 'local_category': local['category'], 'db_category': certificate['category']})
        description_present = bool((certificate.get('description') or '').strip())
        tags_present = bool(certificate.get('career_tags'))
        raw_text = (exam or {}).get('raw_acquisition_text') or ''
        attached_sources = sources_by_id.get(identifier, [])
        texts = [raw_text] + [d.get('content', '') for d in documents_by_code.get(code, [])]
        texts += [json.dumps(source['payload'], ensure_ascii=False) for source in attached_sources if source['kind'] == 'details' and source['collection_status'] == 'fetched']
        # 키워드는 검토 후보만 찾으며 직업 정보의 확정 근거로 사용하지 않는다.
        found = [term for term in ['수행직무', '진로', '전망', '관련직업'] if any(term in text for text in texts)]
        if found:
            keyword_candidates.append({'qnet_code': code, 'name': certificate['name'], 'keywords': found, 'status': 'needs_content_review'})
        gaps = ['ncs_mapping_not_prepared', 'related_jobs_with_evidence_not_prepared']
        if not description_present:
            gaps.append('summary_missing')
        if not tags_present:
            gaps.append('career_tags_empty')
        missing_fields.update(gaps)
        rows.append({'certificate_id': identifier, 'qnet_code': code, 'name': certificate['name'], 'category': certificate['category'], 'qnet_major_job_code': local.get('major_job_code') or '', 'qnet_job_code': local.get('job_code') or '', 'description_present': description_present, 'career_tags_present': tags_present, 'exam_information_present': exam is not None, 'raw_acquisition_present': bool(raw_text.strip()), 'document_count': len(documents_by_code.get(code, [])), 'schedule_count': schedule_by_id.get(identifier, 0), 'latest_detail_source_status': next((source['collection_status'] for source in attached_sources if source['kind'] == 'details'), ''), 'career_keyword_candidate': bool(found), 'gaps': '|'.join(gaps)})

    technical_differences = []
    for code, local_exam in technical_by_code.items():
        certificate = db_by_code.get(code)
        current_exam = exam_by_id.get(str(certificate['id'])) if certificate else None
        if current_exam:
            changed_fields = [field for field in ['subjects', 'pass_criteria', 'fees', 'raw_acquisition_text', 'raw_fee_text'] if local_exam['information'].get(field) != current_exam.get(field)]
            if changed_fields:
                technical_differences.append({'qnet_code': code, 'name': local_exam['name'], 'changed_fields': changed_fields})
    professional_changes = []
    for old_source in professional['results']:
        if old_source['kind'] != 'details':
            continue
        certificate = db_by_code.get(str(old_source['code']))
        if not certificate:
            continue
        current = next((source for source in sources_by_id.get(str(certificate['id']), []) if source['kind'] == 'details'), None)
        if current and old_source['status'] != current['collection_status']:
            professional_changes.append({'qnet_code': str(old_source['code']), 'name': certificate['name'], 'local_status': old_source['status'], 'database_status': current['collection_status']})

    source_states = Counter((s['kind'], s['collection_status']) for s in sources)
    report = {
        'audited_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'local_inventory_and_read_only_database_comparison',
        'writes': 'local_audit_files_only; no database writes or external API calls',
        'catalog': {'local_count': len(catalog), 'database_count': len(certificates), 'local_categories': dict(Counter(x['category'] for x in catalog)), 'database_categories': dict(Counter(x['category'] for x in certificates)), 'duplicate_local_codes': [code for code, count in local_counts.items() if count > 1], 'missing_in_database': sorted(set(local_by_code) - set(db_by_code)), 'database_only': sorted(set(db_by_code) - set(local_by_code)), 'name_category_mismatches': mismatches, 'qnet_major_job_codes_present': sum(bool(x.get('major_job_code')) for x in catalog), 'qnet_job_codes_present': sum(bool(x.get('job_code')) for x in catalog)},
        'existing_database': {'description_present': sum(r['description_present'] for r in rows), 'career_tags_present': sum(r['career_tags_present'] for r in rows), 'exam_information_count': len(exam_rows), 'raw_acquisition_present': sum(r['raw_acquisition_present'] for r in rows), 'certificates_with_schedules': len(schedules), 'schedule_rows': sum(r['count'] for r in schedules), 'sources_history_count': source_history, 'latest_sources_count': len(sources), 'latest_source_states': {kind + ':' + status: count for (kind, status), count in source_states.items()}},
        'existing_documents': {'count': len(documents), 'certificate_count': len(set(d['qnet_code'] for d in documents)), 'sections': dict(Counter(d['section'] for d in documents)), 'review_states': dict(Counter(d['review_status'] for d in documents)), 'unknown_certificate_codes': sorted(set(documents_by_code) - set(db_by_code)), 'replacement_character_documents': sum('\ufffd' in json.dumps(d, ensure_ascii=False) for d in documents)},
        'technical_file': {'count': len(technical), 'content_differences': technical_differences, 'missing_technical_codes': [code for code, item in local_by_code.items() if item['category'] == 'T' and code not in technical_by_code], 'database_id_mismatches': [{'qnet_code': code, 'local_id': item['information'].get('certificate_id'), 'database_id': str(db_by_code[code]['id'])} for code, item in technical_by_code.items() if code in db_by_code and str(item['information'].get('certificate_id')) != str(db_by_code[code]['id'])]},
        'manifest': {'count': len(manifest), 'unchanged': matched, 'issues': manifest_issues, 'note': 'Changed hashes indicate difference from the historical manifest, not proof of corruption.'},
        'professional_snapshot': {'local_status_counts': dict(Counter(x['kind'] + ':' + x['status'] for x in professional['results'])), 'detail_status_changes_in_database': professional_changes},
        'recommendation_gaps': dict(missing_fields),
        'keyword_candidates': keyword_candidates,
        'interpretation': ['Q-Net job codes are not confirmed NCS mappings.', 'Existing documents remain unreviewed and are mainly examination/eligibility material.', 'Keyword presence alone does not validate career evidence.', 'Current official naming, abolition and latest publication status were not checked against live sources in this inventory step.'],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'inventory_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    with (OUTPUT / 'inventory_audit.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {key: value for key, value in report.items() if key in ['catalog', 'existing_database', 'existing_documents', 'recommendation_gaps']}
    summary['manifest'] = {'count': len(manifest), 'unchanged': matched, 'issue_count': len(manifest_issues)}
    summary['career_keyword_candidate_count'] = len(keyword_candidates)
    summary['technical_content_difference_count'] = len(technical_differences)
    summary['professional_detail_status_changes'] = professional_changes
    print(json.dumps(summary, ensure_ascii=True, indent=2, default=str))


if __name__ == '__main__':
    audit_recommendation_inventory()
