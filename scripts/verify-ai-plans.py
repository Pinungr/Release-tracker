from app.database import SessionLocal
from app.services import pds_chat_service
with SessionLocal() as db:
    for question in ["Compare EPCAT failed deployments in September 2026 with EPCAT booked deployments in October 2026", "What percentage of deployments failed in September 2026?"]:
        result = pds_chat_service.ask_pds_ai(db, message=question)
        print(question, result, flush=True)
        assert result['provider'] == 'pds_query_plan'
        assert result.get('evidence'), result
        totals = [row['total'] for row in result['evidence']]
        assert totals == ([1, 2] if question.startswith('Compare') else [2, 6]), result
        if not question.startswith('Compare'):
            assert '33.33%' in result['answer'], result
    previous = pds_chat_service.ask_pds_ai(db, message='How many EPCAT failed deployments in September 2026?')
    result = pds_chat_service.ask_pds_ai(db, message='Compare those deployments with EPCAT booked deployments in October 2026', history=[{'role':'user','content':'How many EPCAT failed deployments in September 2026?'}, {'role':'assistant','content':previous['answer'],'query_scope':previous['query_scope']}])
    print('Follow-up:', result, flush=True)
    assert [row['total'] for row in result['evidence']] == [1, 2], result
