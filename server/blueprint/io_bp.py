"""数据交换：导出 JSON / CSV / GEDCOM，导入 JSON / GEDCOM / ZIP

导入采用「旧 ID → 新 ID 重映射」：源数据里的 id 一律丢弃，关系表按映射表改写后再入库，
因此「导出 → 导入」可以闭环使用（同一份数据既可导入新谱，也可重复导入）。
ZIP 包内的 resources/ 原件会解出并存回上传目录。
"""
import csv
import io
import json
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from server.common import ApiError, now_str
from server.db.conn import execute, query, query_one, transaction
from server.service import audit, settings
from server.service.permission import current_user, require_family, require_login

bp = Blueprint('io', __name__, url_prefix='/api/families')

MODULES = ['family', 'branches', 'persons', 'marriages', 'parentchild', 'events',
           'eventpersons', 'resources', 'resource_relations']


def _collect(family_id, modules):
    data = {}
    if 'family' in modules:
        data['family'] = dict(query_one('SELECT * FROM family WHERE id=?', (family_id,)))
    for key, table in (('branches', 'branch'), ('persons', 'person'), ('marriages', 'marriage'),
                       ('parentchild', 'parentchild'), ('events', 'event'),
                       ('eventpersons', 'eventperson'), ('resources', 'resource'),
                       ('resource_relations', 'resource_relation')):
        if key in modules:
            data[key] = [dict(r) for r in query(f'SELECT * FROM {table} WHERE family_id=?'
                                                f' ORDER BY id', (family_id,))]
    data['meta'] = {'exported_at': now_str(), 'version': '1.0',
                    'source': '家谱管理系统 Web 版'}
    return data


def _csv_bytes(rows):
    buf = io.StringIO()
    if not rows:
        return b''
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode('utf-8-sig')


def _gedcom(data):
    lines = ['0 HEAD', '1 CHAR UTF-8', '1 SOUR 家谱管理系统']
    for p in data.get('persons', []):
        lines.append(f"0 @P{p['id']}@ INDI")
        lines.append(f"1 NAME {p.get('name') or ''}")
        sex = 'M' if p.get('type') in (1, 4, 5) else 'F'
        lines.append(f'1 SEX {sex}')
        if p.get('birth_date'):
            lines.append('1 BIRT')
            lines.append(f"2 DATE {p['birth_date']}")
        if p.get('death_date'):
            lines.append('1 DEAT')
            lines.append(f"2 DATE {p['death_date']}")
    for i, m in enumerate(data.get('marriages', []), 1):
        lines.append(f'0 @F{i}@ FAM')
        lines.append(f"1 HUSB @P{m['spouse1_id']}@")
        lines.append(f"1 WIFE @P{m['spouse2_id']}@")
        for c in [x for x in data.get('parentchild', [])
                  if x['parent_id'] in (m['spouse1_id'], m['spouse2_id'])]:
            lines.append(f"1 CHIL @P{c['child_id']}@")
    lines.append('0 TRLR')
    return '\n'.join(lines).encode('utf-8')


