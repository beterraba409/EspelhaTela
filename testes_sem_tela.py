# -*- coding: utf-8 -*-
"""Verificacoes sem tela e sem aparelho: python testes_sem_tela.py"""

import os
import socket
import sys
import tempfile
import threading
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adb_servidor as A  # noqa: E402
import seletor as S  # noqa: E402
import transferencia as T  # noqa: E402

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


try:
    import av  # noqa: E402
    from PIL import Image  # noqa: E402
    import espelha_tela as E  # noqa: E402
except ImportError:  # sem PyAV/Pillow: as verificacoes do video ficam de fora
    E = None


@unittest.skipIf(E is None, "PyAV ou Pillow ausentes")
class Video(unittest.TestCase):
    def _cap(self):
        return E.Captura("adb", "x", 0.1)

    def _quadro(self, w=32, h=64):
        img = Image.new("RGB", (w, h), (200, 30, 30))
        return av.VideoFrame.from_image(img).reformat(format="yuv420p")

    def test_quadro_do_video_so_converte_quando_pedido(self):
        cap = self._cap()
        self.assertIsNone(cap.tamanho)
        fr = self._quadro()
        cap._av = fr  # como o leitor do video faz
        self.assertEqual(cap.tamanho, (32, 64))
        self.assertIsNone(cap._img)  # saber o tamanho nao converte nada
        img = cap.frame
        self.assertEqual(img.size, (32, 64))
        self.assertIs(cap.frame, img)  # mesmo quadro: conversao reaproveitada
        cap._av = self._quadro()
        self.assertIsNot(cap.frame, img)  # quadro novo: conversao nova

    def test_imagem_ja_sai_no_tamanho_da_janela(self):
        cap = self._cap()
        cap._av = self._quadro()
        ampliada = cap.imagem(64, 128)
        reduzida = cap.imagem(8, 16)
        self.assertEqual((ampliada.size, reduzida.size), ((64, 128), (8, 16)))
        r, g, b = ampliada.getpixel((30, 60))
        self.assertTrue(r > 150 and g < 80 and b < 80, (r, g, b))  # cor preservada na conversao YUV -> RGB

    def test_modo_quadros_continua_com_pil(self):
        cap = self._cap()
        cap._av = self._quadro()
        cap.frame = Image.new("RGB", (10, 20))  # o modo quadros grava uma PIL.Image e descarta o video
        self.assertEqual(cap.tamanho, (10, 20))
        self.assertEqual(cap.imagem(20, 40).size, (20, 40))
        cap.frame = None
        self.assertIsNone(cap.tamanho)
        self.assertIsNone(cap.imagem(20, 40))

    def test_video_que_falhou_e_tentado_de_novo(self):
        cap = self._cap()
        cap.modo = "video"
        self.assertFalse(cap._hora_de_tentar_video())  # nunca falhou
        cap.video_ok, cap.falhas_video, cap.t_falha_video = False, 1, E.time.time()
        self.assertFalse(cap._hora_de_tentar_video())  # acabou de falhar
        cap.t_falha_video -= 31
        self.assertTrue(cap._hora_de_tentar_video())  # 30 s depois
        esperas = []
        for n in (1, 2, 3, 4, 9):
            cap.falhas_video = n
            esperas.append(cap.espera_video())
        self.assertEqual(esperas, [30, 60, 120, 240, 300])
        cap.modo = "quadros"  # quem escolheu quadros nao recebe video a forca
        self.assertFalse(cap._hora_de_tentar_video())

    def test_trocar_de_aparelho_zera_a_falha(self):
        cap = self._cap()
        cap.video_ok, cap.falhas_video = False, 3
        cap.trocar("outro")
        self.assertTrue(cap.video_ok)
        self.assertEqual(cap.falhas_video, 0)


@unittest.skipIf(E is None, "PyAV ou Pillow ausentes")
class Dados(unittest.TestCase):
    def test_configuracao_da_pasta_antiga_vem_junto(self):
        with tempfile.TemporaryDirectory() as base:
            os.makedirs(os.path.join(base, "EspelhaTela"))
            with open(os.path.join(base, "EspelhaTela", "config.json"), "w", encoding="utf-8") as f:
                f.write('{"adb_porta": 5037}')
            antes = os.environ.get("APPDATA")
            os.environ["APPDATA"] = base
            try:
                self.assertEqual(E.carregar_config(), {"adb_porta": 5037})  # copiada para %APPDATA%\Vision
                self.assertTrue(os.path.isfile(os.path.join(base, "Vision", "config.json")))
                E.salvar_config({"adb_porta": 5038})  # a partir dai so a pasta nova e usada
                self.assertEqual(E.carregar_config(), {"adb_porta": 5038})
            finally:
                if antes is None:
                    del os.environ["APPDATA"]
                else:
                    os.environ["APPDATA"] = antes


import atualizacao as U  # noqa: E402


