# SPEC — Mapeamento do SIGAA UFCG e paridade com a UFPB

**Estado:** referência consolidada para a adaptação multi-instituição.
**Levantamento:** 16–19/09/2026.
**SIGAA UFCG observado:** `4.20.6-ufcg.4`.
**Corpus:** 257 estados de DOM, sendo 182 públicos e 75 autenticados.
**Perfil autenticado coberto:** discente.
**Segurança:** nenhuma matrícula, inscrição, tarefa, manifestação, mensagem ou
solicitação foi confirmada.

Esta é a fonte principal dos contratos conhecidos da UFCG para adaptar a
ferramenta que hoje atende a UFPB. Ela consolida o mapa público, as evidências
autenticadas, a comparação executável dos parsers, o knowledge graph do código,
as capturas sanitizadas e as lacunas que ainda dependem de outro estado, período
ou perfil.

## 1. Objetivo e critério de evidência

O objetivo é suportar UFPB e UFCG sem transferir seletores, endpoints ou
suposições de uma instituição para a outra. Um fluxo só está comprovado quando
há evidência do render real ou resposta real correspondente. Teste sintético
prova comportamento do código, mas não prova o DOM do servidor.

Ordem de confiança:

1. Captura real completa e sanitizada ou contrato estrutural observado ao vivo.
2. HTML real privado preservado localmente, usado apenas para análise offline.
3. Código e teste baseados explicitamente em captura real.
4. Relato histórico de navegação.
5. Fixture sintética ou hipótese derivada da UFPB.

O `.ua/knowledge-graph.json` indexa o código, não as páginas do SIGAA. Ele contém
413 nós e 811 arestas e foi usado para seguir cliente → parser → serviço → teste.
Comentários das fixtures e capturas reais prevalecem sobre resumos do grafo.

## 2. Fontes consolidadas

| Fonte | Papel |
| --- | --- |
| `captures/sigaa-ufcg/2026-09-18/` | HTMLs locais integrais; privados, ignorados pelo Git |
| `captures/sigaa-ufcg/2026-09-18/manifest.json` | origem, data, hash e arquivo de cada captura |
| `docs/ufcg-mapping/inventory.json` | inventário estrutural sanitizado |
| `docs/ufcg-mapping/captures.md` | índice dos 257 estados |
| `docs/ufcg-mapping/authenticated-findings.md` | achados autenticados e sondas dos parsers |
| `docs/ufcg-mapping/safe-gap-captures.json` | contratos adicionais sem valores pessoais |
| `docs/ufpb-ufcg-feature-inventory.md` | superfície funcional atual da ferramenta |
| `docs/ufcg-site-mapping.md` | relatório da varredura pública e autenticada |
| `tests/fixtures/ufcg/` | fixtures reais sanitizadas e hipóteses identificadas |
| `.ua/knowledge-graph.json` | dependências do código existente |

Os HTMLs privados têm diretório `0700` e arquivos `0600`. Eles não são fixtures
prontas para commit porque podem conter dados da conta e tokens JSF.

## 3. Cobertura e limites do corpus

| Medida | Quantidade |
| --- | ---: |
| Capturas | 257 |
| Públicas | 182 |
| Autenticadas | 75 |
| HTMLs completos | 250 |
| HTMLs antigos incompletos | 7 |
| URLs normalizadas distintas | 134 |
| Estados `captured_dom` | 243 |
| Formulários de login observados | 4 |
| Renders de erro do servidor | 2 |
| Destino de ação não comprovado | 1 |
| URLs descobertas ainda não capturadas | 525 |

As capturas são `document.documentElement.outerHTML` em UTF-8. Elas não contêm
headers HTTP, status, cadeia integral de redirects, respostas Ajax intermediárias,
conteúdo de iframes ou bytes de downloads. `method_declared` descreve o formulário,
não uma gravação de rede. Uma mesma URL JSF pode representar muitos estados.

