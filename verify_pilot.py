"""Check evidence and entity boundaries that matter to this pilot."""
import json
import sqlite3
from inventory import ROOT

db=sqlite3.connect(ROOT/'data/inventory.sqlite')
db.row_factory=sqlite3.Row
assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
assert not db.execute('PRAGMA foreign_key_check').fetchall()
for e in db.execute('SELECT e.*,t.text FROM Evidence e JOIN TextFragment t ON t.id=e.fragment_id'):
    assert e['text'][e['start_char']:e['end_char']]==e['quote'],e['id']
for m in db.execute('SELECT m.*,t.text FROM Mention m JOIN TextFragment t ON t.id=m.fragment_id'):
    assert m['text'][m['start_char']:m['end_char']]==m['surface'],m['id']
assert not db.execute('SELECT id FROM Relation WHERE id NOT IN (SELECT relation_id FROM RelationEvidence)').fetchall()
assert not db.execute('SELECT m.id FROM Mention m JOIN MentionResolution r ON m.id=r.mention_id WHERE m.method="corpus_name_candidate"').fetchall()
assert db.execute('SELECT status FROM Relation WHERE from_person="sandro" AND to_person="shashiko" AND type="cousin"').fetchone()[0]=='rejected'
assert db.execute('SELECT COUNT(*) FROM Person WHERE id IN ("stepan","lenin","inna","inessa")').fetchone()[0]==4
assert not db.execute('SELECT id FROM Relation WHERE from_person="stepan" AND to_person="girl_amra" AND type="grandparent"').fetchall()
data=json.loads((ROOT/'data/pilot_export.json').read_text(encoding='utf-8'))
pilot_ids={w['id'] for w in data['works'] if w['pilot']}
automatic_ids={w['id'] for w in data['works'] if w.get('automatic')}
assert len(pilot_ids)==data['meta']['pilot_count']==25
assert len(automatic_ids)==data['meta']['automatic_work_count']>=100
assert any(w['title']=='Дядя Сандро и его любимец' and w['pilot'] for w in data['works'])
assert any(w['title']=='Чегемские сплетни' and w['pilot'] for w in data['works'])
assert any(w['title']=='Тали — чудо Чегема' and w['pilot'] for w in data['works'])
assert any(w['title']=='Рассказ мула старого Хабуга' and w['pilot'] for w in data['works'])
assert any(w['title']=='Умыкание, или Загадка эндурцев' and w['pilot'] for w in data['works'])
assert any(w['title']=='Дядя Сандро и раб Хазарат' and w['pilot'] for w in data['works'])
assert any(w['title']=='Дядя Сандро и конец козлотура' and w['pilot'] for w in data['works'])
assert any(w['title']=='Пиры Валтасара' and w['pilot'] for w in data['works'])
assert all(a['work_id'] in pilot_ids | automatic_ids and a['evidence'] for a in data['appearances'])
assert all(p['evidence'] for p in data['people'])
assert len(data['people'])==db.execute('SELECT COUNT(*) FROM Person').fetchone()[0]
assert db.execute('SELECT canonical_name FROM Person WHERE id="brother_sandro"').fetchone()[0]=='Махаз'
assert db.execute('SELECT COUNT(*) FROM Person WHERE canonical_name IN ("Махаз","Брат Сандро")').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM Person WHERE id IN ("brother_sandro","isa")').fetchone()[0]==2
assert db.execute('SELECT canonical_name FROM Person WHERE id="father_sandro"').fetchone()[0]=='Хабуг'
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="lakoba" AND to_person="rauf_lakoba" AND type="parent"').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="brother_sandro" AND to_person="masha" AND type="spouse"').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="isa" AND to_person="adgur" AND type="parent"').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="tali" AND to_person="bagrat" AND type="spouse"').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM Person WHERE id IN ("mule_arapka","donkey_arapka")').fetchone()[0]==2
assert db.execute('SELECT COUNT(*) FROM Person WHERE canonical_name LIKE "Арапка (%"').fetchone()[0]==2
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="father_sandro" AND to_person="kyzym" AND type="parent"').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM MentionResolution r JOIN Mention m ON m.id=r.mention_id WHERE m.surface LIKE "Арапк%" AND r.person_id IN ("mule_arapka","donkey_arapka")').fetchone()[0]>=2
assert db.execute('''SELECT COUNT(*) FROM Mention m JOIN Work w ON w.id=m.work_id
    LEFT JOIN MentionResolution r ON r.mention_id=m.id
    WHERE w.canonical_title='Рассказ мула старого Хабуга'
      AND m.surface LIKE 'Арапк%' AND r.mention_id IS NULL''').fetchone()[0]==0
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="aslan" AND to_person="shazina" AND type="spouse"').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="katya_grandmother" AND to_person="katya" AND type="grandparent"').fetchone()[0]==1
assert db.execute('SELECT COUNT(*) FROM Person WHERE id IN ("katya","german_katrin")').fetchone()[0]==2
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="adamyr" AND to_person="khazarat" AND type="enslaves"').fetchone()[0]==1
print('PASS: evidence quotes, mention spans, relation sources, unresolved corpus matches, false kinship, separate identities, cross-work merge, export consistency')
