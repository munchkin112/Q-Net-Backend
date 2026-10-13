"""인증키 인코딩·전달·오류와 공식 통합 일정의 요청 계약을 검증한다."""
import os
import unittest
from unittest.mock import patch
import httpx
from backend import official_api

EMPTY_XML='<response><header><resultCode>00</resultCode></header><body><items/></body></response>'

class QNetAuthenticationTests(unittest.TestCase):
    def test_encoded_key_is_decoded_once_and_original_params_unchanged(self):
        params={'jmCd':'1320'}
        requests=[]
        def handle(request):
            requests.append(request)
            return httpx.Response(200,text=EMPTY_XML)
        with patch.dict(os.environ,{'QNET_SERVICE_KEY':'sample%2Bkey%2Fvalue%3D'}):
            with httpx.Client(transport=httpx.MockTransport(handle)) as client:
                result=official_api.request_items(client,official_api.EXAM_INFORMATION_URL,params,service_key_parameter='ServiceKey')
        self.assertEqual(requests[0].url.params['ServiceKey'],'sample+key/value=')
        self.assertEqual(params,{'jmCd':'1320'})
        self.assertNotIn('sample',result['source_url'])
        self.assertNotIn('ServiceKey',result['source_url'])

    def test_decoded_key_preserves_plus(self):
        requests=[]
        def handle(request):
            requests.append(request)
            return httpx.Response(200,text=EMPTY_XML)
        with patch.dict(os.environ,{'QNET_SERVICE_KEY':'sample+key/value='}):
            with httpx.Client(transport=httpx.MockTransport(handle)) as client:
                official_api.request_items(client,official_api.CATALOG_URL,service_key_parameter='serviceKey')
        self.assertEqual(requests[0].url.params['serviceKey'],'sample+key/value=')

    def test_missing_key_stops_before_network(self):
        with patch.dict(os.environ,{'QNET_SERVICE_KEY':''}):
            with httpx.Client(transport=httpx.MockTransport(lambda r:self.fail('키 없이 호출됨'))) as client:
                with self.assertRaises(official_api.OfficialAPIError) as caught:
                    official_api.request_items(client,official_api.CATALOG_URL,service_key_parameter='serviceKey')
        self.assertEqual(caught.exception.code,'missing_service_key')

    def test_gateway_auth_failure_is_not_empty_and_not_retried(self):
        xml='<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>'
        calls=[]
        def handle(request):
            calls.append(request)
            return httpx.Response(200,text=xml)
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(official_api.OfficialAPIError) as caught:
                official_api.request_items(client,'https://example.test')
        self.assertEqual(caught.exception.code,'authentication_error')
        self.assertEqual(len(calls),1)

    def test_unified_schedule_uses_documented_parameters(self):
        with patch('backend.official_api.request_items',return_value={'items':[],'source_url':official_api.UNIFIED_SCHEDULE_URL}) as request:
            official_api.fetch_exam_schedules('1320',2026,'T')
        args,kwargs=request.call_args
        self.assertEqual(args[1],official_api.UNIFIED_SCHEDULE_URL)
        self.assertEqual(args[2]['implYy'],'2026')
        self.assertEqual(args[2]['numOfRows'],'50')
        self.assertEqual(args[2]['jmCd'],'1320')
        self.assertEqual(args[2]['qualgbCd'],'T')
        self.assertEqual(kwargs['service_key_parameter'],'serviceKey')

if __name__=='__main__':
    unittest.main()