Quatro capturas incompletas ganharam substitutas integrais: portal do discente,
ofertas extraordinárias e as duas páginas públicas grandes de docente. Permanecem
historicamente incompletas as entradas de matrícula regular, detalhe de oferta e
detalhe curricular; os dois últimos contratos foram depois recapturados de forma
estrutural e sanitizada em `safe-gap-captures.json`.

## 4. Arquitetura atual da ferramenta

O cliente geral continua orientado à UFPB:

- `sigaa/client.py` concentra portal, turmas, notícias, materiais, notas,
  frequência, plano, documentos, currículo e matrícula regular.
- `sigaa/config.py` mantém endpoints, credenciais e horários com pressupostos UFPB.
- `sigaa/services/sync.py` sincroniza o cliente geral para o SQLite.
- `sigaa/mcp_server.py` expõe 25 tools no modo local; o modo hosted remove cinco
  downloads que escrevem arquivos. O servidor ainda se chama `sigaa-ufpb`.
- O banco não possui instituição/conta nas chaves principais de todos os objetos.

O suporte UFCG existente é separado:

- `sigaa/ufcg.py` implementa sessão e login clássico da UFCG.
- `sigaa/extraordinary.py` implementa somente matrícula extraordinária.
- `sigaa/parsers/matricula_extraordinaria.py` contém os contratos reais desse fluxo.
- O CLI fixa componente `1109103`, turma `02` e semestre `2026.2`; não há MCP
  equivalente para a extraordinária.

Trocar apenas o hostname do cliente UFPB não é uma adaptação válida.

## 5. Diferenças principais entre UFPB e UFCG

| Área | UFPB implementada | UFCG observada | Consequência |
| --- | --- | --- | --- |
| Login | `/sigaa/logon.jsf`, formulário `form`, `form:login`, `form:senha` | `/sigaa/verTelaLogin.do`, `loginForm`, `user.login`, `user.senha`, POST `logar.do` | estratégia de autenticação por instituição |
| Portal | portal beta `/sigaa/portais/discente/beta/discente.jsf` | portal clássico `/sigaa/portais/discente/discente.jsf` | parsers e marcadores de sessão distintos |
| Sessão válida | texto “Sair do SIGAA” | URL correta, ausência de `loginForm` e link `logar.do?dispatch=logOff` com “Sair” | não aceitar apenas HTTP 200 ou texto genérico |
| Menus | âncoras/postbacks JSF do portal beta | JSCookMenu em arrays JavaScript, formulário `menu:form_menu_discente`, campo `jscook_action` | menu não pode ser descoberto apenas por `href` |
| IDs JSF | gerados pelo render | também gerados e variáveis | localizar por estrutura/semântica, nunca fixar `j_id_jsp_*` |
| Cabeçalho discente | textos usados por `parse_student` | composição e rótulos diferentes | parser UFPB perde nome, curso e e-mail |
| Turmas | tabela e âncoras reconhecidas por `parse_turmas` | composição diferente; eventos recentes podem parecer turmas | parser atual cria falsos itens e perde sala/horário |
| Notas gerais | 16 colunas, unidades 1–10 | 15 colunas, unidades 1–9 | parser deve mapear cabeçalhos, não quantidade fixa |
| Docentes | legenda “Professor(es)” | bloco `Docentes (1)` | aliases por instituição |
| Notícias | painel `headerBloco`/`rich-stglpanel-body` | painel e formulários diferentes | lista e postback do corpo precisam de adaptador UFCG |
| Frequência | regexes para totais UFPB | datas reconhecíveis, rótulos de resumo diferentes | preservar linhas e adaptar totais |
| Currículo individual | shell beta + JSON `integralizacao/dados/` | estrutura curricular clássica em HTML; nenhum JSON individual comprovado | não reutilizar parser JSON da UFPB |
| Matrícula regular | seleção por checkbox `selecaoTurmas` | fluxo clássico não capturado aberto | implementar somente após período aberto real |
| Extraordinária | sem equivalente no cliente UFPB | seta JSF com `idTurma`, busca e confirmação próprias | módulo UFCG separado já é a base correta |
| Horários | tabela local ainda não confirmada | tabela oficial UFCG encontrada | configuração por instituição |
| Calendário | hipóteses gerais do cliente | datas variam por curso, programa, nível e período | vigência deve vir da turma/calendário correto |
| SIPAC | host e parsers UFPB | não mapeado para UFCG | projeto separado de `sigaa.ufcg.edu.br` |