@bp.get('/<int:family_id>/export')
@require_login
@require_family('member')
def export_data(family_id):
    fmt = (request.args.get('format') or 'json').lower()
    include_res = request.args.get('include_resources') in ('1', 'true', 'True')
    from flask import g
    privileged = getattr(g, 'family_role', None) == 'admin' or bool(current_user()['is_superuser'])
    if include_res and not privileged \
            and not settings.get_bool('export.member_include_resources', False):
        include_res = False
    modules = request.args.get('modules')
    mods = modules.split(',') if modules else MODULES

    data = _collect(family_id, mods)
    fam = data.get('family') or query_one('SELECT * FROM family WHERE id=?', (family_id,))
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    base = f'{fam["name"]}_export_{stamp}'

    if fmt == 'json' and not include_res:
        buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
        return send_file(buf, as_attachment=True, download_name=f'{base}.json',
                         mimetype='application/json')

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        if fmt == 'json':
            z.writestr('data.json', json.dumps(data, ensure_ascii=False, indent=2))
        elif fmt == 'csv':
            for key in ('persons', 'marriages', 'parentchild', 'events', 'eventpersons',
                        'branches', 'resources'):
                if key in data:
                    z.writestr(f'{key}.csv', _csv_bytes(data[key]))
            z.writestr('family.csv', _csv_bytes([data['family']] if 'family' in data else []))
        elif fmt == 'gedcom':
            z.writestr(f'{base}.ged', _gedcom(data))
        else:
            raise ApiError('不支持的导出格式')
        if include_res:
            root = Path(current_app.config['UPLOAD_DIR'])
            for r in data.get('resources', []):
                p = root / r['storage_path']
                if p.exists():
                    z.write(p, f'resources/{r["fid"]}_{r["name"]}{p.suffix}')
    mem.seek(0)
    audit.log(current_user()['id'], family_id, 'export', 'family', family_id, fmt)
    return send_file(mem, as_attachment=True, download_name=f'{base}.zip',
                     mimetype='application/zip')


# ---------------- 导入 ----------------
def _parse_gedcom(text):
    persons, fam_children = [], {}
    cur = None
    cur_fam = None
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = line.split(' ', 2)
        level = parts[0]
        tag = parts[1] if len(parts) > 1 else ''
        val = parts[2] if len(parts) > 2 else ''
        if level == '0' and val == 'INDI':
            cur = {'id': tag.strip('@'), 'name': '', 'type': 1, 'birth_date': None,
                   'death_date': None}
            cur_fam = None
            persons.append(cur)
        elif level == '0' and val == 'FAM':
            cur_fam = tag.strip('@')
            cur = None
            fam_children[cur_fam] = []
        elif cur is not None:
            if level == '1' and tag == 'NAME':
                cur['name'] = val.replace('/', '').strip()
            elif level == '1' and tag == 'SEX':
                cur['type'] = 1 if val.strip().upper() == 'M' else 2
            elif level == '1' and tag in ('BIRT', 'DEAT'):
                cur['_pending'] = 'birth_date' if tag == 'BIRT' else 'death_date'
            elif level == '2' and tag == 'DATE' and cur.get('_pending'):
                cur[cur.pop('_pending')] = val
        elif cur_fam is not None:
            if level == '1' and tag == 'HUSB':
                fam_children.setdefault(cur_fam, []).append(('husb', val.strip('@')))
            elif level == '1' and tag == 'WIFE':
                fam_children.setdefault(cur_fam, []).append(('wife', val.strip('@')))
            elif level == '1' and tag == 'CHIL':
                fam_children.setdefault(cur_fam, []).append(('chil', val.strip('@')))
    return persons, fam_children


def _gedcom_generations(persons, fams):
    """按家谱结构推算世代：无父母者=1 世，子女=父母最大世代+1"""
    parents_of = defaultdict(set)
    children_of = defaultdict(set)
    for members in fams.values():
        husb = next((v for t, v in members if t == 'husb'), None)
        wife = next((v for t, v in members if t == 'wife'), None)
        for tag, child in members:
            if tag != 'chil' or not child:
                continue
            for parent in (husb, wife):
                if parent:
                    parents_of[child].add(parent)
                    children_of[parent].add(child)
    gen = {}
    queue = deque()
    for p in persons:
        if p['id'] not in parents_of:
            gen[p['id']] = 1
            queue.append(p['id'])
    guard = len(persons) * 2 + 10
    while queue and guard > 0:
        guard -= 1
        cur = queue.popleft()
        for child in children_of.get(cur, ()):
            candidate = gen[cur] + 1
            if gen.get(child, 0) < candidate:
                gen[child] = candidate
                queue.append(child)
    # 环路中的人物无法定层，兜底为 1 世
    return {p['id']: gen.get(p['id'], 1) for p in persons}


def _clamp(value, low, high, default):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(num, low), high)


