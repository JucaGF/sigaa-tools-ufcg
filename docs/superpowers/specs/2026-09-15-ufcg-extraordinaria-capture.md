# Captura real — matrícula extraordinária UFCG

**Versão observada:** `SIGAA 4.20.6-ufcg.4`, publicada em 15/09/2026 17:37.
**Data da captura:** 16/09/2026. **Semestre:** `2026.2`.

Sem PII: nomes, matrícula, e-mail, identificadores de usuário e ViewState reais
foram removidos. IDs `j_id_jsp_*` e o ViewState são efêmeros e **nunca** viram
constante de produção — o parser lê tudo do render atual.

## 1. Página de confirmação

**Papel:** último passo antes da mutação. Chega-se a ela após selecionar uma turma
na lista de resultados.

```text
action=/sigaa/graduacao/matricula/extraordinaria/confirmacao.jsf
method=post
enctype=application/x-www-form-urlencoded
```

O formulário **não** se chama `form`: o `name`/`id` é um id JSF gerado
(`j_id_jsp_<n>_1` na captura). Localizar pelo `action` que termina em
`confirmacao.jsf`, nunca pelo nome.

### 1.1 Campos

| Campo | Tipo | Observação |
| --- | --- | --- |
| `<form-id>` | hidden | marcador do formulário, valor igual ao próprio id |
| `<form-id>:inputHiddenOpcaoExibir` | hidden | valor `1` na captura |
| `apenasSenha` | hidden | vazio na captura; nome **não** prefixado pelo form id |
| `<form-id>:Data` | text | Data de Nascimento, `maxlength=10`, máscara `##/##/####` |
| `<form-id>:senha` | password | senha do discente |
| `javax.faces.ViewState` | hidden | efêmero |

Os dois campos de identidade são obrigatórios (`th class="obrigatorio"`) e devem
ser localizados dinamicamente: `input[type=password]` para a senha e o campo cujo
id/título indica data de nascimento.

### 1.2 Botões

```text
<form-id>:btnConfirmar                value="Confirmar Matrícula"
<form-id>:btnRealizarNovaMatricula    value="Realizar Outra Matrícula Extraordinária"
```

Há **dois** submits. O heurístico de seleção do botão deve preferir o que contém
`confirm` no nome ou no valor. O segundo não é cancelamento, mas também não
confirma: enviá-lo descartaria a tentativa.

O `btnConfirmar` carrega `onclick="return confirm('Deseja realmente matricular-se
nessa turma? Esta operação não poderá ser desfeita.')"` — um diálogo do navegador,
irrelevante para um cliente HTTP.

### 1.3 Reconferência do alvo

A turma preparada aparece em `table.listagem` com `caption` "Turmas Selecionadas (N)":

```text
<th>Componente Curricular</th> <th>Turma</th> <th>Local</th>
<td>1109126 - CÁLCULO DIFERENCIAL E INTEGRAL I - 60h</td> <td>Turma 07</td> <td>CAA-402</td>
<td colspan="3">Docente(s): ...</td>
```

Contrato para a reconferência antes do POST final:

- o código do componente é o prefixo numérico da primeira célula, antes de ` - `;
- a turma vem como `Turma NN` e normaliza para o token sem zeros à esquerda;
- a linha seguinte, com `colspan=3`, é de docentes e não é uma turma;
- o `caption` informa quantas turmas foram selecionadas; mais de uma é motivo para
  falhar fechado.

Os dados do discente ficam em `table.visualizacao` (matrícula, matriz curricular,
currículo). O parser não precisa deles e não deve extraí-los.

## 2. Página de resultados da busca

**Papel:** lista as turmas com vaga remanescente e oferece o controle de seleção.
Fixture sanitizada: `tests/fixtures/ufcg/results_real.html`.

A tabela é `<table class="listagem" id="lista-turmas-extra">`, com
`<caption>Turmas Encontradas (N)</caption>` e estes cabeçalhos, nesta ordem:

```text
(vazio) | Turma | Docente(s) | Tipo | Horário | Local | Capacidade | Vagas | (vazio)
```

### 2.1 Agrupamento por componente

O código do componente **não** está na linha da turma. Ele vem numa linha de
cabeçalho que antecede o grupo:

```html
<tr class="destaque no-hover disciplina">
  <td colspan="9"><a onclick="PainelComponente.show(60);">1109103 - CÁLCULO DIFERENCIAL E INTEGRAL I</a></td>
</tr>
```

O parser percorre as linhas em ordem, guarda o componente corrente ao encontrar
`tr.disciplina` e o associa às linhas de turma seguintes — a mesma estratégia do
parser da matrícula regular da UFPB.

### 2.2 Linha de turma

```html
<tr class="linhaPar" id="turma_100002TR">
  <td>...zoom...</td> <td>Turma 02</td> <td>DOCENTE</td> <td>REGULAR</td>
  <td class="small">2T23 4T45 (08/09/2026 - 19/02/2027)</td>
  <td class="small">CAA-202</td> <td>80 alunos</td> <td>18 vagas</td>
  <td>...seleção...</td>
</tr>
```

- turma vem como `Turma NN`;
- vagas como `N vagas`, número inteiro extraído por regex; ausência é `None`;
- capacidade como `N alunos`, apenas diagnóstico;
- o `id` da linha (`turma_<id>TR`) repete o `idTurma` do postback.

### 2.3 Controle de seleção — corrige uma hipótese errada

```html
<a id="form:selecionarTurmaj_id_1" href="#" title="Selecionar turma"
   onclick="if(typeof jsfcljs == 'function'){jsfcljs(document.getElementById('form'),
            {'form:selecionarTurmaj_id_1':'form:selecionarTurmaj_id_1','idTurma':'100002'},'');}return false">
  <img src="/sigaa/img/seta.gif" alt="Selecionar turma" />
</a>
```

Pontos que a captura corrige:

1. O segundo argumento de `jsfcljs` é um **objeto** `{'nome':'valor', ...}`, não a
   string `'k:v,k2:v2'` que o parser assumia a partir da UFPB. O formato antigo
   nunca casaria com este render.
2. O primeiro argumento é `document.getElementById('form')`, não
   `document.forms['form']`.
3. O `name` do controle **muda por linha**: `form:selecionarTurma`,
   `form:selecionarTurmaj_id_1`, `form:selecionarTurmaj_id_2`. Nunca é constante.
4. O par que identifica a turma é `idTurma`, e é ele que define qual linha foi
   escolhida. O payload precisa dos dois pares, mais os hidden do formulário.

O ícone `seta.gif` significa "Selecionar turma" e `zoom.png` significa apenas
"Ver detalhes". Só o primeiro é ação de seleção.

## 3. Sessão

O cabeçalho mostra `Tempo de Sessão` com contagem regressiva (`Relogio.init(90)`,
em minutos). Uma preparação parada perde validade junto com a sessão.

## 3. Ainda sem captura

- Tabela de resultados da busca, com a representação de vagas.
- Controle de seleção de cada linha (o ícone citado no texto da busca).
- Página de verificação do vínculo após a confirmação.
- Mensagens reais de sucesso e de recusa acadêmica.
