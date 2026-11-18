# Relatório de Correção — Prova Prática de Programação Web (UFAM/ICET)

**Disciplina:** Programação Web — Engenharia de Software
**Professor:** Antônio Alberto
**Data da avaliação:** 16/11/2026
**Valor total:** 10,0 pontos

## 1. Especificação da prova (resumo)

Módulo seguro de **Cadastro e Login de Usuários** (Full-Stack):

1. **Banco de Dados (PostgreSQL):** script `schema.sql` com DDL; tabela `usuarios` com `id` (PK, auto-incremento/SERIAL), `nome` (NOT NULL), `email` (NOT NULL, UNIQUE) e `senha` (NOT NULL).
2. **Front-End (HTML/CSS/JS):** interface com navegação/alternância entre Login e Cadastro; JS intercepta `submit`, valida senha (≥ 6 caracteres), confirmação de senha idêntica, impede envio em caso de erro e exibe feedback no DOM; requisições via Fetch API.
3. **Back-End (Node.js):** `package.json` com `express`, `pg`, `cors`; servidor Express; conexão PostgreSQL via `pg`; rotas `POST /api/cadastrar` e `POST /api/login` integradas ao Front via `fetch()`.

**Matriz de avaliação:** HTML 2,0 | CSS 2,0 | JS (client) 2,0 | BD 2,5 | Back-End 1,5.

## 2. Metodologia

- Extração e inspeção de todos os arquivos (exceto `node_modules`) de cada submissão.
- Verificação automatizada de padrões (tags semânticas, atributos de input, `fetch`, endpoints, DDL, dependências).
- Leitura manual dos arquivos-chave (HTML, CSS, JS, SQL, server/routes) para pontuação e detecção de uso de IA.
- **Detecção de IA:** análise de sinais como código excessivamente completo/polido, funcionalidades não solicitadas (upload de avatar, CRUD completo, JWT/bcrypt, Bootstrap/FontAwesome), estrutura idêntica entre alunos (template compartilhado), comentários genéricos, formatação uniforme, ausência de erros típicos de iniciante, e incompatibilidade com o nível da turma.

**Resultado global:** Nenhum aluno implementou integralmente os endpoints `POST /api/cadastrar` e `POST /api/login` com `schema.sql` e integração `fetch` conforme a prova. O aluno mais próximo no Front-End foi **Thiago Silva dos Santos** (toggle Login/Cadastro + fetch aos endpoints corretos, porém sem Back-End/BD). Os mais completos em BD foram **Aila Karoline** e **Sérgio Fernandes** (schema.sql correto), mas com Back-End em arquitetura CRUD divergente.

## 3. Tabela de pontuação (0 a 10)

| Aluno | HTML (2,0) | CSS (2,0) | JS (2,0) | BD (2,5) | Back-End (1,5) | Total | Status | Uso de IA |
|---|---|---|---|---|---|---|---|---|
| Aila Karoline | 1,0 | 1,5 | 1,0 | 2,0 | 0,5 | **6,0** | Parcial | Alta |
| ana_soares | 1,5 | 1,5 | 1,0 | 0,0 | 0,5 | **4,5** | Parcial | Alta |
| dieglison_correia_varejao_22400267 | 1,5 | 1,5 | 1,0 | 0,0 | 0,5 | **4,5** | Parcial | Alta |
| Emelly_Cristina_22402234 | 1,5 | 1,5 | 0,5 | 0,0 | 0,5 | **4,0** | Parcial | Alta |
| Felipe_Aliel_22354536 | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | **0,0** | Não entregue (zip vazio) | N/A |
| Gustavo_de_Oliveira_Pena_22400271 | 0,5 | 1,0 | 0,0 | 0,0 | 0,0 | **1,5** | Não concluído | Baixa |
| heloise.brito | 1,5 | 1,0 | 0,0 | 0,0 | 0,0 | **2,5** | Não concluído | Baixa |
| Icaro_Abreu_22334022 | 0,5 | 1,0 | 1,0 | 0,0 | 0,5 | **3,0** | Parcial | Alta |
| Joel-Carlos-22400269 | 1,5 | 1,0 | 0,0 | 0,0 | 0,5 | **3,0** | Parcial | Média |
| Karen_Rodrigues_22402225 | 0,5 | 1,0 | 0,0 | 2,5 | 0,5 | **4,5** | Parcial | Média |
| Karen_Rodrigues_22402225 (2) | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 | **0,0** | Inválido (coleção de zips) | N/A |
| kaylane_soares_22450510 | 0,5 | 0,5 | 0,0 | 0,0 | 0,0 | **1,0** | Não concluído | Baixa |
| Lucas_Castro_22402227 | 0,5 | 1,0 | 0,0 | 1,0 | 0,0 | **2,5** | Não concluído | Baixa |
| Marcos_Correa_Alves | 0,5 | 1,0 | 0,0 | 0,0 | 0,0 | **1,5** | Não concluído | Baixa |
| Marcos_Gabriel_22450923 | 0,5 | 0,5 | 0,0 | 0,0 | 0,0 | **1,0** | Não concluído | Baixa |
| Prova - Alejjandro Dutra - 22400664 | 1,0 | 1,0 | 0,5 | 0,0 | 0,5 | **3,0** | Parcial | Alta |
| Sabrina_Martins | 1,0 | 1,0 | 0,5 | 0,0 | 0,5 | **3,0** | Parcial | Média |
| Sergio_Fernandes_22450190 | 1,5 | 1,5 | 1,0 | 2,0 | 0,5 | **6,5** | Parcial | Alta |
| Thiago Silva dos Santos | 1,5 | 1,0 | 1,5 | 0,0 | 0,0 | **4,0** | Parcial | Alta |

