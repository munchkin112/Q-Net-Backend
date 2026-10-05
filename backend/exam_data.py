"""공식 상세정보 원문에서 필요한 구간을 찾아 필기·실기 정보를 나눈다."""

from html import unescape
from html.parser import HTMLParser
import re
from uuid import UUID

from backend.exam_schemas import ExamInformationInput, information_status


SECTION_NAMES = (
    "시행처", "관련학과", "시험과목", "검정방법", "검정기준", "검벙방법", "합격기준",
    "응시자격", "작업형실기시험기본정보", "안전등급",
)


class PlainTextParser(HTMLParser):
    """HTML을 실행하지 않고 텍스트만 읽으며 문단 경계를 유지한다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.ignored_tags.append(tag)
        if tag in {"p", "div", "br", "li", "tr"} and not self.ignored_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.ignored_tags and tag == self.ignored_tags[-1]:
            self.ignored_tags.pop()
        if tag in {"p", "div", "li", "tr"} and not self.ignored_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_tags:
            self.parts.append(data)


def plain_text(value: str) -> str:
    """HTML과 불필요한 공백을 정리하되 의미가 있는 줄바꿈은 남긴다."""
    parser = PlainTextParser()
    parser.feed(unescape(value))
    lines = []
    for line in "".join(parser.parts).splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def find_section(text: str, label: str) -> str | None:
    """제목부터 다음 제목 전까지 가져온다. 제목이 없거나 중복되면 추정하지 않는다."""
    # 공식 원문의 '시 행 처'처럼 글자 사이에 공백이 있는 제목도 허용한다.
    patterns = []
    for name in SECTION_NAMES:
        patterns.append(r"\s*".join(name))
    matches = []
    for match in re.finditer("|".join(patterns), text):
        # '합격기준 - 합격기준 : ...'처럼 같은 제목을 바로 반복한 원문은 하나로 취급한다.
        if matches and re.sub(r"\s+", "", matches[-1].group()) == re.sub(r"\s+", "", match.group()):
            between = text[matches[-1].end():match.start()]
            if re.fullmatch(r"[\s:：\-]*", between):
                continue
        matches.append(match)
    selected = [index for index, match in enumerate(matches) if re.sub(r"\s+", "", match.group()) == label]
    if len(selected) != 1:
        return None
    index = selected[0]
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    value = text[matches[index].end():end].strip().lstrip(":：").strip()
    value = re.sub(r"^[\s:：\-]*" + r"\s*".join(label) + r"\s*[:：]?\s*", "", value)
    value = re.sub(r"\s*[①②③④⑤⑥⑦⑧]\s*$", "", value).strip()
    return value or None


def split_phases(text: str | None) -> dict[str, str | None]:
    """명시된 필기·실기 라벨을 기준으로 나눈다. 중복 라벨은 미확인으로 처리한다."""
    result = {"written": None, "practical": None, "interview": None}
    if not text:
        return result
    text = re.sub(r"^\((필기\s*·\s*실기)\s*동일\)\s*[:：]?\s*", r"\1 : ", text)
    labels = r"(?:필기|실기|면접)(?:\s*시험)?(?:\([^\n:：)]{1,30}\))?"
    # 줄바꿈이 없는 '- 실기 : ...'와 '실기(복합형) : ...'도 명시된 제목으로 읽는다.
    heading = labels + r"(?:\s*(?:·|및|,|와|/|ㆍ)\s*" + labels + r")*"
    prefix = r"(?:^|\n|[-·ㆍ]\s*|(?<=\s)(?=" + heading + r"\s*[:：]))"
    pattern = prefix + r"(?:\s*[-·ㆍ])?\s*(" + heading + r")(?=\s|[:：]|\d+\s*[.)]|$)\s*[:：]?\s*"
    matches = list(re.finditer(pattern, text))
    seen = set()
    for index, match in enumerate(matches):
        found = re.findall(r"필기|실기|면접", match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end():end].strip()
        if value:
            for label in found:
                phase = {"필기": "written", "실기": "practical", "면접": "interview"}[label]
                if phase in seen:
                    result[phase] = None
                else:
                    result[phase] = value
                    seen.add(phase)
    return result


def subject_list(text: str | None) -> list[str] | None:
    """번호가 있으면 과목별로 나누고, 없으면 공식 문구 하나를 그대로 보관한다."""
    if not text:
        return None
    # '기술2.프로그래밍'처럼 번호 앞에 공백이 없는 공식 원문도 처리한다.
    # 1부터 연속된 번호인지 확인해 과목명 안의 임의 숫자를 분리하지 않는다.
    numbers = list(re.finditer(r"\d+\s*[.)]\s*", text))
    if not numbers or numbers[0].start() != 0:
        return [text.strip()]
    labels = [int(re.match(r"\d+", match.group()).group()) for match in numbers]
    if labels != list(range(1, len(numbers) + 1)):
        return [text.strip()]
    parts = []
    for index, match in enumerate(numbers):
        end = numbers[index + 1].start() if index + 1 < len(numbers) else len(text)
        parts.append(text[match.end():end])
    subjects = []
    for part in parts:
        value = part.strip()
        if value:
            subjects.append(value)
    return subjects or None


def selected_content(items: list[dict], expected_name: str, label: str) -> str | None:
    """응답 종목명이 일치하는지 확인하고 해당 구분의 원문 한 건만 선택한다."""
    contents = []
    for item in items:
        if item.get("jmfldnm") != expected_name:
            raise ValueError("선택한 자격증과 공식 상세정보의 종목명이 다릅니다.")
        if item.get("infogb") == label:
            contents.append(plain_text(item.get("contents", "")))
    if len(contents) > 1:
        raise ValueError("공식 상세정보의 같은 구분이 중복되었습니다.")
    return contents[0] if contents and contents[0] else None


def parse_fees(text: str | None) -> dict[str, int | None]:
    """기술자격 수수료의 명시된 1차/2차 또는 필기/실기 금액만 읽는다."""
    result = {"written": None, "practical": None}
    if not text:
        return result
    # 정보 API의 1차/2차 표기는 기술자격의 필기/실기에만 대응시킨다.
    matches = list(re.finditer(r"(1차|2차|필기|실기)\s*[:：]\s*", text))
    values_by_label = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        amount = text[match.end():end].strip().rstrip(",").strip()
        if amount.endswith("원"):
            amount = amount[:-1].strip()
        # 잘못된 쉼표, 소수, 음수, '원부터' 같은 표현을 금액 일부로 읽지 않는다.
        if re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", amount):
            values_by_label.append((match.group(1), int(amount.replace(",", ""))))
    for phase, labels in (("written", {"1차", "필기"}), ("practical", {"2차", "실기"})):
        label_count = sum(match.group(1) in labels for match in matches)
        values = [amount for label, amount in values_by_label if label in labels]
        if label_count == 1 and len(values) == 1:
            result[phase] = values[0]
    return result


def sourced_values(values: dict, result: dict, phases: list[str] | None = None) -> dict:
    """값과 원본 조회 시각을 묶는다. DB를 읽은 시각으로 바꾸지 않는다."""
    return {
        **values,
        "status": information_status(values["written"], values["practical"], values.get("interview"), values.get("common"), phases),
        "phases": phases if phases is not None else ["written", "practical"],
        "source_url": result["source_url"],
        "retrieved_at": result["retrieved_at"],
    }


def normalize_exam_information(
    certificate_id: UUID, expected_name: str, detail_result: dict, fee_result: dict,
) -> ExamInformationInput:
    """시험과목·합격기준·수수료를 변환하며 해석할 수 없는 값은 null로 남긴다."""
    acquisition = selected_content(detail_result["items"], expected_name, "취득방법")
    fee_text = selected_content(fee_result["items"], expected_name, "응시수수료")
    subject_text = find_section(acquisition, "시험과목") if acquisition else None
    criteria_text = find_section(acquisition, "합격기준") if acquisition else None
    method_text = find_section(acquisition, "검정방법") if acquisition else None
    if acquisition and method_text is None:
        method_text = find_section(acquisition, "검정기준") or find_section(acquisition, "검벙방법")
    methods = split_phases(method_text)
    subjects = split_phases(subject_text)
    criteria = split_phases(criteria_text)
    interview_method = methods["interview"] is not None or (
        methods["practical"] is not None and "구술" in methods["practical"] and "면접" in methods["practical"]
    )
    no_written_exam = bool(acquisition and re.search(r"필기\s*시험\s*없음", acquisition))
    if interview_method:
        phases = ["written", "interview"]
    elif no_written_exam or (methods["practical"] is not None and methods["written"] is None and subjects["written"] is None):
        phases = ["practical"]
    elif methods["practical"] is not None:
        phases = ["written", "practical"]
    else:
        phases = ["written", "interview"] if subjects["interview"] is not None or criteria["interview"] is not None else ["written", "practical"]
    if "interview" in phases:
        # 일부 공식 원문은 면접 검정방법과 '필기·실기' 합격기준이 충돌한다.
        # 실기 문구를 면접으로 바꾸지 않고 확인되지 않은 단계로 남긴다.
        subjects["practical"] = None
        criteria["practical"] = None
    else:
        subjects["interview"] = None
        criteria["interview"] = None
    for phase in subjects:
        subjects[phase] = subject_list(subjects[phase])
    # 단계 표시가 없는 공식 시험과목·기준은 common에 보관하며 특정 단계로 추정하지 않는다.
    unlabelled_subject = re.sub(r"\(?필기\s*시험\s*없음\)?", "", subject_text or "")
    subjects["common"] = subject_list(subject_text.lstrip("- ")) if subject_text and not re.search(r"필기|실기|면접", unlabelled_subject) else None
    criteria["common"] = criteria_text.lstrip("- ") if criteria_text and not re.search(r"필기|실기|면접", criteria_text) else None
    if criteria_text and criteria_text.startswith("필실기 ") and not any(criteria.values()):
        # 공식 원문의 축약 표기는 단계별 문장으로 바꾸지 않고 common에 그대로 남긴다.
        criteria["common"] = criteria_text
    fees = parse_fees(fee_text)
    if phases == ["written", "interview"]:
        fees["interview"] = fees["practical"]
        fees["practical"] = None
    return ExamInformationInput(
        certificate_id=certificate_id,
        subjects=sourced_values(subjects, detail_result, phases),
        pass_criteria=sourced_values(criteria, detail_result, phases),
        fees=sourced_values(fees, fee_result, phases),
        raw_acquisition_text=acquisition,
        raw_fee_text=fee_text,
    )
