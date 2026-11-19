#!/usr/bin/env python3
"""수호&지호 가족대시보드 — 기기 동기화 항목별 병합 테스트

index.html에 들어 있는 SYNC-MERGE 블록(실제로 배포되는 코드)을 그대로 읽어
헤드리스 크롬에서 실행합니다.

  1) 병합 단위 테스트 — 구버전 기기 기록(예방접종·생년월일·11/20 급식 누락본)과
     최신 원격 기록을 합쳐도 지워지지 않는지, 삭제 표시(tombstone)가 지켜지는지
  2) 통합 테스트 — 실제 페이지의 syncPush가 원격 최신본을 받아 병합한 뒤 올리는지,
     sha 충돌(409)이 나면 다시 받아 재병합·재시도하는지 (GitHub 응답은 가짜로 대신함)

사용법:
    python3 tests/sync-merge.test.py
    python3 tests/sync-merge.test.py --real dashboard-data.json   # 실제 기록으로도 확인
    CHROME=/path/to/chrome python3 tests/sync-merge.test.py
"""
import argparse
import base64
import functools
import http.server
import json
import os
import pathlib
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / 'index.html'
BEGIN = '/* ==== SYNC-MERGE BEGIN ==== */'
END = '/* ==== SYNC-MERGE END ==== */'

CHROME_CANDIDATES = [
    os.environ.get('CHROME', ''),
    '/workspace/build/chrome-headless-shell-linux64/chrome-headless-shell',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
]

RESULTS = []


def check(name, cond, extra=''):
    RESULTS.append((name, bool(cond), extra))
    print(('PASS  ' if cond else 'FAIL  ') + name + (('   ' + str(extra)) if (extra and not cond) else ''), flush=True)


def chrome_path():
    for c in CHROME_CANDIDATES:
        if c and pathlib.Path(c).exists():
            return c
    raise SystemExit('크롬 실행 파일을 찾지 못했어요. CHROME 환경변수로 지정해 주세요.')


def merge_block():
    html = INDEX.read_text(encoding='utf-8')
    i = html.find(BEGIN)
    j = html.find(END)
    if i < 0 or j < 0 or j <= i:
        raise SystemExit('index.html에서 SYNC-MERGE 블록을 찾지 못했어요.')
    return html[i + len(BEGIN):j]


# ---------------------------------------------------------------- 가짜 기록
def quest(qid, text, points=10, done=False, cat='quest', stamp=None):
    q = {'id': qid, 'cat': cat, 'text': text, 'points': points, 'done': done}
    if stamp:
        q['updatedAt'] = stamp
    return q


def member(mid, name, label, birth, quests, xp=60, level=3, last_reset='2026-11-17',
           growth=None, stamp=None, birth_at=None, caught=None, partner=4):
    m = {
        'id': mid, 'name': name, 'label': label, 'partner': partner,
        'caught': caught if caught is not None else [4, 16, 19],
        'level': level, 'xp': xp, 'hatchedDate': '', 'lastReset': last_reset,
        'birth': birth,
        'growth': growth if growth is not None else {'height': None, 'weight': None, 'date': '', 'history': []},
        'quests': quests,
    }
    if stamp:
        m['updatedAt'] = stamp
    if birth_at:
        m['birthAt'] = birth_at
    return m


