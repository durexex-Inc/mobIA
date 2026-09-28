# TEC-352 — Plano: aviso de privacidade e consentimento no chat web

Desenho: `docs/superpowers/specs/2026-09-28-tec-352-privacidade-no-chat-design.md`.

## Passos

- [x] **Backend**: `aviso_de_privacidade_url` e `encarregado_email` no `Settings`, com os validadores; os dois campos em `GET /widget/aparencia`; `.env.example`. Testes de `Settings` e da aparência.
- [x] **`lib/privacidade.ts`**: `lerPrivacidade`, `null` quando falta um dos dois. `buscarAparencia` passa a devolver `privacidade`; `/embed/aparencia` continua mandando só os três campos do botão.
- [x] **Página `/embed/chat`**: sem privacidade, cabeçalho e "indisponível", sem `Conversa`. Teste da página.
- [x] **Redutor**: `consentimento` na `Conversa`, `deuCiencia`, `consentimento_registrado` e os erros de consentimento.
- [x] **`Conversa`**: a faixa (finalidade, links, checkbox) até a primeira mensagem, depois só os links; a ciência na primeira mensagem, com o frame antes dela; o consentimento pendente no `open`; o encerramento zera. Os testes antigos que afirmam a ordem exata dos frames passam a esperar o consentimento.
- [x] **CSS** da faixa e do "indisponível".
- [x] **Gates**: os três do Python, `npm test`, `npm run lint`, `tsc --noEmit`, `npm run build`.
- [x] **Navegador**: sem e com as variáveis; a linha em `consentimentos`.
- [x] **Prosa**: o parágrafo do README do frontend.
