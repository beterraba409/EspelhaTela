# Contribuindo com o EspelhaTela

Obrigado pelo interesse! Bugs, ideias e PRs são bem-vindos.

## Reportar um bug

Abra uma [issue](../../issues/new/choose) e informe:
- o modelo do aparelho e a versão do Android;
- o que aparece no rodapé da janela (modo `VIDEO` ou `quadros`, `clique instantaneo` ou `via adb`, e a porta);
- o conteúdo de `%TEMP%\espelhatela-diagnostico.txt`, gerado com `EspelhaTela.exe --diagnostico` ou `python espelha_tela.py --diagnostico`.

## Rodar a partir do código

```bash
pip install pillow av
python espelha_tela.py
python testes_sem_tela.py   # precisa passar antes do PR
```

## Convenções

- Python 3.8+ com a biblioteca padrão. Dependência nova só se valer a pena, e documentada no README.
- Ação que muda o aparelho (limpar dados, desinstalar, mudar configurações) pede confirmação e usa o serial explícito (`adb -s <serial>`).
- Nunca chame `adb start-server` nem `adb kill-server`: a ferramenta precisa conviver com a automação que já está usando o adb.
- Lógica sem tela vai em módulos testáveis (como `seletor.py` e `adb_servidor.py`), com verificações em `testes_sem_tela.py`.
- Recompile o injetor (`python injetor\build.py`) só se o `Injector.java` mudar, e versione o `espelha-input.jar` gerado.