## 6. Contratos de navegação UFCG

### 6.1 Login e sessão

- Entrada: `/sigaa/verTelaLogin.do`.
- Formulário: `loginForm`.
- Campos: `user.login`, `user.senha`, `width`, `height` e hidden do render.
- Action: `/sigaa/logar.do`, podendo incluir `;jsessionid`.
- Portal autenticado: `/sigaa/portais/discente/discente.jsf`.
- Logout: `logar.do?dispatch=logOff`.
- O cabeçalho mostra contagem de tempo de sessão; ViewState e formulários preparados
  expiram com a sessão.
- A sessão UFCG não deve repetir automaticamente um POST mutável após relogin.

Estados ainda sem evidência específica: seleção entre múltiplos vínculos e timeout
natural. Logout/reentrada e credencial inválida não substituem necessariamente o
render de expiração natural.

### 6.2 Portal e menus

- O menu discente usa `menu:form_menu_discente`.
- A ação selecionada é enviada por `jscook_action`.
- As ações reais ficam nos scripts do JSCookMenu, mesmo quando o hidden está vazio.
- Exemplos confirmados:
  - histórico: `#{ portalDiscente.historico }`;
  - declaração: `#{ declaracaoVinculo.emitirDeclaracao }`;
  - estrutura curricular: `#{ curriculo.popularBuscaGeral }`;
  - extraordinária: `#{ matriculaExtraordinaria.iniciar }`.
- O portal contém vínculo, semestre, índices, integralização resumida, turmas e
  áreas de atualizações. O resumo de integralização não é progresso por componente.

### 6.3 Turma Virtual

- Formulário de menu observado: `formMenu`.
- Cada postback deve partir de um render atual da turma selecionada.
- Reaproveitar o Principal de uma turma para postback de outra permite atribuição
  silenciosa de dados à turma errada.
- Foram percorridas uma turma atual e uma concluída: Principal, Plano, Notícias,
  detalhe de notícia, Frequência, Ver Notas, Arquivos, Conteúdo, Referências,
  Vídeos, Avaliações, Tarefas, Enquetes, Questionários e Participantes.

## 7. Contratos funcionais observados

### 7.1 Identidade e turmas

O portal contém matrícula e semestre em formato aproveitável, mas o parser atual
não encontra nome, curso e e-mail. `parse_turmas` retorna dez itens, todos sem
sala/horário, e inclui elementos que não são turmas. A adaptação deve:

- localizar o bloco real de vínculo;
- aceitar formato de matrícula institucional, sem exigir 11 dígitos;
- distinguir turma de evento/atualização;
- preservar código, nome, id da turma, local, expressão de horário e vigência;
- cobrir turmas atuais, anteriores e estado sem turma.

### 7.2 Horários

O Manual do Discente da UFCG confirma os dias `1`–`7` como domingo–sábado e:

| Slot | Horário | Slot | Horário | Slot | Horário |
| --- | --- | --- | --- | --- | --- |
| M1 | 07:00–08:00 | T1 | 13:00–14:00 | N1 | 18:30–19:20 |
| M2 | 08:00–09:00 | T2 | 14:00–15:00 | N2 | 19:20–20:10 |
| M3 | 09:00–10:00 | T3 | 15:00–16:00 | N3 | 20:10–21:10 |
| M4 | 10:10–11:10 | T4 | 16:10–17:10 | N4 | 21:10–22:00 |
| M5 | 11:10–12:10 | T5 | 17:10–18:10 | — | — |

Exemplo oficial: `45N23` significa quarta e quinta, N2 e N3. O ICS deve usar
essa tabela UFCG e a vigência da turma; as aulas diurnas têm 60 minutos e as
noturnas, 50 minutos.

