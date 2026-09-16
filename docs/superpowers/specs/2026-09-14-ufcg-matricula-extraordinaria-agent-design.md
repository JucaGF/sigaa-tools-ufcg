# SPEC — Agente local de matrícula extraordinária da UFCG

**Status:** pronta para revisão humana

**Data:** 14 de setembro de 2026

**Sistema alvo:** SIGAA UFCG `v4.20.6-ufcg.3`

**Componente alvo:** `1109103 — CÁLCULO DIFERENCIAL E INTEGRAL I`

**Turma alvo:** `02`, sem fallback para outra turma

## 1. Objetivo

Adicionar ao repositório um processo local e determinístico que acompanhe a
matrícula extraordinária da UFCG e efetive a matrícula no componente `1109103`,
turma `02`, quando houver vaga e todas as validações do SIGAA forem satisfeitas.

O processo deve reproduzir os formulários HTML/JSF renderizados pelo SIGAA,
preservar uma única sessão autenticada e confirmar a matrícula no máximo uma vez
por tentativa preparada. Uma resposta HTTP bem-sucedida não prova matrícula: o
resultado só é terminal quando a pós-condição acadêmica for verificada.

O caminho crítico — autenticação, navegação, busca, seleção, confirmação e
verificação — será código Python testado. Um LLM ou servidor MCP não participa da
decisão nem da mutação.

## 2. Resultado esperado

Durante uma execução autorizada, o usuário inicia um comando local com confirmação
explícita. O processo:

1. autentica no SIGAA da UFCG;
2. abre a matrícula extraordinária;
3. busca exatamente o componente `1109103`;
4. seleciona somente a turma `02` quando houver vaga;
5. chega à página de confirmação;
6. envia os dados de confirmação uma única vez;
7. verifica que a turma aparece como `MATRICULADO`;
8. encerra com resultado estruturado e sem expor dados pessoais.

Se a vaga não existir, o processo espera e pesquisa novamente com intervalo
conservador. Se o resultado da confirmação ficar ambíguo, ele verifica o estado
acadêmico antes de considerar qualquer nova tentativa.

## 3. Escopo

### 3.1 Incluído

- SIGAA da Universidade Federal de Campina Grande.
- Uma conta discente e uma sessão HTTP por processo.
- Login clássico da UFCG.
- Navegação pelo menu e acesso direto à extraordinária.
- Busca por código de componente.
- Correspondência exata da turma `02`.
- Consulta de vagas remanescentes.
- Preparação sem mutação como comportamento padrão.
- Confirmação habilitada explicitamente na linha de comando.
- Verificação pós-confirmação.
- Espera e polling sequencial com backoff.
- Tratamento de sessão expirada e estado JSF consumido.
- Logs sanitizados e resultados estruturados.
- Fixtures sintéticas ou sanitizadas e testes de contrato HTTP.

### 3.2 Excluído da primeira versão

- Garantir compatibilidade funcional com a UFPB.
- Refatorar o projeto inteiro para múltiplas instituições.
- Matrícula regular, rematrícula, turma de férias ou turma suplementar.
- Fallback automático para a turma `01`.
- Mais de um componente alvo.
- Mais de uma conta por processo.
- Requisições concorrentes ou múltiplos navegadores.
- Ferramenta MCP capaz de selecionar ou confirmar matrícula.
- LLM no caminho crítico.
- Interface gráfica, painel web ou serviço hospedado.
- Scheduler próprio. A primeira versão é iniciada pelo usuário ou por um
  scheduler do sistema operacional configurado separadamente.
- Remoção, cancelamento ou troca de uma matrícula.
- Resolução atômica de correquisitos.
- Contorno de CAPTCHA, bloqueios de segurança ou limites impostos pelo SIGAA.

## 4. Vocabulário do domínio

**Matrícula extraordinária:** ocupação imediata de vaga remanescente após
matrícula/rematrícula. O critério é ordem de confirmação e não existe processamento
posterior.

**Alvo:** par imutável desta primeira versão: componente `1109103`, turma `02`.

**Render:** uma resposta HTML específica do SIGAA. IDs JSF, campos hidden,
`javax.faces.ViewState` e postbacks pertencem ao render que os produziu.