def remote_data():
    """07:10 하이클래스 스캔 + 휴대폰 복원으로 최신이 된 원격 기록."""
    return {
        'version': 1,
        'updatedAt': '2026-11-18T23:56:09.469Z',
        'settings': {'title': '수호&지호 가족대시보드', 'region': '부산 해운대구',
                     'school': {'name': '장산초등학교', 'grade': '1', 'cls': '2'},
                     'filter': '전체', 'acadView': 'split', 'firstRun': '2026-11-16'},
        'members': [
            member('suho', '김수호', '8세 · 초1', '2019-01-10',
                   [quest('q_s1', '학교 숙제 다 하기', 20, True, stamp='2026-11-20T00:10:00.000Z'),
                    quest('q_s2', '책 20분 읽기', 15, False)],
                   xp=85, growth={'height': 126.6, 'weight': 29.9, 'date': '2026-10-07',
                                  'history': [{'date': '2026-10-07', 'height': 126.6, 'weight': 29.9},
                                              {'date': '2026-06-29', 'height': 126.8, 'weight': 28.5}]},
                   stamp='2026-11-20T00:10:00.000Z'),
            member('jiho', '김지호', '6세 · 어린이집', '2021-06-02',
                   [quest('q_j1', '그림일기 한 장 그리기', 20, False)], xp=40, level=2, partner=25),
        ],
        'ddays': [{'id': 'dd_1', 'title': '겨울방학식', 'date': '2026-12-30'}],
        'wishes': [{'id': 'w_1', 'item': '스마트시계', 'who': '김수호', 'memo': '', 'done': False}],
        'events': [{'id': 'e_family', 'title': '가족 저녁 식사', 'date': '2026-11-20', 'time': '19:00',
                    'owner': '가족 공통', 'cat': '가족', 'memo': ''}],
        'academies': [{'id': 'a_1', 'name': '줄넘기', 'who': '김수호', 'day': '수',
                       'start': '17:00', 'end': '18:00', 'place': ''}],
        'tt': {'김수호': {'label': '초1 시간표', 'rows': ['1교시', '2교시'],
                          'data': {'월': ['국어', '수학'], '화': ['국어', '']}}},
        'diary': [],
        'notices': [
            {'id': 'n_1119', 'date': '2026-11-19', 'title': '수능일 등교 9:20~9:40', 'memo': '9시 이전 등교 금지'},
            {'id': 'n_1120', 'date': '2026-11-20', 'title': '겨울방학 돌봄교실 수요조사 제출', 'memo': '희망하는 경우만'},
        ],
        'preps': [{'id': 'p_1', 'title': '매일 챙기기 (통통통)', 'due': '',
                   'items': [{'t': '물통', 'done': False}, {'t': '우체통', 'done': False}]}],
        'meals': {
            '2026-11-19': ['친환경찰보리밥', '한우배추된장국'],
            '2026-11-20': ['친환경흑미밥', '순살춘천닭갈비', '배추김치'],
            '2026-11-23': ['친환경백미밥', '미역국'],
        },
        'mealSource': {'2026-11-19': 'hiclass', '2026-11-20': 'hiclass', '2026-11-23': 'hiclass'},
        'mealUpdated': '2026-11-20 07:18',
        'schoolSchedule': [{'date': '2026-11-20', 'name': 'book적 book적 한마당', 'memo': '', 'src': 'hiclass'}],
        'schoolUpdated': '2026-11-20 07:18',
        'health': {
            'suho': {
                'bcg': {'done': True, 'date': '2019-01-29', 'src': 'nip.kdca.go.kr'},
                'hep1': {'done': True, 'date': '2019-01-10', 'src': 'nip.kdca.go.kr'},
                'dtap5': {'done': True, 'date': '2023-01-13', 'src': 'nip.kdca.go.kr'},
                'flu': {'done': True, 'date': '2026-09-29', 'src': 'nip.kdca.go.kr'},
            },
            'jiho': {
                'bcg': {'done': True, 'date': '2021-06-16'},
                'flu': {'done': True, 'date': '2026-09-29'},
            },
        },
        'call': {'room': 'soohojiho-family'},
        'weather': None,
        'hiclassSeeded': True,
    }


