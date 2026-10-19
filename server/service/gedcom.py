"""GEDCOM 基本人物/家庭互通；_FTS_* 扩展保留本系统中文字段与逐亲子关系类型。"""
import json
from collections import defaultdict


def _number(value, default=1):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def dumps(data):
    persons = {p['id']: p for p in data.get('persons', [])}
    sex = lambda p: 'M' if p.get('type') in (1, 4, 5) else 'F'
    families, parents, types, orders = [], defaultdict(set), {}, {}
    for pc in data.get('parentchild', []):
        parent, child = pc.get('parent_id'), pc.get('child_id')
        if parent in persons and child in persons and parent != child:
            parents[child].add(parent)
            types[parent, child] = pc.get('type', 1)
            orders[parent, child] = pc.get('child_order')
    emitted = set()
    for m in data.get('marriages', []):
        pair = [m.get('spouse1_id'), m.get('spouse2_id')]
        if any(p not in persons for p in pair) or len(set(pair)) != 2:
            continue
        kids = [c for c, pp in parents.items() if pp == set(pair) and c not in emitted]
        families.append((pair, kids, m))
        emitted.update(kids)
    for child, pp in parents.items():
        if child not in emitted:
            for parent in sorted(pp):
                families.append(([parent], [child], {}))

    lines = ['0 HEAD', '1 SOUR FamilyTreeSystem', '1 GEDC', '2 VERS 5.5.1',
             '2 FORM LINEAGE-LINKED', '1 CHAR UTF-8']

    def text(level, tag, value):
        if value is None or value == '':
            return
        # CONT 保留换行，CONC 将长行拆分，且绝不把用户文本解释为 GEDCOM 标签。
        paragraphs = str(value).replace('\r\n', '\n').replace('\r', '\n').split('\n')
        for i, paragraph in enumerate(paragraphs):
            chunks = [paragraph[j:j + 60] for j in range(0, len(paragraph), 60)] or ['']
            for j, chunk in enumerate(chunks):
                tag2 = tag if i == j == 0 else ('CONT' if j == 0 else 'CONC')
                depth = level if i == j == 0 else level + 1
                lines.append(f'{depth} {tag2} {chunk}')

    for pid, p in persons.items():
        lines.append(f'0 @P{pid}@ INDI')
        text(1, 'NAME', p.get('name'))
        lines.append(f'1 SEX {sex(p)}')
        for tag, date, place in [('BIRT', 'birth_date', 'birth_place'), ('DEAT', 'death_date', None),
                                 ('BURI', None, 'bury_address')]:
            if (date and p.get(date)) or (place and p.get(place)):
                lines.append(f'1 {tag}')
                if date:
                    text(2, 'DATE', p.get(date))
                if place:
                    text(2, 'PLAC', p.get(place))
        text(1, 'NOTE', p.get('record'))
        for field in ('courtesy_name', 'art_name', 'notes', 'generation', 'type', 'is_private', 'address', 'phone', 'company', 'position'):
            text(1, '_FTS_' + field.upper(), p.get(field))
        for i, (pair, kids, _) in enumerate(families, 1):
            if pid in pair:
                lines.append(f'1 FAMS @F{i}@')
            if pid in kids:
                lines.append(f'1 FAMC @F{i}@')
                relation_types = [types.get((parent, pid), 1) for parent in pair]
                if all(t not in (1, 5) for t in relation_types):
                    lines.append('2 PEDI adopted')

    for i, (pair, kids, m) in enumerate(families, 1):
        lines.append(f'0 @F{i}@ FAM')
        ordered = sorted(pair, key=lambda p: (sex(persons[p]) != 'M', p))
        for j, pid in enumerate(ordered):
            tag = ('HUSB' if sex(persons[pid]) == 'M' else 'WIFE') if len(pair) == 1 else ('HUSB' if j == 0 else 'WIFE')
            lines.append(f'1 {tag} @P{pid}@')
        for child in kids:
            lines.append(f'1 CHIL @P{child}@')
            text(2, '_FTS_PC', json.dumps({f'P{p}': types.get((p, child), 1) for p in pair}))
            text(2, '_FTS_CHILD_ORDER', json.dumps({f'P{p}': orders.get((p, child)) for p in pair}))
        for tag, date, place in [('MARR', 'marriage_date', 'marriage_place'), ('DIV', 'divorce_date', None)]:
            if m.get(date) or (place and m.get(place)):
                lines.append(f'1 {tag}')
                text(2, 'DATE', m.get(date))
                if place:
                    text(2, 'PLAC', m.get(place))
        text(1, '_FTS_ORDER', m.get('marriage_order'))
        text(1, '_FTS_SPOUSE1', f'P{m["spouse1_id"]}' if m.get('spouse1_id') else None)
        text(1, 'NOTE', m.get('description'))
        text(1, '_FTS_NOTES', m.get('notes'))
    lines.append('0 TRLR')
    return '\n'.join(lines).encode('utf-8')


