"""로그인 구현과 분리된 라우터다. main.py 연결 시 인증·프로필 조회 함수를 주입한다."""
import json
from collections.abc import Callable
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException

from backend.career_information import get_career_context, build_career_information
from backend.recommendation_api_models import (
    RecommendationRequest, RecommendationResponse, CareerInformationResponse,
)
from backend.recommendation_service import run_recommendation, validate_selection, RecommendationError


def build_recommendation_response(result: dict, profile: dict) -> dict:
    """검증된 선정 순서를 보존하고 카드 사실은 DB 후보에서 구성한다."""
    candidates = {str(item['certificate_id']): item for item in result['candidates']}
    selection = validate_selection(json.dumps(result['selection'], ensure_ascii=False), candidates, profile, True)
    cards = []
    for position, selected in enumerate(selection['items'], start=1):
        candidate = candidates[selected['certificate_id']]
        career = build_career_information(candidate)
        docs = {doc['document_id']: doc for doc in candidate['evidence_documents']}
        ids = set(candidate.get('summary_source_ids', []))
        ids.update(evidence['document_id'] for evidence in selected['evidence'])
        ids.update(source['document_id'] for source in career['sources'])
        if any(source_id not in docs for source_id in ids):
            raise ValueError('카드 출처 연결을 확인해야 합니다.')
        sources = [{'document_id': doc['document_id'], 'source_url': doc['source_url'],
                    'retrieved_at': doc.get('retrieved_at'), 'evidence_scope': doc.get('evidence_scope')}
                   for doc in docs.values() if doc['document_id'] in ids]
        cards.append({**selected, 'qnet_code': candidate['qnet_code'], 'name': candidate['name'],
                      'category': candidate['category'],
                      'category_name': {'T': '국가기술자격', 'S': '국가전문자격'}.get(candidate['category'], '분류 확인 필요'),
                      'summary': candidate['summary'], 'position': position,
                      'recommended_for': career['recommended_for'], 'related_jobs': career['related_jobs'],
                      'related_jobs_status': career['status'], 'sources': sources,
                      'usage_restrictions': career['usage_restrictions']})
    return RecommendationResponse(status=selection['status'], total_count=len(cards),
                                  initial_display_count=min(3, len(cards)), items=cards).model_dump(mode='json')


def create_recommendation_router(
    run_agent: Callable = run_recommendation,
    load_context: Callable = get_career_context,
) -> APIRouter:
    """요청에 포함된 프로필로 추천하고 종목별 공통 직무 정보도 제공한다."""
    router = APIRouter(tags=['추천·연관 직무'])

    @router.post('/recommendations', response_model=RecommendationResponse)
    def create_recommendations(request: RecommendationRequest):
        """요청 프로필의 관심 분야를 기준으로 자격증을 최대 10개 반환한다."""
        profile = request.model_dump()
        try:
            result = run_agent(profile, profile['interest_category_codes'])
            return build_recommendation_response(result, profile)
        except RecommendationError as error:
            status = 504 if error.code == 'timeout' else 503 if error.code == 'data_unavailable' else 502
            raise HTTPException(status, detail={'code': error.code.upper(), 'message': '추천 처리에 실패했습니다.'}) from None
        except psycopg.Error:
            raise HTTPException(503, detail={'code': 'DATA_UNAVAILABLE', 'message': '추천 자료를 조회할 수 없습니다.'}) from None
        except RuntimeError:
            raise HTTPException(503, detail={'code': 'RECOMMENDATION_UNAVAILABLE', 'message': '추천 실행 설정을 확인해야 합니다.'}) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(502, detail={'code': 'INVALID_RECOMMENDATION', 'message': '추천 결과의 근거를 확인할 수 없습니다.'}) from None

    @router.get('/certificates/{certificate_id}/career-info', response_model=CareerInformationResponse)
    def get_certificate_career_information(certificate_id: UUID):
        """한 종목의 공통 추천 대상·검토된 연관 직무·출처를 반환한다."""
        try:
            context = load_context(certificate_id)
            if context is None:
                raise HTTPException(404, detail={'code': 'CERTIFICATE_NOT_FOUND', 'message': '자격증을 찾을 수 없습니다.'})
            if str(context['certificate_id']) != str(certificate_id):
                raise ValueError('조회 종목이 일치하지 않습니다.')
            return build_career_information(context)
        except (psycopg.Error, RuntimeError):
            raise HTTPException(503, detail={'code': 'DATA_UNAVAILABLE', 'message': '직무 자료를 조회할 수 없습니다.'}) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(502, detail={'code': 'INVALID_CAREER_SOURCE', 'message': '직무 근거를 확인할 수 없습니다.'}) from None

    return router


router = create_recommendation_router()

