"""Check referential integrity of the static reading projection."""
import json
import re
from inventory import ROOT

export_path = ROOT / 'data/pilot_export.json'
data = json.loads(export_path.read_text(encoding='utf-8'))
data_js = (ROOT / 'site/dist/data.js').read_text(encoding='utf-8')
prefix = 'window.ISKANDER_DATA='
assert data_js.startswith(prefix) and data_js.rstrip().endswith(';')
embedded = json.loads(data_js[len(prefix):].strip()[:-1])
assert embedded == data

people = {x['id'] for x in data['people']}
works = {x['id'] for x in data['works']}
evidence = {x['id'] for x in data['evidence']}
places = {x['id'] for x in data['places']}

assert data['meta']['person_count'] == len(people)
assert data['meta']['relation_count'] == len(data['relations'])
assert data['meta']['pilot_count'] == sum(bool(x['pilot']) for x in data['works'])
for alias in data['aliases']:
    assert alias['person_id'] in people and alias['evidence_id'] in evidence
for appearance in data['appearances']:
    assert appearance['person_id'] in people and appearance['work_id'] in works
    assert appearance['evidence'] and set(appearance['evidence']) <= evidence
for relation in data['relations']:
    assert relation['from_person'] in people and relation['to_person'] in people
    assert relation['evidence'] and set(relation['evidence']) <= evidence
for link in data['personPlaces']:
    assert link['person_id'] in people and link['place_id'] in places and link['evidence_id'] in evidence
for hit in data['corpusHits']:
    assert hit['person_id'] in people and hit['work_id'] in works and hit['evidence_id'] in evidence

app = (ROOT / 'site/dist/app.js').read_text(encoding='utf-8')
family_blocks = re.findall(r'nodes:\{([^}]*)\}', app)
family_people = {pid for block in family_blocks for pid in re.findall(r'([a-z][a-z0-9_]*):\[', block)}
assert family_blocks and family_people
assert family_people <= people, sorted(family_people - people)
assert 'D.meta.pilot_count' in app
assert '<b>3</b><span>текста в пилоте' not in app
print('PASS: site export parity, entity references, evidence links, family-tree people, dynamic counters')
