# Evidências autenticadas do SIGAA UFCG

Levantamento de 18–19/09/2026. Os HTMLs privados permanecem em
`captures/sigaa-ufcg/2026-09-18/`, ignorados pelo Git e com permissões locais
restritas. Este documento registra contratos estruturais e resultados dos
parsers sem reproduzir dados pessoais, notas ou conteúdo acadêmico privado.

## Cobertura obtida

O manifesto contém 257 estados: 182 públicos e 75 autenticados. Desses, 250
terminam em `</html>` e sete capturas antigas estão marcadas como
`incomplete_html`; elas não podem fundamentar conclusões de compatibilidade.
As recapturas integrais principais são `auth-039-portal-completo` e
`auth-072-extraordinaria-ofertas-completo`.

| Área | Evidência autenticada |
| --- | --- |
| Portal | vínculo, semestre, índices, integralização resumida, turmas atuais, atividades e scripts completos do menu discente |
| Turma Virtual | principal, plano, notícias e detalhe, frequência vazia e preenchida, notas vazias e preenchidas, participantes, materiais, avaliações, tarefas, enquetes e questionários |
| Ensino | notas gerais, índices, atestado, turmas anteriores, matrícula regular fora do período, matrícula extraordinária, estruturas curriculares e calendário |
| Pesquisa e extensão | buscas, participações, planos, certificados, relatórios e resultados de seleção, inclusive estados sem registros |
| Monitoria, bolsas e estágio | busca e vínculos, relatórios, oportunidades, interesses, bolsas e estágios cadastrados ou ausentes |
| Outras áreas | mobilidade, comunidades, fórum, ouvidoria, dossiê, processos, acervo, defesas, atendimento acadêmico e serviços de apoio |

Abrir formulários de inscrição ou solicitação serviu apenas para registrar o
DOM inicial. Nenhuma matrícula, inscrição, manifestação, tarefa, mensagem ou
solicitação foi confirmada.

## Resultado contra os parsers atuais da UFPB

O comando abaixo executa os parsers existentes diretamente sobre capturas
reais da UFCG e imprime apenas contagens e presença de campos:

```bash
.venv/bin/python -m docs.ufcg-mapping.check_existing_parsers
```

| Contrato atual | Resultado UFCG | Consequência para a adaptação |
| --- | --- | --- |
| `parse_student` | matrícula e semestre presentes; nome, curso e e-mail ausentes | o cabeçalho UFCG não usa os textos esperados da UFPB |
| `parse_turmas` | produz 10 itens, todos sem sala/horário | os anchors e as células do portal têm outra composição; também há eventos recentes que parecem turmas |
| `parse_grades` | zero notas em 12 linhas de dados | a UFCG renderiza 15 colunas, enquanto o parser exige 16 |
| `parse_course_plan` | 29 aulas e 3 avaliações | este contrato é compatível na captura examinada |
| `parse_attendance` | reconhece o bloco, mas não lê os totais; lê 33 datas na turma concluída | os rótulos de resumo diferem dos regexes atuais |
| `parse_professors` | zero docentes apesar de existir um bloco `Docentes (1)` | o parser procura uma legenda iniciada por “Professor(es)” |
| `parse_news_list` | zero notícias apesar da lista visível | o painel e os formulários UFCG diferem do contrato UFPB |
| `parse_turma_grades` | unidades, resultado, faltas e situação presentes | compatibilidade parcial; exame final ausente nesse estado é válido |
| `parse_classes` extraordinária | 51 ofertas lidas de 51 exibidas | o parser atual funciona na recaptura integral usada |

Esses resultados são sondas de compatibilidade, não testes de produção. Os
parsers ainda precisam de fixtures sanitizadas e casos separados por
instituição antes de qualquer alteração no cliente compartilhado.

## Contratos observados

- O login clássico usa `loginForm`, `user.login`, `user.senha` e `logar.do`.
- O menu discente usa o formulário `menu:form_menu_discente` e ações JSF
  declaradas em JSCookMenu. IDs gerados não devem ser fixados no código.
- A Turma Virtual usa `formMenu`; seus IDs também variam por render. Cada
  postback deve partir de uma página atual da turma selecionada.
- A página geral de notas da UFCG tem unidades 1–9, final, resultado, faltas e
  situação, totalizando 15 colunas na captura examinada.
- “Ver Notas” sem lançamentos apenas exibe uma mensagem sobre a tela corrente;
  quando há notas, abre o relatório `Alunos Matriculados`.
- Frequência pode afirmar que ainda não foi lançada e, ao mesmo tempo, exibir
  totais agregados. O parser deve preservar ambos os sinais.
- A matrícula regular estava fora do período. A extraordinária estava aberta
  de 16/09/2026 a 06/10/2026 e sua busca por nome retornou uma tabela de
  ofertas que o parser atual conseguiu interpretar integralmente.
- Estados “nenhum registro”, “usuário não participou”, “fora do período” e
  “formulário disponível” são respostas distintas e não devem convergir para
  uma lista vazia sem contexto.

## Limites restantes

O acesso disponível é de discente. Perfis de docente, coordenação e
administração não foram autenticados. Downloads PDF e respostas JSON ainda
precisam ser catalogados por tipo de conteúdo; o corpus atual registra DOM
renderizado, sem headers HTTP. Tarefas e arquivos preenchidos não apareceram
nas duas turmas examinadas, portanto faltam exemplos reais desses estados.

## Fechamento seguro das lacunas em 19/09/2026

Uma nova navegação autenticada fechou três contratos sem persistir HTML bruto,
ViewState ou valores pessoais. O resultado sanitizado está em
`safe-gap-captures.json`.

- O detalhe de uma oferta extraordinária possui tabelas próprias com período,
  componente/turma, tipo, local/horário, capacidade e reservas de vagas.
- A seleção de uma oferta leva a um formulário POST separado em
  `/sigaa/graduacao/matricula/extraordinaria/confirmacao.jsf`, com CPF, senha e
  o botão `Confirmar Matrícula`. Nenhum valor foi preenchido e o formulário não
  foi enviado.
- O detalhe de estrutura curricular foi recapturado estruturalmente: 267 linhas,
  dez níveis e campos de cargas horárias, vigência e prazos de conclusão.
- O manual oficial do discente confirmou os horários M1–M5, T1–T5 e N1–N4;
  esse contrato também foi registrado no arquivo sanitizado.
- Histórico e declaração de vínculo tiveram suas ações de menu confirmadas, mas
  seus documentos não foram abertos nem salvos para cumprir a restrição de não
  capturar dados sensíveis.