**Preparada:** a turma correta foi selecionada e o SIGAA apresentou o formulário
de confirmação. Nenhuma matrícula foi efetivada ainda.

**Confirmada:** o POST final foi enviado e uma resposta foi recebida. Esse estado
sozinho não representa sucesso.

**Verificada:** uma consulta posterior mostra inequivocamente a turma como
`MATRICULADO`.

**Resultado desconhecido:** o POST final pode ter sido processado, mas a resposta
foi perdida e a pós-condição ainda não pôde ser consultada.

## 5. Fontes e nível de confiança

### 5.1 Confirmado em sessão autenticada em 14/09/2026

- Login, URL do portal, formulário e nomes de campos.
- Portal clássico do discente.
- Formulário JSCookMenu e ação da matrícula extraordinária.
- Endpoint direto da matrícula extraordinária.
- Formulário de busca e seus campos.
- Período informado pelo próprio SIGAA.
- Redirecionamento ao portal ao tentar buscar antes da abertura.
- Versão institucional `v4.20.6-ufcg.3`.

### 5.2 Confirmado por fontes oficiais ou consulta pública

- Semântica de uma turma por vez, ocupação imediata e ordem de chegada.
- Componente, unidade responsável, carga horária e situação de matrícula on-line.
- Ofertas públicas das turmas `01` e `02` no período `2026.2`.

### 5.3 Bloqueado até a abertura do período

- HTML real dos resultados da busca extraordinária.
- Colunas e representação real das vagas.
- Postback do ícone de seleção da turma.
- HTML e campos reais da confirmação.
- Mensagens reais de sucesso e falha.
- Página mais confiável para verificar `MATRICULADO` após a confirmação.

Esses itens são um gate de implementação. A confirmação real permanece desabilitada
até que um dry-run autenticado capture e teste todos eles.

### 5.4 Referências

- Pesquisa inicial utilizada na elaboração desta SPEC, mas não necessária para a
  implementação:
  `/Users/juca/Downloads/handoff_sigaa_ufcg_matricula_extraordinaria.md`.
- Manual oficial:
  <https://portal.pre.ufcg.edu.br/phocadownload/SIGAA/Manual-SIGAA-para-os-discentes.pdf>.
- Portal PRE para discentes: <https://portal.pre.ufcg.edu.br/discente>.
- Calendários: <https://portal.pre.ufcg.edu.br/calendarios>.
- Login: <https://sigaa.ufcg.edu.br/sigaa/verTelaLogin.do>.
- Consulta pública de turmas:
  <https://sigaa.ufcg.edu.br/sigaa/public/turmas/listar.jsf>.

## 6. Estado atual do repositório

O projeto é um cliente Python 3.11+ com `httpx`, Beautiful Soup e `lxml`. A
suíte de referência executada antes desta SPEC teve `205 passed, 8 skipped`.

| Área | Estado atual | Lacuna para UFCG |
| --- | --- | --- |
| `sigaa/config.py` | Endpoints e marcadores globais da UFPB | URLs e marcadores incompatíveis |
| `sigaa/auth.py` | Login JSF da UFPB em `/logon.jsf` | UFCG usa formulário clássico `/logar.do` |
| `sigaa/http.py` | Relogin e repetição transparente | Pode repetir POST mutável ou com estado vencido |
| `sigaa/client.py` | Cliente acadêmico e matrícula regular | Não possui extraordinária |
| `sigaa/parsers/matricula.py` | Parser da matrícula regular em lote | Semântica e DOM diferentes |
| `sigaa/cli.py` | `matricula --select --confirm` regular | Não possui worker extraordinário |
| `sigaa/mcp_server.py` | Matrícula somente leitura | Deve continuar sem mutação |
| `sigaa/setup_wizard.py` | UFPB e keyring `sigaa-ufpb` | Não deve ser pré-requisito da primeira versão |

O fluxo regular existente não é base semântica para a extraordinária. Ele pode
servir como referência de organização, mas seus métodos, payloads e modelos não
devem ser reutilizados como se fossem o mesmo processo.

## 7. Arquitetura escolhida

A implementação será isolada para UFCG, sem criar um framework de instituições.
Isso reduz o risco de o comportamento UFPB afetar o agente e evita abstrações que
não são necessárias ao objetivo atual.

