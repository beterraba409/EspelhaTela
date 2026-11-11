# Changelog

## 2.4 - Emuladores Android dentro do Vision

- **Emuladores** (nova ferramenta): cria e liga Androids virtuais que aparecem no espelho do Vision como um aparelho, com todas as ferramentas (toque, Seletor, Reportar bug, Logcat, Arquivos, instalar APK soltando no espelho).
  - **Criar emulador**: perfis **SmartPOS** (720×1280, Android 11 como o GPOS e o L400), **Celular** e **Tablet**; versão do Android 11, 13, 14, 15 ou 16; nome, memória e armazenamento. Antes de criar, verifica aceleração (WHPX), memória e disco e diz como resolver o que faltar.
  - **Sem Android SDK no PC**: o Vision baixa o emulador e a imagem do Android direto do repositório oficial do Google (sem Java nem Android Studio), confere o checksum e continua de onde parou se a internet cair. Na primeira vez, mostra a licença do Android SDK para aceitar. Com SDK no PC, usa o que já existe (e confere se a imagem está inteira).
  - **Janela Emuladores** (abre ao lado do espelho): ligar, desligar, espelhar, ligar num **estado salvo**, salvar o estado atual (ex.: SmartPOS ativado e logado), voltar a ele, apagar os dados, excluir. Vários ao mesmo tempo. Ligam sem janela própria e o Vision passa a espelhar o emulador quando termina de ligar; na lista de aparelhos aparecem como "Emulador · SmartPOS (Android 11)". Ao fechar, o Vision pergunta se desliga os que ele ligou.
  - No SmartPOS, telas e automação rodam; pagamento com cartão não (não há leitor nem SDK de adquirente).
- **Toque instantâneo no Android 14 ou mais novo**: o injetor passou a usar o `InputManagerGlobal` (o `InputManager` exige contexto de app a partir do Android 14). Vale para celulares físicos também.

## 2.3 - Configurações: escolha suas ferramentas

- **Configurações** (seção Vision): um interruptor para cada ferramenta da barra lateral. Desligada, a ferramenta some do Vision, junto com o atalho de teclado dela (F6 do Seletor, F8 do Reportar bug) e o que ela faz ao soltar arquivos no espelho; ligada, volta no mesmo lugar. **Mostrar todas** liga tudo de novo. A escolha fica no `config.json` de cada usuário, então cada um monta o seu Vision.

## 2.2 - reportar bug, logcat ao vivo, pareamento por Wi-Fi

- **Reportar bug** (Ferramentas ou F8): no clique, o Vision guarda a tela em resolução total, o vídeo dos **últimos 30 s** do espelho, o logcat dos últimos 5 minutos e os dados do aparelho e do app em primeiro plano (com a versão). Você preenche Título, Descrição, Teste realizado, Resultado esperado e Resultado obtido, e ele monta uma pasta em `Documentos\Vision\Bugs` com `print.png`, `ultimos-segundos.mp4`, `logcat.txt` e `bug.md`, mais um `.zip` para anexar no Jira. O texto do card vai para a área de transferência. Para ter o vídeo de antes do clique, o Vision guarda sempre os últimos 30 s em quadros reduzidos (cerca de 10 MB; dá para desligar na própria janela).
- **Logcat ao vivo** em janela própria: tempo real com cores por nível, filtro pelo app (já vem o que está na tela; segue o app mesmo se ele reiniciar), nível mínimo e busca com destaque; Pausar, Limpar e Salvar (com os filtros).
- **Conectar pelo Wi-Fi** virou uma janela com duas opções: **Pelo IP** (como antes) e **Parear com código** (Android 11+, Depuração por Wi-Fi): IP e porta de pareamento + código de 6 dígitos; a porta de conexão é achada sozinha na rede.
- **Toques visíveis na gravação**: a janela Gravar tela tem "Mostrar os toques no vídeo" (liga o recurso do Android durante a gravação e devolve como estava no fim).
- **Soltar APK no espelho**: arrastar um `.apk` do Explorer para a janela principal instala, com a confirmação de versão de sempre (vários apps instalam um após o outro; as partes de um app dividido vão juntas). Outros arquivos podem ir para `/sdcard/Download`.
- MP4 (gravação e Reportar bug) com a duração certa em qualquer player, mesmo com a tela parada por um tempo.

## 2.1 - janela de gravação

- **Gravar tela** abre uma janela própria: escolha entre **MP4** (vídeo, 30 quadros/s, sem limite) e **GIF** (animação, 10 quadros/s, até 60 s) em cartões com o que cada um faz; **pasta** (botão Alterar…) e **nome do arquivo** escolhidos ali; opção de abrir a pasta quando salvar. Lembra o formato e a pasta da última vez.

