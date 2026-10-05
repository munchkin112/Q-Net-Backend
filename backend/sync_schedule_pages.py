"""기술자격 전체의 공식 일정 페이지 원본을 순서대로 확보한다."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import time

from backend.official_api import OfficialAPIError
from backend.official_schedule_page import fetch_schedule_page
from backend.sync_batch import PROJECT_ROOT, error_result, load_technical_catalog, write_report


def collect(output: Path, interval: float) -> dict:
    """종목 하나가 실패해도 다음 종목으로 계속하며 DB를 변경하지 않는다."""
    catalog = load_technical_catalog()
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'completed': False,
              'source_type': 'official_page', 'requested_codes': list(catalog), 'results': []}
    directory = output.parent / (output.stem + '_html')
    directory.mkdir(parents=True, exist_ok=True)
    for index, certificate in enumerate(catalog.values(), start=1):
        code = certificate['qnet_code']
        row = {'qnet_code': code, 'name': certificate['name'], 'certificate_id': str(certificate['id'])}
        try:
            response = fetch_schedule_page(code)
            file = directory / (code + '.html')
            file.write_text(response['html'], encoding='utf-8')
            row.update(status='fetched', source_url=response['source_url'],
                       retrieved_at=response['retrieved_at'].isoformat(), retry_count=response['retry_count'],
                       response_file=str(file.resolve().relative_to(PROJECT_ROOT)))
        except (OfficialAPIError, ValueError) as error:
            row.update(error_result(error, 'official_page'))
        report['results'].append(row)
        write_report(output, report)
        print(f"[{index}/{len(catalog)}] {row['name']}: {row['status']}", flush=True)
        time.sleep(interval)
    report['completed'] = True
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    write_report(output, report)
    return report


def main() -> None:
    """기술자격의 종목별 공식 일정 표 원본을 저장한다."""
    parser = argparse.ArgumentParser(description='기술자격 공식 일정 페이지 수집')
    parser.add_argument('--output', type=Path, default=PROJECT_ROOT / 'research/all_technical_schedule_sources.json')
    parser.add_argument('--interval', type=float, default=0.5)
    options = parser.parse_args()
    if not 0.1 <= options.interval <= 30:
        parser.error('요청 간격은 0.1~30초로 지정해주세요.')
    collect(options.output, options.interval)


if __name__ == '__main__':
    main()