### 7.3 Notícias

Foram capturadas lista preenchida e notícia aberta. O parser UFPB retorna zero.
A adaptação deve manter id estável, título, data, turma de origem, indicador de
leitura e postback do corpo. Estado sem notícias e eventual paginação são estados
distintos.

### 7.4 Materiais

Foram abertas as áreas Arquivos, Conteúdo/Página Web, Referências e Vídeos. Nas
turmas examinadas não apareceu arquivo real para download. Falta comprovar:

- `div.topico-aula` preenchido na UFCG;
- controle real de arquivo e link externo;
- postback do download;
- `Content-Type`, `Content-Disposition` e nome do arquivo.

### 7.5 Notas

- Relatório geral: 15 colunas; o parser fixo de 16 retorna zero para 12 linhas.
- Ver Notas: estado vazio mostra mensagem; turma anterior possui unidades,
  resultado, faltas e situação.
- `parse_turma_grades` é parcialmente compatível.
- Exame final preenchido não apareceu no vínculo disponível.

O parser deve mapear colunas por cabeçalho e aceitar campos opcionais, preservando
a diferença entre sem lançamento, nota parcial e resultado consolidado.

### 7.6 Frequência

- A turma corrente apresentou estado sem mapa.
- A turma concluída apresentou 33 datas.
- O parser reconhece o bloco e as datas, mas não os totais.
- A página pode dizer que a frequência ainda não foi lançada e mostrar totais
  agregados simultaneamente; ambos os sinais devem ser preservados.
- Não houve exemplo com falta justificada ou limite máximo preenchido.

### 7.7 Plano de curso

`parse_course_plan` leu 29 aulas e 3 avaliações sem alteração. Este é o contrato
mais compatível entre as instituições na amostra. Ementa, metodologia,
bibliografia e demais campos não são extraídos pelo parser atual.

### 7.8 Docentes e participantes

Há bloco `Docentes (1)`, mas `parse_professors` retorna zero porque procura
“Professor(es)”. O parser deve limitar-se a docentes e não armazenar a lista de
discentes ou seus contatos. Casos com mais de um docente ainda não foram vistos.

### 7.9 Prazos, avaliações e tarefas

O parser UFPB espera menus beta `dropdown-menu-avaliacao/atividade/tarefa/enquete`.
Esse DOM não foi demonstrado na UFCG. Plano de curso permite gerar prazos de
avaliação, mas eventos do portal precisam de contrato separado.

As listas de tarefas das turmas examinadas estavam vazias. Faltam tarefa dentro e
fora do prazo, detalhe, instruções e anexo do professor. Nenhuma resposta deve ser
enviada durante o mapeamento.

### 7.10 Documentos acadêmicos e CRA

- Atestado de matrícula HTML foi capturado.
- As ações de menu de Histórico e Declaração de Vínculo foram confirmadas.
- Histórico e declaração não foram abertos nem salvos na etapa final para evitar
  captura de dados pessoais.
- Não há bytes, headers ou diagramação real desses PDFs no corpus atual.
- Sem histórico PDF real não é possível certificar `parse_cra_pdf` para UFCG.
- Os 65 formulários públicos de validação de documentos foram abertos sem
  preencher identificadores ou resolver CAPTCHA.

### 7.11 Currículo e integralização

O detalhe curricular clássico foi recapturado com 267 linhas e dez níveis. O
formulário `formulario` faz POST para
`/sigaa/geral/estrutura_curricular/resumo.jsf` e usa `formulario:tab_painel`.
Foram observados:

- código, matriz e vigência;
- carga horária mínima e subtotais;
- cargas optativa, complementar, EAD e atividade específica;
- limite de eletivas e carga máxima por período;
- prazos mínimo, médio e máximo para conclusão;
- componentes distribuídos por nível.