## 4. Detalhamento por aluno

### Aila Karoline — 6,0 (Parcial) — IA: Alta
- **Acertos:** `schema.sql` correto (id SERIAL PK, nome/email/senha NOT NULL, email UNIQUE); Front com Bootstrap/FontAwesome; JS com fetch CRUD.
- **Falhas:** sem `POST /api/cadastrar` e `/api/login` (usa `/api/usuarios` CRUD); sem validação de senha ≥ 6 e confirmação; sem `package.json`; login sem campo de senha.
- **Evidência de IA:** template "microservices/usuarios", upload de avatar (multer), CRUD completo, Bootstrap/FontAwesome, comentários padronizados — funcionalidades além do escopo e idênticas a outros alunos.

### ana_soares — 4,5 (Parcial) — IA: Alta
- **Acertos:** HTML semântico (header/main/form), inputs com atributos, CSS, JS com fetch, `package.json`.
- **Falhas:** sem `schema.sql`; rotas `/api/usuarios` em vez de `/api/cadastrar` e `/api/login`; sem validação de comprimento de senha.
- **Evidência de IA:** mesmo template compartilhado (microservices, utils/date, avatar).

### dieglison_correia_varejao_22400267 — 4,5 (Parcial) — IA: Alta
- Mesmo perfil de ana_soares (template compartilhado), sem `schema.sql` e sem `package.json`.

### Emelly_Cristina_22402234 — 4,0 (Parcial) — IA: Alta
- **Acertos:** validação de comprimento de senha no JS; `package.json`.
- **Falhas:** sem `schema.sql`; sem fetch (front não integra à API); rotas `/api/usuarios`; estrutura aninhada (pasta duplicada) indicando cópia.
- **Evidência de IA:** template compartilhado, pasta "Módulo-ICET-UFAM".

### Felipe_Aliel_22354536 — 0,0 — Não entregue
- Zip vazio (192 bytes). Submissão inválida.

### Gustavo_de_Oliveira_Pena_22400271 — 1,5 (Não concluído) — IA: Baixa
- Apenas Front-End (duas páginas), sem JS funcional (script.js vazio), sem Back-End/BD. HTML sem tags semânticas. Trabalho simples, provável autoria manual.

### heloise.brito — 2,5 (Não concluído) — IA: Baixa
- Front-End com 3 páginas e CSS, semantic tags, inputs corretos, porém sem JS, Back-End e BD. Zip aninhado. Trabalho simples.

### Icaro_Abreu_22334022 — 3,0 (Parcial) — IA: Alta
- **Acertos:** `package.json`, server Express + pg, fetch CRUD.
- **Falhas:** sem `schema.sql`; sem validação de senha/confirmação; rotas `/api/usuarios`; inputs com id inválido ("nome de usuario"); sem tags semânticas.
- **Evidência de IA:** template compartilhado (microservices, avatar).

### Joel-Carlos-22400269 — 3,0 (Parcial) — IA: Média
- **Acertos:** HTML semântico, inputs corretos, server + pg.
- **Falhas:** `routes.js` quebrado (AVATAR_DIR indefinido, sem resposta após INSERT, rota PUT duplicada); sem `schema.sql`; sem fetch no cliente; sem validação real.
- **Evidência de IA:** estrutura idêntica ao template compartilhado, mas com erros de cópia (sugere colagem parcial).

### Karen_Rodrigues_22402225 — 4,5 (Parcial) — IA: Média
- **Acertos:** `create-table-usuarios.sql` correto; server + pg; `package.json`.
- **Falhas:** sem validação/fetch no cliente (botões são links `<a>`); rotas `/api/usuarios` (GET/POST); sem confirmação de senha.
- **Evidência de IA:** template compartilhado (microservices), mas Front mais simples (possível mistura).

### Karen_Rodrigues_22402225 (2) — 0,0 — Inválido
- A submissão contém todos os zips dos colegas (coleção), não um projeto. Desconsiderar/invalidar.

### kaylane_soares_22450510 — 1,0 (Não concluído) — IA: Baixa
- Apenas HTML/CSS de uma "ficha de cadastro" com tabela, sem senha/login/JS/Back-End/BD. Trabalho simples.