### 7.1 Componentes

#### `sigaa/ufcg.py`

Responsável pelo protocolo institucional:

- constantes de host e endpoints;
- login clássico;
- sessão autenticada;
- detecção de logout;
- GET e POST com política explícita de retry;
- acesso à resposta HTTP quando URL e headers forem necessários para validar uma
  transição.

Essa sessão usa `httpx.Client`, cookies e redirects já presentes na dependência do
projeto, mas não depende das constantes UFPB de `sigaa/config.py`.

#### `sigaa/parsers/matricula_extraordinaria.py`

Responsável por HTML e JSF:

- copiar campos do formulário atual;
- extrair a ação de login;
- localizar a ação JSCookMenu;
- construir busca por código;
- interpretar resultados e vagas por cabeçalhos;
- extrair o postback de seleção;
- identificar e construir a confirmação;
- classificar mensagens e detectar sucesso/falha.

O parser não realiza I/O e não conhece credenciais.

#### `sigaa/extraordinary.py`

Responsável pelo fluxo e pelos estados:

- abrir ou reconstruir cada etapa;
- aplicar o alvo exato;
- controlar polling e backoff;
- impedir reenvio cego da confirmação;
- verificar a pós-condição;
- retornar um resultado estruturado.

#### `sigaa/cli.py`

Expõe o comando, resolve credenciais e apresenta o resultado. Não contém parsing
HTML nem regras de ViewState.

### 7.2 O que permanece intacto

- Matrícula regular e seus métodos atuais.
- Banco SQLite e sincronização acadêmica.
- MCP e sua política sem mutação.
- Parsers da UFPB.
- Setup wizard na primeira entrega.

## 8. Protocolo UFCG confirmado

### 8.1 Login

Entrada:

```text
GET https://sigaa.ufcg.edu.br/sigaa/verTelaLogin.do
```

Formulário observado:

```text
name=loginForm
method=post
action=/sigaa/logar.do;jsessionid=<dinâmico>?dispatch=logOn
```

Campos observados:

```text
width
height
urlRedirect
subsistemaRedirect
acao
acessibilidade
user.login
user.senha
```

Regras:

1. extrair a `action` real do formulário;
2. copiar todos os hidden inputs do render;
3. preencher somente usuário, senha e dimensões;
4. seguir redirects;
5. abrir ou validar o Portal do Discente;
6. considerar sucesso apenas quando URL e DOM indicarem sessão autenticada.

Destino observado:

```text
https://sigaa.ufcg.edu.br/sigaa/portais/discente/discente.jsf
```

Marcadores de sucesso observados:

- URL do Portal do Discente;
- link `SAIR` para `/sigaa/logar.do?dispatch=logOff`;
- ausência do formulário `loginForm`.

O marcador atual `Sair do SIGAA` do projeto não deve ser usado para UFCG.

### 8.2 Menu

Formulário observado:

```text
name=menu:form_menu_discente
action=/sigaa/portais/discente/discente.jsf
```

Campos:

```text
menu:form_menu_discente
id
jscook_action
javax.faces.ViewState
```

Ação observada:

```text
menu_form_menu_discente_discente_menu:A]#{ matriculaExtraordinaria.iniciar}
```

O parser deve procurar a string que contenha
`matriculaExtraordinaria.iniciar` e usar o valor completo do render. O valor
acima é fixture de referência, não constante de produção.

### 8.3 Endpoint direto

```text
https://sigaa.ufcg.edu.br/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf
```

O acesso direto autenticado apresentou a página de busca antes da abertura. O
fluxo deve preferir:

1. ação do menu, porque inicializa o estado da forma esperada pelo SIGAA;
2. endpoint direto como fallback quando o menu responder `period_closed` ou não
   expuser a ação;
3. erro tipado se nenhum caminho produzir o formulário de busca.

### 8.4 Busca

Formulário observado:

```text
name=form
action=/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf
```

Campos observados:

```text
form
form:checkCodigo
form:txtCodigo
form:checkNome
form:txtNome
form:checkHorario
form:txtHorario
form:checkNomeDocente
form:txtNomeDocente
form:checkUnidade
form:comboDepartamento
form:buscar
form:cancelar
javax.faces.ViewState
```

