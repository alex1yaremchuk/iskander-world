"""Build the canonical structural registry and a separate edition comparison queue.

Rules below were reviewed against this particular ten-volume corpus, not arbitrary EPUBs.
"""
import csv
import json
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
import xml.etree.ElementTree as ET
from inventory import ROOT, digest, local, normalized, resolve, text, title_key


def clean_title(value):
    return re.sub(r'^(?:Глава\s+)?\d+[.\s]+', '', value, flags=re.I).strip()


def prose(node):
    # Paragraphs preserve inline drop capitals; headings are intentionally excluded
    # ONLY from comparison text. Original fragments remain in inventory.sqlite.
    output = []
    def walk(element):
        if local(element) in ('title', 'head', 'script', 'style') or re.fullmatch('h[1-6]', local(element)):
            return
        if local(element) in ('p', 'v'):
            output.append(text(element))
            return
        for child in element:
            walk(child)
    walk(node)
    return '\n'.join(output)


def tokens(value):
    return re.findall(r'\w+', value.casefold().replace('ё', 'е'))


def features(value):
    words = tokens(value)
    return set(zip(*(words[i:] for i in range(5))))


def epub_resources(path):
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read('META-INF/container.xml'))
        package_path = container.find('.//{*}rootfile').get('full-path')
        package = ET.fromstring(z.read(package_path))
        manifest = {e.get('id'): e for e in package.findall('{*}manifest/{*}item')}
        resources = []
        for ref in package.findall('{*}spine/{*}itemref'):
            resource, _ = resolve(package_path, manifest[ref.get('idref')].get('href'))
            tree = ET.fromstring(z.read(resource))
            resources.append((resource, prose(tree.find('.//{*}body'))))
        return resources


