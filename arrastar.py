# -*- coding: utf-8 -*-
"""Arrastar arquivos do Explorer para uma janela Tk.

O Tk nao trata arquivos soltos. No Windows a janela passa a aceitar (DragAcceptFiles) e o
procedimento dela e trocado por um que le a mensagem WM_DROPFILES e repassa o resto ao original.
So a API do Windows (ctypes): nada a mais no instalador.
"""

import sys

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_vivos = {}  # hwnd -> callbacks; precisam viver enquanto a janela existir (senao o GC solta e o Windows chama memoria liberada)


def aceitar(janela, ao_soltar):
    """Faz `janela` (Tk ou Toplevel) aceitar arquivos soltos; `ao_soltar(lista_de_caminhos)` roda no Tk.
    Devolve False fora do Windows ou se a API falhar (o resto da janela segue normal)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        troca = user32.SetWindowLongPtrW
        troca.restype, troca.argtypes = ctypes.c_void_p, [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        chama = user32.CallWindowProcW
        chama.restype = LRESULT
        chama.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        consulta = shell32.DragQueryFileW
        consulta.restype, consulta.argtypes = wintypes.UINT, [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

        janela.update_idletasks()
        hwnd = int(janela.wm_frame(), 16)  # moldura de fora: recebe o que for solto em qualquer ponto da janela
        anterior, soltos = [], []

        def busca():
            try:
                while soltos:
                    ao_soltar(soltos.pop(0))
                janela.after(150, busca)
            except Exception:  # noqa: BLE001  (janela fechada)
                pass

        def proc(h, msg, wp, lp):
            if msg == WM_DROPFILES:
                caminhos = []
                try:
                    for i in range(consulta(wp, 0xFFFFFFFF, None, 0)):
                        n = consulta(wp, i, None, 0) + 1
                        buf = ctypes.create_unicode_buffer(n)
                        consulta(wp, i, buf, n)
                        caminhos.append(buf.value)
                finally:
                    shell32.DragFinish(wp)
                if caminhos:
                    soltos.append(caminhos)  # nada de Tk aqui dentro: o Tk busca na fila (chamar o Tk daqui derruba o Python)
                return 0
            return chama(anterior[0], h, msg, wp, lp)

        novo = WNDPROC(proc)
        anterior.append(troca(hwnd, GWLP_WNDPROC, ctypes.cast(novo, ctypes.c_void_p)))
        if not anterior[0]:
            return False
        shell32.DragAcceptFiles(hwnd, True)
        _vivos[hwnd] = (novo, anterior)
        janela.after(150, busca)
        return True
    except Exception:  # noqa: BLE001
        return False