Para esta versão, a busca preenche:

```text
form:checkCodigo=on
form:txtCodigo=1109103
form:buscar=<valor atual do botão>
form:comboDepartamento=<opção atualmente selecionada do render>
```

Todos os hidden inputs são copiados do render atual.

**Correção pós-abertura (captura real, 2026-09-16 ~05:00-05:06):** o payload
documentado acima nesta seção original (`form:checkCodigo=checked`, sem
`form:comboDepartamento`) foi testado ao vivo contra o endpoint real e
REJEITADO duas vezes antes de funcionar:

1. Omitir `form:comboDepartamento` -- um `<select>` não é um hidden input, e o
   payload original nunca o enviava -- produziu
   `form:comboDepartamento: Campo obrigatório não informado ou valor
   informado para o campo é inválido.` Correção: enviar cada `<select>` do
   formulário com o valor de sua opção atualmente selecionada (a primeira
   opção quando nenhuma tem `selected`).
2. Enviar `form:checkCodigo=checked` -- um navegador real envia `on` para uma
   checkbox marcada sem atributo `value`, nunca a string `checked` -- produziu
   `Por favor, escolha algum critério de busca` (SIGAA leu a checkbox como
   desmarcada). Correção: `form:checkCodigo=on`.

Com as duas correções, a busca funcionou. A resposta real para o alvo (1109103)
foi a mensagem de painel `Não foram encontradas turmas abertas com vagas
remanescentes para os parâmetros de busca especificados.` -- i.e. sem vaga
remanescente no momento, não um erro do agente.

Antes da abertura, o POST de busca retornou silenciosamente ao Portal do Discente.
A detecção de período fechado deve aceitar qualquer um destes sinais:

- mensagem explícita sobre período;
- resposta que volta ao Portal do Discente;
- desaparecimento do formulário de busca;
- URL fora do fluxo extraordinário sem uma mensagem de sucesso.

## 9. Período operacional

O SIGAA autenticado informou:

```text
16/09/2026 a 06/10/2026
```

Um calendário público antecipado informou `08/09/2026 a 06/10/2026`. O agente
deve tratar a página autenticada e a capacidade real de executar a busca como
fonte operacional de verdade. Datas externas orientam quando iniciar o processo,
mas não autorizam inferir que o endpoint já aceita matrícula.

O horário exato de abertura não foi publicado na página observada. A primeira
versão não agenda sozinha: o usuário inicia o worker próximo à data, e o estado
`PERIOD_CLOSED` permanece em polling conservador até a busca ser aceita ou o
processo ser interrompido.

## 10. Alvo acadêmico

### 10.1 Componente

```text
Código: 1109103
Nome: CÁLCULO DIFERENCIAL E INTEGRAL I
Tipo: DISCIPLINA
Modalidade: presencial
Carga horária: 60h
Unidade: CCT — Unidade Acadêmica de Matemática
Matriculável on-line: sim
Pré-requisitos: nenhum cadastrado
Correquisitos: nenhum cadastrado
Equivalências: nenhuma cadastrada
```

### 10.2 Ofertas públicas em 2026.2

```text
Turma 01 — local CAA-204
Turma 02 — local CAA-202
```

Docente e local são informações de diagnóstico. A seleção usa somente o código e
o token de turma.

### 10.3 Regra de seleção

- O único alvo aceito é turma `02`.
- Normalizar `02`, `2` e `Turma 02` para o token `2`.
- Comparar tokens completos.
- Não selecionar turma `01` se a turma `02` estiver ausente ou sem vaga.
- Não selecionar uma linha apenas porque seu texto contém `2`.
- Exigir correspondência simultânea do componente `1109103` e da turma `02`.

## 11. Estado e transições

```text
BOOT
  → AUTHENTICATING
  → AUTHENTICATED
  → OPENING
  → PERIOD_CLOSED ───────────────┐
  → SEARCHING                    │
  → TARGET_UNAVAILABLE ─ wait ──┤
  → TARGET_FOUND                │
  → PREPARING                   │
  → PREPARED                    │
  → CONFIRMING                  │
  → VERIFYING                   │
  → ENROLLED                    │
  → REJECTED                    │
  → UNKNOWN                     │
  → FATAL_ERROR                 │
  → DONE                        │
                                 └─ retry reconstruindo o fluxo
```

