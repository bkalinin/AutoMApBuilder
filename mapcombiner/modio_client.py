"""Small streaming mod.io client. No activation/moderation endpoints."""
import base64
import hashlib
import http.client
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
import uuid

from .credentials import normalize_token

PLATFORMS = {'steam': ('windows',), 'playstation': ('ps4', 'ps5'),
             'xbox': ('xboxone', 'xboxseriesx')}
PLATFORM_NAMES = {'windows': 'Windows', 'ps4': 'PS4', 'ps5': 'PS5',
                  'xboxone': 'Xbox One', 'xboxseriesx': 'Xbox Series X|S'}
MULTIPART_THRESHOLD = 100_000_000
PART_SIZE = 50 * 1024 * 1024


def target_platforms(entry):
    # Preserve the intent of old in-flight requests when reading the v1 journal.
    if 'target_platforms' in entry:
        return tuple(entry['target_platforms'])
    return (entry['target_platform'],) if entry.get('target_platform') else ()


def platform_names(platforms):
    return ' + '.join(PLATFORM_NAMES.get(p, p) for p in platforms) or '—'


def file_platforms(result):
    return list(dict.fromkeys(p['platform'] for p in result.get('platforms', []) if p.get('platform')))


class Cancelled(Exception):
    pass


class ApiError(Exception):
    def __init__(self, message, status=0, error_ref=0, retry_after=0):
        super().__init__(message)
        self.status, self.error_ref, self.retry_after = status, error_ref, retry_after

    @property
    def transient(self):
        return self.status == 0 or self.status in (408, 429) or self.status >= 500


def positive_id(value, name):
    if not re.fullmatch(r'[1-9][0-9]*', str(value).strip()):
        raise ValueError(f'{name}: укажите положительный числовой ID.')
    return int(value)


def check_filename(name):
    if (not name.lower().endswith('.zip') or len(name) > 100
            or re.search(r'[\\/\?"<>|:*\x00-\x1f\x7f]', name)):
        raise ValueError('Имя ZIP: не более 100 символов, без \\ / ? " < > | : *.')