def old_device_data():
    """구버전 기기(태블릿)에 남아 있던 기록 — 예방접종·생년월일·11/20 급식이 비어 있음."""
    d = {
        'version': 1,
        'updatedAt': '2026-11-18T12:00:00.000Z',
        'settings': {'title': '수호&지호 가족대시보드', 'region': '부산 해운대구',
                     'school': {'name': '', 'grade': '1', 'cls': '2'},
                     'filter': '전체', 'acadView': 'split', 'firstRun': '2026-11-16'},
        'members': [
            member('suho', '김수호', '8세 · 초1', '',
                   [quest('q_s1', '학교 숙제 다 하기', 20, False),
                    quest('q_s2', '책 20분 읽기', 15, False),
                    quest('q_local', '태블릿에서 만든 퀘스트', 10, True)],
                   xp=60, growth={'height': 127.0, 'weight': 29.0, 'date': '2026-09-01',
                                  'history': [{'date': '2026-06-29', 'height': 126.8, 'weight': 28.5},
                                              {'date': '2026-09-01', 'height': 127.0, 'weight': 29.0}]}),
            member('jiho', '김지호', '6세 · 어린이집', '',
                   [quest('q_j1', '그림일기 한 장 그리기', 20, False)], xp=40, level=2, partner=25),
        ],
        'ddays': [{'id': 'dd_1', 'title': '겨울방학식', 'date': '2026-12-30'}],
        'wishes': [{'id': 'w_1', 'item': '스마트시계', 'who': '김수호', 'memo': '10만원대', 'done': False}],
        'events': [{'id': 'e_tablet', 'title': '태블릿에서 만든 일정', 'date': '2026-11-21',
                    'time': '10:00', 'owner': '김수호', 'cat': '가족', 'memo': ''}],
        'academies': [],
        'tt': {'김수호': {'label': '초1 시간표', 'rows': ['1교시', '2교시'],
                          'data': {'월': ['국어', '수학'], '화': ['국어', '즐거운생활']}}},
        'diary': [],
        'notices': [{'id': 'n_1117', 'date': '2026-11-17', 'title': '우체통 · 일기장', 'memo': ''}],
        'preps': [],
        'meals': {'2026-11-16': ['친환경백미밥'], '2026-11-17': ['친환경기장밥'], '2026-11-18': ['친환경백미밥']},
        'mealSource': {'2026-11-16': 'hiclass', '2026-11-17': 'hiclass', '2026-11-18': 'hiclass'},
        'mealUpdated': '2026-11-17 19:10',
        'schoolSchedule': [{'date': '2026-11-19', 'name': '대입수능일', 'memo': '등교 9:20~9:40', 'src': 'hiclass'}],
        'schoolUpdated': '2026-11-17 19:10',
        'health': {},
        'call': {'room': 'soohojiho-family'},
        'weather': None,
        'hiclassSeeded': True,
    }
    return d