Regras terminais:

- `ENROLLED`: pós-condição confirmada.
- `REJECTED`: SIGAA recusou explicitamente a operação; não repetir sem mudança de
  estado observável.
- `UNKNOWN`: confirmação pode ter sido processada, mas a verificação não concluiu;
  parar sem reenviar.
- `FATAL_ERROR`: credencial inválida, DOM incompatível, alvo ambíguo ou regra de
  segurança violada.
- `DONE`: processo encerrado após um estado terminal.

## 12. Regras de formulários JSF

Cada ação segue o princípio de replay do navegador:

1. localizar o formulário que contém o controle acionado;
2. copiar os campos hidden com `name` e seus valores atuais;
3. preservar o `javax.faces.ViewState` atual;
4. extrair a `action` do formulário atual;
5. adicionar apenas os campos correspondentes à ação;
6. enviar uma vez;
7. descartar todos os IDs, payloads e ViewState usados.

IDs iniciados por `j_id_jsp_`, sufixos numéricos, `jsessionid` e ViewState são
dados efêmeros. Eles nunca entram como constantes de produção nem são reutilizados
depois de login, navegação ou qualquer POST.

Uma função pura pode construir o payload:

```python
build_form_payload(form, overrides) -> list[tuple[str, str]]
```

A lista de pares preserva campos repetidos sem inventar uma abstração além da
necessária para `application/x-www-form-urlencoded`.

## 13. Parsing dos resultados

Quando a janela abrir, a fixture real deve orientar o parser. Os requisitos já
fixados são:

- localizar a tabela por ID conhecido ou conteúdo/cabeçalhos;
- normalizar cabeçalhos com Unicode NFKC, espaços e `casefold`;
- mapear índices a partir de `<th>`, nunca por posição fixa;
- extrair componente, turma, docentes, horário, local, capacidade e vagas quando
  presentes;
- representar valores ausentes como `None`, não como zero;
- guardar o postback completo de seleção associado à linha;
- rejeitar resultado ambíguo com duas linhas que normalizem para o mesmo alvo;
- considerar disponível somente uma vaga explicitamente positiva ou uma ação de
  seleção habilitada cuja semântica tenha sido confirmada pela fixture real.

Modelo mínimo sugerido, local ao módulo extraordinário:

```python
@dataclass(frozen=True)
class ExtraordinaryClass:
    component_code: str
    class_token: str
    class_label: str
    vacancies: int | None
    schedule_raw: str | None
    room: str | None
    selection_fields: tuple[tuple[str, str], ...]
```

Não modelar campos que não influenciam seleção, logs ou diagnóstico.

## 14. Preparação e dry-run

Dry-run é o comportamento padrão. Ele pode:

- autenticar;
- abrir a extraordinária;
- pesquisar;
- selecionar a turma;
- chegar ao formulário de confirmação;
- validar que os campos esperados existem.

Ele termina em `PREPARED` e não envia o botão de confirmação.

O valor preparado é efêmero e contém somente dados do render atual. Ele não pode
ser serializado, salvo em SQLite ou reutilizado depois de relogin.

## 15. Confirmação

A confirmação só fica disponível quando todas as condições forem verdadeiras:

1. execução contém a opção explícita `--confirm`;
2. dry-run real capturou o formulário de confirmação da versão atual;
3. componente e turma foram reconferidos na página de confirmação;
4. campos de identidade foram localizados dinamicamente;
5. ViewState pertence ao render preparado atual;
6. nenhuma confirmação foi enviada nesta tentativa preparada.

Senha e eventual data de nascimento são lidas do keyring ou do ambiente no
momento do uso. O agente não as recebe como argumentos de linha de comando, não
as inclui no modelo preparado e não as imprime.

O POST final é enviado exatamente uma vez. Depois de iniciado, qualquer timeout,
reset de conexão ou resposta inesperada leva diretamente a `VERIFYING`, nunca a
um segundo POST com o mesmo payload.

## 16. Verificação da pós-condição

