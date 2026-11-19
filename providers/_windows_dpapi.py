"""Windows Data Protection API helper used by the Qoder adapter."""
import ctypes
from ctypes import wintypes as wt
import os


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, encrypt: bool) -> bytes | None:
    if not data or len(data) > 65536 or os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(DataBlob)]
    function.restype = wt.BOOL
    buffer = ctypes.create_string_buffer(data, len(data))
    incoming = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    outgoing = DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN: never prompt for user interaction.
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        return None
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)
