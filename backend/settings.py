"""로컬 설정 파일을 읽되 실행 환경의 기존 설정을 우선한다."""

from pathlib import Path

from dotenv import load_dotenv


def load_settings(path: Path | None = None) -> None:
    """실행 위치와 관계없이 backend/.env를 읽으며 기존 환경변수를 덮어쓰지 않는다."""
    settings_path = path if path is not None else Path(__file__).with_name(".env")
    load_dotenv(settings_path, override=False)


load_settings()
