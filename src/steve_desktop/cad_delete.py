"""Delete saved documents and component files.

Parts and designs move to the Trash, and only a person can purge them.
A component file is removed by saving a new revision of its design.
"""
import ast
import copy
import shutil
from pathlib import Path

from fastapi import HTTPException


def document_references(server, identifier):
    designs = [{'id': doc['id'], 'name': doc['name'], 'trashed': bool(doc.get('deleted_at')), 'branches': []}
               for doc in server.state['documents'].values()
               if any(ref.get('document_id') == identifier for ref in doc.get('links', {}).values())]
    count = len(designs)
    return {'designs': designs, 'studies': [], 'programs': [], 'count': count,
            'used_by': f'Used by {count} designs' if count else ''}


def trash_documents(server, ids):
    from steve_desktop.cad_server import now
    moved, skipped = [], []
    with server.lock:
        for identifier in ids:
            doc = server.state['documents'].get(identifier)
            if not doc or doc.get('deleted_at'):
                skipped.append({'id': identifier, 'reason': 'Document not found or already in Trash.'})
                continue
            doc.update(deleted_at=now(), deleted_by='Local')
            moved.append({'document': copy.deepcopy(doc), 'used_by': document_references(server, identifier)['used_by']})
        server.save()
    return {'moved': moved, 'skipped': skipped}


def restore_documents(server, ids):
    restored, skipped = [], []
    with server.lock:
        for identifier in ids:
            doc = server.state['documents'].get(identifier)
            if not doc or not doc.get('deleted_at'):
                skipped.append({'id': identifier, 'reason': 'Document is not in Trash.'})
                continue
            doc.pop('deleted_at', None)
            doc.pop('deleted_by', None)
            restored.append(copy.deepcopy(doc))
        server.save()
    return {'restored': restored, 'skipped': skipped}


def _live_linkers(server, identifier, removing):
    return [doc for doc in server.state['documents'].values()
            if doc['id'] != identifier and doc['id'] not in removing and not doc.get('deleted_at')
            and any(ref.get('document_id') == identifier for ref in doc.get('links', {}).values())]


def purge_documents(server, ids):
    """Permanently remove trashed documents. A live design that still links one keeps it in the Trash."""
    purged, skipped = [], []
    with server.lock:
        removing = set(ids)
        for identifier in ids:
            doc = server.state['documents'].get(identifier)
            if not doc or not doc.get('deleted_at'):
                skipped.append({'id': identifier, 'name': doc.get('name') if doc else None,
                                'reason': 'Document is not in Trash.'})
                continue
            users = _live_linkers(server, identifier, removing)
            if users:
                skipped.append({
                    'id': identifier, 'name': doc['name'],
                    'reason': f"Used by {len(users)} designs",
                    'references': [{'document_id': user['id'], 'name': user['name'], 'path': None, 'line': None,
                                    'detail': f"{user['name']} links this document"} for user in users],
                })
                continue
            server.state.get('history', {}).pop(identifier, None)
            del server.state['documents'][identifier]
            folder = server.folder / 'documents' / identifier
            if folder.is_dir() and not folder.is_symlink():
                shutil.rmtree(folder)
            purged.append({'id': identifier, 'name': doc['name']})
        server.save()
    return {'purged': purged, 'skipped': skipped}


def empty_trash(server):
    with server.lock:
        ids = [doc['id'] for doc in server.state['documents'].values() if doc.get('deleted_at')]
    return purge_documents(server, ids)


def _component_path(path):
    if not isinstance(path, str) or not path.startswith('components/') or not path.endswith('.py'):
        return False
    parts = Path(path).parts
    return '..' not in parts and ':' not in path and '\\' not in path and not Path(path).is_absolute() and len(parts) >= 2


def _module_names(path):
    relative = path[len('components/'):-3]
    names = {f'components.{relative.replace("/", ".")}'}
    if '/' not in relative:
        names.add('components.' + relative)
    return names, {relative, relative.split('/')[-1], relative.replace('/', '.')}


def _drop_lines(source, spans):
    if not spans:
        return source
    drop = set()
    for start, end in spans:
        drop.update(range(start, (end or start) + 1))
    kept = [line for number, line in enumerate(source.splitlines(), 1) if number not in drop]
    text = '\n'.join(kept)
    if source.endswith('\n'):
        text += '\n'
    return text


def _span(node):
    return node.lineno, getattr(node, 'end_lineno', None) or node.lineno


