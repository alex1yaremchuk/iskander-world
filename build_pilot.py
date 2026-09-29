"""Import the checked pilot; discover unresolved name matches; export the reading app."""
import json
import re
import sqlite3
from collections import defaultdict
from inventory import ROOT, digest
from prepare_pilot import prepare
from pilot_seed import PEOPLE, RELATIONS, PLACES, PERSON_PLACES, AMBIGUOUS, RESOLVED_MENTIONS

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS ExtractionRun(id TEXT PRIMARY KEY, method TEXT, metadata_json TEXT);
CREATE TABLE IF NOT EXISTS Person(id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, description TEXT, kind TEXT, notes TEXT, evidence_json TEXT);
CREATE TABLE IF NOT EXISTS Evidence(id TEXT PRIMARY KEY, work_id TEXT REFERENCES Work(id), source_id TEXT REFERENCES Source(id), fragment_id TEXT REFERENCES TextFragment(id), quote TEXT NOT NULL, start_char INTEGER, end_char INTEGER, location TEXT, paragraph_key TEXT);
CREATE TABLE IF NOT EXISTS Alias(id TEXT PRIMARY KEY, person_id TEXT REFERENCES Person(id), name TEXT, scope_work_id TEXT REFERENCES Work(id), evidence_id TEXT REFERENCES Evidence(id));
CREATE TABLE IF NOT EXISTS Mention(id TEXT PRIMARY KEY, work_id TEXT REFERENCES Work(id), fragment_id TEXT REFERENCES TextFragment(id), start_char INTEGER, end_char INTEGER, surface TEXT, candidates_json TEXT, method TEXT, run_id TEXT REFERENCES ExtractionRun(id));
CREATE TABLE IF NOT EXISTS MentionResolution(mention_id TEXT PRIMARY KEY REFERENCES Mention(id), person_id TEXT REFERENCES Person(id), confidence TEXT CHECK(confidence IN ('explicit','strongly_implied','inferred','uncertain')), evidence_id TEXT REFERENCES Evidence(id), rationale TEXT);
CREATE TABLE IF NOT EXISTS Appearance(id TEXT PRIMARY KEY, person_id TEXT REFERENCES Person(id), work_id TEXT REFERENCES Work(id), role TEXT CHECK(role IN ('main','secondary','episode','mention')), confidence TEXT, evidence_json TEXT, rationale TEXT, UNIQUE(person_id,work_id));
CREATE TABLE IF NOT EXISTS Relation(id TEXT PRIMARY KEY, from_person TEXT REFERENCES Person(id), to_person TEXT REFERENCES Person(id), type TEXT, label TEXT, confidence TEXT CHECK(confidence IN ('explicit','strongly_implied','inferred','uncertain')), perspective TEXT, status TEXT CHECK(status IN ('accepted','reported','rejected')), note TEXT);
CREATE TABLE IF NOT EXISTS RelationEvidence(relation_id TEXT REFERENCES Relation(id), evidence_id TEXT REFERENCES Evidence(id), PRIMARY KEY(relation_id,evidence_id));
CREATE TABLE IF NOT EXISTS Place(id TEXT PRIMARY KEY, name TEXT, kind TEXT, description TEXT, x REAL,y REAL, evidence_json TEXT);
CREATE TABLE IF NOT EXISTS PersonPlace(id TEXT PRIMARY KEY, person_id TEXT REFERENCES Person(id), place_id TEXT REFERENCES Place(id), label TEXT, confidence TEXT, evidence_id TEXT REFERENCES Evidence(id));
CREATE TABLE IF NOT EXISTS CorpusHit(id TEXT PRIMARY KEY, person_id TEXT REFERENCES Person(id), work_id TEXT REFERENCES Work(id), mention_id TEXT REFERENCES Mention(id), evidence_id TEXT REFERENCES Evidence(id), count INTEGER, status TEXT);
CREATE INDEX IF NOT EXISTS mention_work ON Mention(work_id);
CREATE INDEX IF NOT EXISTS resolution_person ON MentionResolution(person_id);
CREATE INDEX IF NOT EXISTS appearance_work ON Appearance(work_id);
CREATE INDEX IF NOT EXISTS relation_from ON Relation(from_person);
CREATE INDEX IF NOT EXISTS relation_to ON Relation(to_person);
CREATE INDEX IF NOT EXISTS evidence_fragment ON Evidence(fragment_id);
CREATE INDEX IF NOT EXISTS corpus_person ON CorpusHit(person_id,work_id);
'''


def main():
    texts=prepare()
    paragraphs={p['key']:dict(p,work_id=w['id'],source_id=w['source_id']) for w in texts for p in w['paragraphs']}
    db=sqlite3.connect(ROOT/'data/inventory.sqlite')
    db.row_factory=sqlite3.Row
    db.executescript(SCHEMA)
    run_id='pilot_v1'
    quote_cache={}
    def evidence(key, surface=None):
        p=paragraphs[key]
        if surface is None:
            start,end=0,len(p['text'])
        else:
            start=p['text'].find(surface)
            assert start>=0,(key,surface)
            end=start+len(surface)
        return fragment_evidence(p['work_id'],p['source_id'],p['fid'],p['text'],p['location'],start,end,key)
    def fragment_evidence(wid,sid,fid,value,location,start,end,key=''):
        # Context is the whole pilot paragraph, or a bounded window for corpus search.
        left,right=(0,len(value)) if key else (max(0,start-150),min(len(value),end+250))
        quote=value[left:right]
        eid='ev_'+digest(f'{wid}:{fid}:{left}:{right}')[:24]
        db.execute('INSERT OR REPLACE INTO Evidence VALUES (?,?,?,?,?,?,?,?,?)',(eid,wid,sid,fid,quote,left,right,location,key))
        quote_cache[eid]=quote
        return eid
    def mention(wid,fid,start,end,surface,candidates,method):
        mid='men_'+digest(f'{wid}:{fid}:{start}:{end}')[:24]
        db.execute('INSERT OR REPLACE INTO Mention VALUES (?,?,?,?,?,?,?,?,?)',
                   (mid,wid,fid,start,end,surface,json.dumps(candidates),method,run_id))
        return mid
    with db:
        # Only derived pilot tables are rebuilt; the corpus and canonical registry remain.
        # An open review queue points at Mention and Person, so clear it before rebuilding them.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ReviewItem'").fetchone():
            db.execute('DELETE FROM ReviewItem')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ReviewBatch'").fetchone():
            db.execute('DELETE FROM ReviewBatch')
        for table in ['CorpusHit','PersonPlace','RelationEvidence','Relation','Appearance','MentionResolution','Mention','Alias','Place','Person','Evidence','ExtractionRun']:
            db.execute('DELETE FROM '+table)
        raw_extraction={'people':PEOPLE,'relations':RELATIONS,'places':PLACES,'person_places':PERSON_PLACES,'ambiguous_names':AMBIGUOUS,'resolved_mentions':RESOLVED_MENTIONS}
        db.execute('INSERT INTO ExtractionRun VALUES (?,?,?)',(run_id,'assistant_reading_then_dictionary_candidates',json.dumps({'seed_sha256':digest((ROOT/'pilot_seed.py').read_bytes()),'scope':f'{len(texts)} canonical texts','coreference':'selected explicit anchors; no exhaustive pronoun resolution','raw_extraction':raw_extraction},ensure_ascii=False)))
        for wi,w in enumerate(texts):
            for pi,p in enumerate(w['paragraphs']):
                fid='para_'+digest(w['source_id']+':'+p['location'])
                paragraphs[p['key']]['fid']=fid
                raw=dict(p,kind='pilot_paragraph',section=p['resource'],source_format='xhtml',normalization='inline itertext joined; whitespace collapsed')
                db.execute('INSERT INTO TextFragment VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET text=excluded.text,raw_json=excluded.raw_json',
                           (fid,w['source_id'],1000000+pi,p['location'],p['text'],digest(p['text']),json.dumps(raw,ensure_ascii=False)))
                db.execute('INSERT OR IGNORE INTO WorkFragment VALUES (?,?)',(w['id'],fid))
        for person in PEOPLE:
            keys=list(dict.fromkeys([a[0] for a in person['anchors']]+person['extra']))
            eids=[evidence(k) for k in keys]
            db.execute('INSERT INTO Person VALUES (?,?,?,?,?,?)',(person['id'],person['name'],person['description'],person['kind'],person['notes'],json.dumps(eids)))
        # Mentions are made first. Entity decisions below are a distinct operation.
        patterns=[]
        for person in PEOPLE:
            if person['pattern']:
                patterns.append((re.compile(r'(?<!\w)(?:'+person['pattern']+r')(?!\w)'),[person['id']],set(person['roles'])))
        for _,pattern,candidates,work_number in AMBIGUOUS:
            patterns.append((re.compile(r'(?<!\w)(?:'+pattern+r')(?!\w)'),candidates,{work_number}))
        for key,p in paragraphs.items():
            work_number=key.split('_',1)[0][1:]
            hits=[]
            for pattern,candidates,scope in patterns:
                if work_number not in scope: continue
                for match in pattern.finditer(p['text']): hits.append((match.start(),match.end(),match.group(),candidates))
            # A full personal name takes priority over a shorter ambiguous substring.
            for start,end,surface,candidates in hits:
                if any(a<=start and b>=end and b-a>end-start for a,b,_,_ in hits): continue
                # If the same span has both a person's broad name pattern and an
                # explicit homonym rule, keep it unresolved until the contextual
                # decisions below.  This is what prevents equal names from being
                # merged merely because one candidate was seeded first.
                if len(candidates)==1 and any(a==start and b==end and len(cs)>1 for a,b,_,cs in hits): continue
                mid=mention(p['work_id'],p['fid'],start,end,surface,candidates,'pilot_name_pattern')
                if len(candidates)==1:
                    eid=evidence(key,surface)
                    db.execute('INSERT OR REPLACE INTO MentionResolution VALUES (?,?,?,?,?)',
                               (mid,candidates[0],'strongly_implied',eid,'Имя проверено в контексте пилота; решение ограничено этими текстами.'))
        for person in PEOPLE:
            for key,surface in person['anchors']:
                p=paragraphs[key];start=p['text'].find(surface)
                assert start>=0,(person['id'],key,surface)
                mid=mention(p['work_id'],p['fid'],start,start+len(surface),surface,[person['id']],'assistant_context_anchor')
                eid=evidence(key,surface)
                confidence='strongly_implied' if person['id']=='narrator' else 'explicit'
                db.execute('INSERT OR REPLACE INTO MentionResolution VALUES (?,?,?,?,?)',(mid,person['id'],confidence,eid,person['notes'] or 'Контекст прочитан; имя или описание относится к этому персонажу.'))
                if person['pattern'] and len(surface)>2:
                    aid='alias_'+digest(person['id']+surface+p['work_id'])[:20]
                    db.execute('INSERT OR IGNORE INTO Alias VALUES (?,?,?,?,?)',(aid,person['id'],surface,p['work_id'],eid))
            for number,role in person['roles'].items():
                w=texts[int(number)-1]
                keys=[key for key,_ in person['anchors'] if key.split('_',1)[0][1:]==number]
                keys+= [key for key in person['extra'] if key.split('_',1)[0][1:]==number]
                assert keys,(person['id'],number)
                db.execute('INSERT INTO Appearance VALUES (?,?,?,?,?,?,?)',
                           ('app_'+person['id']+'_'+number,person['id'],w['id'],role,'inferred',json.dumps([evidence(k) for k in dict.fromkeys(keys)]),'Участие подтверждено текстом; роль — редакционная оценка для навигации.'))
        for key,surface,occurrence,person_id in RESOLVED_MENTIONS:
            p=paragraphs[key]
            matches=list(re.finditer(re.escape(surface),p['text']))
            assert occurrence < len(matches),(key,surface,occurrence)
            match=matches[occurrence]
            candidates=next((cs for _,pattern,cs,number in AMBIGUOUS
                             if number==key.split('_',1)[0][1:] and re.fullmatch(pattern,surface)),[person_id])
            mid=mention(p['work_id'],p['fid'],match.start(),match.end(),surface,
                        candidates,'assistant_context_resolution')
            eid=fragment_evidence(p['work_id'],p['source_id'],p['fid'],p['text'],p['location'],match.start(),match.end(),key)
            db.execute('INSERT OR REPLACE INTO MentionResolution VALUES (?,?,?,?,?)',
                       (mid,person_id,'explicit',eid,'Омонимичное имя разрешено по ближайшему контексту прочитанного фрагмента.'))
        for pid,name,key in [('stepan','Ленин','p3_0041'),('stepan','Дедушка Ленин','p3_0288'),('inna','Инесса','p3_0041'),('sandro','Сандро Хабугович','p3_0090'),('tengo','Тенго','p2_0154'),('khrushchev','Хрущит','p2_0202'),('tali','Талико','p6_0001'),('tali','Таликошка','p6_0001')]:
            db.execute('INSERT OR REPLACE INTO Alias VALUES (?,?,?,?,?)',('alias_'+digest(pid+name)[:20],pid,name,paragraphs[key]['work_id'],evidence(key)))
        for i,r in enumerate(RELATIONS):
            rid='rel_'+digest(r['a']+r['b']+r['type'])[:20]
            db.execute('INSERT INTO Relation VALUES (?,?,?,?,?,?,?,?,?)',(rid,r['a'],r['b'],r['type'],r['label'],r['confidence'],r['perspective'],r['status'],r['note']))
            for key in r['keys']: db.execute('INSERT INTO RelationEvidence VALUES (?,?)',(rid,evidence(key)))
        for p in PLACES:
            db.execute('INSERT INTO Place VALUES (?,?,?,?,?,?,?)',(p['id'],p['name'],p['kind'],p['description'],p['x'],p['y'],json.dumps([evidence(k) for k in p['keys']])))
        for pid,place,label,key in PERSON_PLACES:
            link_id='pp_'+digest(':'.join((pid,place,label,key)))[:20]
            db.execute('INSERT INTO PersonPlace VALUES (?,?,?,?,?,?)',(link_id,pid,place,label,'strongly_implied',evidence(key)))
    print('Pilot imported; finding unresolved appearances...',flush=True)
    # Global lookup is discovery, not an entity-resolution pass. Never turn these into Appearance.
    work_map=defaultdict(list)
    canonical_sources=set()
    rows=db.execute('SELECT wf.fragment_id,wf.work_id,t.source_id FROM WorkFragment wf JOIN WorkDetail d ON d.work_id=wf.work_id JOIN TextFragment t ON t.id=wf.fragment_id JOIN SourceFile s ON s.source_id=t.source_id WHERE s.collection="canonical_10vol" AND d.kind NOT IN ("novel","cycle") AND t.id NOT LIKE "para_%"').fetchall()
    for row in rows:
        work_map[row['fragment_id']].append(row['work_id']);canonical_sources.add(row['source_id'])
    pilot_work_ids={w['id'] for w in texts}
    global_patterns=[(p['id'],re.compile(r'(?<!\w)(?:'+p['pattern']+r')(?!\w)')) for p in PEOPLE if p['pattern']]
    counts=defaultdict(int);first={}
    fragments=db.execute('SELECT id,source_id,location,text FROM TextFragment WHERE id NOT LIKE "para_%"').fetchall()
    with db:
        for row in fragments:
            if row['source_id'] not in canonical_sources: continue
            for pid,pattern in global_patterns:
                matches=list(pattern.finditer(row['text']))
                if not matches: continue
                for wid in work_map.get(row['id'],[]):
                    if wid in pilot_work_ids: continue
                    counts[(pid,wid)]+=len(matches)
                    if (pid,wid) in first: continue
                    m=matches[0]
                    mid=mention(wid,row['id'],m.start(),m.end(),m.group(),[pid],'corpus_name_candidate')
                    eid=fragment_evidence(wid,row['source_id'],row['id'],row['text'],row['location'],m.start(),m.end())
                    first[(pid,wid)]=(mid,eid)
        for (pid,wid),count in counts.items():
            mid,eid=first[(pid,wid)]
            db.execute('INSERT INTO CorpusHit VALUES (?,?,?,?,?,?,?)',('hit_'+digest(pid+wid)[:20],pid,wid,mid,eid,count,'unresolved'))
    def table(name): return [dict(row) for row in db.execute('SELECT * FROM '+name)]
    def json_column(rows,column,target):
        for r in rows:r[target]=json.loads(r.pop(column))
        return rows
    people=json_column(table('Person'),'evidence_json','evidence')
    for p in people:
        p['mention_count']=db.execute('SELECT COUNT(*) FROM MentionResolution WHERE person_id=?',(p['id'],)).fetchone()[0]
    relations=table('Relation')
    for r in relations:r['evidence']=[row[0] for row in db.execute('SELECT evidence_id FROM RelationEvidence WHERE relation_id=?',(r['id'],))]
    works=[]
    for row in db.execute('SELECT w.id,w.canonical_title,d.kind,d.parent_id,d.metadata_json FROM Work w JOIN WorkDetail d ON w.id=d.work_id'):
        meta=json.loads(row['metadata_json'])
        works.append(dict(id=row['id'],title=row['canonical_title'],kind=row['kind'],parent_id=row['parent_id'],volume=meta.get('volume'),pilot=row['id'] in pilot_work_ids))
    export=dict(people=people,aliases=table('Alias'),relations=relations,works=works,
                appearances=json_column(table('Appearance'),'evidence_json','evidence'),
                places=json_column(table('Place'),'evidence_json','evidence'),personPlaces=table('PersonPlace'),
                evidence=table('Evidence'),corpusHits=table('CorpusHit'),
                meta=dict(pilot_count=len(texts),person_count=len(people),relation_count=len(relations),
                          mention_count=db.execute('SELECT COUNT(*) FROM Mention').fetchone()[0],
                          unresolved_count=db.execute('SELECT COUNT(*) FROM Mention m LEFT JOIN MentionResolution r ON r.mention_id=m.id WHERE r.mention_id IS NULL').fetchone()[0],
                          coverage=f'Пилот: {len(texts)} текстов. Остальной корпус доступен как поиск совпадений имён.',
                          extraction='Чтение текстов ассистентом + словарный поиск; не исчерпывающее извлечение персонажей.'))
    (ROOT/'data/pilot_export.json').write_text(json.dumps(export,ensure_ascii=False,indent=2),encoding='utf-8')
    site=ROOT/'site/dist';site.mkdir(parents=True,exist_ok=True)
    (site/'data.js').write_text('window.ISKANDER_DATA='+json.dumps(export,ensure_ascii=False)+';\n',encoding='utf-8')
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    for e in db.execute('SELECT e.*,t.text AS original FROM Evidence e JOIN TextFragment t ON t.id=e.fragment_id'):
        assert e['original'][e['start_char']:e['end_char']]==e['quote'],e['id']
    db.execute('PRAGMA optimize')
    print(json.dumps(export['meta'],ensure_ascii=True),flush=True)
    db.close()


if __name__=='__main__':main()
