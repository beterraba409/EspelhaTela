# -*- coding: utf-8 -*-
"""Copias entre o PC e o aparelho (adb pull/push) com progresso, cancelamento e aviso de sobrescrita.

O adb nao mostra progresso quando a saida nao e um terminal, entao o andamento e medido pelo
tamanho do que ja chegou: no PC (pull) pelo disco, no aparelho (push) com `stat`/`du` a cada segundo.
"""

import os
import posixpath
import subprocess
import threading
import time

MEDIR_A_CADA = 0.5  # s


def tamanho_local(caminho):
    """Bytes de um arquivo ou de uma pasta inteira do PC (0 se nao existir)."""
    if os.path.isfile(caminho):
        return os.path.getsize(caminho)
    total = 0
    for raiz, _, arqs in os.walk(caminho):
        for a in arqs:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return total


def conflitos(existentes, caminhos):
    """Nomes que ja existem no destino (para perguntar antes de sobrescrever)."""
    nomes = set(existentes)
    return [os.path.basename(c.rstrip("/\\")) for c in caminhos if os.path.basename(c.rstrip("/\\")) in nomes]


def texto_progresso(acao, i, n, nome, feito, total, fmt):
    """'Baixando 2 de 3: log.txt - 12.0 MB de 40.0 MB (30%)'."""
    partes = "%s %d de %d: %s" % (acao, i, n, nome) if n > 1 else "%s %s" % (acao, nome)
    if total > 0:
        return "%s  -  %s de %s (%d%%)" % (partes, fmt(min(feito, total)), fmt(total), porcentagem(feito, total))
    return "%s  -  %s" % (partes, fmt(feito)) if feito else partes


def porcentagem(feito, total):
    return 100 if total <= 0 else max(0, min(100, int(feito * 100 / total)))


class Copia:
    """Um item: comando do adb, nome exibido, total esperado, medidor do que ja chegou e limpeza se cancelar."""

    def __init__(self, args, nome, total, medir, limpar=None):
        self.args, self.nome, self.total, self.medir, self.limpar = args, nome, total, medir, limpar


class Transferencia:
    """Roda as copias em sequencia numa thread. `avisa(evento, dados)` e chamado da thread:
    ('andamento', (i, n, nome, feito, total, feito_geral, total_geral)) e ('fim', (falhas, cancelado))."""

    def __init__(self, adb, serial, copias, avisa, sem_janela=0):
        self.adb, self.serial, self.copias, self.avisa = adb, serial, copias, avisa
        self.sem_janela = sem_janela
        self.cancelado = False
        self._proc = None
        self.total_geral = 0

    def iniciar(self):
        threading.Thread(target=self._roda, daemon=True).start()

    def cancelar(self):
        self.cancelado = True
        p = self._proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    def _roda(self):
        for c in self.copias:  # total de pasta do aparelho custa uma consulta: feita aqui, fora do Tk
            if callable(c.total):
                c.total = _seguro(c.total)
        self.total_geral = sum(max(0, c.total) for c in self.copias)
        falhas, antes = [], 0
        n = len(self.copias)
        for i, c in enumerate(self.copias, 1):
            if self.cancelado:
                break
            self.avisa("andamento", (i, n, c.nome, 0, c.total, antes, self.total_geral))
            try:
                self._proc = subprocess.Popen([self.adb, "-s", self.serial] + c.args, stdout=subprocess.PIPE,
                                              stderr=subprocess.STDOUT, creationflags=self.sem_janela)
                saida = []
                leitor = threading.Thread(target=lambda p=self._proc: saida.append(p.stdout.read()), daemon=True)
                leitor.start()
                while self._proc.poll() is None:
                    time.sleep(MEDIR_A_CADA)
                    if self.cancelado:
                        break
                    feito = self._mede(c)
                    self.avisa("andamento", (i, n, c.nome, feito, c.total, antes + min(feito, c.total), self.total_geral))
                leitor.join(5)
                try:
                    self._proc.stdout.close()
                except Exception:  # noqa: BLE001
                    pass
                if self.cancelado:
                    try:
                        self._proc.wait(5)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()  # o adb demorou a morrer: forca, e limpa do mesmo jeito
                    if c.limpar:
                        try:
                            c.limpar()
                        except Exception:  # noqa: BLE001
                            pass
                    break
                if self._proc.returncode != 0:
                    texto = (b"".join(saida).decode("utf-8", "replace").strip().splitlines() or ["falhou"])[-1]
                    falhas.append("%s: %s" % (c.nome, texto[:160]))
            except Exception as e:  # noqa: BLE001
                falhas.append("%s: %s" % (c.nome, str(e)[:160]))
            antes += max(0, c.total)
            self.avisa("andamento", (i, n, c.nome, c.total, c.total, antes, self.total_geral))
        self.avisa("fim", (falhas, self.cancelado))

    @staticmethod
    def _mede(c):
        return _seguro(c.medir)


def _seguro(fn):
    """Numero devolvido por fn; 0 se falhar (medir nunca derruba a copia)."""
    try:
        return int(fn() or 0)
    except Exception:  # noqa: BLE001
        return 0


def nome_remoto(caminho):
    return posixpath.basename(caminho.rstrip("/")) or caminho
