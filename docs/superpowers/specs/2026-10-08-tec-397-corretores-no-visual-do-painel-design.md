# TEC-397 — a tela de corretores no visual do painel

Card: TEC-397. Épico: TEC-308. Continua a TEC-396, de quem herda `Trilha`, `Selo`, `Cartao`, `Botao`, `.campo`, `.campo-com-unidade` e `.so-leitor`. Referência: imagem de `/admin/corretores` enviada por Eduardo em 08/10/2026.

## O que muda

A aparência de `/admin/corretores` e dois comportamentos de abertura (D1, D2). Validação, `POST`/`PATCH` parciais, 409 de e-mail no campo e a desativação com confirmação continuam como na TEC-332.

## Decisões

**D1 — O cadastro fica sempre aberto, num cartão "Novo cadastro".** Some o botão "Cadastrar corretor" que abria o formulário: a referência mostra o formulário de pé. Depois de cadastrar, o formulário volta vazio (em vez de fechar). "Cancelar" limpa o que foi digitado e as recusas.

**D2 — A edição abre num `<dialog>` modal, "Editar corretor", e não dentro da célula da tabela.** O formulário em grade de quatro colunas não cabe numa célula; é o mesmo molde da desativação (`DesativarCorretor`), que já é um `<dialog>`. Fechar com Esc vale como "Cancelar".

**D3 — CRECI não leva asterisco.** A referência o marca obrigatório, mas o backend aceita nulo (`Corretor.creci: string | null`) e a validação da TEC-332 não o exige. Especialidades e regiões levam, porque a validação exige.

**D4 — O asterisco é desenhado em CSS (`::after`)**, para não entrar no nome acessível do campo: o leitor de tela ouve "Nome", e o campo leva `aria-required`.

**D5 — A jornada continua em hora inteira, com sufixo "h"**, e não um seletor de horário com minutos como na referência: o backend guarda `SmallInteger` de 0 a 23 (`horario_inicio < horario_fim`).

**D6 — Os textos de ajuda dizem o que o campo faz no código.** A referência fala em "contatos roteados" e "horário limite para transferência por IA"; no código, a capacidade é o teto de **visitas por dia** (`agendamento/alocacao.py`) e a jornada limita as janelas de visita oferecidas e os avisos ao corretor (`agendamento/janelas.py`, `notificacao/envio.py`). O plantonista recebe o lead sem corretor compatível.

**D7 — "Corretores cadastrados" leva o selo com a contagem de ativos e o total.** O estado vazio passa para dentro de `ListaDeCorretores`, num cartão, com o mesmo texto de antes ("Nenhum corretor cadastrado.").

**D8 — O cabeçalho do cartão diz "* obrigatório"**, no lugar de "Campos de cadastro interno", que não diz nada a quem preenche.

## Lacunas

- **L1** — A referência mostra a trilha "Administração / Equipe / Corretores". Não existe página "Equipe"; a trilha é "Administração / Corretores".
