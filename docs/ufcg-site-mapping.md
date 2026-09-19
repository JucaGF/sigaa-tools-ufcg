# Mapeamento do SIGAA UFCG — 18/09/2026

**Estado: levantamento parcial, com 257 HTMLs preservados: 182 públicos e 75 autenticados. A varredura completa ainda não foi concluída.** O Portal do Discente e duas Turmas Virtuais foram percorridos, junto com os principais menus do perfil de discente. Sete capturas antigas foram identificadas como incompletas; as principais páginas afetadas já têm recapturas integrais. Perfis autenticados de docente, coordenação e administração continuam fora do acesso disponível.

O objetivo desta fase é conhecer os contratos da UFCG antes de adaptar a ferramenta para duas instituições. Nenhum código de produção foi alterado, nenhuma matrícula foi realizada e nenhum cadastro, manifestação, inscrição ou resposta acadêmica foi enviado.

## Onde estão os resultados

| Artefato | Conteúdo |
| --- | --- |
| [Inventário UFPB/UFCG](ufpb-ufcg-feature-inventory.md) | 30 funcionalidades atuais, superfícies CLI/MCP, seletores, endpoints, testes, proveniência das fixtures e lacunas de compatibilidade |
| [Índice navegável das capturas](ufcg-mapping/captures.md) | Cada HTML, ação de origem e estado observado |
| [Inventário estrutural JSON](ufcg-mapping/inventory.json) | Páginas, formulários, campos, tabelas, links, controles JSF e fronteira de URLs não capturadas |
| [Evidências autenticadas](ufcg-mapping/authenticated-findings.md) | Cobertura do Portal/Turma Virtual, contratos UFCG e resultado dos parsers atuais sobre capturas reais |
| [Manifesto original local](../captures/sigaa-ufcg/2026-09-18/manifest.json) | Data, URL, origem, SHA-256 e arquivo de cada captura |
| [Pasta local de HTMLs](../captures/sigaa-ufcg/2026-09-18/) | Documentos integrais, disponíveis nesta máquina e ignorados pelo Git |
| [Gerador e verificador offline](ufcg-mapping/build_inventory.py) | Reconstrói o inventário e confere todos os hashes sem acessar a rede |
| [Grafo de código existente](../.ua/knowledge-graph.json) | Índice de dependências do repositório usado na análise; preservado sem misturar páginas web com seus nós de código |

A pasta de captura tem permissão `0700`; arquivos têm `0600`. Os HTMLs conservam dados públicos, dados da conta e campos de sessão do site, por isso não são fixtures sanitizadas nem devem entrar em commits. Para capturas autenticadas, o inventário estrutural omite títulos, cabeçalhos, rótulos de links, URLs externas, valores de query e valores de formulários. Nenhum cookie ou senha foi exportado.

## Método e limites da evidência

Navegação pelo site real, seguindo URLs e controles encontrados no DOM, incluindo postbacks de consulta. Cada HTML é a serialização UTF-8 de `document.documentElement.outerHTML`, com scripts e formulários. **Não é o corpo HTTP original**: headers, status HTTP, encoding da resposta, cadeia completa de redirects, respostas Ajax intermediárias, conteúdo de iframes e downloads binários não foram capturados. O HTML original pode declarar outro charset; para análise offline, ler estes arquivos como UTF-8. Propriedades de controles alteradas apenas em memória não são necessariamente refletidas nos atributos serializados.

O campo `method_declared` vem do formulário; não é uma gravação de rede. IDs JSF, ViewState e ações dependem do render atual. O campo `source` registra a navegação realizada; `requested_url`, quando presente, distingue links de entrada de destinos após redirect. `captured_dom` significa somente HTML salvo, nunca validação integral de uma funcionalidade.

