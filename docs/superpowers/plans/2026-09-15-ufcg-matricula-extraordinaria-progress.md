# Progresso — agente de matrícula extraordinária UFCG

Registro de retomada. SPEC: `docs/superpowers/specs/2026-09-14-ufcg-matricula-extraordinaria-agent-design.md`.
Plano: `docs/superpowers/plans/2026-09-15-ufcg-matricula-extraordinaria-claude.md`.

## Situação em 16/09/2026

Branch `joaquim/ufcg-matricula-extraordinaria`, 12 commits a partir de `2709474`.
Sem push, sem merge. `uv run --extra dev pytest -q` → 445 passed; `ruff check .` limpo.

**Alvo ainda não matriculado.** O período abriu às 05:00 de 16/09/2026 e o componente
`1109103` não tem vaga remanescente. A execução ao vivo com `--confirm` parou sem
enviar nada, como projetado.

## Verificado ao vivo (SIGAA real, 15–16/09/2026)

- Login clássico `/logar.do`, Portal do Discente e detecção de sessão.
- Abertura da extraordinária pelo endpoint direto.
- Busca por código, incluindo `form:comboDepartamento` e `form:checkCodigo=on`.
- Classificação de período fechado (`period_closed`/2) e de ausência de vaga
  (`no_vacancy`/2, pollable sob `--watch`).
- Captura em disco com diretório 0700 e arquivos 0600.
- Reaproveitamento da sessão: um login para cada quatro ciclos de polling.

## Ainda não capturado (hipótese, falha fechado)

Nenhuma busca retornou linhas, porque nada tinha vaga. Continuam sem evidência real:

- tabela de resultados e representação de vagas;
- controle de seleção da linha;
- página de confirmação e seus campos de identidade;
- página de verificação do vínculo.

Esses parsers derivam da matrícula regular da UFPB (mesma família SIGAA; UFCG roda
`v4.20.6-ufcg.4`, UFPB `26.9.1`) e **falham fechado**: render desconhecido retorna
`error`/6 com `captura de resultados necessária`, sem enviar nada, e `--capture`
salva a página.

## Como retomar

Vigiar até aparecer vaga e matricular quando aparecer:

```bash
uv run sigaa matricula-extraordinaria --codigo 1109103 --turma 02 \
  --watch --interval 20 --confirm --capture ~/.sigaa-captures/vigia
```

Sem `--confirm`, o mesmo comando apenas prepara e para. Não há scheduler embutido
nem retomada persistida: cada processo é uma sessão.

Se a execução terminar com `error`/6, a tela de resultados finalmente existe:
sanitizar o HTML capturado (remover nome, matrícula, e-mail, curso, ViewState e
jsessionid), transformar em fixture e implementar `parse_classes`,
`selection_action`, `confirmation_action` e `is_enrolled` contra ela.

Depois de `unknown`/4, conferir o vínculo no SIGAA **antes** de qualquer nova
execução com `--confirm`. Reiniciar o processo não é autorização para reenviar.

## Decisões registradas

O ledger completo da execução, com as 15 decisões tomadas pelo orquestrador e os
achados de revisão adiados, fica em
`.superpowers/sdd/2026-09-15-ufcg-matricula-extraordinaria-claude/progress.md`
(ignorado pelo Git, local). As decisões com efeito duradouro:

- Autorização prévia do autor da SPEC para o POST de confirmação em `1109103`/`02`,
  registrada em §§25/27/28 da SPEC; `--confirm` continua obrigatório.
- SPEC §8.4 corrigida com a evidência ao vivo de 16/09/2026: o envio precisa dos
  `<select>` do formulário e do checkbox com valor `on`.
- Achados menores em aberto: `_validate_url` aceita porta não padrão;
  `_MENU_ACTION_RE` não casa aspas por backreference; o comentário de
  `_retry_after` afirma tratamento de HTTP-date que na prática não chega ao fluxo;
  `_COMPONENT_CODE_RE` ancora o código no início da célula, o que no pior caso
  degrada para `unknown`/4 e nunca para uma afirmação errada.
