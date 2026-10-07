"""보관한 공식 일정 표를 검증하고 종목별 트랜잭션으로 저장한다."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import psycopg

from backend.db.connection import database_connection
from backend.db.repository import save_schedule
from backend.official_schedule_page import inspect_schedule_page, is_school_exam, normalize_schedule_page
from backend.sync_batch import PROJECT_ROOT, error_result, load_technical_catalog, write_report


def reprocess_schedule_pages(source: Path, output: Path, apply: bool, notice_path: Path) -> dict:
    """외부 재호출 없이 원본 시각을 유지하고 실패·빈 일정은 기존 DB를 보존한다."""
    original = json.loads(source.read_text(encoding='utf-8'))
    catalog = load_technical_catalog()
    notice = json.loads(notice_path.read_text(encoding='utf-8'))
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'source_report': str(source),
              'apply_requested': apply, 'completed': False, 'results': []}
    with database_connection() as connection:
        connection.autocommit = True
        for row in original['results']:
            result = dict(row)
            step = 'normalize'
            try:
                if row['status'] != 'fetched':
                    report['results'].append(result)
                    continue
                certificate = catalog.get(row['qnet_code'])
                if certificate is None or str(certificate['id']) != row['certificate_id'] or certificate['name'] != row['name']:
                    raise ValueError('원본의 종목과 현재 DB의 종목이 일치하지 않습니다.')
                file = (PROJECT_ROOT / row['response_file']).resolve()
                if not file.is_relative_to(PROJECT_ROOT / 'research'):
                    raise ValueError('원본 HTML은 프로젝트 research 폴더에 있어야 합니다.')
                response = {**row, 'html': file.read_text(encoding='utf-8'),
                            'retrieved_at': datetime.fromisoformat(row['retrieved_at'])}
                schedules = normalize_schedule_page(certificate, response, notice)
                page = inspect_schedule_page(response['html'])
                result['excluded_school_exam_rows'] = sum(is_school_exam(cells) for table in page['tables'] for cells in table)
                result['schedules'] = [schedule.model_dump(mode='json') for schedule in schedules]
                result['status'] = 'validated' if schedules else 'empty'
                if certificate['name'] in notice['on_demand_names']:
                    result['on_demand_notice'] = {'source_url': notice['source_url'], 'retrieved_at': notice['retrieved_at'],
                                                'message': '상시검정 시행종목. 지역·시험장별 상시 일정은 별도 연동이 필요합니다.'}
                if apply and schedules:
                    step = 'database_save'
                    saved_count = 0
                    retained_keys = []
                    # 전체 행을 검증한 다음 같은 종목의 모든 단계를 함께 확정한다.
                    with connection.transaction():
                        for schedule in schedules:
                            saved = save_schedule(connection, schedule, preserve_known=True)
                            if saved['last_synced_at'] == schedule.last_synced_at:
                                saved_count += 1
                            else:
                                retained_keys.append({'round_key': schedule.round_key, 'phase': schedule.phase})
                    result.update(status='saved' if saved_count else 'unchanged', saved_rows=saved_count,
                                  retained_rows=len(retained_keys), retained_keys=retained_keys)
            except (ValueError, OSError, psycopg.Error) as error:
                result.update(error_result(error, step))
            report['results'].append(result)
            if len(report['results']) % 25 == 0:
                write_report(output, report)
                print(f"[{len(report['results'])}/{len(original['results'])}] {result['name']}: {result['status']}", flush=True)
    report['summary'] = dict(Counter(row['status'] for row in report['results']))
    report['normalized_rows'] = sum(len(row.get('schedules', [])) for row in report['results'])
    report['saved_rows'] = sum(row.get('saved_rows', 0) for row in report['results'])
    report['retained_rows'] = sum(row.get('retained_rows', 0) for row in report['results'])
    report['excluded_school_exam_rows'] = sum(row.get('excluded_school_exam_rows', 0) for row in report['results'])
    report['completed'] = original['completed'] and len(report['results']) == len(original['requested_codes'])
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    write_report(output, report)
    return report


def main() -> None:
    """기본은 검증이며 --apply가 있어야 DB에 저장한다."""
    parser = argparse.ArgumentParser(description='공식 일정 페이지 검증·저장')
    parser.add_argument('--from-report', type=Path, default=PROJECT_ROOT / 'research/all_technical_schedule_sources.json')
    parser.add_argument('--output', type=Path, default=PROJECT_ROOT / 'research/all_technical_schedule_preview.json')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--notice', type=Path, default=PROJECT_ROOT / 'research/technical_2026_annual_notice.json', help='검토한 공식 시행공고의 접수 예외·출처')
    options = parser.parse_args()
    if options.from_report.resolve() == options.output.resolve():
        parser.error('원본 파일과 출력 파일은 다른 경로로 지정해주세요.')
    report = reprocess_schedule_pages(options.from_report, options.output, options.apply, options.notice)
    print(json.dumps({key: report[key] for key in ('summary', 'normalized_rows', 'saved_rows', 'retained_rows')}, ensure_ascii=False))
    if report['summary'].get('failed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