Requisitos podem variar por currículo e vigência. Um componente cujo requisito
geral é `-` pode possuir expressão específica para o currículo vigente. A
estrutura pública não informa componentes concluídos pelo estudante. Nenhum
equivalente UFCG do JSON `integralizacao/dados/` da UFPB foi comprovado.

### 7.12 Matrícula regular

Foi observado somente o estado fora do período. Permanecem sem captura real:

- instruções de período aberto;
- turmas abertas do currículo;
- reservas e permissões;
- seleção de turmas;
- página de conferência;
- recibo ou número da solicitação.

A janela 2026.2 registrada no calendário já havia encerrado. Uma lista vazia não
pode representar “período fechado”.

### 7.13 Matrícula extraordinária

Busca e resultado usam
`/sigaa/graduacao/matricula/extraordinaria/matricula_extraordinaria.jsf`.

Busca:

- formulário `form`;
- `form:checkCodigo=on` e `form:txtCodigo`;
- todos os `<select>` devem ser enviados com o valor selecionado;
- botão `form:buscar` usa o valor do render atual;
- hidden e ViewState vêm do render atual.

Resultados:

- `table#lista-turmas-extra.listagem`;
- grupos `tr.disciplina` carregam o código do componente;
- cabeçalhos úteis: Turma, Horário, Local e Vagas;
- seleção é uma seta JSF com campo variável e `idTurma`;
- zoom abre detalhe e não seleciona;
- parser atual leu 51 de 51 ofertas na recaptura integral.

O detalhe observado contém período, componente/turma, tipo do componente, tipo
da turma, local/horário, capacidade e reservas para ingressantes/demais.

Após selecionar uma oferta, sem efetivar matrícula, apareceu:

```text
POST /sigaa/graduacao/matricula/extraordinaria/confirmacao.jsf
```

O id do formulário é gerado. Campos sem valores preservados no contrato:
`inputHiddenOpcaoExibir`, `apenasSenha`, um campo de identidade rotulado no
render, senha, `btnConfirmar` e `btnRealizarNovaMatricula`. A observação de
19/09 mostrou sufixo `cpf`; a captura real anterior mostrou Data de Nascimento.
O parser deve localizar o campo pelo render atual e não fixar uma única variante.

Nenhum valor foi preenchido e `Confirmar Matrícula` não foi enviado. Continuam
sem evidência real: sucesso, recusas acadêmicas e página posterior que prove o
vínculo. `tests/fixtures/ufcg/enrolled.html` é hipótese derivada da UFPB.

## 8. Sondas dos parsers atuais

Comando:

```bash
.venv/bin/python docs/ufcg-mapping/check_existing_parsers.py
```

| Parser | Resultado sobre UFCG | Estado |
| --- | --- | --- |
| `parse_student` | matrícula e semestre; sem nome, curso e e-mail | incompatível |
| `parse_turmas` | 10 itens; nenhum horário/sala válidos | incompatível e sujeito a falso positivo |
| `parse_grades` | zero notas para 12 linhas | incompatível |
| `parse_course_plan` | 29 aulas e 3 avaliações | compatível na amostra |
| `parse_attendance` | 33 datas; totais ausentes | parcial |
| `parse_professors` | zero para `Docentes (1)` | incompatível |
| `parse_news_list` | zero com notícias visíveis | incompatível |
| `parse_turma_grades` | unidades, resultado, faltas e situação | parcial |
| `parse_classes` extraordinária | 51 de 51 ofertas | compatível na amostra |

Retorno vazio em DOM desconhecido deve virar incompatibilidade explícita quando
a página anuncia dados, não “nenhum registro”.

## 9. Mapa das superfícies observadas

### 9.1 Público

Foram observadas entrada/login, autocadastro, docentes, responsáveis, centros,
departamentos, cursos, componentes, turmas, currículos, páginas de curso,
programas de pós-graduação, produção docente, pesquisa, extensão, seleções,
biblioteca, ouvidoria, mobilidade, calendário e os 65 tipos de validação de
documentos.

Observações relevantes:

