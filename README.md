# EspelhaTela

Espelho e controle de tela Android numa **janela própria do Windows**, sem navegador e sem servidor, no estilo
Vysor/scrcpy, pensado para quem testa apps Android no dia a dia: QA, automação de testes e desenvolvimento.

Além do espelho, a ferramenta reúne, a um clique, o que costuma exigir um terminal com `adb`:
- instalar e desinstalar APK;
- navegar pelos arquivos do aparelho;
- acompanhar a memória de cada app;
- exportar o logcat;
- preparar o aparelho para automação;
- **copiar o seletor de qualquer elemento da tela pronto para o [Maestro](https://maestro.mobile.dev)**.

## Por que existe

Espelhos que trazem o próprio `adb` (de outra versão) derrubam o servidor adb de quem já estava usando, e a
automação perde a sessão (`protocol fault`) no meio de um teste. O EspelhaTela usa **o mesmo adb do Android SDK**
que as suas ferramentas, nunca chama `start-server` nem `kill-server`, e avisa quando vê outro adb rodando.

## Desempenho

| Parte | Como funciona |
|---|---|
| Imagem | **Vídeo H.264** (`screenrecord`, decodificado com PyAV): dezenas de quadros por segundo. Perfis Rápido, Equilibrado e Nítido, e o modo "Quadros (leve)" para aparelhos fracos. |
| Clique | **Injetor sempre ativo** (`injetor/`, ~3,5 KB): um processo Java no aparelho recebe os eventos por uma conexão já aberta, com toque, arraste e rolagem em tempo real. É a mesma técnica do scrcpy. |
| Retorno visual | Um círculo aparece no ponto do clique **na hora**, antes de o aparelho responder. |

Cada parte tem um plano B automático, então funciona em qualquer aparelho:
- se o vídeo não estiver disponível, a ferramenta tenta o tamanho nativo e depois cai para quadros;
- se o firmware bloquear o injetor, os toques passam a ir pelo `adb shell input`, mais lento mas universal;
- o rodapé mostra o que está em uso: `VIDEO` ou `quadros`, `clique instantaneo` ou `clique via adb (lento)`, e a porta do servidor adb.

## O que tem

| Recurso | Para que serve |
|---|---|
| Espelho + **controle** | Clique, arraste, rolagem e teclado do PC vão para o aparelho. |
| Voltar / Início / Recentes / Volume / Tela | Teclas do Android. |
| Salvar captura | PNG em `Imagens\EspelhaTela` (Ctrl+S). |
| Tela cheia | F11. |
| **Seletor** (F6) | Modo de inspeção. O mouse destaca o elemento sob ele e o clique **não vai para o aparelho**: ele escolhe o elemento e mostra o seletor do Maestro pronto para copiar. As opções são `id:` (o `resource-id`; no React Native é o `testID`), o id do elemento clicável que o contém, `text:` (texto visível ou de um filho), accessibilityLabel, `assertVisible` e, como último recurso, `point:` em porcentagem. Um id repetido ganha `index:`. |
| **Exportar logcat** | Salva o log dos **últimos 2, 5 ou 10 minutos** em `Documentos\EspelhaTela\Logcat`, usando a hora do aparelho. |
| **+ IP** | `adb connect` pela rede. O endereço fica salvo e é reconectado sozinho. Aparelho `unauthorized` ou `offline` aparece no rodapé com o que fazer. |
| **App e aparelho** | Para qualquer app instalado: versão, código, datas, PID, abrir, parar, reiniciar, limpar dados e conceder permissões. Do aparelho: modelo, Android, bateria, IP e ANDROID_ID. **Preparar para automação** desliga as animações, mantém a tela ligada e trava a rotação, guardando os valores antigos para restaurar. Marque seus apps como **★ favoritos** para tê-los no topo. |
| Instalar / Desinstalar APK | `adb install -r` (com tratamento de downgrade) e `adb uninstall` de vários pacotes, com atalho para marcar os favoritos. |
| Arquivos | Navega pelas pastas do aparelho: baixar, enviar, abrir no PC, criar pasta, renomear e excluir (só em `/sdcard`, `/storage` e `/data/local/tmp`). |
| Memória | Gerenciador de tarefas: RSS por processo, PSS sob demanda, variação desde o início, gráficos, detalhe por app e exportação para CSV. Tem chave liga/desliga. |
| **Aviso de adb e porta** | Se o `adb` do PATH é um wrapper (`.cmd`/`.bat` com `-P <porta>`) ou `ADB_SERVER_PORT` aponta para um servidor sem aparelhos, e outro servidor adb tem o aparelho, uma faixa avisa e oferece **Usar a porta N**. |

## Instalar e usar

Para quem só quer usar, sem Python: baixe o `EspelhaTela-<versão>.zip` em **Releases**, extraia e dê dois cliques
em `EspelhaTela.exe`. A primeira abertura leva de 10 a 15 s.

Para rodar a partir do código:

```bash
pip install pillow av
python espelha_tela.py                    # abre a janela
python espelha_tela.py --serial 0123abcd  # aparelho especifico
python espelha_tela.py --abrir-app        # ja abre um painel (tambem --abrir-memoria, --abrir-arquivos)
python espelha_tela.py --adb C:\caminho\adb.exe
python espelha_tela.py --diagnostico      # grava %TEMP%\espelhatela-diagnostico.txt (adb, porta, video, injetor) e sai
python testes_sem_tela.py                 # verificacoes sem tela e sem aparelho
```

Se preferir não ver o console, use o `iniciar.bat`. Para gerar o `.exe`, rode `compilar.bat`, que monta um ambiente
isolado com PyInstaller, Pillow e PyAV. Recompile o injetor (`espelha-input.jar`) só se mudar o
`injetor/src/espelhatela/Injector.java`: `python injetor\build.py` (precisa do JDK e do Android SDK).

**Requisitos:**
- Windows 10 ou 11;
- `adb` do Android SDK platform-tools. Ele é procurado na variável `ADB`, no `PATH`, em `ANDROID_SDK_ROOT`/`ANDROID_HOME` e em `%LOCALAPPDATA%\Android\Sdk`, ou como `adb.exe` ao lado do programa;
- aparelho com a depuração USB ligada.

O código está em três arquivos:
- `espelha_tela.py`: a janela;
- `seletor.py`: a árvore da tela e os seletores do Maestro;
- `adb_servidor.py`: a porta do servidor adb e a detecção de wrapper.

## Convivência com a automação

- Só captura com a janela visível e não pausada.
- O vídeo usa o encoder do aparelho, que pode pesar em aparelhos fracos. Em rodadas longas, troque para **Quadros (leve)**.
- **Os seus cliques mexem no aparelho de verdade**: cuidado com uma rodada em andamento.
- O **Seletor** usa `uiautomator dump`, que registra um UiAutomation no aparelho. Com um flow do Maestro rodando, isso pode derrubar o driver dele. Use o seletor só com o aparelho livre; a leitura só acontece quando você clica.
- "Preparar para automação", "Limpar dados" e "Desinstalar" mudam o aparelho, e todos pedem confirmação.

## Limites conhecidos

- Alguns firmwares restringem o logcat ao shell. Nesse caso a exportação avisa, em vez de gerar um arquivo vazio.
- O `.exe` de arquivo único leva de 9 a 12 s para abrir na primeira vez, porque extrai ~45 MB. Não clique duas vezes.
- Texto com acentos não passa pelo teclado do PC.
- O vídeo é reiniciado a cada 180 s (limite do `screenrecord`), com uma pausa de cerca de 1 s.
- Depois de uma rotação de tela, pode ser preciso reiniciar o vídeo (trocar o modo e voltar).
- Por ser um programa novo sem assinatura digital, o Windows ou o antivírus podem alertar. Nesse caso, use Propriedades > Desbloquear.

As preferências (barra lateral, modo de captura, favoritos, porta do adb e medição de memória) ficam em
`%APPDATA%\EspelhaTela\config.json`.

## Licença

[MIT](LICENSE). Use, adapte e compartilhe.