def loads(text):
    """按层级解析；支持 CONT/CONC，不把下一个事件的 DATE 错配给出生事件。"""
    roots, stack = [], []
    for raw in text.lstrip('\ufeff').splitlines():
        parts = raw.strip().split(' ', 2)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        level, tag, value = int(parts[0]), parts[1], parts[2] if len(parts) == 3 else ''
        xref = None
        if level == 0 and tag.startswith('@'):
            xref, tag, value = tag.strip('@'), value, ''
        if tag in ('CONT', 'CONC') and stack:
            while stack and stack[-1]['level'] >= level:
                stack.pop()
            if stack:
                stack[-1]['value'] += ('\n' if tag == 'CONT' else '') + value
            continue
        node = {'tag': tag, 'value': value, 'xref': xref, 'level': level, 'children': []}
        while stack and stack[-1]['level'] >= level:
            stack.pop()
        (stack[-1]['children'] if stack else roots).append(node)
        stack.append(node)

    def child(node, tag):
        return next((n for n in node['children'] if n['tag'] == tag), None)

    def value(node, tag):
        found = child(node, tag) if node else None
        return found['value'] if found else None

    persons, families = [], {}
    for node in roots:
        if node['tag'] == 'INDI':
            p = {'id': node['xref'], 'name': (value(node, 'NAME') or '').replace('/', '').strip(),
                 'type': 1 if value(node, 'SEX') == 'M' else 2,
                 'record': value(node, 'NOTE'), 'birth_date': None, 'death_date': None, '_pedi': {}}
            for tag, date, place in [('BIRT', 'birth_date', 'birth_place'), ('DEAT', 'death_date', None),
                                     ('BURI', None, 'bury_address')]:
                event = child(node, tag)
                if date:
                    p[date] = value(event, 'DATE')
                if place:
                    p[place] = value(event, 'PLAC')
            for field in ('courtesy_name', 'art_name', 'notes', 'generation', 'type', 'is_private', 'address', 'phone', 'company', 'position'):
                v = value(node, '_FTS_' + field.upper())
                if v is not None:
                    p[field] = _number(v) if field in ('generation', 'type', 'is_private') else v
            for family in node['children']:
                if family['tag'] == 'FAMC':
                    p['_pedi'][family['value'].strip('@')] = value(family, 'PEDI')
            persons.append(p)
        elif node['tag'] == 'FAM':
            fam = {'members': [], 'types': {}, 'orders': {}, 'marriage': {
                'marriage_date': value(child(node, 'MARR'), 'DATE'),
                'marriage_place': value(child(node, 'MARR'), 'PLAC'),
                'divorce_date': value(child(node, 'DIV'), 'DATE'),
                'marriage_order': _number(value(node, '_FTS_ORDER')),
                'order_explicit': value(node, '_FTS_ORDER') is not None,
                'spouse1_source': value(node, '_FTS_SPOUSE1'),
                'description': value(node, 'NOTE'), 'notes': value(node, '_FTS_NOTES')}}
            for n in node['children']:
                if n['tag'] in ('HUSB', 'WIFE', 'CHIL'):
                    pid = n['value'].strip('@')
                    fam['members'].append(({'HUSB': 'husb', 'WIFE': 'wife', 'CHIL': 'chil'}[n['tag']], pid))
                    if n['tag'] == 'CHIL':
                        try:
                            types = json.loads(value(n, '_FTS_PC') or '{}')
                            if isinstance(types, dict):
                                fam['types'][pid] = types
                        except ValueError:
                            pass
                        try:
                            orders = json.loads(value(n, '_FTS_CHILD_ORDER') or '{}')
                            if isinstance(orders, dict):
                                fam['orders'][pid] = orders
                        except ValueError:
                            pass
            families[node['xref']] = fam
    return persons, families
