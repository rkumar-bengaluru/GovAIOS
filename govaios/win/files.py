"""Windows file primitives: byte-range lock, no-follow open, known folders."""
import ctypes
import errno
import os
import stat
import uuid
from ctypes import wintypes
from pathlib import Path

_LOCKFILE_FAIL_IMMEDIATELY = 0x1
_LOCKFILE_EXCLUSIVE_LOCK = 0x2
_ERROR_LOCK_VIOLATION = 33
_ERROR_IO_PENDING = 997
_ERROR_NOT_LOCKED = 158
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

_FOLDERID_PROFILE = "5E6C858F-0E22-4760-9AFE-EA3317B67173"
_FOLDERID_LOCALAPPDATA = "F1B32785-6FBA-4FCF-9D55-7B8E7F157091"


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


def _handle(f):
    import msvcrt
    fd = f if isinstance(f, int) else f.fileno()
    return msvcrt.get_osfhandle(fd)


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)]
    k.LockFileEx.restype = wintypes.BOOL
    k.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(_OVERLAPPED)]
    k.UnlockFileEx.restype = wintypes.BOOL
    return k


def flock_ex(f, blocking: bool = True) -> None:
    """Exclusive lock on byte 0 (length 1) of f, independent of the file position."""
    k = _kernel32()
    flags = _LOCKFILE_EXCLUSIVE_LOCK | (0 if blocking else _LOCKFILE_FAIL_IMMEDIATELY)
    ov = _OVERLAPPED()  # Offset = OffsetHigh = 0
    if not k.LockFileEx(_handle(f), flags, 0, 1, 0, ctypes.byref(ov)):
        err = ctypes.get_last_error()
        if err in (_ERROR_LOCK_VIOLATION, _ERROR_IO_PENDING):
            raise BlockingIOError(errno.EAGAIN, "lock held by another handle")
        raise ctypes.WinError(err)


def funlock(f) -> None:
    """Release the flock_ex range; no error if it is not locked."""
    k = _kernel32()
    ov = _OVERLAPPED()
    if not k.UnlockFileEx(_handle(f), 0, 1, 0, ctypes.byref(ov)):
        err = ctypes.get_last_error()
        if err != _ERROR_NOT_LOCKED:
            raise ctypes.WinError(err)


def open_nofollow(path, flags: int, mode: int = 0o600) -> int:
    """os.open that refuses reparse points (symlinks, junctions) and non-regular files."""
    fd = os.open(path, flags | os.O_BINARY, mode)
    try:
        st = os.lstat(path)
        if getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(errno.ELOOP, "refusing to follow reparse point", str(path))
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.ELOOP, "not a regular file", str(path))
    except BaseException:
        os.close(fd)
        raise
    return fd


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


def _known_folder(folder_id: str) -> Path:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    guid = _GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
                                             ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ptr = ctypes.c_void_p()
    hr = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(ptr))
    try:
        if hr != 0:
            raise OSError(f"SHGetKnownFolderPath failed: 0x{hr & 0xFFFFFFFF:08x}")
        return Path(ctypes.wstring_at(ptr.value))
    finally:
        if ptr.value:
            ole32.CoTaskMemFree(ptr)


def user_home() -> Path:
    return _known_folder(_FOLDERID_PROFILE)


def local_appdata() -> Path:
    return _known_folder(_FOLDERID_LOCALAPPDATA)


def display_name() -> str:
    """Display name of the signed-in user; falls back to the account name, then 'Admin'."""
    try:
        secur32 = ctypes.WinDLL("secur32", use_last_error=True)
        n = wintypes.ULONG(0)
        secur32.GetUserNameExW(3, None, ctypes.byref(n))  # NameDisplay = 3; sizes the buffer
        if n.value:
            buf = ctypes.create_unicode_buffer(n.value)
            if secur32.GetUserNameExW(3, buf, ctypes.byref(n)) and buf.value:
                return buf.value
    except OSError:
        pass
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        n = wintypes.DWORD(257)
        buf = ctypes.create_unicode_buffer(n.value)
        if advapi32.GetUserNameW(buf, ctypes.byref(n)) and buf.value:
            return buf.value
    except OSError:
        pass
    return "Admin"