A implementação deve escolher, após captura real, uma página autenticada que
mostre inequivocamente o vínculo da turma e a situação `MATRICULADO`. Candidatas:

- lista de turmas do semestre;
- atestado de matrícula;
- página de resultado retornada pela extraordinária.

Critério de verificação:

```text
component_code == 1109103
AND class_token == 2
AND status == MATRICULADO
```

Mensagem de sucesso sem essa pós-condição permite resultado provisório, mas não
autoriza reenvio. Se a verificação estiver temporariamente indisponível, repetir
somente a consulta de verificação, com backoff. Se a sessão expirar, relogar e
reabrir a página de verificação; não reconstruir uma nova confirmação.

## 17. Política de retry

| Operação | Retry automático | Condição |
| --- | --- | --- |
| GET de login/portal | Sim | Uma vez para erro transitório |
| Login POST | Sim, reconstruído | Novo GET e nova `action` |
| Abrir extraordinária | Sim | Novo portal e novo ViewState |
| Busca | Sim, reconstruída | Novo formulário de busca |
| Seleção | Não com payload antigo | Rebuscar e revalidar a turma |
| Confirmação | Nunca | Verificar pós-condição |
| Verificação | Sim | Somente leitura e com backoff |

Erros HTTP `429` e `503` respeitam `Retry-After` válido. Ausência desse header
usa backoff crescente limitado. Respostas `4xx` não previstas são fatais, exceto
o bounce de autenticação reconhecido.

## 18. Polling e carga no servidor

- Uma única requisição em voo.
- Intervalo padrão: 20 segundos.
- Configurável, com mínimo de 10 segundos.
- Backoff para 30, 60 e no máximo 120 segundos em erros transitórios.
- Respeitar `Retry-After` quando entre 1 e 300 segundos.
- Restaurar gradualmente o intervalo normal após resposta saudável.
- Encerrar imediatamente após `ENROLLED`, `REJECTED`, `UNKNOWN` ou erro fatal.

Não usar threads, async concorrente, múltiplas sessões ou rajadas no instante de
abertura.

## 19. Interface de linha de comando

Comando proposto:

```bash
sigaa matricula-extraordinaria \
  --codigo 1109103 \
  --turma 02
```

Esse comando executa uma tentativa dry-run e para em `PREPARED` ou informa que o
alvo está indisponível.

Worker com polling, ainda sem mutação:

```bash
sigaa matricula-extraordinaria \
  --codigo 1109103 \
  --turma 02 \
  --watch
```

Execução autorizada para confirmar:

```bash
sigaa matricula-extraordinaria \
  --codigo 1109103 \
  --turma 02 \
  --watch \
  --confirm
```

Opções da primeira versão:

```text
--codigo CODE       obrigatório; deve ser 1109103 nesta configuração
--turma LABEL       obrigatório; deve normalizar para 2
--watch             repetir enquanto período fechado ou alvo indisponível
--confirm           habilitar POST final
--interval SECONDS  padrão 20; mínimo 10
--json              emitir resultado estruturado
```

Não adicionar YAML, arquivo de alvos ou subcomandos extras na primeira versão.

## 20. Credenciais e privacidade

Fontes aceitas:

1. keyring com serviço separado `sigaa-ufcg`;
2. `SIGAA_USER`, `SIGAA_PASS` e `SIGAA_BIRTH_DATE` como fallback local.

Regras:

- não aceitar senha ou data de nascimento em argumentos CLI;
- não persistir cookies;
- não registrar bodies HTTP completos;
- não registrar headers de cookie;
- não registrar ViewState;
- não registrar nome, matrícula, CPF, e-mail ou data de nascimento;
- sanitizar mensagens do SIGAA antes de logar;
- fixtures reais só entram no repositório depois de remoção de PII, cookies,
  tokens, IDs pessoais e valores de ViewState;
- usar permissões privadas quando um arquivo de diagnóstico local for
  explicitamente solicitado;
- a senha compartilhada durante a pesquisa deve ser trocada antes da execução
  real do agente.

## 21. Logs e saída

Formato humano mínimo:

Os horários abaixo são apenas ilustrativos e não representam o horário de
abertura, que ainda não foi confirmado.