class Client:
    def __init__(self, game_id, token, *, cancelled=lambda: False, progress=lambda text: None):
        self.game_id = positive_id(game_id, 'Game ID')
        self.token = normalize_token(token)
        self.cancelled, self.progress = cancelled, progress
        self.host = f'g-{self.game_id}.modapi.io'

    def safe(self, message):
        return str(message).replace(self.token, '[REDACTED]')

    def check(self):
        if self.cancelled():
            raise Cancelled('Загрузка отменена. Локальные ZIP сохранены.')

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            time.sleep(min(.2, max(0, end - time.monotonic())))

    def request(self, method, path, *, query=None, form=None, body=None, headers=None):
        """One attempt. In particular, never transparently retry Add Modfile."""
        self.check()
        url = '/v1' + path + ('?' + urlencode(query) if query else '')
        outgoing = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json',
                    'User-Agent': 'CarXMapCombiner/0.1'}
        if form is not None:
            body = urlencode(form).encode('utf-8')
            outgoing['Content-Type'] = 'application/x-www-form-urlencoded'
        outgoing.update(headers or {})
        connection = http.client.HTTPSConnection(self.host, timeout=60)
        try:
            connection.request(method, url, body=body, headers=outgoing)
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024)
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                data = {}
            if not 200 <= response.status < 300:
                error = data.get('error', {}) if isinstance(data, dict) else {}
                ref = error.get('error_ref', 0)
                hint = ('OAuth-токен недействителен/истёк. API key не заменяет OAuth Access Token. '
                        if response.status == 401 else
                        'Нет прав на этот мод (нужен manager/admin команды). ' if ref == 15006 else
                        'Доступ запрещён: проверьте права токена read + write и права на мод. '
                        if response.status == 403 else '')
                details = json.dumps(error.get('errors', {}), ensure_ascii=False)
                message = f'mod.io HTTP {response.status} / {ref}: {hint}{error.get("message", "Ошибка API")}'
                if details != '{}':
                    message += '\n' + details
                retry = response.getheader('Retry-After', '0')
                raise ApiError(self.safe(message), response.status, ref,
                               int(retry) if retry.isdigit() else 0)
            if not isinstance(data, dict) or not data:
                raise ApiError('mod.io вернул нечитаемый ответ; результат запроса неизвестен.')
            return data
        except (OSError, http.client.HTTPException) as error:
            # Never include request headers, URLs with credentials, or raw exceptions.
            raise ApiError('Соединение с mod.io прервано или истёк таймаут (' + type(error).__name__ + ').') from None
        finally:
            connection.close()

    def get(self, path, query=None):
        for attempt in range(3):
            try:
                return self.request('GET', path, query=query)
            except ApiError as error:
                if not error.transient or attempt == 2 or error.retry_after > 30:
                    raise
                self.wait(max(error.retry_after, 2 ** attempt))

    def rows(self, path, query=None):
        offset = 0
        for _ in range(100):
            result = self.get(path, {**(query or {}), '_limit': 100, '_offset': offset})
            rows = result.get('data', [])
            yield from rows
            offset += len(rows)
            if not rows or offset >= result.get('result_total', offset):
                return
        raise ApiError('Слишком много результатов mod.io; повторная отправка остановлена.')

    def base(self, mod_id):
        return f'/games/{self.game_id}/mods/{positive_id(mod_id, "Mod ID")}'

    def lookup(self, mod_id):
        data = self.get(self.base(mod_id))
        if data.get('id') != int(mod_id) or data.get('game_id') != self.game_id or not data.get('name'):
            raise ApiError('mod.io вернул мод с неожиданным ID или Game ID.')
        return {'game_id': self.game_id, 'mod_id': int(mod_id), 'name': data['name']}

    def reconcile(self, mod_id, entry):
        matches = []
        expected = set(target_platforms(entry))
        for row in self.rows(self.base(mod_id) + '/files', {'_sort': '-date_added'}):
            # mod.io rewrites ZIP names; match content and destination instead.
            if (row.get('mod_id') == int(mod_id)
                    and row.get('filehash', {}).get('md5', '').lower() == entry['md5'].lower()
                    and ('filesize' not in entry or row.get('filesize') == entry['filesize'])
                    and int(row.get('date_added', 0)) >= entry['create_started'] - 300
                    and expected and expected.issubset(file_platforms(row))):
                matches.append(row)
        return matches[0] if len(matches) == 1 else None

    def modfile(self, mod_id, modfile_id):
        result = self.get(self.base(mod_id) + '/files/' + str(positive_id(modfile_id, 'Modfile ID')))
        if result.get('id') != int(modfile_id) or result.get('mod_id') != int(mod_id):
            raise ApiError('mod.io вернул файл с неожиданным Modfile ID или Mod ID.')
        return result

    def _chunks(self, parts):
        for part in parts:
            self.check()
            if isinstance(part, Path):
                total = part.stat().st_size
                done, last_percent = 0, -1
                with part.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        self.check()
                        yield chunk
                        done += len(chunk)
                        percent = done * 100 // max(1, total)
                        if percent != last_percent:
                            last_percent = percent
                            self.progress(f'Отправка ZIP: {percent}%')
            else:
                yield part

    def add_file(self, mod_id, entry, path=None, upload_id=None):
        platforms = target_platforms(entry)
        if not platforms:
            raise ValueError('Не указаны платформы Modfile.')
        # Repeated form fields: one ZIP / Modfile may target multiple platforms.
        fields = [('active', 'false'), ('filehash', entry['md5'])]
        fields.extend(('platforms[]', platform) for platform in platforms)
        if upload_id:
            fields.append(('upload_id', upload_id))
        boundary = 'MapCombiner' + uuid.uuid4().hex
        parts = []
        for key, value in fields:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        if path is not None:
            filename = entry.get('filename', Path(path).name)
            check_filename(filename)
            parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="filedata"; filename="{filename}"\r\nContent-Type: application/zip\r\n\r\n'.encode('utf-8'), Path(path), b'\r\n']
        parts.append(f'--{boundary}--\r\n'.encode())
        length = sum(p.stat().st_size if isinstance(p, Path) else len(p) for p in parts)
        return self.request('POST', self.base(mod_id) + '/files', body=self._chunks(parts), headers={
            'Content-Type': 'multipart/form-data; boundary=' + boundary, 'Content-Length': str(length)})

    def multipart(self, mod_id, path, entry, save):
        base = self.base(mod_id) + '/files/multipart'
        if not entry.get('upload_id'):
            # Nonce is persisted before this request; the API deduplicates session creation.
            entry.setdefault('nonce', uuid.uuid4().hex)
            save()
            result = self.request('POST', base, form={'filename': entry.get('filename', path.name), 'nonce': entry['nonce']})
            entry['upload_id'] = result['upload_id']
            save()
        upload_id = entry['upload_id']
        sessions = list(self.rows(base + '/sessions', {'upload_id': upload_id}))
        session = next((s for s in sessions if s.get('upload_id') == upload_id), None)
        if not session or session.get('status') == 4:
            # No Modfile has been created in this phase. A new session is safe next time.
            entry.pop('upload_id', None)
            entry.pop('nonce', None)
            save()
            raise ApiError('Multipart-сессия истекла/отменена. Повторите Upload для новой сессии.')
        status = session.get('status')
        size = path.stat().st_size
        if status == 0:
            existing = {p['part_number']: p['part_size'] for p in self.rows(base, {'upload_id': upload_id})}
            with path.open('rb') as stream:
                for start in range(0, size, PART_SIZE):
                    self.check()
                    number = start // PART_SIZE + 1
                    stream.seek(start)
                    chunk = stream.read(min(PART_SIZE, size - start))
                    self.progress(f'Отправка части {number}/{(size + PART_SIZE - 1) // PART_SIZE}')
                    if existing.get(number) == len(chunk):
                        continue
                    digest = base64.b64encode(hashlib.sha256(chunk).digest()).decode('ascii')
                    for attempt in range(3):
                        try:
                            self.request('PUT', base, query={'upload_id': upload_id}, body=chunk, headers={
                                'Content-Range': f'bytes {start}-{start + len(chunk) - 1}/{size}',
                                'Digest': 'sha-256=' + digest, 'Content-Type': 'application/octet-stream'})
                            break
                        except ApiError as error:
                            if not error.transient and error.error_ref != 29015:
                                raise
                            # A timeout or duplicate range may mean the part was received.
                            parts = {p['part_number']: p['part_size'] for p in self.rows(base, {'upload_id': upload_id})}
                            if parts.get(number) == len(chunk):
                                break
                            if attempt == 2 or error.retry_after > 30:
                                raise
                            self.wait(max(error.retry_after, 2 ** attempt))
            self.request('POST', base + '/complete', query={'upload_id': upload_id}, body=b'')
        for _ in range(60):
            self.check()
            sessions = list(self.rows(base + '/sessions', {'upload_id': upload_id}))
            session = next((s for s in sessions if s.get('upload_id') == upload_id), {})
            if session.get('status') == 3:
                return upload_id
            if session.get('status') not in (1, 2):
                raise ApiError('Multipart ещё не завершён или сессия недоступна. Повторите Upload.')
            self.progress('mod.io собирает загруженные части…')
            self.wait(5)
        raise ApiError('mod.io ещё обрабатывает части. Повторите Upload позже; части сохранены.')