### Lucas_Castro_22402227 — 2,5 (Não concluído) — IA: Baixa
- **Acertos:** `scherma.sql` com tabela (id SERIAL, nome, email, senha NOT NULL).
- **Falhas:** `UNIQUE` aplicado à senha (errado — deveria ser email); sem `name` nos inputs; sem JS fetch; sem Back-End; HTML sem semântica.
- **Evidência de IA:** baixa; erros típicos de iniciante.

### Marcos_Correa_Alves — 1,5 (Não concluído) — IA: Baixa
- Apenas cadastro HTML/CSS, sem confirmação de senha, sem login, sem JS/Back-End/BD. Trabalho simples.

### Marcos_Gabriel_22450923 — 1,0 (Não concluído) — IA: Baixa
- Front-End básico (cadastro/login) com JS em memória (arrays), senha como `type="text"`, sem fetch/Back-End/BD. Trabalho simples.

### Prova - Alejjandro Dutra - 22400664 — 3,0 (Parcial) — IA: Alta
- **Acertos:** validação de senha (regex ≥ 6 + maiúscula + número + especial) e confirmação no servidor; Front com Bootstrap; server + pg.
- **Falhas:** `cadastro.js`/`login.js` são código de servidor colado no Front (quebrado no navegador); rotas `/api/usuarios` em vez de `/api/cadastrar` e `/api/login`; sem `schema.sql` e `package.json`; `router.get` referencia variável inexistente (`rows`).
- **Evidência de IA:** template compartilhado (avatar/multer, CRUD, Bootstrap/FontAwesome).

### Sabrina_Martins — 3,0 (Parcial) — IA: Média
- **Acertos:** `package.json`, server + pg, validação de confirmação de senha no cliente.
- **Falhas:** credenciais hardcoded no Front (sem fetch/BD); rotas `/api/usuarios` vazias; sem `schema.sql`.
- **Evidência de IA:** template compartilhado, mas Front mais simples (possível mistura).

### Sergio_Fernandes_22450190 — 6,5 (Parcial) — IA: Alta
- **Acertos:** `schema.sql` correto; `package.json`; server + pg; HTML semântico; JS com fetch CRUD e validação de senha/confirmação.
- **Falhas:** rotas `/api/usuarios` em vez de `/api/cadastrar` e `/api/login`; sem login funcional; zip protegido por senha (123456) — suspeito.
- **Evidência de IA:** template compartilhado (avatar/multer, CRUD, Bootstrap/FontAwesome), código muito polido.

### Thiago Silva dos Santos — 4,0 (Parcial) — IA: Alta
- **Acertos:** Front-End mais próximo da prova: alternância Login/Cadastro, `fetch` para `/api/cadastro` e `/api/login`, validação `minlength="6"`, feedback no DOM, sessão/JWT.
- **Falhas:** sem `server.js` (Back-End ausente) e sem `schema.sql`; sem campo de confirmação de senha; inputs sem `name`.
- **Evidência de IA:** código muito polido (JWT, cookies, bcryptjs, dotenv), além do escopo da prova.

## 5. Correções necessárias (para atingir 10,0)

1. **schema.sql:** criar com `id SERIAL PRIMARY KEY`, `nome VARCHAR(...) NOT NULL`, `email VARCHAR(...) NOT NULL UNIQUE`, `senha VARCHAR(...) NOT NULL`.
2. **HTML:** usar `<header>`, `<main>`, `<section>`, `<form>`; inputs com `type`, `id`, `name`, `required`, `placeholder`; duas telas (Login/Cadastro) com alternância.
3. **CSS:** Flexbox/Grid centralizado e responsivo; botões com `:hover`, `:focus`, `:active`; classes `.alert-error`/`.alert-success`.
4. **JS cliente:** interceptar `submit` (`preventDefault`); validar `senha.length >= 6`; validar confirmação idêntica; exibir feedback; `fetch` para `/api/cadastrar` e `/api/login`.
5. **package.json:** dependências `express`, `pg`, `cors`.
6. **server.js:** Express + `pg.Pool`; rotas `POST /api/cadastrar` (verifica email duplicado, insere) e `POST /api/login` (verifica credenciais); servir estáticos.

## 6. Estatísticas

- Total de submissões: 19 (excluindo a coleção inválida).
- Média aproximada: 3,1 pontos.
- Maiores notas: Sérgio Fernandes (6,5), Aila Karoline (6,0).
- Não concluídos (nota ≤ 2,5): 8 alunos.
- Submissões inválidas/vazias: Felipe Aliel, Karen (2).
- Alta probabilidade de uso de IA: 11 alunos.
- Média probabilidade: 3 alunos.
- Baixa probabilidade: 5 alunos.

## 7. Observações finais

- A maioria das submissões de maior volume (microservices, avatar, CRUD, Bootstrap/FontAwesome) não corresponde ao escopo da prova e apresenta forte indício de geração por IA ou cópia de template compartilhado.
- Recomenda-se entrevista individual/oral para as submissões com alta probabilidade de IA e para as notas elevadas com divergência de escopo (Aila, Sérgio, Thiago).
- O gabarito de referência está em `prova_pratica/` (index.html, style.css, script.js, server.js, package.json).