def main():
    db = sqlite3.connect(ROOT / 'data/inventory.sqlite')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS WorkDetail(work_id TEXT PRIMARY KEY REFERENCES Work(id), kind TEXT, parent_id TEXT REFERENCES Work(id), metadata_json TEXT);
    CREATE TABLE IF NOT EXISTS WorkFragment(work_id TEXT REFERENCES Work(id), fragment_id TEXT REFERENCES TextFragment(id), PRIMARY KEY(work_id, fragment_id));
    CREATE TABLE IF NOT EXISTS EditionComparison(id TEXT PRIMARY KEY, work_id TEXT REFERENCES Work(id), source_id TEXT REFERENCES Source(id), location TEXT, decision TEXT, metrics_json TEXT);
    CREATE INDEX IF NOT EXISTS workfragment_fragment ON WorkFragment(fragment_id);
    ''')
    works, excluded, alt, volumes = [], [], [], []
    for sid, rel, meta in db.execute('SELECT s.id,f.path,s.metadata_json FROM Source s JOIN SourceFile f ON s.id=f.source_id ORDER BY f.path'):
        path = ROOT / 'corpus' / rel
        if rel.startswith('canonical_10vol/'):
            volume = int(re.search(r'Том (\d+)', path.name)[1])
            entries = [dict(id=i, **json.loads(raw)) for i, t, raw in
                       db.execute('SELECT id,title,raw_json FROM TocEntry WHERE source_id=? ORDER BY ordinal', (sid,))]
            resources = epub_resources(path)
            resource_index = {r: i for i, (r, _) in enumerate(resources)}
            assert all('#' not in e['location'] and e['location'] in resource_index for e in entries)
            root_location = entries[0]['location']
            groups = {e['location']: e['title'] for e in entries if volume == 10 and
                      e['title'] in ('Стихотворения и баллады', 'Поэмы', 'Эпиграммы и шутки',
                                     'Переводы из Редьярда Киплинга', 'Эссе', 'Понемногу о многом')}
            volumes.append({'volume': volume, 'file': rel, 'source_id': sid, 'metadata': json.loads(meta), 'toc_entries': len(entries)})
            for index, entry in enumerate(entries):
                if entry['location'] == root_location or entry['location'] in groups or entry['title'] in ('Фазиль Великолепный', 'Библиография [1]'):
                    excluded.append({'source': rel, **entry, 'reason': 'edition_container' if index == 0 else 'editorial_material' if entry['title'] in ('Фазиль Великолепный','Библиография [1]') else 'genre_group'})
                    continue
                # Span includes continuation resources and descendants up to next peer/ancestor.
                def ancestor_locations(e):
                    result = []
                    while e.get('parent'):
                        result.append(e['parent'])
                        e = next(x for x in entries if x['location'] == e['parent'])
                    return result
                start = resource_index[entry['location']]
                end = len(resources)
                for later in entries[index + 1:]:
                    if entry['location'] not in ancestor_locations(later):
                        end = resource_index[later['location']]
                        break
                selected = resources[start:end]
                # Converter's footnote resources are apparatus, not the last work.
                selected = [(r, t) for r,t in selected if re.search(r'/section\d+\.xhtml$', r)]
                group = groups.get(entry['parent'])
                kind = 'work'
                parent = None
                if volume in (4,5,6):
                    kind, parent = 'novel_chapter', 'work_sandro_iz_chegema'
                elif volume == 3:
                    kind, parent = 'cycle_story', 'work_detstvo_chika'
                elif volume == 7 and entry['parent'] != root_location:
                    kind = 'work_part'
                    parent = 'work_' + next(e['id'][4:] for e in entries if e['location'] == entry['parent'])
                elif group:
                    kind = {'Стихотворения и баллады':'poem', 'Поэмы':'long_poem',
                            'Эпиграммы и шутки':'epigram', 'Переводы из Редьярда Киплинга':'translation',
                            'Эссе':'essay', 'Понемногу о многом':'notes'}[group]
                works.append({'id': 'work_' + entry['id'][4:], 'title': clean_title(entry['title']),
                              'kind': kind, 'parent_id': parent, 'volume': volume,
                              'source_id': sid, 'source': rel, 'location': entry['location'],
                              'resources': [r for r,_ in selected], 'text': '\n'.join(t for _,t in selected),
                              'toc_id': entry['id'], 'group': group, 'status': 'canonical_structure_verified'})
        else:
            tree = ET.fromstring(path.read_bytes())
            title = json.loads(meta)['title']
            for bi, body in enumerate(tree.findall('{*}body')):
                if body.get('name') in ('notes', 'comments'):
                    continue
                sections = [(i,s) for i,s in enumerate(body) if local(s) == 'section']
                for i, section in sections:
                    heading = text(section.find('{*}title')) or title
                    alt.append({'source_id': sid, 'source': rel, 'location': f'body[{bi}]/section[{i}]',
                                'title': clean_title(heading), 'text': prose(section), 'book_title': title})
    # Parent work identity is explicit in the canonical volume headings.
    parents = [{'id':'work_sandro_iz_chegema','title':'Сандро из Чегема','kind':'novel', 'parent_id':None},
               {'id':'work_detstvo_chika','title':'Детство Чика','kind':'cycle', 'parent_id':None}]
    with db:
        for work in parents + works:
            db.execute('INSERT OR REPLACE INTO Work VALUES (?,?,?)', (work['id'],work['title'],'Canonical TOC structure; identity is source-anchored, not name-based.'))
        for work in parents + works:
            db.execute('INSERT OR REPLACE INTO WorkDetail VALUES (?,?,?,?)',
                       (work['id'],work['kind'],work['parent_id'],json.dumps({k:v for k,v in work.items() if k!='text'},ensure_ascii=False)))
        for work in works:
            db.execute('INSERT OR REPLACE INTO WorkSource VALUES (?,?,?,?)',
                       (work['id'],work['source_id'],work['location'],json.dumps({'resources':work['resources'],'boundary_rule':'next TOC peer or ancestor, exclusive'},ensure_ascii=False)))
            for fid,location in db.execute('SELECT id,location FROM TextFragment WHERE source_id=?',(work['source_id'],)):
                if location.split('::',1)[0] in work['resources']:
                    db.execute('INSERT OR IGNORE INTO WorkFragment VALUES (?,?)',(work['id'],fid))
        for parent in parents:
            children = [w for w in works if w['parent_id'] == parent['id']]
            for child in children:
                db.execute('INSERT OR IGNORE INTO WorkFragment SELECT ?,fragment_id FROM WorkFragment WHERE work_id=?', (parent['id'],child['id']))
                db.execute('INSERT OR REPLACE INTO WorkSource VALUES (?,?,?,?)',
                           (parent['id'],child['source_id'],child['location'],'Parent work membership via canonical child: '+child['id']))
    index = defaultdict(set)
    title_index = defaultdict(set)
    for i,w in enumerate(works):
        w['_features'] = features(w['text'])
        w['_normalized'] = ' '.join(tokens(w['text']))
        for f in w['_features']:
            index[f].add(i)
        title_index[title_key(w['title']).replace('ё','е')].add(i)
    comparisons, unmatched = [], []
    for a in alt:
        f = features(a['text'])
        votes = Counter(i for feature in f for i in index.get(feature, ()))
        candidates = {i for i,_ in votes.most_common(3)} | title_index.get(title_key(a['title']).replace('ё','е'), set())
        matches = []
        for i in candidates:
            w = works[i]
            overlap = len(f & w['_features'])
            ca = overlap / max(1,len(f))
            cw = overlap / max(1,len(w['_features']))
            if max(ca,cw) < .12 and title_key(a['title']) != title_key(w['title']):
                continue
            exact = ' '.join(tokens(a['text'])) == w['_normalized'] and bool(w['_normalized'])
            decision = 'normalized_text_identical' if exact else 'variant_candidate' if min(ca,cw) >= .70 else 'containment_candidate' if max(ca,cw) >= .70 else 'title_or_partial_overlap_review'
            matches.append({'work_id':w['id'],'canonical_title':w['title'],'canonical_volume':w['volume'],
                            'source_id':a['source_id'],'source':a['source'],'location':a['location'],
                            'alternate_title':a['title'],'decision':decision,
                            'alternate_coverage':round(ca,5),'canonical_coverage':round(cw,5),
                            'canonical_characters':len(w['text']),'alternate_characters':len(a['text'])})
        matches.sort(key=lambda m:min(m['alternate_coverage'],m['canonical_coverage']),reverse=True)
        if not matches:
            unmatched.append({k:v for k,v in a.items() if k!='text'})
        comparisons.extend(matches)
    with db:
        db.execute("DELETE FROM WorkSource WHERE review_note LIKE 'Full comparison text identical%'")
        for m in comparisons:
            key=digest(m['work_id']+m['source_id']+m['location'])
            db.execute('INSERT OR REPLACE INTO EditionComparison VALUES (?,?,?,?,?,?)',
                       (key,m['work_id'],m['source_id'],m['location'],m['decision'],json.dumps(m,ensure_ascii=False)))
            if m['decision']=='normalized_text_identical':
                db.execute('INSERT OR REPLACE INTO WorkSource VALUES (?,?,?,?)',
                           (m['work_id'],m['source_id'],m['location'],'Full comparison text identical after case/punctuation/whitespace/ё normalization. Original typography not identical by this test.'))
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert len({v['volume'] for v in volumes}) == 10
    assert len([w for w in works if w['kind']=='novel_chapter']) == 32
    assert all(w['text'] for w in works)
    out=ROOT/'data'
    export=[{k:v for k,v in w.items() if k not in ('text','_features','_normalized')} for w in parents+works]
    def save(name,value):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    save('canonical_works.json',export)
    save('edition_comparisons.json',comparisons)
    save('unmatched_alternate.json',unmatched)
    save('excluded_toc.json',excluded)
    save('volumes.json',sorted(volumes,key=lambda v:v['volume']))
    with (out/'canonical_works.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields=['id','title','kind','parent_id','volume','source','location']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(export)
    summary={'canonical_entries':len(export),'text_units':len(works),'alternate_segments':len(alt),
             'comparison_pairs':len(comparisons),'decisions':dict(Counter(m['decision'] for m in comparisons)),
             'unmatched_alternate_segments':len(unmatched),'excluded_toc_entries':len(excluded),
             'kinds':dict(Counter(w['kind'] for w in export)),
             'fragment_count':db.execute('SELECT COUNT(*) FROM TextFragment').fetchone()[0]}
    save('registry_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))
    db.close()


if __name__=='__main__':
    main()
