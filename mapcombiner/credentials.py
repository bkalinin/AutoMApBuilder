"""OAuth token encrypted by Windows DPAPI for the current Windows user."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path


def normalize_token(value):
    value = value.strip()
    if value.lower().startswith('bearer '):
        value = value[7:].strip()
    if not value or any(c.isspace() for c in value):
        raise ValueError('Укажите один OAuth Access Token без пояснений и переносов строк.')
    return value


class TokenStore:
    def __init__(self, path):
        self.path = Path(path)

    def exists(self):
        return self.path.is_file()

    @staticmethod
    def _crypt(data, decrypt=False):
        if os.name != 'nt':
            raise RuntimeError('Защищённое хранение токена доступно только в Windows.')
        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        result = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        # CRYPTPROTECT_UI_FORBIDDEN; never use machine-wide encryption.
        if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise RuntimeError('Windows не смог прочитать/сохранить токен для текущего пользователя.')
        try:
            return ctypes.string_at(result.data, result.size)
        finally:
            kernel.LocalFree(result.data)

    def save(self, token):
        encrypted = self._crypt(normalize_token(token).encode('utf-8'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)

    def load(self):
        if not self.exists():
            raise ValueError('Сохраните OAuth Access Token на вкладке mod.io.')
        return normalize_token(self._crypt(self.path.read_bytes(), decrypt=True).decode('utf-8'))

    def delete(self):
        self.path.unlink(missing_ok=True)