@bp.post('/<int:family_id>/import')
@require_login
@require_family('admin')
def import_data(family_id):
    file = request.files.get('file')
    if file is None:
        raise ApiError('请选择要导入的文件')
    strategy = (request.form.get('strategy')
                or settings.get_str('storage.default_strategy', 'append')).lower()
    if strategy not in ('append', 'overwrite'):
        raise ApiError('导入策略取值不合法')
    name = (file.filename or '').lower()
    ts = now_str()
    stats = {}

    with transaction():
        if strategy == 'overwrite':
            for table in ('parentchild', 'marriage', 'eventperson', 'event', 'resource_relation',
                          'resource', 'person', 'branch'):
                execute(f'DELETE FROM {table} WHERE family_id=?', (family_id,))

        if name.endswith('.zip'):
            import zipfile as zf
            mem = io.BytesIO(file.read())
            with zf.ZipFile(mem) as z:
                json_name = next((n for n in z.namelist() if n.endswith('.json')), None)
                ged_name = next((n for n in z.namelist() if n.lower().endswith('.ged')), None)
                if json_name:
                    data = json.loads(z.read(json_name).decode('utf-8'))
                    stats = _apply_json(family_id, data, ts, _zip_resources(z))
                elif ged_name:
                    stats = _apply_gedcom(family_id, z.read(ged_name).decode('utf-8', 'ignore'), ts)
                else:
                    raise ApiError('压缩包中未找到 data.json 或 .ged 文件')
        elif name.endswith('.json'):
            stats = _apply_json(family_id, json.loads(file.read().decode('utf-8')), ts)
        elif name.endswith('.ged'):
            stats = _apply_gedcom(family_id, file.read().decode('utf-8', 'ignore'), ts)
        else:
            raise ApiError('仅支持 JSON / GEDCOM / ZIP 数据包')

    audit.log(current_user()['id'], family_id, 'import', 'family', family_id,
              f'{file.filename}（{", ".join(f"{k}={v}" for k, v in stats.items())}）')
    total = {t: query_one(f'SELECT COUNT(*) c FROM {t} WHERE family_id=?', (family_id,))['c']
             for t in ('person', 'marriage', 'parentchild', 'event', 'resource', 'branch')}
    total['imported'] = stats
    return jsonify({'code': 0, 'msg': '导入完成', 'data': total})


def _zip_resources(z):
    """解出 ZIP 内的 resources/ 原件：{源 fid: (文件名, 字节)}"""
    out = {}
    for info in z.infolist():
        if not info.filename.startswith('resources/') or info.is_dir():
            continue
        base = Path(info.filename).name
        if '_' not in base:
            continue
        fid = base.split('_', 1)[0]
        out[fid] = (base, z.read(info))
    return out