def _imports_removed(node, modules):
    if isinstance(node, ast.ImportFrom) and node.module in modules:
        return True
    if isinstance(node, ast.ImportFrom) and node.module == 'components':
        stems = {module.split('.')[-1] for module in modules}
        return any(alias.name in stems for alias in node.names)
    if isinstance(node, ast.Import):
        return any(alias.name in modules for alias in node.names)
    return False


def _bound_names(tree, modules):
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in modules:
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module == 'components':
            stems = {module.split('.')[-1] for module in modules}
            names.update(alias.asname or alias.name for alias in node.names if alias.name in stems)
    return {name for name in names if name.isidentifier()}


def _mentions(node, names):
    return any(isinstance(child, ast.Name) and child.id in names for child in ast.walk(node))


def _is_placement(statement, names):
    if not names or not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call) or not statement.value.args:
        return False
    call = statement.value
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return False
    if func.value.id == 'design' and func.attr in ('add', 'pattern'):
        return _mentions(call.args[0], names)
    return func.value.id == 'result' and func.attr == 'add' and _mentions(call.args[0], names)


def _line_text(source, line):
    rows = source.splitlines()
    if not line or line < 1 or line > len(rows):
        return ''
    return rows[line - 1].strip()


def _reference(document_id, name, path, line, detail):
    return {'document_id': document_id, 'name': name, 'path': path, 'line': line, 'detail': detail}


def _scan_main(document_id, name, source, modules):
    tree = ast.parse(source)
    bound = _bound_names(tree, modules)
    bound.update(module.split('.')[-1] for module in modules if module.split('.')[-1].isidentifier())
    spans, covered = [], set()
    for statement in tree.body:
        if _imports_removed(statement, modules) or _is_placement(statement, bound):
            start, end = _span(statement)
            spans.append((start, end))
            covered.update(range(start, end + 1))
    references = []
    for node in ast.walk(tree):
        line = getattr(node, 'lineno', None)
        if line in covered:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in bound:
            references.append(_reference(document_id, name, 'main.py', line, _line_text(source, line) or f'uses {node.id}'))
        elif _imports_removed(node, modules) and line not in covered:
            references.append(_reference(document_id, name, 'main.py', line, _line_text(source, line) or 'imports a removed component'))
    return _drop_lines(source, spans), references


def _scan_other(document_id, name, path, source, modules):
    tree = ast.parse(source)
    references = []
    for node in ast.walk(tree):
        if _imports_removed(node, modules):
            line = getattr(node, 'lineno', None)
            references.append(_reference(document_id, name, path, line, _line_text(source, line) or f'imports a removed component'))
    return references


def _external_refs(server, document_id, ids):
    references = []
    for doc in server.state['documents'].values():
        if doc['id'] == document_id or doc.get('deleted_at'):
            continue
        for alias, ref in doc.get('links', {}).items():
            if ref.get('document_id') == document_id and ref.get('component') in ids:
                references.append(_reference(
                    doc['id'], doc['name'], None, None, f'Link {alias} uses component {ref.get("component")}'))
    return references


def _unparsed(document_id, name, path, exc):
    return _reference(document_id, name, path, exc.lineno, exc.msg or 'could not be parsed')


