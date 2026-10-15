"""Check evidence and entity boundaries that matter to this pilot."""
import json
import sqlite3
import re
from collections import defaultdict
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
assert len(pilot_ids)==data['meta']['pilot_count']>=26
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
assert not db.execute('SELECT 1 FROM Person WHERE id="kyzym_wife"').fetchone()
assert db.execute('SELECT canonical_name FROM Person WHERE id="nutsa"').fetchone()[0]=='Тётя Нуца'
assert db.execute("SELECT 1 FROM Relation WHERE from_person='kyzym' AND to_person='nutsa' AND type='spouse'").fetchone()
assert db.execute("SELECT 1 FROM Relation WHERE from_person='kyzym' AND to_person='sandro' AND type='sibling'").fetchone()
assert db.execute("SELECT 1 FROM Relation WHERE from_person='chik_grandmother' AND to_person='chik_uncle_kolya' AND type='parent'").fetchone()
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
def normalized_name(value):
    value=value.casefold().replace('ё','е').replace('—','-').replace('–','-')
    value=re.sub(r'[«»„“”\"\'()]','',value)
    return re.sub(r'\s+',' ',value).strip()
name_groups=defaultdict(list)
for person in db.execute('SELECT id,canonical_name FROM Person'):
    name_groups[normalized_name(person['canonical_name'])].append(person['id'])
exact_name_collisions={name: ids for name, ids in name_groups.items() if len(ids)>1}
assert not exact_name_collisions, exact_name_collisions

# Removing an address/title catches cards such as «Катя» / «Тётя Катя».
# Every remaining collision must be an explicitly reviewed homonym or a
# possessive family label, never an unnoticed duplicate.
honorific = re.compile(r'^(?:тетя|тетушка|дядя|дядюшка|старик|старый|молодой|князь|княгиня|принц|принцесса|дедушка|бабушка|товарищ|доктор|генерал|царь)\s+')
core_groups=defaultdict(list)
for person in db.execute('SELECT id,canonical_name FROM Person'):
    core=normalized_name(person['canonical_name'])
    previous=None
    while previous != core:
        previous=core
        core=honorific.sub('',core)
    core_groups[core].append(person['id'])
reviewed_core_collisions={
    frozenset({'safar','prince_safar'}),
    frozenset({'chik_aunt','chik_grandmother'}),
}
unexpected_core_collisions=[]
for ids in core_groups.values():
    if len(ids)>1 and frozenset(ids) not in reviewed_core_collisions:
        names={db.execute('SELECT canonical_name FROM Person WHERE id=?',(person_id,)).fetchone()[0] for person_id in ids}
        if len(names)>1:
            unexpected_core_collisions.append(ids)
assert not unexpected_core_collisions, unexpected_core_collisions
assert db.execute('SELECT COUNT(*) FROM Person WHERE id IN ("masha","bulk_c44e41ad44f251d83d9c03ff")').fetchone()[0]==1
assert not db.execute('SELECT 1 FROM Person WHERE id="bulk_d75876aee084ff286f0e0120"').fetchone()
assert db.execute('SELECT canonical_name FROM Person WHERE id="masha"').fetchone()[0]=='Тётя Маша'
assert not db.execute("SELECT 1 FROM Person WHERE id IN ('bulk_c96e91b9c2ef1d8ab1b8fd77','bulk_f685f65324fc1063e369b5db','bulk_b020369a25fac95da7da9c02','bulk_b6bfec204320a6902221dfb8','bulk_330dfb4a60de2f5f3e8db99e','bulk_4095a9fcb0ae940df31a4f23')").fetchone()
assert db.execute('SELECT COUNT(*) FROM Person WHERE id="sandro"').fetchone()[0]==1
assert not db.execute("SELECT 1 FROM Person WHERE id IN ('tsiala','bulk_e969d96f858677047d9473e6','bulk_6ae702f9c69e29fff63c19ab','bulk_9607a4997fc8625ed92f09f6','bulk_a9fdf1d196dc6b219d00709f','bulk_9b3c18df05f8035248c1891f')").fetchone()
assert db.execute('SELECT COUNT(*) FROM Person WHERE id IN ("safar","prince_safar")').fetchone()[0]==2
assert db.execute("SELECT 1 FROM Relation WHERE from_person='safar' AND to_person='chik' AND type='cousin'").fetchone()
assert db.execute("SELECT 1 FROM Relation WHERE from_person='bata_safar_foster_brother' AND to_person='prince_safar' AND type='kills'").fetchone()
assert db.execute("SELECT canonical_name FROM Person WHERE id='beer_seller_lena'").fetchone()[0]=='Лена — продавщица на вокзале'
assert db.execute("SELECT canonical_name FROM Person WHERE id='mikha_wife_raven_story'").fetchone()[0]=='Жена Михи — хозяина ворона'
assert db.execute("SELECT canonical_name FROM Person WHERE id='mikha_wife_ankhara'").fetchone()[0]=='Жена Михи из Анхары'
assert db.execute("SELECT COUNT(*) FROM Appearance WHERE person_id='mikha_hunter'").fetchone()[0]==1
assert db.execute("SELECT COUNT(*) FROM Appearance WHERE person_id='mikha_raven_owner'").fetchone()[0]==1
assert not db.execute("""SELECT 1 FROM Appearance a JOIN Appearance b ON a.work_id=b.work_id
    WHERE a.person_id='omar_forester' AND b.person_id='omar_chik'""").fetchone()
assert not db.execute("SELECT 1 FROM Person WHERE id IN ('bulk_a620ff4860a1877fd6eeeb01','bulk_e27dc5727f3a13376d03c426','bulk_ea6ba1a4b0ad8a08df637ef3','bulk_c8f26b2a6f59f3295a4a4d1d')").fetchone()
assert db.execute('SELECT COUNT(*) FROM Relation WHERE from_person="adamyr" AND to_person="khazarat" AND type="enslaves"').fetchone()[0]==1
print('PASS: evidence quotes, mention spans, relation sources, unresolved corpus matches, false kinship, separate identities, cross-work merge, export consistency')