- a consulta graduação/UASC/2026.2 exibiu 87 turmas públicas;
- a listagem apresentou 101 cursos de graduação, 108 stricto sensu e 5 técnicos;
- a UASC apresentou 139 componentes;
- `nivel=G` não garantiu que o seletor abrisse em graduação;
- uma busca por componente produziu “Comportamento Inesperado!”, sem provar
  indisponibilidade permanente;
- currículo e componente possuem caminhos alternativos por curso e por docente;
- o link “Visualizar Programa” de um componente ficou sem destino comprovado;
- biblioteca sem resultado e erro do servidor são estados diferentes;
- candidato e extensão possuem logins próprios.

### 9.2 Autenticado

Foram observados Portal, Turma Virtual, Ensino, Pesquisa, Extensão, Monitoria,
Ações Associadas, Bolsas/Auxílios, Estágio, Relações Internacionais e Outros.
Isso inclui índices, atestado, turmas anteriores, calendário, estruturas
curriculares, comunidades, fórum, ouvidoria, dossiê, processos, acervo, defesas,
atendimento e serviços de apoio. Formulários mutáveis foram apenas abertos.

Perfis de docente, coordenação e administração não foram autenticados.

## 10. Matriz de paridade funcional

| Funcionalidade existente | Evidência UFCG | Situação para implementação |
| --- | --- | --- |
| Login/sessão | real | criar estratégia UFCG e renovação segura |
| Identidade | real | adaptar parser |
| Turmas atuais/anteriores | real | adaptar parser e isolamento de contexto |
| Horários | manual oficial | configurar slots UFCG |
| Docentes | real | adaptar legenda/estrutura |
| Notícias lista/corpo | real | adaptar painel e postbacks |
| Materiais lista | menus reais, sem arquivo | parser pendente de estado preenchido |
| Download de material | sem arquivo real | bloqueado por conteúdo disponível |
| Notas por semestre | real | mapear 15 colunas por cabeçalho |
| Notas por turma | real | adaptação parcial |
| Frequência | real | adaptar totais; faltas justificadas pendentes |
| Plano de curso | real | compatível na amostra |
| Prazos do portal | parcial | contrato clássico pendente |
| Prazos do plano | avaliações reais | reutilizar com IDs por instituição/turma |
| Tarefa detalhe/anexo | listas vazias | bloqueado por conteúdo disponível |
| Histórico PDF | ação real, corpo não capturado | pendente por privacidade |
| Declaração de vínculo | ação real, corpo não capturado | pendente por privacidade |
| Atestado | HTML real | adaptar formato/assets |
| CRA | sem PDF real | pendente |
| Integralização individual | apenas resumo/estrutura | contrato individual pendente |
| Matrícula regular aberta | somente período fechado | pendente de janela acadêmica |
| Matrícula regular confirmação | sem evidência | pendente de janela acadêmica |
| Extraordinária busca/ofertas | real | compatível na amostra |
| Extraordinária conferência | real, sem envio | contrato capturado |
| Extraordinária vínculo posterior | hipótese | não implementar como comprovado |
| Sync/SQLite | depende dos parsers | incluir instituição/conta nas fronteiras |
| Novidades/seen | depende de IDs estáveis | validar após sync multi-instituição |
| ICS | slots agora comprovados | separar calendário UFCG |
| SIPAC processo/busca | apenas UFPB | fora do escopo deste host |

## 11. Requisitos para a adaptação

1. Introduzir instituição como escolha explícita de configuração e sessão.
2. Manter autenticação e endpoints por instituição atrás do cliente compartilhado.
3. Isolar parsers quando o DOM divergir; compartilhar apenas normalização e
   modelos realmente comuns.
4. Tornar chaves persistidas seguras para instituição e conta antes de sincronizar
   duas origens no mesmo banco.
5. Mapear tabelas por cabeçalho e blocos por semântica, evitando número fixo de
   colunas e ids JSF gerados.
6. Distinguir vazio legítimo, período fechado, acesso negado, sessão expirada,
   erro do servidor e DOM incompatível.
