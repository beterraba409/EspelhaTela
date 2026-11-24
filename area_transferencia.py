# -*- coding: utf-8 -*-
"""Area de transferencia do Windows sem depender do Tk.

O `clipboard_append` do Tk no Windows tenta abrir a area de transferencia uma vez so: se outro programa a
estiver usando naquele instante (historico do Win+V, Teams, area de trabalho remota, gerenciadores de
area de transferencia), a copia falha em silencio. E o texto copiado some quando o Vision fecha. Aqui a
copia vai direto pela API do Windows, com novas tentativas, e o texto fica no Windows na hora."""

import ctypes
import os
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _api():
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.OpenClipboard.argtypes, u32.OpenClipboard.restype = [wintypes.HWND], wintypes.BOOL
    u32.SetClipboardData.argtypes, u32.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
    u32.GetClipboardData.argtypes, u32.GetClipboardData.restype = [wintypes.UINT], wintypes.HANDLE
    k32.GlobalAlloc.argtypes, k32.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
    k32.GlobalLock.argtypes, k32.GlobalLock.restype = [wintypes.HGLOBAL], ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                    wintypes.HINSTANCE, wintypes.LPVOID]
    u32.CreateWindowExW.restype = wintypes.HWND
    u32.DestroyWindow.argtypes = [wintypes.HWND]
    return u32, k32


def _abre(u32, espera, janela=None):
    fim = time.time() + espera
    while True:
        if u32.OpenClipboard(janela):
            return True
        if time.time() >= fim:
            return False
        time.sleep(0.03)  # outro programa esta com ela aberta: tenta de novo


def copiar(texto, espera=1.5):
    """Poe `texto` na area de transferencia do Windows. True se deu certo.

    A dona e uma janela invisivel so desta copia (sem dona, a doc do Windows diz que o SetClipboardData
    pode falhar; com a janela do Tk como dona, o Tk esvazia a area de transferencia quando ela fecha)."""
    if os.name != "nt":
        return False
    u32, k32 = _api()
    dona = u32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    try:
        return _copiar(u32, k32, texto, espera, dona)
    finally:
        if dona:
            u32.DestroyWindow(dona)


def _copiar(u32, k32, texto, espera, dona):
    dados = (texto or "").encode("utf-16-le") + b"\x00\x00"
    if not _abre(u32, espera, dona):
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(dados))
        if not h:
            return False
        p = k32.GlobalLock(h)
        ctypes.memmove(p, dados, len(dados))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            k32.GlobalFree(h)
            return False
        return True  # a memoria agora e do Windows: nao liberar
    finally:
        u32.CloseClipboard()


def ler(espera=1.5):
    """Texto da area de transferencia do Windows (None se nao der para ler)."""
    if os.name != "nt":
        return None
    u32, k32 = _api()
    if not _abre(u32, espera):
        return None
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()
