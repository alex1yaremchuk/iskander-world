"""Create source-anchored paragraph windows for the expanding pilot corpus."""
import json
import zipfile
import xml.etree.ElementTree as ET
from inventory import ROOT, local, text


def prepare():
    registry = json.loads((ROOT/'data/canonical_works.json').read_text(encoding='utf-8'))
    titles = [
        'Сандро из Чегема',
        'Дядя Сандро у себя дома',
        'Ленин и дядя Сандро',
        'Дядя Сандро и его любимец',
        'Чегемские сплетни',
        'Тали — чудо Чегема',
        'Рассказ мула старого Хабуга',
        'Умыкание, или Загадка эндурцев',
        'Дядя Сандро и раб Хазарат',
        'Дядя Сандро и конец козлотура',
        'Пиры Валтасара',
        'Кутеж трех князей в зеленом дворике',
        'История молельного дерева',
        'Ночь и день Чика',
        'Защита Чика',
        'Чик и Пушкин',
        'Чик знал, где зарыта собака',
        'Чик на охоте',
        'Подвиг Чика',
        'Чик идет на оплакивание',
        'Чик и лунатик',
        'Чик — играющий судья',
        'Страшная месть Чика',
        'Чик чтит обычаи',
        'Чик и белая курица',
    ]
    selected = []
    for i,title in enumerate(titles,1):
        work = next(dict(w) for w in registry if w['title']==title and 'source' in w)
        paragraphs=[]
        with zipfile.ZipFile(ROOT/'corpus'/work['source']) as book:
            for resource in work['resources']:
                body=ET.fromstring(book.read(resource)).find('.//{*}body')
                def walk(element, location):
                    if local(element)=='p':
                        value=text(element)
                        if value:
                            paragraphs.append({'key':f'p{i}_{len(paragraphs)+1:04}',
                                               'location':resource+'::'+location,
                                               'resource':resource,'text':value})
                        return
                    for index, child in enumerate(element):
                        walk(child,f'{location}/{local(child)}[{index}]')
                walk(body,'body')
        work['paragraphs']=paragraphs
        selected.append(work)
    (ROOT/'data/pilot_texts.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
    return selected


if __name__=='__main__':
    data=prepare()
    print('Prepared',len(data),'texts;',sum(len(w['paragraphs']) for w in data),'paragraphs')