O rodapé público informou **`v4.20.6-ufcg.4`**. A UFPB tem observações históricas de junho de 2026 e testes locais, mas não foi autenticada ou verificada live nesta execução. Não se pode transferir a validade de um parser de uma instituição para a outra. [Entrada oficial UFCG](https://sigaa.ufcg.edu.br/), [exploração histórica UFPB](sigaa-exploration.md).

## Cobertura pública obtida

Na fase pública foram capturados 182 estados de DOM, incluindo duas recapturas integrais de páginas grandes, distribuídos em **79 caminhos de URL** e 109 URLs normalizadas. A fase autenticada adicionou 75 estados; o inventário completo contém 134 URLs normalizadas. Vários estados compartilham a mesma URL. A lista completa está no índice; a tabela abaixo reúne famílias de telas, não declara esgotamento de todas as entidades e filtros.

| Família | Capturas | O que foi observado / limite |
| --- | --- | --- |
| Entrada e login | `001-public-home`, `002-login`, `public-046`, `176-login-acessivel` | Menu público completo no DOM; login clássico, acessibilidade e redirecionamento para empréstimos. A sessão discente é tratada na seção autenticada |
| Autocadastro | `174-cadastro-discente`, `175-cadastro-familiar` | Formulários de aluno e familiar; nenhum envio |
| Acadêmico público | `public-002` a `public-007` | Busca de docentes e responsáveis; centros, departamentos, programas e tipos de documentos |
| Cursos | `public-008`, `014`–`019`, `024`, `027`, `029`, `030` | Listagens em vários níveis: 101 registros de graduação, 108 stricto sensu e 5 técnicos apresentados pelo site. Os detalhes de todos esses cursos não foram percorridos |
| Componentes | `public-009`, `013`, `025`, `028`, `032`, `053`, `066`, `177` | Busca por nível, um erro de consulta, detalhe via currículo e detalhe via link público de docente |
| Turmas públicas | `public-012`, `068-public-turmas-result` | Busca por nível, unidade, ano e período. Consulta graduação/UASC/2026.2 retornou 87 turmas; é oferta pública, não matrícula do estudante |
| Curso de Computação | `054-course-computacao`, `course-00` a `course-08` | Portal, currículos, monografias, artigos, memoriais, outros trabalhos, turmas, calendário, projeto pedagógico e notícias |
| Currículo 2023 | `064`, `065`, `066`, `067` | Estrutura, aba do primeiro período e detalhe de Programação I. Clique em Visualizar Programa não teve destino comprovado; `067` não é evidência de programa baixado |
| Centro CEEI | `156-centro-portal`, `centro-0` a `centro-4` | Apresentação, departamentos, cursos, programas, bases de pesquisa e documentos |
| Unidade UASC | `162-departamento-portal`, `departamento-0` a `departamento-6` | Administração, docentes, componentes, extensão, pesquisa, ensino e documentos. A listagem informa 139 componentes |
| Pesquisa | `public-020` a `public-023` | Formulários de projetos, bases, bolsistas e laboratórios; resultados de todas as consultas não percorridos |
| Programa de pós-graduação | `071-programa-portal`, `programa-00` a `programa-11`, `178-noticia-publica` | Apresentação, áreas, cursos, grade, alunos, docentes, defesas, turmas, pesquisa, calendário, seleções, notícias e uma notícia aberta |
| Docente público | `084-docente-portal`, `docente-00` a `docente-05` | Produção, disciplinas, relatórios, pesquisa, extensão e monitoria, em um perfil público representativo |
| Extensão | `public-033` a `public-040` | Consultas por tipo de ação, inscrições abertas e login próprio da área de inscritos |
| Seleções | `public-031`, `041`–`043`, `069`, `070`, `179`, `180` | Níveis técnico, infantil/fundamental, formação complementar, stricto e lato; detalhe de seleção e formulário da área do candidato. Sem inscrição |
| Biblioteca | `public-044` a `public-048`, `170`–`173` | Acervo, artigos, aquisições, modalidades simples/multicampo/avançada/autoridades. Busca por título “algoritmos” retornou mensagem de ausência de resultados; paginação com resultados ainda pendente |
| Ouvidoria e mobilidade | `public-049` a `public-051` | Formulários de manifestação, esclarecimento e consulta de acordos; nenhuma manifestação enviada |
| Validação de documentos | `public-003`, `validacao-00` a `validacao-64` | Todos os 65 tipos exibidos no seletor foram abertos e capturados. Capturados os formulários, sem validar documentos, preencher identificadores ou resolver CAPTCHA |

## Diferenças e achados que orientam a adaptação

1. **Login e portal diferem da UFPB.** A captura real `002-login` tem `loginForm`, campos `user.login` e `user.senha` e action `logar.do`. O cliente UFPB usa outro formulário e portal beta. A sessão UFCG já existente é uma base apropriada para login, mas hoje só atende o fluxo extraordinário. [Comparação de código](ufpb-ufcg-feature-inventory.md#contratos-de-navegação-que-devem-acompanhar-cada-html).

2. **Uma URL não equivale a uma tela.** Os 65 formulários de validação reaparecem em `tipo_documento.jsf`; a biblioteca também troca de modalidade sem trocar de caminho. O currículo usa POST para abrir outro estado. Guardar apenas URLs ou fazer GET recursivo perde parte significativa da navegação. [Validador oficial](https://sigaa.ufcg.edu.br/sigaa/public/autenticidade/tipo_documento.jsf), capturas `validacao-*`, `170`–`173`.

3. **O parâmetro de nível não garante o filtro selecionado.** Em `public-009`, o link contém `nivel=G`, mas `form:nivel` abre com “INFANTIL”. A tentativa de selecionar graduação e pesquisar `1109103` produziu o render “Comportamento Inesperado!” em `053-component-search-result`. É uma ocorrência observada, não prova de falha permanente do endpoint. [Consulta oficial](https://sigaa.ufcg.edu.br/sigaa/public/componentes/busca_componentes.jsf?nivel=G&aba=p-graduacao).

4. **Há caminhos alternativos públicos para componentes.** Curso → Currículos → Visualizar Estrutura Curricular → Visualizar Detalhes funcionou. A estrutura renderiza em `curriculo.jsf`, mas seu formulário `formulario` aponta para `resumo_curriculo.jsf`. Outro caminho, pela página docente, redireciona de `/link/public/ensino/visualizarComponente/...` para `/public/componentes/resumo.jsf`. Não é seguro deduzir o destino do POST apenas da URL visível. Capturas `064`, `066`, `177`; [currículos do curso usado](https://sigaa.ufcg.edu.br/sigaa/public/curso/curriculo.jsf?lc=pt_BR&id=108095).

5. **Requisitos dependem de currículo e vigência.** Em `066-component-detail`, Programação I (`1411167`) apresenta pré/co-requisitos gerais como `-`, mas a tabela “Expressões específicas de currículo” contém correquisito `( 1411180 )` para currículo 2023, com início em `2024.1`. O futuro modelo deve preservar essa associação, sem concluir “não há correquisito” a partir do campo geral. Essa evidência é da estrutura pública, não da integralização individual do estudante.

6. **Currículo público não é progresso individual.** A estrutura 2023 expõe totais, componentes obrigatórios/optativos/complementares, períodos e vigência. Ela não informa quais disciplinas uma conta concluiu. O endpoint JSON de integralização da UFPB ainda não foi demonstrado na UFCG. Capturas `course-00`, `064`, `065`; [contrato UFPB](ufpb-ufcg-feature-inventory.md).

7. **Calendário varia por nível/programa.** O curso de graduação consultado mostra término de `2026.2` em `19/02/2027`, enquanto o programa consultado mostra `05/02/2027`. Não usar uma data global para toda a UFCG. Isso também não confirma os horários de relógio de M/T/N. [Calendário do curso](https://sigaa.ufcg.edu.br/sigaa/public/curso/calendario.jsf?lc=pt_BR&id=108095), [calendário do programa](https://sigaa.ufcg.edu.br/sigaa/public/programa/calendario.jsf?lc=pt_BR&id=322).

8. **Conteúdo vazio, erro e acesso restrito são estados distintos.** Há telas sem notícias, projetos ou documentos; busca de biblioteca sem resultados; erro de componente; e logins separados para discente, candidato e extensão. Nenhum desses estados deve virar uma lista vazia indistinta no cliente. O inventário usa `server_error_render`, `login_form` e `action_destination_unverified` quando a evidência permite essa classificação; os demais exigem leitura do contexto.

9. **A documentação existente está parcialmente desatualizada.** Existem fixtures reais sanitizadas de resultados e confirmação da matrícula extraordinária UFCG de 16/09; a verificação posterior de vínculo continua baseada em hipótese. Na UFPB, já há parser de docentes e detalhe de tarefa, apesar de notas antigas dizerem “pendente”. O inventário de funcionalidades explica a proveniência, sem reescrever a história das capturas.

## Cobertura autenticada obtida

O levantamento autenticado percorreu o Portal do Discente, duas Turmas
Virtuais (uma atual e uma concluída) e menus de Ensino, Pesquisa, Extensão,
Monitoria, Ações Associadas, Bolsas/Auxílios, Estágio, Relações Internacionais
e Outros. O detalhamento, incluindo os estados vazios e a comparação executável
com os parsers da UFPB, está em [Evidências autenticadas](ufcg-mapping/authenticated-findings.md).

Os principais resultados para a implementação são: o parser de plano de curso
funcionou na captura examinada; o parser da matrícula extraordinária leu 51 de
51 ofertas da recaptura integral; parsers de estudante, turmas, notas gerais,
frequência, docentes e notícias exigem adaptações específicas para o DOM da
UFCG. Nenhuma operação acadêmica com efeito externo foi finalizada.

## Fronteira restante e critério de fechamento

O inventário registra **525 URLs normalizadas não capturadas**, sendo 480 internas e 45 externas, além das ações JSF listadas em cada página. Esse número não mede quantidade de funcionalidades faltantes: inclui outras entidades, idiomas, aliases, downloads e destinos externos. URLs normalizadas não conservam tokens necessários a certos downloads e não devem ser usadas como payloads. A lista é uma fila de inspeção, não uma afirmação de acessibilidade ou autorização para executar ações.

| Prioridade | Falta obter | Condição para avançar |
| --- | --- | --- |
| 1 | Downloads de histórico, declaração, comprovantes e respectivos metadados | Catalogar PDF/HTML e tipo de conteúdo sem publicar dados privados |
| 2 | Integralização individual e eventual resposta JSON | Confirmar se a UFCG possui contrato equivalente ao endpoint beta da UFPB |
| 3 | Exemplos preenchidos de tarefa, arquivo, enquete e questionário | As duas turmas acessíveis apresentaram esses estados vazios |
| 4 | Menus autenticados restantes e variantes com dados | O menu completo está inventariado; nem toda entrada possui um estado representativo com conteúdo |
| 5 | Perfis docente, coordenação e administração | Exigem contas autorizadas desses perfis; acesso discente não os cobre |
| 6 | Fronteira pública restante | Abrir detalhes restantes, filtros e paginações; registrar erros, indisponibilidade e estados sem dados |
| 7 | Comparação efetiva com parsers | Criar fixtures sanitizadas revisadas dos contratos reais e testar cada funcionalidade; os HTMLs privados não são fixtures prontas |

Não existe denominador confiável de “100% de todo o SIGAA” sem definir perfis, entidades e estados. O critério operacional é fechar a fronteira **declarada**: toda entrada descoberta tem artefato ou motivo explícito de não captura; cada funcionalidade atual da UFPB tem comparação UFCG; cada ação de navegação tem origem e destino comprovados. Este levantamento ainda não atende esse critério e não comprova paridade entre as instituições.

## Reproduzir a verificação local

```bash
.venv/bin/python docs/ufcg-mapping/build_inventory.py --self-test
.venv/bin/python docs/ufcg-mapping/build_inventory.py captures/sigaa-ufcg/2026-09-18
```

O gerador confere unicidade dos IDs, contenção dos caminhos, fechamento do HTML e SHA-256 antes de reconstruir JSON e índice. Seu teste mínimo confere remoção de tokens, privacidade das capturas autenticadas, reconhecimento de erro, truncamento e método declarado. A análise do código executou também a suíte existente: **454 testes passaram**. Esses resultados são offline e não cobrem downloads, outros perfis ou estados privados que não existiam nas turmas acessíveis.
