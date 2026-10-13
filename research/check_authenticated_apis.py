"""활용승인된 API 세 가지를 표본 호출하며 인증키·DB는 저장하지 않는다."""
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.official_api import OfficialAPIError, fetch_catalog, fetch_exam_information, fetch_exam_schedules


def check_authenticated_apis() -> dict:
    """목록·정보처리기사 자격정보·올해 일정을 호출하고 안전한 결과 요약만 기록한다."""
    year = datetime.now(timezone.utc).year
    results = []
    calls = [
        ('certificate_list', fetch_catalog, []),
        ('certificate_information', fetch_exam_information, ['1320']),
        ('unified_exam_schedule', fetch_exam_schedules, ['1320', year, 'T']),
    ]
    for name, fetch, arguments in calls:
        try:
            response = fetch(*arguments)
            row = {'api':name,'status':'success' if response['items'] else 'empty','item_count':len(response['items']),'source_url':response['source_url'],'retrieved_at':response['retrieved_at'].isoformat(),'retry_count':response['retry_count']}
            if response['items']:
                row['response_field_names'] = sorted(response['items'][0])
            if name=='certificate_list':
                row['unique_codes'] = len({item.get('jmcd') for item in response['items']})
                row['selected_certificate_found'] = any(item.get('jmcd')=='1320' for item in response['items'])
        except OfficialAPIError as error:
            row = {'api':name,'status':'failed','error_code':error.code,'message':str(error),'retry_count':error.retry_count}
        results.append(row)
        print(json.dumps(row,ensure_ascii=True),flush=True)
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'sample_certificate_code':'1320','sample_year':year,'results':results,'database_changed':False,'github_pushed':False,'note':'키를 전달한 실제 호출 확인. 기존 DB 전체 재동기화 및 통합 일정 DB 변환은 실행하지 않음.'}
    path=Path(__file__).resolve().parent/'preparation/recommendation/authenticated_api_check.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    check_authenticated_apis()