def _apply_json(family_id, data, ts, resource_files=None):
    """按旧 ID → 新 ID 重映射写入，返回各表实际入库行数"""
    resource_files = resource_files or {}
    maps = {k: {} for k in ('branch', 'person', 'event', 'resource', 'marriage', 'parentchild')}
    stats = defaultdict(int)

    def insert(table, cols, vals):
        cur = execute(f'INSERT INTO {table} ({",".join(cols)})'
                      f' VALUES ({",".join(["?"] * len(cols))})', vals)
        return cur

    fam = query_one('SELECT slug FROM family WHERE id=?', (family_id,))
    slug = fam['slug'] if fam else f'f{family_id}'

    # 1) 分支：先建（父子关系第二遍补，避免顺序依赖）
    pending_parents = []
    for b in data.get('branches') or []:
        old = b.get('id')
        name = (b.get('name') or '').strip() or '未命名分支'
        bid = insert('branch',
                     ['family_id', 'parent_id', 'name', 'origin_place', 'establish_time',
                      'description', 'hall_name', 'generation_chars', 'direction',
                      'created_at', 'updated_at'],
                     [family_id, None, name, b.get('origin_place'), b.get('establish_time'),
                      b.get('description'), b.get('hall_name'), b.get('generation_chars'),
                      b.get('direction'), ts, ts])
        maps['branch'][old] = bid
        pending_parents.append((bid, b.get('parent_id')))
        stats['branch'] += 1
    for bid, old_parent in pending_parents:
        new_parent = maps['branch'].get(old_parent)
        if new_parent and new_parent != bid:
            execute('UPDATE branch SET parent_id=? WHERE id=?', (new_parent, bid))

    # 2) 人物
    for p in data.get('persons') or []:
        old = p.get('id')
        pid = insert('person',
                     ['family_id', 'generation', 'name', 'courtesy_name', 'art_name', 'type',
                      'birth_date', 'birth_place', 'death_date', 'bury_address', 'record',
                      'notes', 'branch_id', 'is_private', 'created_at', 'updated_at'],
                     [family_id, _clamp(p.get('generation'), 1, 999, 1),
                      (p.get('name') or '').strip() or '未命名',
                      p.get('courtesy_name'), p.get('art_name'),
                      _clamp(p.get('type'), 1, 6, 1), p.get('birth_date'), p.get('birth_place'),
                      p.get('death_date'), p.get('bury_address'), p.get('record'), p.get('notes'),
                      maps['branch'].get(p.get('branch_id')),
                      1 if p.get('is_private') else 0, ts, ts])
        maps['person'][old] = pid
        stats['person'] += 1

    # 3) 事件
    for e in data.get('events') or []:
        old = e.get('id')
        eid = insert('event',
                     ['family_id', 'name', 'time', 'place', 'type', 'description', 'notes',
                      'branch_id', 'created_at', 'updated_at'],
                     [family_id, (e.get('name') or '').strip() or '未命名事件',
                      e.get('time') or '', e.get('place'),
                      _clamp(e.get('type'), 1, 2, 1), e.get('description'), e.get('notes'),
                      maps['branch'].get(e.get('branch_id')), ts, ts])
        maps['event'][old] = eid
        stats['event'] += 1

    # 4) 婚姻（配偶必须都在本次导入中，否则跳过并计入 skipped）
    skipped = 0
    for m in data.get('marriages') or []:
        s1 = maps['person'].get(m.get('spouse1_id'))
        s2 = maps['person'].get(m.get('spouse2_id'))
        if not s1 or not s2 or s1 == s2:
            skipped += 1
            continue
        mid = insert('marriage',
                     ['family_id', 'spouse1_id', 'spouse2_id', 'marriage_order', 'marriage_date',
                      'divorce_date', 'marriage_place', 'description', 'notes',
                      'created_at', 'updated_at'],
                     [family_id, s1, s2, _clamp(m.get('marriage_order'), 1, 99, 1),
                      m.get('marriage_date'), m.get('divorce_date'), m.get('marriage_place'),
                      m.get('description'), m.get('notes'), ts, ts])
        maps['marriage'][m.get('id')] = mid
        stats['marriage'] += 1

    # 5) 亲子
    for pc in data.get('parentchild') or []:
        parent = maps['person'].get(pc.get('parent_id'))
        child = maps['person'].get(pc.get('child_id'))
        if not parent or not child or parent == child:
            skipped += 1
            continue
        pcid = insert('parentchild',
                      ['family_id', 'parent_id', 'child_id', 'type', 'description', 'notes',
                       'created_at', 'updated_at'],
                      [family_id, parent, child, _clamp(pc.get('type'), 1, 7, 1),
                       pc.get('description'), pc.get('notes'), ts, ts])
        maps['parentchild'][pc.get('id')] = pcid
        stats['parentchild'] += 1

    # 6) 事件参与人
    for ep in data.get('eventpersons') or []:
        eid = maps['event'].get(ep.get('event_id'))
        pid = maps['person'].get(ep.get('person_id'))
        if not eid or not pid:
            skipped += 1
            continue
        if query_one('SELECT id FROM eventperson WHERE event_id=? AND person_id=?', (eid, pid)):
            continue
        insert('eventperson',
               ['family_id', 'event_id', 'person_id', 'role', 'description', 'notes',
                'created_at', 'updated_at'],
               [family_id, eid, pid, ep.get('role'), ep.get('description'), ep.get('notes'),
                ts, ts])
        stats['eventperson'] += 1

    # 7) 文献资源：重新生成 fid，ZIP 内原件写回上传目录
    upload_root = Path(current_app.config['UPLOAD_DIR'])
    target_dir = upload_root / slug
    for r in data.get('resources') or []:
        old = r.get('id')
        old_fid = r.get('fid')
        new_fid = uuid.uuid4().hex
        name = (r.get('name') or '').strip() or '未命名文献'
        stored = None
        payload = resource_files.get(old_fid)
        if payload:
            fname, blob = payload
            safe = secure_filename(fname) or f'{new_fid}.bin'
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / f'{new_fid}_{safe}'
            dest.write_bytes(blob)
            stored = f'{slug}/{dest.name}'
            file_size = len(blob)
        else:
            stored = r.get('storage_path') or ''
            file_size = r.get('file_size')
        rid = insert('resource',
                     ['family_id', 'name', 'fid', 'type', 'storage_path', 'file_size',
                      'mime_type', 'description', 'notes', 'created_at', 'updated_at'],
                     [family_id, name, new_fid, _clamp(r.get('type'), 1, 7, 1), stored,
                      file_size, r.get('mime_type'), r.get('description'), r.get('notes'),
                      ts, ts])
        maps['resource'][old] = rid
        stats['resource'] += 1

    # 8) 资源关联
    for rel in data.get('resource_relations') or []:
        rid = maps['resource'].get(rel.get('resource_id'))
        etype = rel.get('entity_type')
        eid = maps.get(etype, {}).get(rel.get('entity_id')) if etype else None
        if not rid or not eid:
            skipped += 1
            continue
        if query_one('SELECT id FROM resource_relation WHERE resource_id=? AND entity_type=?'
                     ' AND entity_id=?', (rid, etype, eid)):
            continue
        insert('resource_relation',
               ['family_id', 'resource_id', 'entity_type', 'entity_id', 'notes',
                'created_at', 'updated_at'],
               [family_id, rid, etype, eid, rel.get('notes'), ts, ts])
        stats['resource_relation'] += 1

    stats['skipped'] = skipped
    return dict(stats)