```text
2026-09-16T12:00:00-03:00 AUTHENTICATED
2026-09-16T12:00:01-03:00 SEARCHING component=1109103 class=02
2026-09-16T12:00:02-03:00 TARGET_UNAVAILABLE reason=no_vacancy
2026-09-16T12:00:22-03:00 TARGET_FOUND vacancies=1
2026-09-16T12:00:23-03:00 PREPARED
2026-09-16T12:00:24-03:00 VERIFYING
2026-09-16T12:00:25-03:00 ENROLLED
```

Saída JSON mínima:

```json
{
  "status": "enrolled",
  "component_code": "1109103",
  "class": "02",
  "message": "matrícula verificada"
}
```

Estados permitidos:

```text
prepared
period_closed
target_not_found
no_vacancy
enrolled
already_enrolled
rejected
session_expired
unknown
error
```

## 22. Erros acadêmicos

Mensagens do SIGAA devem ser classificadas sem perder o texto sanitizado:

- sem vaga;
- já matriculado;
- choque de horário;
- pré-requisito ou correquisito;
- limite de carga horária;
- matrícula on-line não permitida;
- período fechado;
- dados de confirmação incorretos;
- sessão expirada;
- indisponibilidade do sistema;
- resposta desconhecida.

Rejeições acadêmicas são terminais para a execução atual. O worker não tenta
contornar regras acadêmicas nem escolhe outra turma.

## 23. Testes obrigatórios

### 23.1 Parsers

Fixtures para:

- login clássico e `action` com `jsessionid` variável;
- portal e ação JSCookMenu variável;
- busca extraordinária;
- período fechado por mensagem;
- período fechado por bounce ao portal;
- resultado sem o componente;
- componente com turma `01`, mas sem turma `02`;
- turma `02` sem vaga;
- turma `02` com vaga;
- cabeçalhos em ordem diferente;
- ação de seleção por link, submit, imagem ou `jsfcljs` conforme captura real;
- confirmação;
- sucesso e cada erro acadêmico observado;
- página de verificação com `MATRICULADO`.

### 23.2 Contrato HTTP

Uma sequência completa com `httpx.MockTransport`:

```text
login GET
login POST
portal GET/redirect
menu POST ou endpoint GET
busca POST
seleção POST
confirmação POST
verificação GET/POST
```

Asserções:

- cookies permanecem na mesma instância de `httpx.Client`;
- cada payload usa campos do render imediatamente anterior;
- ViewState muda entre renders e o valor antigo não reaparece;
- turma `01` nunca é selecionada;
- confirmação não ocorre sem `--confirm`;
- confirmação é enviada uma única vez;
- timeout na confirmação inicia verificação;
- bounce de autenticação reconstrói busca/seleção;
- logs e erros não contêm segredos ou PII.

### 23.3 CLI

- argumentos obrigatórios;
- `--interval` rejeita valores abaixo de 10;
- dry-run como padrão;
- `--confirm` chega à confirmação somente depois de `PREPARED`;
- JSON contém apenas o contrato documentado;
- códigos de saída estáveis.

### 23.4 Regressão

A suíte existente deve continuar verde. Não é necessário provar que os fluxos UFPB
funcionam ao vivo, mas a implementação UFCG não deve quebrar seus testes atuais.

## 24. Códigos de saída

```text
0  enrolled, already_enrolled ou prepared em dry-run
2  period_closed, target_not_found ou no_vacancy sem --watch
3  rejected por regra acadêmica
4  unknown após confirmação
5  autenticação ou configuração inválida
6  protocolo/DOM incompatível
7  rede indisponível após retries permitidos
```

## 25. Fases e gates

### Fase 1 — protocolo já conhecido

Implementar login UFCG, sessão, menu, endpoint direto e busca com fixtures
sintéticas baseadas na captura de 14/09/2026.

**Concluída quando:** login e abertura/busca passam nos testes de contrato, e uma
execução live sem mutação classifica corretamente período fechado ou página de
busca.

### Fase 2 — captura durante o período

Em 16/09/2026 ou depois, executar uma busca live por `1109103`, capturar HTML
sanitizado, mapear turma `02`, vagas e seleção, e chegar à confirmação sem enviar o
botão final.

**Concluída quando:** o dry-run termina em `PREPARED` usando a fixture sanitizada
da versão real.

