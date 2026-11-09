# Changelog

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