class Atualizacao(unittest.TestCase):
    RELEASES = [
        {"tag_name": "v1.3", "name": "Vision 1.3", "draft": True, "assets": [{"name": "Vision-Setup-1.3.exe"}]},
        {"tag_name": "v1.10", "name": "Vision 1.10", "body": " novidades ", "html_url": "https://x/v1.10",
         "assets": [{"name": "Vision-1.10.zip"}, {"name": "Vision-Setup-1.10.exe", "size": 9, "url": "https://api/a/1",
                                                    "browser_download_url": "https://dl/Vision-Setup-1.10.exe"}]},
        {"tag_name": "v1.9", "assets": [{"name": "Vision-Setup-1.9.exe"}]},
        {"tag_name": "v2.0", "assets": [{"name": "Vision-2.0.zip"}]},  # sem instalador: nao serve
        {"tag_name": "outro-v9.0", "assets": [{"name": "Vision-Setup-9.0.exe"}]},  # outro utilitario do repo
    ]

    def test_versoes(self):
        self.assertTrue(U.mais_nova("1.10", "1.9"))
        self.assertTrue(U.mais_nova("v1.2.1", "1.2"))
        self.assertFalse(U.mais_nova("1.2", "1.2"))
        self.assertFalse(U.mais_nova("", "1.0"))

    def test_escolhe_a_mais_nova_publicada_com_instalador(self):
        r = U.escolhe_release(self.RELEASES, "v", "Vision-Setup-")
        self.assertEqual((r["versao"], r["arquivo"], r["notas"]), ("1.10", "Vision-Setup-1.10.exe", "novidades"))
        self.assertEqual(r["url_publica"], "https://dl/Vision-Setup-1.10.exe")
        self.assertIsNone(U.escolhe_release(self.RELEASES, "vision-v", "Vision-SmartPOS-Setup-"))

    def test_token_nao_segue_para_outro_servidor(self):
        h = U.SemTokenNoRedirecionamento()
        req = U._pedido("https://api.github.com/repos/a/b/releases/assets/1", "segredo", "application/octet-stream")
        mesmo = h.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/outro")
        fora = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/x")
        self.assertIn("Authorization", mesmo.headers)
        self.assertNotIn("Authorization", fora.headers)
        self.assertNotIn("Authorization", fora.unredirected_hdrs)


