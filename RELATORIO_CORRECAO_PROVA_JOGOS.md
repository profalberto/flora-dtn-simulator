# Relatório de Correção — Prova Prática de Programação Web (UFAM/ICET)

**Avaliação:** Cadastro de Jogos (PlayStation, Xbox e PC)
**Data:** Sexta-feira, 13/11/2026 — Laboratório 312
**Valor total:** 10,0 pontos

## 1. Especificação da prova (resumo)

Sistema web de **Cadastro e Catálogo de Jogos Eletrônicos** (PlayStation, Xbox, PC).

1. **Banco de Dados (PostgreSQL):** `schema.sql` com DDL; tabela `jogos` com `id` (PK, auto-incremento/SERIAL), `titulo` (NOT NULL), `plataforma` (NOT NULL — PlayStation/Xbox/PC), `genero` (NOT NULL), `ano_lancamento` (INTEGER) e `preco` (NUMERIC).
2. **Front-End (HTML/CSS/JS):** formulário de cadastro + tabela/lista de catálogo; JS valida plataforma válida, ano válido (1970–2026) e preço não negativo; manipulação do DOM para listar jogos; Fetch API.
3. **Back-End (Node.js):** `package.json` com `express`, `pg`, `cors`; servidor Express + `pg`; rotas `POST /api/jogos` (cadastrar) e `GET /api/jogos` (listar), integradas via `fetch()`.

**Matriz:** HTML 1,5 | CSS 2,0 | JS (client) 2,0 | BD 2,0 | Back-End 2,5.

## 2. Tabela de pontuação (0 a 10)

| Aluno | HTML (1,5) | CSS (2,0) | JS (2,0) | BD (2,0) | Back-End (2,5) | Total |
|---|---|---|---|---|---|---|
| Cadastrodejogo (modelo aula) | — | — | — | — | — | — |
| Chyntia_Prestes_22325026 | 1.5 | 2.0 | 0.0 | 1.0 | 0.0 | 4.5 |
| Clara_Vieira_22351494 | 1.5 | 2.0 | 1.0 | 1.5 | 1.0 | 7.0 |
| Felipe_Aliel-22354536 | 1.0 | 2.0 | 1.0 | 1.0 | 1.0 | 6.0 |
| Felipe_Rangel | 1.0 | 2.0 | 0.0 | 0.5 | 0.5 | 4.0 |
| Gustavo_souza22400228 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Joao_Simoes | 1.5 | 2.0 | 0.0 | 1.0 | 0.0 | 4.5 |
| Kaio Sobral Moreira | 1.5 | 2.0 | 0.0 | 1.5 | 0.5 | 5.5 |
| Luanna_Benezar | 1.0 | 2.0 | 0.5 | 1.5 | 0.5 | 5.5 |
| MarcosDeOliveiradaSilva-SI | 1.5 | 2.0 | 1.0 | 2.0 | 2.0 | 8.5 |
| Marcos_Gabriel_22353965 | 0.5 | 2.0 | 0.5 | 0.5 | 0.5 | 4.0 |
| Nádia_leao_ | 0.5 | 2.0 | 0.0 | 0.0 | 1.0 | 3.5 |
| Pedro-Jhevison-22352323 | 1.5 | 2.0 | 2.0 | 1.5 | 2.5 | 9.5 |
| SilviaLeticia_22153888 | 1.0 | 2.0 | 1.5 | 2.0 | 0.5 | 7.0 |
| ennoile_ferreira_22400268 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| helioNogueira-2235462 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| jean_carlos | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| joaoReboucas_22351500 | 1.5 | 2.0 | 0.5 | 2.0 | 2.0 | 8.0 |
| johnny_xavier_22450270 | 1.5 | 2.0 | 0.5 | 1.0 | 2.0 | 7.0 |
| matheus_damasceno | 1.0 | 2.0 | 0.0 | 0.0 | 0.0 | 3.0 |
| nodes Lais Samily | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| ricky_brendon | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Guilherme_Nunes_22352022 | 1.0 | 2.0 | 0.5 | 1.5 | 2.0 | 7.0 |

## 3. Correções necessárias (gabarito)

1. **schema.sql:** `CREATE TABLE jogos (id SERIAL PRIMARY KEY, titulo VARCHAR(...) NOT NULL, plataforma VARCHAR(...) NOT NULL, genero VARCHAR(...) NOT NULL, ano_lancamento INTEGER, preco NUMERIC);`
2. **HTML:** tags semânticas; `<select>` de plataforma com PlayStation, Xbox, PC; campos Título, Gênero, Ano, Preço; inputs com `type`, `id`, `name`, `required`, `placeholder`; `<table>` de catálogo.
3. **CSS:** Flexbox/Grid responsivo; identidade temática; botões `:hover`/`:focus`; tabela estilizada.
4. **JS cliente:** validar plataforma (PlayStation/Xbox/PC), ano (1970–2026), preço ≥ 0; manipular DOM para listar jogos; `fetch` POST/GET `/api/jogos`.
5. **package.json:** dependências `express`, `pg`, `cors`.
6. **server.js:** Express + `pg.Pool`; rotas `POST /api/jogos` e `GET /api/jogos`; servir estáticos.

## 4. Observações

- Submissões com nota 0,0: uso visível de IA (código mocados/gerado) ou não uso do PostgreSQL.
- Submissão 'Cadastrodejogo (modelo aula)' é o modelo de aula, não avaliada.