# ---------------------------------------------------------------- 단위 테스트
def run_unit_tests(page, block):
    page.set_content('<!doctype html><meta charset="utf-8"><body></body>')
    page.add_script_tag(content=block)

    def merge(remote, local, now='2026-11-20T07:20:00.000Z'):
        return page.evaluate(
            '([r, l, n]) => mergeFamilyData(r, l, n)', [remote, local, now])

    R, L = remote_data(), old_device_data()

    # 1) 구버전 기기 ↔ 최신 원격
    m = merge(R, L)
    suho = [x for x in m['members'] if x['id'] == 'suho'][0]
    texts = [q['text'] for q in suho['quests']]
    check('구버전 기기: 예방접종 기록이 살아남음 (4건)',
          sorted(m['health'].get('suho', {}).keys()) == ['bcg', 'dtap5', 'flu', 'hep1'],
          m['health'].get('suho'))
    check('구버전 기기: 접종 완료·날짜 보존', m['health']['suho']['flu']['done'] is True
          and m['health']['suho']['flu']['date'] == '2026-09-29')
    check('구버전 기기: 생년월일 보존 (수호)', suho['birth'] == '2019-01-10', suho.get('birth'))
    check('구버전 기기: 생년월일 보존 (지호)', [x for x in m['members'] if x['id'] == 'jiho'][0]['birth'] == '2021-06-02')
    check('구버전 기기: 11/20 급식 유지', m['meals'].get('2026-11-20') == R['meals']['2026-11-20'], m['meals'].get('2026-11-20'))
    check('구버전 기기: 11/23 급식 유지', '2026-11-23' in m['meals'])
    check('구버전 기기: mealUpdated는 더 최신', m['mealUpdated'] == '2026-11-20 07:18', m.get('mealUpdated'))
    check('구버전 기기: schoolUpdated는 더 최신', m['schoolUpdated'] == '2026-11-20 07:18', m.get('schoolUpdated'))
    check('구버전 기기: 11/20 학사일정 유지',
          any(s['date'] == '2026-11-20' for s in m['schoolSchedule']))
    check('구버전 기기: 11/20 공지 유지', any(n['id'] == 'n_1120' for n in m['notices']))
    check('구버전 기기: 기기에만 있던 공지도 유지', any(n['id'] == 'n_1117' for n in m['notices']))
    check('구버전 기기: 체크된 퀘스트 유지 (done)', [q for q in suho['quests'] if q['id'] == 'q_s1'][0]['done'] is True)
    check('구버전 기기: 기기에만 있던 퀘스트 유지', '태블릿에서 만든 퀘스트' in texts, texts)
    check('구버전 기기: xp는 최신 쪽(85)', suho['xp'] == 85, suho['xp'])
    check('구버전 기기: 기기에만 있던 일정 유지', any(e['id'] == 'e_tablet' for e in m['events']))
    check('구버전 기기: 원격 일정도 유지', any(e['id'] == 'e_family' for e in m['events']))
    check('구버전 기기: 장바구니 메모는 비어 있지 않은 쪽', m['wishes'][0]['memo'] == '10만원대', m['wishes'][0])
    check('구버전 기기: 성장 기록 합쳐짐 (3건)', len(suho['growth']['history']) == 3, suho['growth']['history'])
    check('구버전 기기: 최신 키·몸무게', suho['growth']['date'] == '2026-10-07' and suho['growth']['height'] == 126.6)
    check('구버전 기기: 빈 설정값이 채워짐', m['settings']['school']['name'] == '장산초등학교')
    check('구버전 기기: 빈 학원 목록이 원격 학원을 지우지 않음', any(a['id'] == 'a_1' for a in m['academies']))
    check('구버전 기기: 빈 준비물 목록이 원격 준비물을 지우지 않음', any(p['id'] == 'p_1' for p in m['preps']))

    # 2) 반대 방향 — 새 기기에만 있는 기록도 유지
    R2 = old_device_data()
    L2 = remote_data()
    L2['health']['suho']['rota3'] = {'done': True, 'date': '2019-05-15'}
    L2['meals']['2026-11-24'] = ['새 급식']
    L2['mealSource']['2026-11-24'] = 'hiclass'
    L2['mealUpdated'] = '2026-11-20 08:00'
    m2 = merge(R2, L2)
    check('반대 방향: 이 기기의 접종 기록 추가분 유지', 'rota3' in m2['health']['suho'])
    check('반대 방향: 원격의 예전 접종 기록도 유지', len(m2['health']['suho']) >= 4, sorted(m2['health']['suho']))
    check('반대 방향: 새 급식 유지', m2['meals'].get('2026-11-24') == ['새 급식'])
    check('반대 방향: 생년월일 유지', [x for x in m2['members'] if x['id'] == 'suho'][0]['birth'] == '2019-01-10')

    # 3) 빈 칸은 채워진 칸을 지우지 않음
    m3 = merge({'health': {'suho': {'bcg': {'done': True, 'date': '2019-01-29'}}}},
               {'health': {}})
    check('빈 health가 기존 기록을 지우지 않음', m3['health']['suho']['bcg']['done'] is True)
    m4 = merge({'health': {}}, {'health': {'suho': {'bcg': {'done': True, 'date': '2019-01-29'}}}})
    check('빈 원격 health도 이 기기 기록을 지우지 않음', m4['health']['suho']['bcg']['date'] == '2019-01-29')

    # 4) 예방접종 완료 표시는 해제되지 않음 / 접종일은 이른 날짜
    m5 = merge({'health': {'suho': {'flu': {'done': True, 'date': '2026-09-29'}}}},
               {'health': {'suho': {'flu': {'done': False, 'date': '', 'at': '2026-11-20T01:00:00.000Z'}}}})
    check('접종 완료 표시는 지워지지 않음', m5['health']['suho']['flu']['done'] is True)
    m6 = merge({'health': {'suho': {'flu': {'done': True, 'date': '2026-09-29'}}}},
               {'health': {'suho': {'flu': {'done': True, 'date': '2026-10-02'}}}})
    check('접종일이 다르면 이른 날짜 유지', m6['health']['suho']['flu']['date'] == '2026-09-29')

    # 5) 생년월일 충돌 — 더 최근에 고친 쪽
    base_r = remote_data()
    base_l = old_device_data()
    base_r['members'][0]['birth'] = '2019-01-11'
    base_l['members'][0]['birth'] = '2019-01-10'
    base_r['members'][0]['birthAt'] = '2026-11-20T00:00:00.000Z'
    base_l['members'][0]['birthAt'] = '2026-11-20T02:00:00.000Z'
    m7 = merge(base_r, base_l)
    check('생년월일: 최근에 고친 이 기기 값', m7['members'][0]['birth'] == '2019-01-10', m7['members'][0]['birth'])
    base_r['members'][0]['birthAt'] = '2026-11-20T03:00:00.000Z'
    m8 = merge(base_r, base_l)
    check('생년월일: 최근에 고친 원격 값', m8['members'][0]['birth'] == '2019-01-11', m8['members'][0]['birth'])

    # 6) 퀘스트 — 같은 날이면 최신 updatedAt, 다른 날이면 최신 lastReset
    qr = remote_data()
    ql = old_device_data()
    qr['members'][0]['lastReset'] = '2026-11-20'
    ql['members'][0]['lastReset'] = '2026-11-20'
    qr['members'][0]['updatedAt'] = '2026-11-20T00:10:00.000Z'
    ql['members'][0]['updatedAt'] = '2026-11-20T00:20:00.000Z'
    ql['members'][0]['xp'] = 70
    qr['members'][0]['quests'] = [quest('q_s1', '학교 숙제 다 하기', 20, True)]
    ql['members'][0]['quests'] = [quest('q_s1', '학교 숙제 다 하기', 20, False)]
    m9 = merge(qr, ql)
    s9 = m9['members'][0]
    check('퀘스트: 같은 날 최신 updatedAt 우선 (이 기기)', s9['xp'] == 70 and s9['quests'][0]['done'] is False, s9)
    m10 = merge(ql, qr)
    s10 = m10['members'][0]
    check('퀘스트: 같은 day라도 더 최신 쪽 기준', s10['xp'] == 70)
    qr2 = remote_data()
    ql2 = old_device_data()
    qr2['members'][0]['lastReset'] = '2026-11-20'
    qr2['members'][0]['quests'] = [quest('q_s1', '학교 숙제 다 하기', 20, False)]
    qr2['members'][0]['xp'] = 0
    ql2['members'][0]['lastReset'] = '2026-11-17'
    ql2['members'][0]['quests'] = [quest('q_s1', '학교 숙제 다 하기', 20, True)]
    ql2['members'][0]['xp'] = 85
    m11 = merge(qr2, ql2)
    check('퀘스트: 하루 초기화가 더 최근이면 그쪽 우선', m11['members'][0]['lastReset'] == '2026-11-20'
          and m11['members'][0]['quests'][0]['done'] is False and m11['members'][0]['xp'] == 0)

    # 7) 삭제 표시(tombstone)
    d_r = remote_data()
    d_l = old_device_data()
    d_r['deleted'] = {'events': {'e_tablet': '2026-11-20T00:00:00.000Z'}}
    m12 = merge(d_r, d_l)
    check('삭제한 일정은 되살아나지 않음', not any(e['id'] == 'e_tablet' for e in m12['events']))
    d_l2 = old_device_data()
    d_l2['deleted'] = {'events': {'e_family': '2026-11-20T01:00:00.000Z'}}
    m13 = merge(remote_data(), d_l2)
    check('이 기기에서 지운 일정도 되살아나지 않음', not any(e['id'] == 'e_family' for e in m13['events']))
    d_l3 = old_device_data()
    d_l3['events'].append({'id': 'e_family', 'title': '가족 저녁 식사 (다시 저장)', 'date': '2026-11-21',
                           'time': '19:00', 'owner': '가족 공통', 'cat': '가족', 'memo': '',
                           'updatedAt': '2026-11-20T02:00:00.000Z'})
    d_l3['deleted'] = {'events': {'e_family': '2026-11-20T01:00:00.000Z'}}
    m14 = merge(remote_data(), d_l3)
    check('삭제 뒤에 다시 고친 항목은 유지', any(e['id'] == 'e_family' for e in m14['events']))
    check('삭제 표시는 병합 결과에 남음', isinstance(m14.get('deleted'), dict))

    # 8) 성장 기록 삭제
    g_l = old_device_data()
    g_l['deleted'] = {'growth': {'suho|2026-06-29': '2026-11-20T01:00:00.000Z'}}
    m15 = merge(remote_data(), g_l)
    s15 = [x for x in m15['members'] if x['id'] == 'suho'][0]
    check('지운 성장 기록은 되살아나지 않음',
          not any(h['date'] == '2026-06-29' for h in s15['growth']['history']), s15['growth']['history'])
    check('성장 요약은 남은 최신 기록', s15['growth']['date'] == '2026-10-07')

    # 9) 기기별 id로 중복된 공지·준비물은 하나로
    dup_r = remote_data()
    dup_l = old_device_data()
    dup_l['notices'].append({'id': 'n_dup', 'date': '2026-11-20', 'title': '겨울방학 돌봄교실 수요조사 제출', 'memo': ''})
    m16 = merge(dup_r, dup_l)
    same = [n for n in m16['notices'] if n['date'] == '2026-11-20' and '돌봄교실' in n['title']]
    check('같은 공지는 하나로 합쳐짐', len(same) == 1, same)
    dup_l['preps'].append({'id': 'p_dup', 'title': '매일 챙기기 (통통통)', 'due': '',
                           'items': [{'t': '물통', 'done': True}, {'t': '필통', 'done': False}]})
    m17 = merge(dup_r, dup_l)
    preps = [p for p in m17['preps'] if p['title'] == '매일 챙기기 (통통통)']
    items = dict((i['t'], i['done']) for i in preps[0]['items']) if preps else {}
    check('같은 준비물은 하나로 합쳐짐', len(preps) == 1 and items.get('필통') is False and items.get('물통') is True, preps)

    # 10) 시간표 — 비어 있는 칸이 채워진 칸을 지우지 않음
    m18 = merge({'tt': {'김수호': {'label': '초1 시간표', 'rows': ['1교시', '2교시'], 'data': {'월': ['국어', '수학']}}},
                 'ttUpdated': '2026-11-20T05:00:00.000Z'},
                {'tt': {'김수호': {'label': '초1 시간표', 'rows': ['1교시', '2교시'], 'data': {'월': ['', '']}}},
                 'ttUpdated': '2026-11-20T01:00:00.000Z'})
    check('시간표: 빈 칸이 채워진 칸을 지우지 않음', m18['tt']['김수호']['data']['월'] == ['국어', '수학'])
    m19 = merge({'tt': {'김수호': {'label': '초1 시간표', 'rows': ['1교시', '2교시'], 'data': {'월': ['국어', '수학']}}},
                 'ttUpdated': '2026-11-20T01:00:00.000Z'},
                {'tt': {'김수호': {'label': '초1 시간표', 'rows': ['1교시', '2교시'], 'data': {'월': ['국어', '체육']}}},
                 'ttUpdated': '2026-11-20T05:00:00.000Z'})
    check('시간표: 더 최근에 고친 쪽', m19['tt']['김수호']['data']['월'] == ['국어', '체육'])

    # 10-1) id가 없는 예전 기록도 잃지 않음
    m22 = merge({'events': [{'title': 'id 없는 일정', 'date': '2026-11-22'}]},
               {'events': [{'title': 'id 없는 일정2', 'date': '2026-11-23'}]})
    titles = [e['title'] for e in m22['events']]
    check('id가 없는 기록도 잃지 않음', 'id 없는 일정' in titles and 'id 없는 일정2' in titles, titles)

    # 11) 정상·비어 있는 입력
    m20 = merge(None, L)
    check('원격이 없으면 이 기기 기록 그대로', m20['members'][0]['id'] == 'suho')
    m21 = merge(R, {})
    check('이 기기 기록이 비어도 원격 유지', m21['health']['suho']['bcg']['done'] is True)
    check('병합 시각이 updatedAt에 기록됨', m21['updatedAt'] == '2026-11-20T07:20:00.000Z')
    check('통화 역할은 병합 결과에서 빠짐', 'role' not in m21.get('call', {}))

    # 12) 되돌아가지 않음 — 병합 결과를 다시 병합해도 같음
    once = merge(R, L)
    twice = merge(once, once)
    same_keys = ['health', 'meals', 'mealSource', 'members', 'notices', 'events']
    check('병합은 한 번 더 해도 그대로 (멱등)', all(json.dumps(once[k], sort_keys=True) == json.dumps(twice[k], sort_keys=True)
                                                 for k in same_keys))