@unittest.skipIf(E is None, "PyAV ou Pillow ausentes")
class OutroProcesso(unittest.TestCase):
    def test_ambiente_limpo_tira_as_variaveis_do_pyinstaller(self):
        antes = dict(os.environ)
        os.environ.update({"_PYI_APPLICATION_HOME_DIR": "C:/sumiu", "_MEIPASS2": "C:/sumiu", "PATH_TESTE": "fica"})
        try:
            amb = E.ambiente_limpo()
        finally:
            os.environ.clear()
            os.environ.update(antes)
        self.assertNotIn("_PYI_APPLICATION_HOME_DIR", amb)
        self.assertNotIn("_MEIPASS2", amb)
        self.assertEqual(amb["PATH_TESTE"], "fica")
        self.assertEqual(amb["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_ajudante_espera_para_e_so_depois_instala(self):
        cmd = E.comando_de_instalacao("C:/Temp/Vision-Setup-9.9.exe", "C:/Program Files/O'Vision/Vision.exe", [10, 20, 0])
        self.assertEqual(cmd[0], "powershell.exe")
        script = cmd[-1]
        espera, para, instala = script.index("Wait-Process -Id 10,20"), script.index("Stop-Process -Force"), script.index("Start-Process")
        self.assertTrue(espera < para < instala)  # nesta ordem
        self.assertIn("'C:/Program Files/O''Vision/Vision.exe'", script)  # aspas simples escapadas
        self.assertIn("'/SILENT','/SUPPRESSMSGBOXES','/NORESTART'", script)


import apk as K  # noqa: E402

APK_REAL = r"C:\codigos_fontes\automacao-maestro\scripts\apks\Getnet P2-A7\getnet-linx-postos-smartpos.1.17.0.2026-09-21_17-40.apk"


class Apk(unittest.TestCase):
    def test_versao_no_aparelho(self):
        saida = "    versionCode=11701000 minSdk=24 targetSdk=34\n    versionName=1.17.1\n    versionCode=1 minSdk=1\n"
        self.assertEqual(K.versao_no_aparelho(saida), ("1.17.1", 11701000))  # a primeira e a que vale
        self.assertEqual(K.versao_no_aparelho(""), (None, None))

    def test_tipo_de_mudanca(self):
        self.assertEqual(K.tipo_de_mudanca(47, None), "nova")
        self.assertEqual(K.tipo_de_mudanca(47, 46), "atualizacao")
        self.assertEqual(K.tipo_de_mudanca(47, 47), "mesma")
        self.assertEqual(K.tipo_de_mudanca(46, 47), "downgrade")

    def test_manifesto_invalido(self):
        with self.assertRaises(ValueError):
            K.le_manifesto(b"<manifest/>")

    @unittest.skipUnless(os.path.isfile(APK_REAL), "APK de exemplo ausente nesta maquina")
    def test_apk_real_igual_ao_aapt(self):
        i = K.le_apk(APK_REAL)  # conferido com: aapt2 dump badging
        self.assertEqual((i["pacote"], i["versao"], i["codigo"]), ("com.smartposv2.getnet", "1.17.0", 11700000))
        self.assertEqual(K.le_apks([APK_REAL])["pacote"], "com.smartposv2.getnet")


import diagnostico_video as DV  # noqa: E402


class DiagnosticoVideo(unittest.TestCase):
    def _registro(self):
        self.t = [1000.0]
        pasta = tempfile.mkdtemp()
        self.arq = os.path.join(pasta, "video.log")
        return DV.RegistroVideo(self.arq, relogio=lambda: self.t[0])

    def _texto(self):
        return open(self.arq, encoding="utf-8").read() if os.path.isfile(self.arq) else ""

    def test_pausa_depois_de_toque_vem_do_aparelho(self):
        r = self._registro()
        r.quadro(2)
        r.toque()
        self.t[0] += 0.8  # 0,8 s sem quadro logo depois do toque, sem video esperando no PC
        r.quadro(2, fila_bytes=0)
        self.assertIn("RESPOSTA LENTA: 0.8 s", self._texto())
        self.assertIn("aparelho", self._texto())

    def test_pausa_com_video_acumulado_e_do_pc(self):
        r = self._registro()
        r.quadro(2)
        r.toque()
        self.t[0] += 0.6
        r.quadro(80, fila_bytes=300 * 1024)
        self.assertIn("PC: havia 300 KB", self._texto())

    def test_tela_parada_sem_toque_nao_e_travada(self):
        r = self._registro()
        r.quadro(2)
        self.t[0] += 5  # ninguem tocou: tela parada nao manda quadro, e isso e normal
        r.quadro(2)
        self.assertNotIn("PAUSA", self._texto())

    def test_resumo_a_cada_10_s(self):
        r = self._registro()
        for _ in range(30):
            self.t[0] += 0.05
            r.quadro(3)
        r.desenhou(4)
        self.t[0] += 10
        r.periodico()
        self.assertIn("resumo", self._texto())
        self.assertIn("30 quadros", self._texto())


class DiagnosticoAparelho(unittest.TestCase):
    def _registro(self):
        self.t = [1000.0]
        self.arq = os.path.join(tempfile.mkdtemp(), "video.log")
        return DV.RegistroVideo(self.arq, relogio=lambda: self.t[0])

    def _texto(self):
        return open(self.arq, encoding="utf-8").read() if os.path.isfile(self.arq) else ""

    def test_tela_parada_e_depois_toque_mede_so_a_resposta(self):
        r = self._registro()
        r.quadro(2)
        self.t[0] += 30  # 30 s de tela parada (normal)
        r.toque()
        self.t[0] += 0.5  # o aparelho respondeu em 0,5 s
        r.quadro(2)
        self.assertIn("RESPOSTA LENTA: 0.5 s", self._texto())
        self.assertNotIn("30.", self._texto())

    def test_toque_sem_mudanca_na_tela_nao_e_travada(self):
        r = self._registro()
        r.quadro(2)
        r.toque()
        self.t[0] += 8
        r.quadro(2)
        self.assertIn("toque sem mudanca", self._texto())
        self.assertNotIn("RESPOSTA LENTA", self._texto())

    def test_uso_recente(self):
        r = self._registro()
        self.assertFalse(r.teve_uso())
        r.toque()
        self.assertTrue(r.teve_uso())
        self.t[0] += 20
        self.assertFalse(r.teve_uso())

    def test_amostra_do_aparelho(self):
        saida = ("##pkg com.smartposv2.linxtef\nTotal frames rendered: 240\nJanky frames: 30 (12.50%)\n##top\n"
                 "12.5 surfaceflinger\n 9.3 com.smartposv2.linxtef\n 3.1 screenrecord --output-format=h264 -\n"
                 " 0.0 grep -E screenrecord|surfaceflinger|com.smartposv2.linxtef\n"
                 " 5.0 sh -c screenrecord '--output-format=h264'\n")
        pkg, quadros, cpu = DV.le_amostra(saida)
        self.assertEqual(pkg, "com.smartposv2.linxtef")
        self.assertEqual(quadros, (240, 30))
        self.assertEqual(cpu, {"surfaceflinger": 12.5, "com.smartposv2.linxtef": 9.3, "screenrecord": 3.1})  # sem o grep e o sh

    def test_codificadores(self):
        xml = ('<MediaCodecs><Encoders>'
               '<MediaCodec name="OMX.qcom.video.encoder.avc" type="video/avc"><Limit name="size"/></MediaCodec>'
               '<MediaCodec name="c2.android.avc.encoder"><Type name="video/avc"/></MediaCodec>'
               '<MediaCodec name="OMX.qcom.video.encoder.hevc" type="video/hevc"/>'
               '</Encoders><Decoders><MediaCodec name="OMX.qcom.video.decoder.avc" type="video/avc"/></Decoders></MediaCodecs>')
        self.assertEqual(DV.codificadores_h264(xml), [("OMX.qcom.video.encoder.avc", False), ("c2.android.avc.encoder", True)])


class CodificadorEmUso(unittest.TestCase):
    CONHECIDOS = {"c2.android.avc.encoder": True, "OMX.MTK.VIDEO.ENCODER.AVC": False}

    def test_le_o_codificador_do_logcat(self):
        saida = ("11-10 16:02:11.909 20198 20198 I MediaCodec: (0xaf1c9000) init name(OMX.MTK.VIDEO.ENCODER.AVC)\n"
                 "11-10 16:02:12.226 20198 20200 I MediaCodec: (0xaf1c9000) Component Allocated (OMX.MTK.VIDEO.ENCODER.AVC)\n")
        self.assertEqual(DV.codificador_em_uso(saida, self.CONHECIDOS), "OMX.MTK.VIDEO.ENCODER.AVC")

    def test_codec2(self):
        saida = "I CCodec  : Created component [c2.android.avc.encoder]\n"
        self.assertEqual(DV.codificador_em_uso(saida, self.CONHECIDOS), "c2.android.avc.encoder")

    def test_logcat_restrito(self):
        self.assertIsNone(DV.codificador_em_uso("", self.CONHECIDOS))
        self.assertIsNone(DV.codificador_em_uso("I MediaCodec: init name(outro.codec)", self.CONHECIDOS))


TELA_TEXTOS = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="app" content-desc="" bounds="[0,0][720,1280]">
<node index="0" text="Serial: 4AG602S0G" resource-id="" class="android.widget.TextView" package="app" content-desc="" bounds="[40,1200][680,1240]" />
<node index="1" text="Bem-vindo" resource-id="" class="android.widget.TextView" package="app" content-desc="" bounds="[40,100][400,150]" />
<node index="2" text="" resource-id="button-iniciar" class="android.view.ViewGroup" package="app" content-desc="" clickable="true" bounds="[40,300][680,500]">
<node index="0" text="Iniciar Atendimento" resource-id="" class="android.widget.TextView" package="app" content-desc="" bounds="[100,420][620,470]" />
</node>
<node index="3" text="" resource-id="" class="android.widget.ImageView" package="app" content-desc="Fechar" bounds="[620,100][700,180]" />
</node>
</hierarchy>"""


class CopiarTextos(unittest.TestCase):
    def setUp(self):
        self.nos = S.le_nos(TELA_TEXTOS)

    def test_texto_sob_o_mouse(self):
        self.assertEqual(S.textos_no_ponto(self.nos, 300, 1220), ["Serial: 4AG602S0G"])

    def test_botao_com_texto_no_filho(self):
        # clique na area do botao, fora do texto: o texto do filho vem junto
        self.assertEqual(S.textos_no_ponto(self.nos, 60, 320), ["Iniciar Atendimento"])

    def test_icone_so_com_descricao(self):
        self.assertEqual(S.textos_no_ponto(self.nos, 650, 140), ["Fechar"])

    def test_ponto_sem_texto(self):
        self.assertEqual(S.textos_no_ponto(self.nos, 10, 700), [])

    def test_todo_o_texto_em_ordem_de_leitura(self):
        self.assertEqual(S.texto_da_tela(self.nos).split(chr(10)), ["Bem-vindo", "Iniciar Atendimento", "Serial: 4AG602S0G"])


class Transferencias(unittest.TestCase):
    def test_tamanho_de_arquivo_e_de_pasta(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "sub"))
            for nome, n in (("a.txt", 10), (os.path.join("sub", "b.bin"), 2500)):
                with open(os.path.join(d, nome), "wb") as f:
                    f.write(b"x" * n)
            self.assertEqual(T.tamanho_local(os.path.join(d, "a.txt")), 10)
            self.assertEqual(T.tamanho_local(d), 2510)
            self.assertEqual(T.tamanho_local(os.path.join(d, "nao-existe")), 0)

    def test_conflitos_pelo_nome(self):
        self.assertEqual(T.conflitos(["log.txt", "Download"], ["C:/pc/log.txt", "C:/pc/novo.apk", "C:/pc/Download/"]),
                         ["log.txt", "Download"])

    def test_texto_do_progresso(self):
        fmt = lambda n: "%d B" % n  # noqa: E731
        self.assertEqual(T.texto_progresso("Baixando", 2, 3, "log.txt", 30, 100, fmt), "Baixando 2 de 3: log.txt  -  30 B de 100 B (30%)")
        self.assertEqual(T.texto_progresso("Enviando", 1, 1, "a.apk", 0, 0, fmt), "Enviando a.apk")
        self.assertEqual(T.porcentagem(150, 100), 100)

    def _adb_falso(self, d, codigo):
        script = os.path.join(d, "adb_falso.py")
        with open(script, "w") as f:
            f.write(chr(10).join(["import sys", "print('erro de teste: ' + sys.argv[-1])", "sys.exit(%d)" % codigo, ""]))
        cmd = os.path.join(d, "adb.cmd")
        with open(cmd, "w") as f:
            f.write('@"%s" "%s" %%*' % (sys.executable, script) + chr(10))
        return cmd

    def _roda(self, codigo):
        with tempfile.TemporaryDirectory() as d:
            eventos, pronto = [], threading.Event()

            def avisa(ev, dados):
                eventos.append((ev, dados))
                if ev == "fim":
                    pronto.set()

            copias = [T.Copia(["pull", "/sdcard/x", "dest%d" % i], "x%d" % i, 100, lambda: 50) for i in (1, 2)]
            T.Transferencia(self._adb_falso(d, codigo), "serial", copias, avisa).iniciar()
            self.assertTrue(pronto.wait(30))
            return eventos

    def test_copia_completa_soma_o_total(self):
        eventos = self._roda(0)
        self.assertEqual(eventos[-1], ("fim", ([], False)))
        ultimo = [d for e, d in eventos if e == "andamento"][-1]
        self.assertEqual(ultimo[5:], (200, 200))

    def test_falha_traz_a_mensagem_do_adb(self):
        falhas, cancelado = self._roda(1)[-1][1]
        self.assertEqual(falhas, ["x1: erro de teste: dest1", "x2: erro de teste: dest2"])
        self.assertFalse(cancelado)


class UltimoQuadro(unittest.TestCase):
    """Com a tela do aparelho parada, o ultimo quadro (o estado atual da tela) tem que aparecer."""

    def test_codigo_de_inicio_do_h264(self):
        import diagnostico_video as D
        self.assertTrue(D.comeca_com_inicio_de_quadro(bytes([0, 0, 0, 1, 0x65])))
        self.assertTrue(D.comeca_com_inicio_de_quadro(bytes([0, 0, 1, 0x41])))
        self.assertFalse(D.comeca_com_inicio_de_quadro(bytes([0x88, 0, 0, 1])))

    def test_tres_quadros_e_tela_parada_mostra_os_tres(self):
        import fractions
        import subprocess
        import time
        import av
        import numpy as np
        import espelha_tela as E
        enc = av.CodecContext.create("libx264", "w")
        enc.width, enc.height, enc.pix_fmt = 320, 240, "yuv420p"
        enc.time_base = fractions.Fraction(1, 30)
        enc.options = {"tune": "zerolatency", "preset": "ultrafast"}
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                fr = av.VideoFrame.from_ndarray(np.full((240, 320, 3), 60 * i, np.uint8), format="rgb24").reformat(format="yuv420p")
                fr.pts = i
                with open(os.path.join(d, "q%d.h264" % i), "wb") as f:
                    f.write(b"".join(bytes(p) for p in enc.encode(fr)))
            falso = os.path.join(d, "aparelho.py")
            with open(falso, "w") as f:
                f.write(chr(10).join([
                    "import os, sys, time",
                    "for i in range(3):",
                    "    sys.stdout.buffer.write(open(os.path.join(%r, 'q%%d.h264' %% i), 'rb').read())" % d,
                    "    sys.stdout.flush()",
                    "    time.sleep(0.3)",
                    "time.sleep(3)", ""]))
            original = E.subprocess.Popen
            E.subprocess.Popen = lambda cmd, **k: original([sys.executable, falso], **k)
            try:
                cap = E.Captura("adb", "falso", 0.05)
                fluxo = cap._abre_fluxo("falso", None, "4M")
                cap._fluxo_ativo = fluxo
                time.sleep(2.0)
                self.assertEqual(fluxo["frames"], 3)
                self.assertEqual(fluxo["cortados"], 0)
                fluxo["proc"].kill()
                fluxo["proc"].wait(5)
                fluxo["proc"].stdout.close()
                fluxo["proc"].stderr.close()
            finally:
                E.subprocess.Popen = original


class GravarTela(unittest.TestCase):
    def _grava(self, formato):
        import av
        import numpy as np
        import gravacao as G
        fim = threading.Event()
        with tempfile.TemporaryDirectory() as d:
            g = G.Gravacao(os.path.join(d, "t." + formato), formato, lambda c, e, m: fim.set())
            for i in range(20):
                img = np.zeros((641, 287, 3), np.uint8)
                img[:, :i * 10] = 200
                g.quadro(av.VideoFrame.from_ndarray(img, format="rgb24"))
                g.t_ultimo = -1.0  # sem esperar o intervalo entre quadros
            g.parar()
            self.assertTrue(fim.wait(30))
            self.assertEqual(g.erro, "")
            with av.open(g.caminho) as ct:
                s = ct.streams.video[0]
                n = sum(1 for _ in ct.decode(s))
            self.assertEqual(g.gravados + g.pulados, 21)  # 20 quadros + o ultimo repetido no fim; fila cheia pula, nunca trava
            self.assertEqual(n, g.gravados)
            return s.codec_context.name, s.width, s.height, n

    def test_mp4_h264_com_lados_pares(self):
        nome, larg, alt, n = self._grava("mp4")
        self.assertEqual((nome, larg, alt), ("h264", 286, 640))
        self.assertGreater(n, 1)

    def test_gif_animado(self):
        nome, larg, alt, n = self._grava("gif")
        self.assertEqual((nome, larg, alt), ("gif", 287, 641))
        self.assertGreater(n, 1)

    def test_tempo_no_rodape(self):
        import gravacao as G
        self.assertEqual(G.nome_do_tempo(75.4), "01:15")


class JanelaDeGravacao(unittest.TestCase):
    def test_extensao_segue_o_formato(self):
        import janela_gravacao as J
        p = os.path.join("C:" + os.sep, "videos")
        self.assertEqual(J.caminho_final(p, "teste.mp4", "gif"), os.path.join(p, "teste.gif"))
        self.assertEqual(J.caminho_final(p, "teste", "mp4"), os.path.join(p, "teste.mp4"))
        self.assertEqual(J.caminho_final(p, "a:b?c", "mp4"), os.path.join(p, "a_b_c.mp4"))
        self.assertEqual(J.caminho_final(p, "   ", "gif"), os.path.join(p, "gravacao.gif"))

    def test_nome_sugerido(self):
        import datetime
        import janela_gravacao as J
        self.assertEqual(J.nome_sugerido("192.168.1.6:5555", datetime.datetime(2026, 11, 11, 15, 48, 34)),
                         "gravacao-192.168.1.6_5555-20261111-154834")


class PareamentoWifi(unittest.TestCase):
    MDNS = chr(10).join([
        "List of discovered mdns services",
        "adb-4AG602S0G-xYz12\t_adb-tls-pairing._tcp.\t192.168.1.20:37451",
        "adb-4AG602S0G-xYz12\t_adb-tls-connect._tcp.\t192.168.1.20:41235",
        "adb-OUTRO-aa\t_adb-tls-connect._tcp.\t192.168.1.30:40000",
    ])

    def test_porta_de_conexao_do_mesmo_ip(self):
        import janela_wifi as W
        self.assertEqual(W.porta_de_conexao(self.MDNS, "192.168.1.20"), "192.168.1.20:41235")
        self.assertIsNone(W.porta_de_conexao(self.MDNS, "192.168.1.99"))

    def test_enderecos(self):
        import janela_wifi as W
        self.assertTrue(W.endereco_valido("192.168.1.20"))
        self.assertFalse(W.endereco_valido("192.168.1.20", exige_porta=True))
        self.assertFalse(W.endereco_valido("300.1.1.1:5555"))
        self.assertTrue(W.pareou("Successfully paired to 192.168.1.20:37451 [guid=adb-4AG602S0G-xYz12]"))

    def test_parear_e_conectar_acha_a_porta_sozinho(self):
        import janela_wifi as W
        chamadas = []

        def rodar(cmd, timeout=0):
            chamadas.append(cmd[1:])
            if cmd[1] == "pair":
                return 0, "Successfully paired to 192.168.1.20:37451", ""
            if cmd[1] == "mdns":
                return 0, self.MDNS, ""
            return 0, "connected to 192.168.1.20:41235", ""

        self.assertEqual(W.parear_e_conectar(rodar, "adb", "192.168.1.20:37451", "123456"),
                         ("192.168.1.20:41235", "conectado em 192.168.1.20:41235"))
        self.assertEqual(chamadas[0], ["pair", "192.168.1.20:37451", "123456"])

    def test_codigo_errado(self):
        import janela_wifi as W
        rodar = lambda cmd, timeout=0: (1, "", "Failed: Wrong password or connection was dropped.")  # noqa: E731
        end, msg = W.parear_e_conectar(rodar, "adb", "192.168.1.20:37451", "000000")
        self.assertIsNone(end)
        self.assertIn("Wrong password", msg)


class LogcatAoVivo(unittest.TestCase):
    def test_linha_do_logcat(self):
        import janela_logcat as L
        i = L.parse_linha("11-11 16:01:02.345  1234  1250 E ReactNativeJS: Placa nao encontrada")
        self.assertEqual((i["pid"], i["nivel"], i["tag"], i["msg"]), (1234, "E", "ReactNativeJS", "Placa nao encontrada"))
        self.assertIsNone(L.parse_linha("--------- beginning of main"))

    def test_filtros(self):
        import janela_logcat as L
        i = L.parse_linha("11-11 16:01:02.345  1234  1250 W Rede: tempo esgotado")
        self.assertTrue(L.passa(i, "D", None, ""))
        self.assertFalse(L.passa(i, "E", None, ""))
        self.assertTrue(L.passa(i, "V", {1234}, "ESGOTADO"))
        self.assertFalse(L.passa(i, "V", {999}, ""))
        self.assertFalse(L.passa(i, "V", set(), ""))  # app escolhido que nao esta rodando


class ReportarBug(unittest.TestCase):
    def test_nome_da_pasta(self):
        import datetime
        import janela_bug as B
        self.assertEqual(B.nome_pasta("Placa não encontrada: sem retorno!", datetime.datetime(2026, 11, 11, 16, 20)),
                         "2026-11-11_1620-placa-nao-encontrada-sem-retorno")

    def test_texto_do_card(self):
        import datetime
        import janela_bug as B
        props = B.le_getprop(chr(10).join(["ro.product.manufacturer=Positivo", "ro.product.model=L400",
                                           "ro.build.version.release=11", "ro.build.version.sdk=30", "ro.serialno=4AG602S0G"]))
        amb = B.ambiente_de(props, "4AG602S0G", "com.smartposv2.rede", "1.0.47 (código 147)", datetime.datetime(2026, 11, 11, 16, 20, 33), "2.2")
        self.assertEqual(amb[0], "Aparelho: Positivo L400 (Android 11, SDK 30), serial 4AG602S0G")
        t = B.texto_bug("Placa não encontrada", {"descricao": "Leitura de placa", "obtido": "Nada aparece"}, amb, ["print.png"])
        for trecho in ("**Placa não encontrada**", "**Teste realizado**" + chr(10) + "-", "**Resultado obtido**" + chr(10) + "Nada aparece",
                       "- App em primeiro plano: com.smartposv2.rede 1.0.47 (código 147)", "**Anexos:** print.png"):
            self.assertIn(trecho, t)

    def test_zip_com_os_arquivos(self):
        import zipfile
        import janela_bug as B
        with tempfile.TemporaryDirectory() as d:
            pasta = os.path.join(d, "bug")
            os.makedirs(pasta)
            for n in ("bug.md", "logcat.txt"):
                with open(os.path.join(pasta, n), "w") as f:
                    f.write("x")
            with zipfile.ZipFile(B.compacta(pasta)) as z:
                self.assertEqual(sorted(z.namelist()), ["bug.md", "logcat.txt"])


class UltimosSegundos(unittest.TestCase):
    def test_guarda_so_a_janela_e_vira_mp4(self):
        import time
        import av
        from PIL import Image
        import recentes as R
        m = R.UltimosSegundos(segundos=1.0, fps=50)
        for i in range(40):
            m.quadro(Image.new("RGB", (305, 641), (i * 6, 0, 0)))
            time.sleep(0.04)
        time.sleep(0.3)
        q = m.congela()
        self.assertTrue(q)
        self.assertLessEqual(q[-1][0] - q[0][0], 1.0 + 1e-6)  # so o ultimo segundo
        self.assertEqual(Image.open(__import__("io").BytesIO(q[0][1])).height, R.ALTURA_MAX)
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "v.mp4")
            R.salva_mp4(q, c, ate=q[-1][0] + 2.0)
            with av.open(c) as ct:
                s = ct.streams.video[0]
                self.assertEqual((s.codec_context.name, s.height % 2, s.width % 2), ("h264", 0, 0))
                self.assertGreater(float(ct.duration) / 1e6, 2.5)  # a tela do clique fica no fim


class SoltarApk(unittest.TestCase):
    def test_apps_diferentes_um_apos_o_outro(self):
        import espelha_tela as E
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.apk"), os.path.join(d, "b.apk")
            for c in (a, b):
                open(c, "wb").close()  # nao e APK valido: cada um vai sozinho
            self.assertEqual(E.grupos_de_apks([a, b]), [[a], [b]])


class Configuracoes(unittest.TestCase):
    def test_ferramentas_ocultas_salvas(self):
        import janela_config as C
        chaves = {"bug", "seletor", "memoria"}
        self.assertEqual(C.ocultas_do_config({"ferramentas_ocultas": ["seletor", "sumiu"]}, chaves), {"seletor"})
        self.assertEqual(C.ocultas_do_config({}, chaves), set())
        self.assertEqual(C.ocultas_do_config({"ferramentas_ocultas": None}, chaves), set())


REPO_FALSO = """<?xml version="1.0"?>
<sdk:sdk-repository xmlns:sdk="http://schemas.android.com/sdk/android/repo/repository2/03">
<license id="android-sdk-license" type="text">Termos de teste</license>
<channel id="channel-0">stable</channel>
<remotePackage path="emulator"><revision><major>37</major><minor>1</minor><micro>0</micro></revision>
<uses-license ref="android-sdk-license"/><channelRef ref="channel-1"/>
<archives><archive><complete><size>10</size><checksum type="sha1">aa</checksum><url>emu-beta.zip</url></complete><host-os>windows</host-os><host-arch>x64</host-arch></archive></archives></remotePackage>
<remotePackage path="emulator"><revision><major>36</major><minor>4</minor><micro>9</micro></revision>
<uses-license ref="android-sdk-license"/><channelRef ref="channel-0"/>
<archives><archive><complete><size>20</size><checksum type="sha1">bb</checksum><url>emu-linux.zip</url></complete><host-os>linux</host-os></archive>
<archive><complete><size>30</size><checksum type="sha1">cc</checksum><url>emu-win.zip</url></complete><host-os>windows</host-os><host-arch>x64</host-arch></archive></archives></remotePackage>
<remotePackage path="system-images;android-30;google_apis;x86_64"><type-details><api-level>30</api-level><tag><id>google_apis</id></tag></type-details>
<revision><major>16</major></revision><uses-license ref="android-sdk-license"/><channelRef ref="channel-0"/>
<archives><archive><complete><size>40</size><checksum type="sha1">dd</checksum><url>x86_64-30_r16.zip</url></complete></archive></archives></remotePackage>
</sdk:sdk-repository>"""


class Emuladores(unittest.TestCase):
    def test_repositorio_escolhe_o_estavel_do_windows(self):
        import emulador_sdk as S
        r = S.le_repositorio(REPO_FALSO)
        emu = r["pacotes"]["emulator"]
        self.assertEqual((emu["canal"], emu["revisao"], emu["url"], emu["size"]), ("channel-0", (36, 4, 9), "emu-win.zip", 30))
        img = r["pacotes"]["system-images;android-30;google_apis;x86_64"]
        self.assertEqual((img["api"], img["tag"], img["url"]), (30, "google_apis", "x86_64-30_r16.zip"))
        self.assertEqual(r["licencas"]["android-sdk-license"], "Termos de teste")

    def test_imagem_incompleta_sem_kernel(self):
        import emulador_sdk as S
        with tempfile.TemporaryDirectory() as d:
            p = S.pasta_imagem(d, 30)
            os.makedirs(p)
            open(os.path.join(p, "system.img"), "wb").close()
            self.assertFalse(S.imagem_completa(d, 30))
            open(os.path.join(p, "kernel-ranchu"), "wb").close()
            self.assertTrue(S.imagem_completa(d, 30))

    def test_download_continua_e_confere_o_checksum(self):
        import hashlib
        import http.server
        import emulador_sdk as S
        dados = os.urandom(300000)

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                ini = int(self.headers.get("Range", "bytes=0-")[6:].split("-")[0] or 0)
                self.send_response(206 if ini else 200)
                self.send_header("Content-Length", str(len(dados) - ini))
                self.end_headers()
                self.wfile.write(dados[ini:])

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/x.zip" % srv.server_port
        try:
            with tempfile.TemporaryDirectory() as d:
                destino = os.path.join(d, "x.zip")
                with open(destino + ".part", "wb") as f:
                    f.write(dados[:100000])  # tentativa anterior interrompida
                vistos = []
                S.baixa(url, destino, hashlib.sha1(dados).hexdigest(), len(dados), lambda f, t: vistos.append(f))
                self.assertEqual(open(destino, "rb").read(), dados)
                self.assertGreaterEqual(vistos[0], 100000)  # continuou de onde parou
                os.remove(destino)
                with self.assertRaises(ValueError):
                    S.baixa(url, destino, "0" * 40, len(dados))
                self.assertFalse(os.path.exists(destino + ".part"))  # corrompido: apaga
        finally:
            srv.shutdown()

    def test_extrai_tira_a_pasta_de_cima(self):
        import emulador_sdk as S
        with tempfile.TemporaryDirectory() as d:
            z = os.path.join(d, "img.zip")
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("x86_64/system.img", "s")
                zf.writestr("x86_64/data/a.txt", "a")
            S.extrai(z, os.path.join(d, "destino"))
            self.assertEqual(sorted(os.listdir(os.path.join(d, "destino"))), ["data", "system.img"])

    def test_criar_listar_e_excluir_avd(self):
        import emulador_avd as A
        with tempfile.TemporaryDirectory() as d:
            nome = A.sugere_nome("smartpos", 30, set())
            self.assertEqual(nome, "vision-smartpos-android11")
            A.cria(nome, "smartpos", 30, pasta=d)
            cfg = A.le_ini(os.path.join(d, nome + ".avd", "config.ini"))
            self.assertEqual((cfg["hw.lcd.width"], cfg["hw.lcd.height"], cfg["image.sysdir.1"]), ("720", "1280", "system-images\\android-30\\google_apis\\x86_64\\"))
            with self.assertRaises(ValueError):
                A.cria(nome, "smartpos", 30, pasta=d)
            [a] = A.lista(d)
            self.assertEqual((a["nome"], a["perfil"], a["api"], a["do_vision"]), (nome, "smartpos", 30, True))
            self.assertEqual(A.sugere_nome("smartpos", 30, {nome}), nome + "-2")
            os.makedirs(os.path.join(a["pasta"], "snapshots", "logado"))
            os.makedirs(os.path.join(a["pasta"], "snapshots", "default_boot"))
            self.assertEqual(A.instantaneos(a["pasta"]), ["logado"])
            self.assertTrue(A.exclui(nome, d))
            self.assertEqual(A.lista(d), [])
            self.assertFalse(A.nome_valido("com espaço"))

    def test_linha_de_comando_e_portas(self):
        import emulador_proc as P
        base = P.comando("C:/sdk", "x", 5556)
        self.assertIn("-no-window", base)
        self.assertEqual(base[base.index("-port") + 1], "5556")
        self.assertIn("-no-snapshot-load", base)  # boot limpo: abrir de um estado salvo deixa o adb offline
        self.assertNotIn("-wipe-data", base)
        self.assertIn("-wipe-data", P.comando("C:/sdk", "x", 5556, "apagar"))
        self.assertEqual(P.porta_livre([5554], em_uso=lambda p: p == 5556), 5558)

    def test_console_do_emulador(self):
        import emulador_proc as P
        resposta = {"devices": "List of devices attached\nemulator-5554\tdevice\n192.168.1.6:5555\tdevice\n",
                    "name": "vision-smartpos-android11\nOK\n",
                    "load": "KO: Device 'cache' does not have the requested snapshot 'x'\nKO: Snapshot load failure\n"}

        def rodar(cmd, timeout=0):
            chave = "devices" if cmd[-1] == "devices" else ("name" if cmd[-1] == "name" else "load")
            return 0, resposta[chave], ""

        self.assertEqual(P.emuladores_ligados(rodar, "adb"), {"emulator-5554": "vision-smartpos-android11"})
        with self.assertRaises(RuntimeError) as e:
            P.carrega_estado(rodar, "adb", "emulator-5554", "x")
        self.assertIn("Snapshot load failure", str(e.exception))

    def test_nome_do_emulador_na_lista_de_aparelhos(self):
        import espelha_tela as E
        E.ROTULOS_EMULADOR["emulator-5554"] = "Emulador \u00b7 SmartPOS (Android 11)"
        try:
            self.assertTrue(E.rotulo_aparelho({"serial": "emulator-5554", "modelo": "sdk_gphone64", "estado": "device"})
                            .startswith("emulator-5554  \u00b7  Emulador \u00b7 SmartPOS"))
        finally:
            E.ROTULOS_EMULADOR.clear()


if __name__ == "__main__":
    unittest.main(verbosity=1)