### Fase 3 — confirmação segura

Adicionar confirmação e verificação usando testes de contrato. A autorização
humana para o primeiro POST live foi concedida pelo autor da SPEC em 15/09/2026,
especificamente para `1109103`, turma `02`. O worker confirma sozinho quando a
preparação estiver validada, sem nova pergunta no momento da execução.

**Concluída quando:** confirmação única e pós-condição verificada funcionam, e o
teste de timeout prova que não há reenvio cego.

### Fase 4 — worker

Adicionar `--watch`, intervalo, backoff e encerramento terminal.

**Concluída quando:** um teste com relógio controlado percorre período fechado,
sem vaga, vaga encontrada e sucesso sem concorrência.

## 26. Critérios de aceite

- [ ] Login usa `loginForm` e a `action` atual do HTML.
- [ ] Portal autenticado é reconhecido sem depender de marcador UFPB.
- [ ] Menu encontra dinamicamente `matriculaExtraordinaria.iniciar`.
- [ ] Endpoint direto funciona como fallback.
- [ ] Busca usa somente código `1109103`.
- [ ] Seleção exige turma `02` e nunca usa turma `01` como fallback.
- [ ] Parser de vagas usa cabeçalhos, não índices fixos.
- [ ] IDs JSF e ViewState nunca são reutilizados entre renders.
- [ ] Dry-run é o padrão e chega à confirmação sem efetivar matrícula.
- [ ] `--confirm` é necessário para o POST final.
- [ ] O POST final ocorre no máximo uma vez por preparação.
- [ ] Timeout final inicia verificação, não retry.
- [ ] Sucesso terminal exige `1109103`, turma `02`, situação `MATRICULADO`.
- [ ] Worker usa uma sessão e uma requisição por vez.
- [ ] Polling respeita mínimo, backoff e `Retry-After`.
- [ ] Credenciais e PII não aparecem em arquivos, fixtures, logs ou saída.
- [ ] MCP continua incapaz de confirmar matrícula.
- [ ] Testes novos e suíte existente passam.

## 27. Instruções para o agente de codificação

1. Leia esta SPEC inteira antes de editar.
2. Verifique o estado do worktree e preserve alterações do usuário.
3. Implemente uma fase por vez, test-first.
4. Mantenha a extraordinária separada da matrícula regular.
5. Use o HTML atual como fonte dos payloads JSF.
6. Use fixtures sanitizadas; nunca use a conta real em testes automatizados.
7. Pare no gate da Fase 2 se o período ainda não permitir capturar resultados.
8. A autorização humana específica para a matrícula `1109103`, turma `02`, foi
   concedida pelo autor em 15/09/2026 e vale enquanto `--confirm` for passado
   explicitamente. O worker valida a preparação e envia o POST final sozinho, uma
   única vez, sem pausa para nova confirmação humana. As travas técnicas
   permanecem: alvo exato, reconhecimento do contrato atual, envio único e
   verificação da pós-condição.
9. Não adicione dependências: `httpx`, Beautiful Soup, `lxml`, stdlib e keyring já
   cobrem o problema.
10. Não adicione framework multi-instituição, YAML, banco ou MCP mutável.
11. Execute `uv run --extra dev pytest -q` e `uv run --extra dev ruff check .`.
12. Considere pronto somente quando todos os critérios de aceite aplicáveis à fase
    estiverem demonstrados por testes ou por captura live sanitizada.

## 28. Decisões finais

- O agente é local e determinístico.
- UFCG é o único alvo funcional.
- UFPB permanece fora do escopo, mas seus testes não podem ser quebrados.
- O componente é `1109103`.
- A turma é exclusivamente `02`.
- A turma `01` não é fallback.
- Dry-run é padrão.
- Confirmação automática requer `--confirm`.
- A confirmação não é repetida automaticamente.
- O POST final é autorizado previamente pelo autor (15/09/2026) para o alvo fixo;
  o gate humano por execução foi removido a pedido dele. `--confirm` continua
  obrigatório e a preparação validada continua sendo pré-condição.
- O SIGAA autenticado é a fonte operacional do período.
- A implementação aguarda captura real dos resultados e da confirmação para
  habilitar mutação.