# ---------------------------------------------------------------- 통합 테스트
class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(directory):
    handler = functools.partial(QuietHandler, directory=str(directory))
    httpd = socketserver.TCPServer(('127.0.0.1', 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


MOCK = r"""
(cfg) => {
  const origFetch = window.fetch.bind(window);
  const remote = cfg.remote;
  const sha = 'sha_remote_1';
  const enc = (s) => btoa(unescape(encodeURIComponent(s)));
  window.__puts = [];
  window.__gets = 0;
  window.fetch = function(url, opts){
    opts = opts || {};
    const u = String(url && url.url ? url.url : url);
    const isData = u.indexOf('/contents/dashboard-data.json') >= 0;
    if (isData && (!opts.method || opts.method === 'GET')){
      window.__gets += 1;
      return Promise.resolve(new Response(JSON.stringify({
        name: 'dashboard-data.json', sha: sha, encoding: 'base64',
        content: enc(JSON.stringify(cfg.remoteEnv))
      }), { status: 200, headers: { 'ETag': '"etag-1"', 'Content-Type': 'application/json' } }));
    }
    if (isData && opts.method === 'PUT'){
      const body = JSON.parse(opts.body);
      window.__puts.push(body);
      const okNow = window.__puts.length >= cfg.failFirst + 1;
      if (!okNow){
        return Promise.resolve(new Response(JSON.stringify({ message: 'is at abc but expected def' }),
          { status: 409, headers: { 'Content-Type': 'application/json' } }));
      }
      return Promise.resolve(new Response(JSON.stringify({ content: { sha: 'sha_new_' + window.__puts.length } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return origFetch(url, opts);
  };
}
"""


def run_integration_test(page, base):
    R = remote_data()
    L = old_device_data()
    remote_env = {'app': 'suho-jiho-family-dashboard', 'schema': 1, 'updatedAt': R['updatedAt'],
                  'device': 'dev_lc0td1eu', 'deviceName': '휴대폰', 'savedAt': R['updatedAt'], 'data': R}
    errors = []
    page.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
    page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
    page.goto(base, wait_until='domcontentloaded')
    page.wait_for_timeout(1500)
    page.evaluate("""(local) => {
        State = local;
        try { localStorage.setItem('suho_jiho_family_dashboard_v1', JSON.stringify(local)); } catch(e){}
        Sync.cfg = { owner:'soohojiho', repo:'Family-board', path:'dashboard-data.json', branch:'main',
          token:'ghp_test', auto:true, deviceId:'dev_tablet', deviceName:'태블릿', lastSync:'' };
        Sync.busy = false;
        State.health = {};
        State.members[0].birth = '';
        delete State.meals['2026-11-20'];
        delete State.mealSource['2026-11-20'];
    }""", L)
    page.evaluate(MOCK, {'remote': R, 'failFirst': 1, 'remoteEnv': remote_env})
    result = page.evaluate("() => syncPush({ manual: true })")
    page.wait_for_timeout(500)
    puts = page.evaluate("() => window.__puts.map(b => JSON.parse(decodeURIComponent(escape(atob(b.content)))))")
    check('통합: PUT 두 번 (409 뒤 재병합 재시도)', len(puts) == 2, len(puts))
    check('통합: 성공 반환', result is True, result)
    if puts:
        last = puts[-1]['data']
        check('통합: 올린 기록에 예방접종 유지', sorted(last['health'].get('suho', {}).keys()) == ['bcg', 'dtap5', 'flu', 'hep1'],
              last['health'].get('suho'))
        check('통합: 올린 기록에 생년월일', last['members'][0]['birth'] == '2019-01-10')
        check('통합: 올린 기록에 11/20 급식', last['meals'].get('2026-11-20') == R['meals']['2026-11-20'])
        check('통합: 올린 기록에 11/20 공지', any(n['id'] == 'n_1120' for n in last['notices']))
        check('통합: 이 기기에만 있던 일정도 함께 올라감', any(e['id'] == 'e_tablet' for e in last['events']))
        check('통합: 통화 역할은 올리지 않음', 'role' not in last.get('call', {}))
        first = puts[0]['data']
        check('통합: 첫 시도에도 병합된 내용을 올림', first['health'].get('suho', {}).get('flu', {}).get('done') is True)
    local_after = page.evaluate("() => ({ health: State.health, birth: State.members[0].birth, meal: State.meals['2026-11-20'] })")
    check('통합: 병합 결과가 이 기기 화면에도 반영', local_after['health'].get('suho', {}).get('flu', {}).get('date') == '2026-09-29'
          and local_after['birth'] == '2019-01-10' and local_after['meal'] == R['meals']['2026-11-20'], local_after)
    check('통합: 페이지 오류 없음', not [e for e in errors if 'Failed to load resource' not in e], errors[:4])


def run_real_data(page, block, path):
    real = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    data = real.get('data', real)
    page.set_content('<!doctype html><meta charset="utf-8"><body></body>')
    page.add_script_tag(content=block)
    merged = page.evaluate("([r, l, n]) => mergeFamilyData(r, l, n)",
                           [data, data, '2026-11-20T07:20:00.000Z'])
    check('실제 기록: 병합해도 예방접종 그대로', json.dumps(merged['health'], sort_keys=True) == json.dumps(data['health'], sort_keys=True))
    check('실제 기록: 병합해도 생년월일 그대로',
          [m.get('birth') for m in merged['members']] == [m.get('birth') for m in data['members']])
    check('실제 기록: 병합해도 급식·학사일정 그대로',
          sorted(merged['meals']) == sorted(data['meals']) and len(merged['schoolSchedule']) == len(data['schoolSchedule']))
    # 실제 기록에서 예방접종·생년월일·11/20 급식을 지운 구버전 기기
    broken = json.loads(json.dumps(data))
    broken['health'] = {}
    for m in broken['members']:
        m['birth'] = ''
        m['growth'] = {'height': None, 'weight': None, 'date': '', 'history': []}
    broken['meals'] = dict((d, v) for d, v in broken['meals'].items() if d != '2026-11-20')
    broken['mealSource'] = dict((d, v) for d, v in broken['mealSource'].items() if d != '2026-11-20')
    broken['schoolSchedule'] = []
    broken['updatedAt'] = '2026-11-18T12:00:00.000Z'
    fixed = page.evaluate("([r, l, n]) => mergeFamilyData(r, l, n)",
                          [data, broken, '2026-11-20T07:20:00.000Z'])
    check('실제 기록: 구버전 기기 병합 후 예방접종 복원',
          json.dumps(fixed['health'], sort_keys=True) == json.dumps(data['health'], sort_keys=True))
    check('실제 기록: 구버전 기기 병합 후 생년월일 복원',
          [m.get('birth') for m in fixed['members']] == [m.get('birth') for m in data['members']])
    check('실제 기록: 구버전 기기 병합 후 11/20 급식 복원',
          fixed['meals'].get('2026-11-20') == data['meals'].get('2026-11-20'))
    check('실제 기록: 구버전 기기 병합 후 학사일정 복원',
          len(fixed['schoolSchedule']) >= len(data['schoolSchedule']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--real', help='실제 dashboard-data.json 경로 (선택)')
    ap.add_argument('--skip-integration', action='store_true')
    args = ap.parse_args()

    block = merge_block()
    httpd = None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome_path(), args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        try:
            run_unit_tests(page, block)
            if args.real:
                run_real_data(page, block, args.real)
            if not args.skip_integration:
                httpd, port = serve(ROOT)
                run_integration_test(page, 'http://127.0.0.1:%d/index.html' % port)
        finally:
            browser.close()
            if httpd:
                httpd.shutdown()

    failed = [r for r in RESULTS if not r[1]]
    print('\n%d개 확인 · %d개 통과 · %d개 실패' % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    if failed:
        for name, _, extra in failed:
            print('  FAIL  ' + name + (('   ' + str(extra)) if extra else ''))
        return 1
    print('모든 테스트를 통과했어요 ✅')
    return 0


if __name__ == '__main__':
    sys.exit(main())