def delete_files(server, document_id, paths, revision, force=False, code=None, files=None, links=None, source_supplied=False):
    """Remove component files. `force` is the human Delete-anyway path; callers that are not the UI pass False."""
    with server.lock:
        saved = server.state['documents'].get(document_id)
        if not saved or saved.get('deleted_at'):
            raise HTTPException(404, 'Document not found')
        if saved.get('kind') != 'design':
            raise HTTPException(422, detail={'message': 'Component files belong to designs.', 'references': []})
        if type(revision) is not int or revision != saved['revision']:
            raise HTTPException(409, 'Document changed. Reopen or reconcile your edits.')
        ordered, seen = [], set()
        for path in paths:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
        if not ordered:
            raise HTTPException(422, detail={'message': 'Choose a component file.', 'references': []})
        if any(not _component_path(path) for path in ordered):
            raise HTTPException(422, detail={'message': 'Choose a component file under components/.', 'references': []})
        if not source_supplied:
            current = server.context.get('document')
            if server.context.get('document_id') == document_id and current:
                from steve_desktop.cad_live import fingerprint
                if fingerprint(current) != fingerprint(saved):
                    raise HTTPException(409, 'Save or send the current source before deleting.')
        base_code = code if code is not None else saved.get('code', '')
        base_files = dict(files if files is not None else saved.get('files') or {})
        base_links = links if links is not None else copy.deepcopy(saved.get('links') or {})
        missing = [path for path in ordered if path not in base_files]
        if missing:
            raise HTTPException(422, detail={'message': 'This component is already gone.', 'references': []})
        modules, ids = set(), set()
        for path in ordered:
            module_names, component_ids = _module_names(path)
            modules.update(module_names)
            ids.update(component_ids)
        warnings = []
        references = []
        try:
            new_code, main_refs = _scan_main(document_id, saved['name'], base_code, modules)
            references.extend(main_refs)
        except SyntaxError as exc:
            if not force:
                raise HTTPException(422, detail={'message': 'main.py could not be parsed.',
                                                 'references': [_unparsed(document_id, saved['name'], 'main.py', exc)]}) from None
            new_code = base_code
            warnings.append('main.py could not be parsed and was left unchanged.')
        for path, text in base_files.items():
            if path in ordered or not path.endswith('.py'):
                continue
            try:
                references.extend(_scan_other(document_id, saved['name'], path, text, modules))
            except SyntaxError as exc:
                if not force:
                    raise HTTPException(422, detail={'message': f'{path} could not be parsed.',
                                                     'references': [_unparsed(document_id, saved['name'], path, exc)]}) from None
                warnings.append(f'{path} could not be parsed.')
        references.extend(_external_refs(server, document_id, ids))
        # The same Name can be visited twice (the load and a wrapper). Keep the first line.
        unique, marked = [], set()
        for item in references:
            key = (item['document_id'], item['path'], item['line'], item['detail'])
            if key not in marked:
                marked.add(key)
                unique.append(item)
        references = unique
        if references and not force:
            raise HTTPException(422, detail={'message': 'Still used.', 'references': references})
        if force:
            warnings.extend(f"{item['path']}:{item['line']} {item['detail']}" if item['line'] else item['detail']
                            for item in references)
        new_files = {path: text for path, text in base_files.items() if path not in ordered and path != 'main.py'}
        message = 'Removed ' + ', '.join(ordered)
        if len(message) > 200:
            message = message[:197] + '...'
        doc = server.update_document(document_id, {
            'name': saved['name'], 'kind': saved['kind'], 'code': new_code, 'files': new_files,
            'links': base_links, 'revision': saved['revision'], 'message': message,
            'preview_build_id': saved.get('preview_build_id'),
        })
        return {'document': doc, 'removed': ordered, 'warnings': warnings, 'references': references if force else []}


def _reply(ok, action, document_id=None, revision=None, removed=None, references=None, warnings=None, error=None):
    return {'ok': ok, 'action': action, 'document_id': document_id, 'revision': revision,
            'removed': list(removed or []), 'references': list(references or []),
            'warnings': list(warnings or []), 'error': error}


def mcp_delete(server, mode, document_id=None, path=None, paths=None, expected_revision=None):
    """Trash, restore, or remove component files. Permanent deletion is not available here."""
    if mode not in ('trash', 'restore', 'remove_file'):
        return _reply(False, 'refused', document_id, error='Permanent deletion is not available from this tool.')
    identifier = document_id or server.context.get('document_id')
    if not identifier:
        return _reply(False, 'refused', error='Open a document or pass document_id.')
    try:
        if mode == 'trash':
            result = trash_documents(server, [identifier])
            if not result['moved']:
                reason = result['skipped'][0]['reason'] if result['skipped'] else 'Document was not trashed.'
                return _reply(False, 'refused', identifier, error=reason)
            doc = result['moved'][0]['document']
            return _reply(True, 'trashed', identifier, doc.get('revision'), [identifier])
        if mode == 'restore':
            result = restore_documents(server, [identifier])
            if not result['restored']:
                reason = result['skipped'][0]['reason'] if result['skipped'] else 'Document was not restored.'
                return _reply(False, 'refused', identifier, error=reason)
            doc = result['restored'][0]
            return _reply(True, 'restored', identifier, doc.get('revision'), [identifier])
        names = [*(paths or []), *([path] if path else [])]
        if not names:
            return _reply(False, 'refused', identifier, error='Pass path or paths for remove_file.')
        result = delete_files(server, identifier, names, expected_revision, force=False)
        return _reply(True, 'file_removed', identifier, result['document']['revision'], result['removed'],
                      warnings=result['warnings'])
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            return _reply(False, 'refused', identifier, error=detail.get('message') or 'Refused.',
                          references=detail.get('references') or [])
        return _reply(False, 'refused', identifier, error=str(detail))