7. Reconstruir postbacks com formulário e ViewState do render atual.
8. Reentrar na turma antes de cada postback dependente de contexto.
9. Separar navegação somente leitura de mutação; confirmações acadêmicas exigem
   opção explícita e reconferência do alvo.
10. Criar fixtures UFCG sanitizadas por funcionalidade antes de alterar parsers
    compartilhados.
11. Configurar horários e calendário por instituição; não reutilizar constantes
    UFPB no ICS UFCG.
12. Manter conteúdo pessoal, tokens, cookies e documentos reais fora do Git.

## 12. Lacunas e motivo

| Lacuna | Motivo atual |
| --- | --- |
| Material e tarefa preenchidos | não existiam nas turmas examinadas |
| Anexos de material/tarefa | dependem de publicação do docente |
| Frequência com justificativa | vínculo disponível não possui o estado |
| Exame final preenchido | vínculo disponível não possui o estado |
| Matrícula regular aberta/recibo | janela 2026.2 encerrada |
| Integralização individual detalhada | nenhuma tela/JSON equivalente descoberta |
| Histórico, declaração e CRA reais | conteúdo pessoal deliberadamente não capturado |
| Sucesso/recusa da extraordinária | exigiria enviar solicitação acadêmica real |
| Vínculo posterior da extraordinária | mesma limitação; fixture atual é hipótese |
| Múltiplos vínculos | conta acessível não apresenta o estado |
| Portal sem turmas | conta acessível possui turmas |
| Docente/coordenação/administração | exigem credenciais autorizadas desses perfis |
| SIPAC UFCG | host e sistema separados, fora desta varredura |

## 13. Observações que não podem se perder

- URL igual não implica tela igual; estado e postback fazem parte da identidade.
- `captured_dom` não significa fluxo funcional validado.
- Erro, vazio, período fechado e falta de permissão são resultados diferentes.
- Currículo público não é integralização individual.
- Calendários de curso e programa podem terminar em datas diferentes.
- Requisitos de componente podem variar por currículo e vigência.
- IDs `j_id_jsp_*`, ViewState e nomes de controles por linha são efêmeros.
- Links `href` não enumeram ações guardadas em scripts JSCookMenu.
- Download exige bytes e headers; HTML não comprova suporte binário.
- Um sync bem-sucedido não prova que cada submenu foi interpretado.
- Resultados e confirmação extraordinária são reais; vínculo posterior continua
  hipotético. Documentos históricos que dizem o contrário estão desatualizados.
- Dados pessoais de participantes, documentos e cabeçalhos de conta não fazem
  parte do domínio que a ferramenta precisa armazenar.

## 14. Validação e critério de conclusão

Verificações executadas durante o levantamento:

```bash
.venv/bin/python docs/ufcg-mapping/build_inventory.py --self-test
.venv/bin/python docs/ufcg-mapping/build_inventory.py captures/sigaa-ufcg/2026-09-18
.venv/bin/python docs/ufcg-mapping/check_existing_parsers.py
.venv/bin/python -m pytest -q
```

A suíte completa registrada no levantamento teve 454 testes aprovados. Após as
capturas seguras finais, 70 testes focados em extraordinária, currículo e
calendário também passaram. São testes offline.

O mapeamento estará fechado para um perfil e conjunto de estados declarados
quando:

- cada entrada descoberta tiver artefato ou motivo explícito de não captura;
- cada ação relevante tiver origem, formulário, método e destino comprovados;
- cada funcionalidade da matriz tiver contrato UFCG, bloqueio explícito ou
  decisão formal de fora de escopo;
- parsers UFCG tiverem fixtures sanitizadas e falharem explicitamente em DOM
  desconhecido;
- sync, armazenamento, CLI, MCP e ICS distinguirem instituição e conta;
- nenhuma conclusão depender de fixture marcada como hipótese.

Esta SPEC não afirma que todo o SIGAA UFCG foi capturado. Ela define o conjunto
observado, as diferenças comprovadas e o trabalho necessário para atingir paridade
com a superfície atual da UFPB.