## 2.0 - vídeo sem quadro preso, gravar tela, área de transferência e arquivos

- **Vídeo preso no quadro anterior (causa das "travadas" que ficavam até mexer na tela de novo)**: o decodificador só soltava um quadro quando chegava o começo do próximo. Com a tela do aparelho parada depois de uma mudança (fechar um aviso, por exemplo), o estado final ficava preso no PC, e o espelho mostrava a tela anterior até algo mudar de novo. Agora, quando o aparelho para de mandar dados por um instante, o último quadro é mostrado na hora. A mesma causa fazia a gravação "falhar sem imagem" em telas paradas.
- **Área de transferência do aparelho → Windows sozinha**: o que for copiado no aparelho (o botão de copiar de um app, como o do serial no SmartPOS, ou uma seleção) vai para a área de transferência do PC em cerca de 1 s, sem Ctrl+C. No Android 12+ o Vision só lê o conteúdo quando ele muda, para não mostrar o aviso de "colou da área de transferência" o tempo todo.
- **Gravar tela** em **MP4** (vídeo) ou **GIF** (animação, até 60 s), pelo botão em Ferramentas. Salva em `Vídeos\Vision` e abre a pasta com o arquivo selecionado. Grava o que o espelho recebe: para mais resolução, use "Vídeo nítido".
- **Arquivos**: **⬇ Baixar para o PC** e **⬆ Enviar para o aparelho** com uma faixa de progresso (arquivo, MB e %), botão **Cancelar** (apaga o que ficou pela metade) e o resultado no fim ("Download concluído…" com **Abrir pasta**). A pasta de download usada por último fica lembrada.
- **Arrastar e soltar**: arquivos e pastas soltos do Explorer na janela Arquivos são enviados para a pasta aberta. Antes de sobrescrever um item com o mesmo nome, o Vision pergunta.

## 1.9 - copiar textos da tela do aparelho

- **Botão direito** no espelho abre "Copiar “texto”" com o texto do elemento sob o mouse (ou do botão que o contém) e "Copiar todo o texto da tela". Funciona com textos que não dá para selecionar no Android, como o serial na tela inicial do SmartPOS. O texto vem da árvore da tela (a mesma leitura do Seletor; não use com um flow do Maestro rodando).

## 1.8 - codificador de vídeo em uso, de verdade

- O registro do vídeo dizia qual codificador estava em uso pela ordem dos arquivos do Android, que não é a ordem em que ele escolhe: no L400 isso deu um aviso falso de "codificador de software". Agora ele lê no logcat o codificador que a gravação abriu de fato (sem limpar o logcat). Em aparelho que restringe o logcat, o registro diz que não deu para ver, em vez de chutar.

## 1.7 - diagnóstico do vídeo pelo lado do aparelho

- **Resposta ao toque medida certo**: o registro conta o tempo entre o toque e o primeiro quadro depois dele (antes contava desde o último quadro, e uma tela parada por 30 s virava uma "pausa de 30 s"). Toque sem mudança na tela por mais de 5 s aparece à parte, não como travada.
- **Dados do aparelho no registro**: os codificadores H.264 que ele tem (e se o usado é de hardware ou de software) e, a cada 10 s de uso, quantos quadros o próprio app desenhou e quanto processador o screenrecord, o desenho da tela e o app usam.
- **Vídeo leve (aparelho fraco)**: 480 px a 2 Mbps, menos trabalho para o codificador de POS fracos.

## 1.6 - versão antes de instalar e vídeo sem travadas

- **Instalar APK** pede confirmação mostrando o aparelho, o pacote, a versão do APK e a que já está no aparelho, e diz se é instalação nova, atualização, mesma versão ou downgrade (o downgrade já instala com `-d`). A versão é lida direto do APK, sem precisar do Android SDK no PC.
- **Desinstalar APK** confirma listando cada app com a versão instalada.
- **Vídeo contínuo**: a gravação seguinte abre antes de a atual acabar (o `screenrecord` grava no máximo 180 s) e a troca é sem pausa. No Moto G7 Play, 4 trocas seguidas sem nenhum buraco maior que 0,25 s.
- **Vídeo rápido** a 4 Mbps (antes 2): telas que mudam inteiras, como véus de carregamento, deixam de borrar e engasgar.
- **Registro do vídeo** (`%APPDATA%\Vision\video.log`, botão na seção Vision): gravações, um resumo a cada 10 s e cada travada percebida depois de um toque, com a causa provável (aparelho ou PC).

