"""世系树数据装配"""
from flask import Blueprint, jsonify, request

from server.db.conn import query
from server.service import privacy
from server.service.permission import require_family, require_login

bp = Blueprint('pedigree', __name__, url_prefix='/api/families')


@bp.get('/<int:family_id>/pedigree')
@require_login
@require_family('member')
def pedigree(family_id):
    persons = query('SELECT id, generation, name, courtesy_name, type, birth_date, death_date,'
                    ' branch_id FROM person WHERE family_id=? ORDER BY generation, id', (family_id,))
    pc = query('SELECT id, parent_id, child_id, type, child_order FROM parentchild WHERE family_id=? ORDER BY id', (family_id,))
    marriages = query('SELECT id, spouse1_id, spouse2_id, marriage_order FROM marriage'
                      ' WHERE family_id=? ORDER BY spouse1_id, marriage_order, id', (family_id,))

    parents = {}
    children = {}
    for r in pc:
        children.setdefault(r['parent_id'], []).append({'id': r['child_id'], 'type': r['type']})
        parents.setdefault(r['child_id'], []).append(r['parent_id'])

    spouses = {}
    for m in marriages:
        spouses.setdefault(m['spouse1_id'], []).append(m['spouse2_id'])
        spouses.setdefault(m['spouse2_id'], []).append(m['spouse1_id'])

    masked_ids = privacy.visible_person_ids(family_id)
    nodes = []
    for p in persons:
        nodes.append({
            'id': p['id'],
            'name': p['name'],
            'courtesy_name': p['courtesy_name'],
            'generation': p['generation'],
            'type': p['type'],
            'birth_date': None if p['id'] in masked_ids else p['birth_date'],
            'death_date': p['death_date'],
            'branch_id': p['branch_id'],
            'masked': p['id'] in masked_ids,
            'parents': parents.get(p['id'], []),
            'children': [c['id'] for c in children.get(p['id'], [])],
            'spouses': sorted(set(spouses.get(p['id'], []))),
        })

    root = request.args.get('root', type=int)
    if not root:
        no_parent = [n for n in nodes if not n['parents']]
        if no_parent:
            root = min(no_parent, key=lambda n: (n['generation'], n['id']))['id']
        elif nodes:
            root = min(nodes, key=lambda n: (n['generation'], n['id']))['id']
        else:
            root = None

    return jsonify({'code': 0, 'msg': 'ok', 'data': {
        'nodes': nodes,
        'root': root,
        'total': len(nodes),
        'marriages': [dict(m) for m in marriages],
        'parentchild': [dict(r) for r in pc],
    }})
