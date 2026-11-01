"""Local document revisions and source packages using Studio's HTTP contracts."""
from fastapi import HTTPException
from steve_desktop.cad_delete import (
    delete_files, document_references, empty_trash, purge_documents, restore_documents, trash_documents,
)


def install(server):
    app = server.app

    @app.get('/v1/documents/{identifier}/package')
    def package(identifier: str, revision: int | None = None):
        documents, seen = [], set()

        def visit(doc):
            key = (doc['id'], doc['revision'])
            if key in seen:
                return
            seen.add(key)
            documents.append({**doc, 'document_id': doc['id']})
            for ref in doc.get('links', {}).values():
                visit(server.revision(ref['document_id'], ref['revision']))
        with server.lock:
            visit(server.revision(identifier, revision))
        return {'documents': documents}

    @app.get('/v1/documents/{identifier}/history')
    def history(identifier: str):
        with server.lock:
            documents = [*server.state.get('history', {}).get(identifier, []), server.revision(identifier)]
            return {'document_id': identifier, 'revisions': [
                {'event_id': d['revision'], 'revision': d['revision'], 'recorded_at': d['updated_at'], 'commit_id': str(d['revision']),
                 'message': d.get('message'), 'preview_build_id': server.matching_preview(d, d.get('preview_build_id'))}
                for d in reversed(documents)]}

    @app.get('/v1/documents/{identifier}/history/{commit}')
    def historical(identifier: str, commit: int):
        return {'commit_id': str(commit), 'document': server.revision(identifier, commit)}

    @app.post('/v1/documents/{identifier}/history/restore')
    def restore(identifier: str, body: dict):
        if body.get('branch', 'main') != 'main':
            raise HTTPException(422, 'This local document has only a main revision history.')
        with server.lock:
            previous = server.revision(identifier, int(body['commit_id']))
            previous['revision'] = body['revision']
            previous['message'] = f"Restored revision {body['commit_id']}"
            doc = server.update_document(identifier, previous)
            build = server.state['builds'].get(doc.get('preview_build_id'))
            if build is None:
                build = server.submit(doc)
            return {'document': doc, 'model': build, 'restored_from': body['commit_id']}

    def references(identifier):
        return document_references(server, identifier)

    @app.get('/v1/documents/{identifier}/references')
    def read_references(identifier: str):
        return references(identifier)

    @app.post('/v1/documents/{identifier}/files/delete')
    def delete_component_files(identifier: str, body: dict):
        return delete_files(
            server, identifier, body.get('paths') or [], body.get('revision'),
            force=bool(body.get('force')),
            code=body.get('code') if 'code' in body else None,
            files=body.get('files') if 'files' in body else None,
            links=body.get('links') if 'links' in body else None,
            source_supplied='code' in body or 'files' in body)

    @app.post('/v1/trash')
    def trash(body: dict):
        return trash_documents(server, body.get('ids', []))

    @app.get('/v1/trash')
    def list_trash():
        return {'retention_days': None, 'documents': [
            {**d, 'purge_at': None, 'references': references(d['id']), 'used_by': references(d['id'])['used_by']}
            for d in server.state['documents'].values() if d.get('deleted_at')]}

    @app.post('/v1/trash/restore')
    def untrash(body: dict):
        return restore_documents(server, body.get('ids', []))

    @app.post('/v1/trash/purge')
    def purge(body: dict):
        # `force` is ignored. Permanent deletion never overrides a live link.
        return purge_documents(server, body.get('ids') or [])

    @app.post('/v1/trash/empty')
    def empty():
        return empty_trash(server)
