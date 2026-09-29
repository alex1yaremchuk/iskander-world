"""Conservative EPUB/FB2 corpus inventory; Python 3.11+, standard library only."""
import argparse
import hashlib
import json
import posixpath
import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import unquote, urldefrag
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def local(element):
    return element.tag.rsplit('}', 1)[-1] if isinstance(element.tag, str) else ''


def text(element):
    return ' '.join(''.join(element.itertext()).split()) if element is not None else ''


def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', value)).strip()


def title_key(value):
    return re.sub(r'[^\w]+', ' ', normalized(value).casefold()).strip()


def resolve(base, href):
    path, anchor = urldefrag(href)
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(path))), unquote(anchor)


def parse_fb2(raw):
    tree = ET.fromstring(raw)
    info = tree.find('.//{*}description/{*}title-info')
    metadata = {'title': text(info.find('{*}book-title')) if info is not None else '',
                'authors': [text(e) for e in info.findall('{*}author')] if info is not None else []}
    metadata['publication'] = {local(e): text(e) for e in tree.findall('.//{*}description/{*}publish-info/*')}
    toc, fragments = [], []

    def walk(node, path, parent=None):
        title = text(node.find('{*}title'))
        if local(node) == 'section':
            toc.append({'title': title, 'location': path, 'parent': parent,
                        'source_id': node.get('id'), 'kind': 'section_candidate'})
            parent = path
        # Each direct block is stored once; nested sections recurse independently.
        for index, child in enumerate(node):
            location = f'{path}/{local(child)}[{index}]'
            if local(child) == 'section':
                walk(child, location, parent)
            elif local(child) not in ('image', 'binary') and text(child):
                fragments.append({'location': location, 'text': text(child), 'section': parent})

    for i, body in enumerate(tree.findall('{*}body')):
        walk(body, f'body[{i}]')
    return metadata, toc, fragments


