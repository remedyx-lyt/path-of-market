"""核对真实已生成报告的年度、阅读覆盖和来源；不启动模型。"""
import argparse
import json
from pathlib import Path
import sys


def check(path, expected):
    job = json.loads(Path(path).read_text(encoding='utf-8'))
    assert job['status'] == 'completed', job['status']
    report = job['report']
    assert report['run'].get('reviewOutcome') in {'unchanged', 'revised'}, '真实案例须完成模型复核，不能用discarded冒充复核通过'
    scope = report['annualHistory']
    assert scope['count'] == expected
    assert len(scope['requiredDocuments']) == expected and scope['gap'] is None, scope
    sources = {s['sourceId']: s for s in report['sources']}
    coverage = {c['sourceId']: c for c in report['coverage']}
    required = [sources[d['documentId']] for d in scope['requiredDocuments']]
    assert {d['fiscalYear'] for d in required} == set(scope['years'])
    for c in coverage.values():
        assert c.get('readingComplete', c['textComplete'])
        if c.get('unit') != 'segment':
            assert set(c['emptyTextPages']) <= set(c.get('visuallyProcessedPages', []))
    for s in sources.values():
        assert not s['publishedAt'] or s['publishedAt'] <= report['asOfDate']
    def check_citation(citation):
        sid, page = citation['sourceId'], citation.get('page')
        assert sid in sources, citation
        source = sources[sid]
        if source['kind'] == 'document':
            read = coverage[sid]
            assert page in read['processedPages'], citation
            assert page not in read['emptyTextPages'] or page in read.get('visuallyProcessedPages', []), citation
        elif source['kind'] == 'web':
            assert page is None and source.get('citationEligible') and source.get('publishedAt'), citation
            assert coverage[sid]['textComplete'], citation
        else:
            assert page is None, citation
    citations = 0
    for section in report['sections']:
        assert section['content'].strip() and section['citations'], section['heading']
        refs = section['citations'] + [c for n in (section.get('visual') or {}).get('nodes', []) for c in n.get('citations', [])]
        for table in section.get('tables', []):
            refs += [c for row in table['rows'] for c in [row, *row.get('alsoFrom', [])]]
        for c in refs:
            check_citation(c)
        citations += len(refs)
    assert report['marketData']['series'] and report['financialData']['charts']
    tables = [t for s in report['sections'] for t in s.get('tables', [])]
    checked = sum(t.get('verification', {}).get('checkedCells', 0) for t in tables)
    matched = sum(t.get('verification', {}).get('matchedCells', 0) for t in tables)
    return {'taskId': job['taskId'], 'target': report['target'], 'years': scope['years'],
            'documentPages': sum(c['pageCount'] for c in coverage.values() if c.get('unit') != 'segment'),
            'scannedPagesRead': sum(len(c['emptyTextPages']) for c in coverage.values()),
            'webSources': sum(s['kind'] == 'web' for s in sources.values()), 'sections': len(report['sections']),
            'financialCharts': len(report['financialData']['charts']), 'tables': len(tables),
            'citationsChecked': citations,
            'tableCellsMatched': matched, 'tableCellsChecked': checked,
            'modelCallsThisAttempt': job['modelCalls'], 'tokensThisAttempt': job['usage'].get('total_tokens')}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file')
    parser.add_argument('--years', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.file, args.years), ensure_ascii=False))