## 1.5 - atualização que fecha o app e reabre sem erro

- Depois de atualizar, o Vision abria com o erro "Failed to load Python DLL": o Vision aberto pelo instalador herdava as variáveis internas do PyInstaller do Vision antigo e procurava a pasta temporária dele, que já tinha sido apagada. Agora tudo o que o Vision abre (instalador, nova sessão, reabrir) recebe um ambiente limpo, e o instalador abre o Vision pelo Explorer.
- Antes de instalar, o Vision fecha de verdade: um ajudante espera ele sair, força a parada de qualquer janela do Vision que ainda estiver aberta e só então roda o instalador.

## 1.4 - textos naturais e revisão visual

- Textos em português natural, com acentos, em todas as janelas; a lista mostra o modelo do aparelho ("0123abcd · GPOS780").
- Letras sem contorno, mais limpas; a versão do Vision fica no canto do rodapé.
- Rodapé com etiquetas curtas que nunca saem cortadas: as do fim somem inteiras quando falta espaço.
- Revisão visual nos temas claro e escuro: tabelas, botões, caixas, campos, molduras e barras de rolagem seguem o tema (antes a tabela de Arquivos ficava branca no escuro e o cabeçalho de Memória ficava ilegível no claro); cores de destaque legíveis nos dois temas.

## 1.3 - primeira atualização pelo próprio app

- Versão para quem tem a 1.2 atualizar pelo botão **Buscar atualizações**, com o ícone novo e os últimos ajustes de visual.

## 1.2 - Vision, instalador e mais leve em máquina lenta

- **Novo nome: Vision** (antigo EspelhaTela). Na primeira abertura, a configuração salva pelo EspelhaTela é trazida junto.
- **Visual novo**: botões com contorno e cantos arredondados, ícones do próprio Windows, barra lateral em seções com rolagem, rodapé em etiquetas, cursor de seta e ícone novo.
- **Buscar atualizações**: o Vision consulta as Releases deste repositório (uma vez por dia e no botão) e, com um clique, baixa e instala a versão nova.
- **Menu de cada aparelho**: clique com o botão direito num aparelho da lista para usar nesta sessão, abrir em nova sessão, copiar o serial ou excluir (aparelho de rede: desconecta e esquece o IP).
- **Aparência**: tema claro ou escuro e cor de destaque (roxo, azul, verde, laranja ou rosa).
- **Janela estreita**: a janela agora diminui para os lados; a barra lateral recolhe sozinha quando falta espaço.
- **Ícone nítido** em todos os tamanhos do Windows.
- **Instalador** `Vision-Setup-<versão>.exe`: instala sem pedir administrador, cria o atalho no Menu Iniciar (e, se quiser, na área de trabalho) e aparece em "Aplicativos instalados" para desinstalar. Gerado com `compilar-instalador.bat` (Inno Setup 6).
- O vídeo usa cerca de metade da CPU: cada quadro só vira imagem quando vai para a tela, já no tamanho da janela, e a imagem da janela é reaproveitada. Em computador fraco, o clique não espera mais na fila do desenho.
- Se o vídeo falhar (rede instável, aparelho ocupado), ele volta sozinho: nova tentativa depois de 30 s, 1, 2 e 4 min e depois a cada 5 min, com a imagem por quadros enquanto isso. Antes ficava no modo quadros até a troca manual.

## 1.1 - copiar e colar

- **Ctrl+V** cola no aparelho o texto copiado no PC, com acentos e símbolos (pela área de transferência do Android).
- **Ctrl+C** copia o texto selecionado no aparelho e o traz para o PC.
- Antes, as duas teclas não faziam nada.

## 1.0 - primeira versão pública

- Espelho por vídeo H.264 (três perfis) ou por quadros, com plano B automático.
- Controle com injetor sempre ativo (toque, arraste, rolagem, teclado) e plano B pelo `adb shell input`.
- Seletor de identificador para o Maestro (F6): `id:`, `text:`, accessibilityLabel, `assertVisible`, `point:` e `index:`.
- Aviso de adb e porta: detecta wrapper `.cmd`/`.bat` ou `ADB_SERVER_PORT` em outro servidor e oferece a troca.
- Painel "App e aparelho" para qualquer app instalado, com favoritos e preparo do aparelho para automação.
- Instalar e desinstalar APK, gerenciador de arquivos, monitor de memória, exportação de logcat e conexão por IP.
- Executável único para Windows (`compilar.bat`) e verificações sem tela (`testes_sem_tela.py`).