def parse_epub(path):
    with zipfile.ZipFile(path) as book:
        container = ET.fromstring(book.read('META-INF/container.xml'))
        package_path = container.find('.//{*}rootfile').get('full-path')
        package = ET.fromstring(book.read(package_path))
        metadata = {'title': text(package.find('.//{*}metadata/{*}title')),
                    'authors': [text(e) for e in package.findall('.//{*}metadata/{*}creator')]}
        metadata['publication'] = [{'field': local(e), 'value': text(e), 'attributes': e.attrib}
                                   for e in package.findall('{*}metadata/*') if local(e) in ('date', 'publisher', 'identifier')]
        manifest = {e.get('id'): e for e in package.findall('{*}manifest/{*}item')}
        toc, fragments = [], []
        nav = next((e for e in manifest.values() if 'nav' in e.get('properties', '').split()), None)
        if nav is not None:
            nav_path, _ = resolve(package_path, nav.get('href'))
            document = ET.fromstring(book.read(nav_path))
            for node in document.iter():
                if local(node) != 'nav' or 'toc' not in node.get('{http://www.idpf.org/2007/ops}type', '').split():
                    continue
                def walk_nav(element, parent=None):
                    current = parent
                    if local(element) == 'li':
                        link = element.find('{*}a')
                        if link is not None:
                            target, anchor = resolve(nav_path, link.get('href', ''))
                            current = target + ('#' + anchor if anchor else '')
                            toc.append({'title': text(link), 'location': current, 'parent': parent,
                                        'kind': 'toc_candidate'})
                    for child in element:
                        walk_nav(child, current)
                walk_nav(node)
        if not toc:
            spine = package.find('{*}spine')
            ncx = manifest.get(spine.get('toc')) if spine is not None else None
            if ncx is None:
                ncx = next((e for e in manifest.values() if e.get('media-type') == 'application/x-dtbncx+xml'), None)
            if ncx is not None:
                ncx_path, _ = resolve(package_path, ncx.get('href'))
                def walk_ncx(node, parent=None):
                    for point in node.findall('{*}navPoint'):
                        content = point.find('{*}content')
                        target, anchor = resolve(ncx_path, content.get('src', ''))
                        location = target + ('#' + anchor if anchor else '')
                        toc.append({'title': text(point.find('{*}navLabel')), 'location': location,
                                    'parent': parent, 'kind': 'toc_candidate'})
                        walk_ncx(point, location)
                walk_ncx(ET.fromstring(book.read(ncx_path)).find('{*}navMap'))
        for order, reference in enumerate(package.findall('{*}spine/{*}itemref')):
            item = manifest[reference.get('idref')]
            resource, _ = resolve(package_path, item.get('href'))
            document = ET.fromstring(book.read(resource))
            body = document.find('.//{*}body')
            if body is None:
                raise ValueError(f'No XHTML body: {resource}')
            # DOM text runs avoid overlapping parent/child text and preserve order.
            def walk(node, xpath):
                if local(node) in ('script', 'style'):
                    return
                if node.text and normalized(node.text):
                    fragments.append({'location': f'{resource}::{xpath}/text()',
                                      'text': normalized(node.text), 'section': resource, 'spine': order})
                for index, child in enumerate(node):
                    walk(child, f'{xpath}/{local(child)}[{index}]')
                    if child.tail and normalized(child.tail):
                        fragments.append({'location': f'{resource}::{xpath}/tail[{index}]',
                                          'text': normalized(child.tail), 'section': resource, 'spine': order})
            walk(body, 'body')
        return metadata, toc, fragments


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS Source(id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS SourceFile(path TEXT PRIMARY KEY, collection TEXT NOT NULL, source_id TEXT REFERENCES Source(id));
CREATE TABLE IF NOT EXISTS TocEntry(id TEXT PRIMARY KEY, source_id TEXT REFERENCES Source(id), ordinal INTEGER, title TEXT, title_key TEXT, location TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS TextFragment(id TEXT PRIMARY KEY, source_id TEXT REFERENCES Source(id), ordinal INTEGER, location TEXT, text TEXT, text_sha256 TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS Work(id TEXT PRIMARY KEY, canonical_title TEXT NOT NULL, review_note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS WorkSource(work_id TEXT REFERENCES Work(id), source_id TEXT REFERENCES Source(id), location TEXT NOT NULL, review_note TEXT NOT NULL, PRIMARY KEY(work_id, source_id, location));
CREATE INDEX IF NOT EXISTS fragment_source ON TextFragment(source_id);
CREATE INDEX IF NOT EXISTS toc_source ON TocEntry(source_id);
CREATE INDEX IF NOT EXISTS file_source ON SourceFile(source_id);
CREATE INDEX IF NOT EXISTS worksource_source ON WorkSource(source_id);
'''


def run(corpus, output):
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output / 'inventory.sqlite')
    db.executescript(SCHEMA)
    report = {'status': 'inventory_only_not_canonical_registry', 'sources': [], 'errors': [],
              'same_title_candidates': [], 'identical_files': [], 'unhandled_archives': []}
    titles, hashes = {}, {}
    for path in sorted(corpus.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(corpus).as_posix()
        if path.suffix.lower() == '.zip':
            report['unhandled_archives'].append(relative)
        if path.suffix.lower() not in ('.epub', '.fb2'):
            continue
        raw = path.read_bytes()
        sha = digest(raw)
        source_id = 'src_' + sha
        try:
            metadata, toc, fragments = parse_epub(path) if path.suffix.lower() == '.epub' else parse_fb2(raw)
            with db:
                db.execute('INSERT INTO Source VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET metadata_json=excluded.metadata_json', (source_id, sha, json.dumps(metadata, ensure_ascii=False)))
                db.execute('INSERT OR REPLACE INTO SourceFile VALUES (?,?,?)', (relative, relative.split('/')[0], source_id))
                for index, entry in enumerate(toc):
                    entry_id = 'toc_' + digest(f'{source_id}:{index}:{entry["location"]}')
                    db.execute('INSERT OR REPLACE INTO TocEntry VALUES (?,?,?,?,?,?,?)',
                               (entry_id, source_id, index, entry['title'], title_key(entry['title']), entry['location'], json.dumps(entry, ensure_ascii=False)))
                    if title_key(entry['title']):
                        titles.setdefault(title_key(entry['title']), []).append({'source': relative, **entry})
                for index, fragment in enumerate(fragments):
                    fragment_id = 'frag_' + digest(source_id + ':' + fragment['location'])
                    db.execute('INSERT INTO TextFragment VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ordinal=excluded.ordinal, location=excluded.location, text=excluded.text, text_sha256=excluded.text_sha256, raw_json=excluded.raw_json',
                               (fragment_id, source_id, index, fragment['location'], fragment['text'], digest(normalized(fragment['text'])), json.dumps(fragment, ensure_ascii=False)))
            hashes.setdefault(sha, []).append(relative)
            report['sources'].append({'path': relative, 'source_id': source_id, 'metadata': metadata,
                                      'toc_count': len(toc), 'fragment_count': len(fragments),
                                      'warnings': [] if toc else ['No table of contents extracted']})
        except Exception as error:
            report['errors'].append({'path': relative, 'error': str(error)})
    report['same_title_candidates'] = [{'title_key': key, 'occurrences': values, 'decision': 'needs_review'}
                                       for key, values in titles.items() if len(values) > 1]
    report['identical_files'] = [paths for paths in hashes.values() if len(paths) > 1]
    report['canonical_work_count'] = db.execute('SELECT COUNT(*) FROM Work').fetchone()[0]
    db.close()
    (output / 'inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: len(report[key]) for key in ('sources', 'errors', 'same_title_candidates', 'identical_files')}, ensure_ascii=False))
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=ROOT / 'corpus')
    parser.add_argument('--output', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    if not args.corpus.is_dir():
        parser.error('Corpus directory does not exist')
    raise SystemExit(run(args.corpus, args.output))
