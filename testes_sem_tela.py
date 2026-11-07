# -*- coding: utf-8 -*-
"""Verificacoes sem tela e sem aparelho: python testes_sem_tela.py"""

import os
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adb_servidor as A  # noqa: E402
import seletor as S  # noqa: E402

WRAPPER = r"""@echo off
setlocal
set "ADB_EXE=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
set "DEFAULT_ADB_SERVER_PORT=5038"
set "HAS_PORT_ARG="
for %%A in (%*) do (
  if /I "%%~A"=="-P" set "HAS_PORT_ARG=1"
)
if defined ADB_SERVER_PORT (
  "%ADB_EXE%" -P %ADB_SERVER_PORT% %*
  exit /b %ERRORLEVEL%
)
"%ADB_EXE%" -P %DEFAULT_ADB_SERVER_PORT% %*
"""

XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node index="0" text="" resource-id="" class="android.widget.FrameLayout" content-desc="" clickable="false" bounds="[0,0][720,1280]">
 <node index="0" text="" resource-id="button-teste-conexao" class="android.view.ViewGroup" content-desc="" clickable="true" bounds="[60,540][400,620]">
  <node index="0" text="Conexão com a internet" resource-id="title-button-teste-conexao" class="android.widget.TextView" content-desc="title-button-teste-conexao" clickable="false" bounds="[100,560][380,600]" />
 </node>
 <node index="1" text="" resource-id="item-lista" class="android.view.ViewGroup" content-desc="" clickable="true" bounds="[0,700][720,760]">
  <node index="0" text="R$ 10,00 &quot;promo&quot;" resource-id="" class="android.widget.TextView" content-desc="" clickable="false" bounds="[10,710][300,750]" />
 </node>
 <node index="2" text="" resource-id="item-lista" class="android.view.ViewGroup" content-desc="" clickable="true" bounds="[0,760][720,820]" />
 <node index="3" text="" resource-id="com.exemplo.app:id/campo" class="android.widget.EditText" content-desc="" clickable="true" bounds="[0,900][720,980]" />
 <node index="4" text="" resource-id="" class="android.view.View" content-desc="" clickable="false" bounds="[0,0][0,0]" />
