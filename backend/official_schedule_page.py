"""공식 Q-Net 종목 페이지에서 일정 표를 읽고 원본을 보관한다."""

from datetime import datetime, timezone
from html.parser import HTMLParser
import re

import httpx

from backend.official_api import OfficialAPIError, MAX_RESPONSE_BYTES
from backend.official_data import normalize_technical_schedules, parse_official_date
from backend.schemas import ScheduleInput


PAGE_URL = 'https://www.q-net.or.kr/crf005.do'


class SchedulePageParser(HTMLParser):
    """스크립트를 실행하지 않고 본문과 바깥쪽 표의 행·열을 읽는다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.depth = 0
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif self.depth == 1 and tag == 'tr':
            self.row = []
        elif self.depth == 1 and tag in ('th', 'td'):
            # HTML에서는 다음 셀이 시작되면 이전 셀의 닫는 태그를 생략할 수 있다.
            self.finish_cell()
            self.cell = []
        elif tag == 'br' and self.cell is not None:
            self.cell.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if self.depth == 1 and tag in ('th', 'td') and self.cell is not None:
            self.finish_cell()
        elif self.depth == 1 and tag == 'tr' and self.row is not None:
            self.finish_cell()
            self.table.append(self.row)
            self.row = None
        elif tag == 'table':
            if self.depth == 1:
                self.tables.append(self.table)
                self.table = None
            self.depth = max(0, self.depth - 1)

    def finish_cell(self):
        """명시적·생략된 셀 종료를 같은 방법으로 처리한다."""
        if self.cell is not None and self.row is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None

    def handle_data(self, value):
        if self.hidden:
            return
        self.text.append(value)
        if self.cell is not None:
            self.cell.append(value)


def inspect_schedule_page(text: str) -> dict:
    """종목 대조용 본문과 날짜 표를 추출한다."""
    parser = SchedulePageParser()
    parser.feed(text)
    return {'visible_text': ' '.join(' '.join(parser.text).split()), 'tables': parser.tables}


def fetch_schedule_page(code: str) -> dict:
    """최대 1회 재시도하며 성공 응답의 실제 조회 시각을 남긴다."""
    params = {'id': 'crf00503s02', 'jmCd': code, 'jmInfoDivCcd': 'B0'}
    with httpx.Client(follow_redirects=False) as client:
        for attempt in range(2):
            try:
                with client.stream('GET', PAGE_URL, params=params, timeout=15) as response:
                    if response.status_code != 200:
                        raise OfficialAPIError('page_http_error', f'공식 페이지 HTTP 상태: {response.status_code}', response.status_code >= 500 or response.status_code == 429)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise OfficialAPIError('page_too_large', '공식 일정 페이지 크기가 제한을 넘었습니다.')
                    try:
                        text = body.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        raise OfficialAPIError('page_encoding_error', '공식 일정 페이지의 문자 인코딩을 확인하지 못했습니다.') from None
                    return {'source_url': str(response.url), 'retrieved_at': datetime.now(timezone.utc),
                            'retry_count': attempt, 'html': text}
            except httpx.TimeoutException:
                error = OfficialAPIError('page_timeout', '공식 일정 페이지 응답시간을 초과했습니다.', True)
            except httpx.RequestError:
                error = OfficialAPIError('page_connection_error', '공식 일정 페이지에 연결하지 못했습니다.', True)
            except OfficialAPIError as caught:
                error = caught
            error.retry_count = attempt
            if attempt == 1 or not error.retryable:
                raise error
    raise RuntimeError('공식 페이지 재시도 흐름을 확인해주세요.')


def cell_dates(cell: str, counts: set[int]) -> list[str]:
    """연·월·일이 명시된 날짜만 읽으며 일자 누락이나 예상 밖 구조를 거절한다."""
    matches = re.findall(r'(?<!\d)(\d{4})\.(\d{1,2})\.(\d{1,2})(?!\d)', cell)
    remaining = re.sub(r'(?<!\d)\d{4}\.\d{1,2}\.\d{1,2}(?!\d)', '', cell)
    if re.sub(r'[\s~./,:;\-\[\]()]+', '', remaining):
        raise ValueError('공식 날짜 셀에 해석하지 못한 표기가 있습니다.')
    if len(matches) not in counts:
        raise ValueError('공식 일정 표의 날짜 개수가 예상과 다릅니다.')
    values = []
    for year, month, day in matches:
        value = year + month.zfill(2) + day.zfill(2)
        parse_official_date(value)
        values.append(value)
    return values


def registration_values(cell: str) -> dict:
    """일반 접수의 실제 기간과 빈자리 접수기간을 구분한다."""
    pieces = cell.split('빈자리접수')
    if len(pieces) > 2:
        raise ValueError('빈자리 접수 표기가 중복되었습니다.')
    dates = cell_dates(pieces[0], {0, 2, 4})
    periods = []
    for index in range(0, len(dates), 2):
        periods.append({'starts_on': parse_official_date(dates[index]), 'ends_on': parse_official_date(dates[index + 1])})
    result = {'registration_start': periods[0]['starts_on'] if periods else None,
              'registration_end': periods[-1]['ends_on'] if periods else None,
              'registration_periods': periods}
    if len(pieces) == 2:
        vacancy = cell_dates(pieces[1], {2})
        result.update(vacancy_registration_start=parse_official_date(vacancy[0]),
                      vacancy_registration_end=parse_official_date(vacancy[1]))
    return result


def is_school_exam(row: list[str]) -> bool:
    """일반인이 응시할 수 없다고 명시된 학교별 별도 검정을 구분한다."""
    return (len(row) >= 2 and re.fullmatch(r'\d{4}년 정기 기능사', row[0]) is not None
            and '특성화 고등학교' in row[1] and '필기시험 면제자' in row[1]
            and '일반인' in row[1] and '응시 불가' in row[1])


def normalize_schedule_page(certificate: dict, response: dict, notice: dict | None = None) -> list[ScheduleInput]:
    """공식 7열 일정 표를 기존 날짜·중복 검증에 연결한다."""
    page = inspect_schedule_page(response['html'])
    if certificate['name'] not in page['visible_text']:
        raise ValueError('공식 일정 페이지에서 선택한 종목명을 확인하지 못했습니다.')
    tables = []
    for table in page['tables']:
        if not table:
            continue
        header = [re.sub(r'\s+', '', value) for value in table[0]]
        if len(header) == 7 and header[0] == '구분' and '필기원서접수' in header[1] and '실기원서접수' in header[4] and '최종합격자' in header[6]:
            tables.append(table)
    if len(tables) != 1:
        raise ValueError('공식 일정 표가 없거나 중복되어 구조를 확정하지 못했습니다.')
    schedules = []
    seen = set()
    for row in tables[0][1:]:
        if is_school_exam(row):
            continue
        if len(row) == 1 and row[0] == '시험 일정이 없습니다.':
            if len(tables[0]) != 2:
                raise ValueError('빈 일정 안내와 일정 행이 함께 존재합니다.')
            return []
        if len(row) != 7 or not re.fullmatch(r'\d{4}년 (?:정기|수시) (?:기술사|기능장|기사|기능사) \d+회', row[0]):
            raise ValueError('공식 일정의 회차명 또는 열 구성을 확인하지 못했습니다.')
        item = {'jmfldnm': certificate['name'], 'implplannm': row[0]}
        extras = {}
        for phase, prefix, offset in (('written', 'doc', 1), ('practical', 'prac', 4)):
            values = registration_values(row[offset])
            extras[phase] = values
            exam = cell_dates(row[offset + 1], {0, 1, 2})
            result = cell_dates(row[offset + 2], {0, 1})
            for name in ('registration_start', 'registration_end'):
                value = values[name]
                item[prefix + ('regstartdt' if name.endswith('start') else 'regenddt')] = value.strftime('%Y%m%d') if value else ''
            item[prefix + 'examstartdt'] = exam[0] if exam else ''
            item[prefix + 'examenddt'] = exam[-1] if exam else ''
            item['docpassdt' if phase == 'written' else 'pracpassstartdt'] = result[0] if result else ''
        rows = normalize_technical_schedules([item], certificate['id'], certificate['name'], response['source_url'], response['retrieved_at'])
        for schedule in rows:
            values = schedule.model_dump()
            values.update(extras['practical' if schedule.phase == 'interview' else schedule.phase])
            periods = values['registration_periods']
            source_url, retrieved_at = response['source_url'], response['retrieved_at']
            if notice:
                for override in notice['registration_overrides']:
                    if schedule.round_label == override['round_label'] and schedule.phase == override['phase']:
                        periods = override['periods']
                        if (str(values['registration_start']) != periods[0]['starts_on']
                                or str(values['registration_end']) != periods[-1]['ends_on']):
                            raise ValueError('종목 페이지와 시행공고의 접수 범위가 달라 추가 확인이 필요합니다.')
                        source_url, retrieved_at = notice['source_url'], notice['retrieved_at']
            values['registration_periods'] = [{**period, 'source_url': source_url, 'retrieved_at': retrieved_at} for period in periods]
            schedule = ScheduleInput(**values)
            key = (schedule.round_key, schedule.phase)
            if key in seen:
                raise ValueError('공식 표에서 같은 회차·시험 단계가 중복되었습니다.')
            seen.add(key)
            schedules.append(schedule)
    if not schedules:
        raise ValueError('공식 표에 검증할 일정이나 명시된 빈 일정 안내가 없습니다.')
    return schedules
