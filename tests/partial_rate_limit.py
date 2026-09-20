import os, sys, pathlib
from types import SimpleNamespace
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests' / 'stubs'))
os.environ.update({
    'EXA_API_KEY': 'test', 'CEREBRAS_API_KEY': 'test',
    'TELEGRAM_BOT_TOKEN': 'test', 'TELEGRAM_CHANNEL': '@ComicsNewsroom'
})
import main

old_state = main.STATE
old_process = main.process_story_candidate
old_verify = main.verify_stories_batch
old_rate = main._cerebras_rate_limited
try:
    main.STATE = main.default_state()
    main._cerebras_rate_limited = False

    processed = []

    def fake_process(item):
        processed.append(item['title'])
        if item['title'] == 'Rate Limit Here':
            raise main.CerebrasRateLimitError('429 Requests per minute limit exceeded')
        return {
            **item,
            'headline': item['title'],
            'summary': 'A verified development was announced.',
            'sector': item['sector'],
            'news_type': 'Major Announcement',
            'priority_type': item['priority_type'],
            'highlights': ['The announcement is confirmed.', 'More details are expected.'],
            'why_it_matters': 'Fans need to know about the development.',
            'source_class': 'official',
            'research_official_verified': True,
            'official_source_url': item['url'],
            '_source_article_text': 'Official source evidence.',
            'category_hashtags': ['#ComicsNews'],
        }

    main.process_story_candidate = fake_process
    main.verify_stories_batch = lambda stories: stories

    ranked = []
    for i in range(8):
        title = 'Rate Limit Here' if i == 4 else f'Strong Event {i}'
        item = {
            'title': title,
            'headline': title,
            'sector': ['Anime', 'Manga', 'Comics'][i % 3],
            'importance_score': 95 - i,
            'important': True,
            'editor_rank': i + 1,
            'canonical': f'fixture.example/{i}',
            'url': f'https://fixture.example/{i}',
            'region': main.REGION,
            'priority_type': 'Major Announcement',
            'source_class': 'official',
        }
        main.STATE['queue'][item['canonical']] = {**item, 'status': 'pending'}
        ranked.append(item)

    result = main.process_ranked_region(main.REGION, ranked)

    # Four successful candidates must survive; the fifth fails with 429 and
    # later candidates must not be processed in the same run.
    assert processed == [
        'Strong Event 0', 'Strong Event 1', 'Strong Event 2',
        'Strong Event 3', 'Rate Limit Here'
    ], processed
    assert len(result) == 4, len(result)
    rate_item = main.STATE['queue']['fixture.example/4']
    assert rate_item['status'] == 'retryable'
    assert rate_item['failure_stage'] == 'ai_rate_limit'
    assert rate_item['retry_exhausted'] is False
    assert all(main.STATE['queue'][f'fixture.example/{i}']['status'] == 'selected' for i in range(4))
    assert main.STATE['queue']['fixture.example/5']['status'] == 'pending'
    print('PARTIAL-RATE-LIMIT TEST: PASS | successful stories preserved | 429 candidate retryable | later work deferred')
finally:
    main.STATE = old_state
    main.process_story_candidate = old_process
    main.verify_stories_batch = old_verify
    main._cerebras_rate_limited = old_rate