</node>
</hierarchy>UI hierchary dumped to: /dev/tty"""


class TestAdbServidor(unittest.TestCase):
    def _wrapper(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".CMD", delete=False, encoding="utf-8")
        f.write(WRAPPER)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_wrapper_porta_e_exe(self):
        info = A.analisa_adb(self._wrapper(), env={"LOCALAPPDATA": r"C:\U\AppData\Local"})
        self.assertTrue(info["wrapper"])
        self.assertEqual(info["porta"], 5038)
        self.assertEqual(info["exe"], r"C:\U\AppData\Local\Android\Sdk\platform-tools\adb.exe")

    def test_wrapper_respeita_ambiente(self):
        info = A.analisa_adb(self._wrapper(), env={"LOCALAPPDATA": "C:\\x", "ADB_SERVER_PORT": "5037"})
        self.assertEqual(info["porta"], 5037)

    def test_exe_comum(self):
        self.assertEqual(A.analisa_adb(r"C:\sdk\adb.exe", env={})["porta"], 5037)
        self.assertEqual(A.analisa_adb(r"C:\sdk\adb.exe", env={"ADB_SERVER_PORT": "6000"})["porta"], 6000)
        self.assertFalse(A.analisa_adb(r"C:\sdk\adb.exe", env={})["wrapper"])

    def test_consulta_servidor_falso(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        porta = srv.getsockname()[1]
        recebido = []

        def atende():
            c, _ = srv.accept()
            recebido.append(c.recv(64))
            corpo = b"0123abcd\tdevice\n192.168.1.7:5555\toffline\n"
            c.sendall(b"OKAY" + b"%04x" % len(corpo) + corpo)
            c.close()

        t = threading.Thread(target=atende)
        t.start()
        lista = A.aparelhos_no_servidor(porta)
        t.join()
        srv.close()
        self.assertEqual(recebido[0], b"000chost:devices")
        self.assertEqual(lista, [{"serial": "0123abcd", "estado": "device"}, {"serial": "192.168.1.7:5555", "estado": "offline"}])

    def test_porta_sem_servidor(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
        s.close()
        self.assertIsNone(A.aparelhos_no_servidor(porta, timeout=0.5))

    def test_sugestao(self):
        info = {"caminho": r"C:\bin\adb.CMD", "exe": "adb.exe", "porta": 5038, "wrapper": True}
        dev = [{"serial": "0123abcd", "estado": "device"}]
        sug = A.sugestao(info, {5037: dev, 5038: []})
        self.assertEqual(sug["porta"], 5037)
        self.assertIn("porta 5038, sem aparelhos", sug["texto"])
        self.assertIn("0123abcd", sug["texto"])
        self.assertIn("que nem esta no ar", A.sugestao(info, {5037: dev})["texto"])
        self.assertIsNone(A.sugestao(info, {5037: dev, 5038: dev}))  # a porta em uso ja tem aparelho
        self.assertIsNone(A.sugestao(info, {5037: [{"serial": "x", "estado": "unauthorized"}], 5038: []}))
        self.assertIsNone(A.sugestao(info, {5038: []}))

    def test_servidores_so_os_no_ar(self):
        achados = A.servidores([6001], consulta=lambda p: [] if p in (5037, 6001) else None)
        self.assertEqual(achados, {5037: [], 6001: []})


class TestSeletor(unittest.TestCase):
    def setUp(self):
        self.nos = S.le_nos(S.extrai_xml(XML))

    def _idx(self, rid=None, texto=None):
        return next(i for i, n in enumerate(self.nos) if (rid is None or n["resource-id"] == rid) and (texto is None or n["text"] == texto))

    def test_extrai_xml(self):
        self.assertTrue(S.extrai_xml(XML).endswith("</hierarchy>"))
        self.assertEqual(S.extrai_xml("ERROR: could not get idle state."), "")

    def test_menor_no_no_ponto(self):
        i = S.no_no_ponto(self.nos, 200, 580)
        self.assertEqual(self.nos[i]["resource-id"], "title-button-teste-conexao")
        self.assertEqual(self.nos[S.no_no_ponto(self.nos, 70, 545)]["resource-id"], "button-teste-conexao")
        self.assertIsNone(S.no_no_ponto(self.nos, 9999, 9999))

    def test_seletores_testid_e_clicavel(self):
        i = self._idx("title-button-teste-conexao")
        sug = dict(S.seletores(self.nos, i, (720, 1280)))
        self.assertEqual(sug["id"], '- tapOn:\n    id: "title-button-teste-conexao"')
        self.assertEqual(sug["id do elemento clicavel que contem este"], '- tapOn:\n    id: "button-teste-conexao"')
        self.assertEqual(sug["texto"], '- tapOn: "Conexão com a internet"')
        self.assertNotIn("accessibilityLabel", sug)  # content-desc igual ao testID nao vira sugestao
        self.assertEqual(sug["ponto (ultimo recurso)"], '- tapOn:\n    point: "33%,45%"')

    def test_id_repetido_ganha_index_e_texto_escapado(self):
        i = self._idx(texto='R$ 10,00 "promo"')
        sug = S.seletores(self.nos, i, (720, 1280))
        rotulo, yaml = sug[0]
        self.assertIn("do elemento pai", rotulo)
        self.assertIn("2 elementos com esse id", rotulo)
        self.assertEqual(yaml, '- tapOn:\n    id: "item-lista"\n    index: 0')
        self.assertIn(("texto", '- tapOn: "R$ 10,00 \\"promo\\""'), sug)
        j = self.nos.index(next(n for n in self.nos if n["bounds"] == (0, 760, 720, 820)))
        self.assertIn("index: 1", S.seletores(self.nos, j, (720, 1280))[0][1])

    def test_view_nativa_e_campo(self):
        i = self._idx("com.exemplo.app:id/campo")
        sug = dict(S.seletores(self.nos, i, (720, 1280)))
        self.assertEqual(sug["id"], '- tapOn:\n    id: "campo"')
        self.assertIn("digitar no campo", sug)

    def test_texto_do_filho_quando_clica_no_botao(self):
        i = self._idx("button-teste-conexao")
        self.assertIn(("texto", '- tapOn: "Conexão com a internet"'), S.seletores(self.nos, i, (720, 1280)))

    def test_ler_tela_com_plano_b(self):
        chamadas = []

        def rodar(cmd, timeout=0):
            chamadas.append(cmd[-1])
            if cmd[-1].startswith("uiautomator dump /dev/tty"):
                return 0, "", "dump para /dev/tty nao suportado"
            return 0, XML, ""

        nos, erro = S.ler_tela(rodar, "adb", "x")
        self.assertEqual(erro, "")
        self.assertEqual(len(nos), len(self.nos))
        self.assertEqual(len(chamadas), 2)

    def test_ler_tela_falha(self):
        nos, erro = S.ler_tela(lambda cmd, timeout=0: (1, "ERROR: could not get idle state.", ""), "adb", "x")
        self.assertIsNone(nos)
        self.assertIn("idle state", erro)


if __name__ == "__main__":
    unittest.main(verbosity=1)