def _apply_gedcom(family_id, text, ts):
    persons, fams = _parse_gedcom(text)
    gens = _gedcom_generations(persons, fams)
    idmap = {}
    stats = defaultdict(int)
    for p in persons:
        pid = execute(
            'INSERT INTO person (family_id, generation, name, type, birth_date, death_date,'
            ' created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)',
            (family_id, gens.get(p['id'], 1), (p['name'] or '').strip() or '未命名',
             _clamp(p['type'], 1, 6, 1), p.get('birth_date'), p.get('death_date'), ts, ts))
        idmap[p['id']] = pid
        stats['person'] += 1
    for members in fams.values():
        husb = next((v for t, v in members if t == 'husb'), None)
        wife = next((v for t, v in members if t == 'wife'), None)
        if husb and wife and husb in idmap and wife in idmap and idmap[husb] != idmap[wife]:
            execute('INSERT INTO marriage (family_id, spouse1_id, spouse2_id, marriage_order,'
                    ' created_at, updated_at) VALUES (?,?,?,1,?,?)',
                    (family_id, idmap[husb], idmap[wife], ts, ts))
            stats['marriage'] += 1
        for t, v in members:
            if t == 'chil' and v in idmap:
                for parent in (husb, wife):
                    if parent and parent in idmap and idmap[parent] != idmap[v]:
                        execute('INSERT INTO parentchild (family_id, parent_id, child_id, type,'
                                ' created_at, updated_at) VALUES (?,?,?,1,?,?)',
                                (family_id, idmap[parent], idmap[v], ts, ts))
                        stats['parentchild'] += 1
    return dict(stats)
