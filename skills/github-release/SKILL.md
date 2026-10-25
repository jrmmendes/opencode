---
name: github-release
description: >
  Publica uma release nova no GitHub com a `gh` CLI: detecta a última tag,
  levanta os commits não lançados, decide o bump semver (major/minor/patch),
  atualiza os arquivos de versão do projeto, roda as verificações, cria commit
  `chore(release)`, tag anotada, push e `gh release create` com notas no formato
  do repositório. Use quando pedirem "nova release", "publicar versão", "gerar
  tag e release", "bump de versão", "release no GitHub" ou "lançar a vX.Y.Z".
  Não use para deploy, publicação em registry (npm/PyPI) nem para changelog de
  PR isolado.
---

# github-release — Publicar uma release no GitHub

Fluxo completo de release em repositório já versionado: versão → commit → tag →
push → release publicada. A release é o **último** passo, nunca o primeiro.

## Quando usar

- "gere uma release nova", "publique a versão", "cria a tag e a release".
- "bump para vX.Y.Z" com intenção de publicar no GitHub.
- Republicar notas de uma release já tagueada (`gh release edit`).

Não use para deploy, publicação em registry de pacotes nem para escrever
changelog de uma única mudança.

## Pré-requisitos

- `gh` autenticado: `gh auth status` (escopo `repo` basta em repositório público;
  `repo` + permissões de tag para push via SSH/HTTPS funcionando).
- Remoto configurado (`git remote -v`) e branch padrão identificada.
- Working tree limpo. Se houver alteração não commitada, **pare** e pergunte se
  ela entra na release ou fica de fora — nunca misture trabalho alheio no commit
  `chore(release)`.

## 1. Contexto

Rode o helper (somente leitura) na raiz do repositório:

```bash
bash ~/.config/opencode/skills/github-release/scripts/release-context.sh
```

Ele imprime: repositório e branch, status limpo/sujo, última tag, commits desde
a última tag, releases existentes e onde a versão atual está declarada.

O que importa reter:

- **Última tag** → base do bump.
- **Commits não lançados** → matéria-prima do bump e das notas. Se a lista vier
  vazia, não existe release a fazer: pare e avise.
- **Convenção de tag** (`v1.2.3` vs `1.2.3`) e de título (`v1.2.3` vs
  `projeto v1.2.3`) → copie a do repositório, não invente.

## 2. Decidir a versão

Semver a partir dos commits não lançados:

| Sinal nos commits | Bump |
| --- | --- |
| `feat:` / nova capacidade | minor |
| só `fix:`, `perf:`, `docs:`, `chore:`, `refactor:`, `style:`, `test:` | patch |
| `!` no tipo, `BREAKING CHANGE:` no corpo, remoção de API/comando/flag | major |

Regras:

- Respeite o **0.x**: em `0.y.z` o minor pode carregar breaking change; avalie o
  repositório, não aplique a tabela cegamente.
- A versão nova precisa ser **maior** que a última tag e **inexistente**:
  `git rev-parse -q --verify refs/tags/<tag>` deve falhar.
- **Pergunte** com a tool `question` quando o bump não for óbvio: mudança
  breaking, mistura de `feat` + breaking, release com número escolhido a dedo,
  ou usuário pediu "release nova" sem dizer a versão. Opções: patch, minor,
  major (a recomendada primeiro, com o motivo no label).
- Se o usuário já disse a versão, use exatamente ela — não "arredonde".

## 3. Bump dos arquivos de versão

Atualize **todas** as declarações de versão detectadas no passo 1, não só
`package.json`. Fontes comuns:

- `package.json` → `"version"`.
- `src/**/version.ts`, `version.py`, `__init__.py`, `__version__`.
- `Cargo.toml` (`[package] version`), `pyproject.toml`, `setup.cfg`.
- Arquivo `VERSION`, `meson.build`, `CMakeLists.txt`, `*.goreleaser.yml`.
- Constantes embutidas (`VERSION = "1.1.0"`) usadas por `--version` ou por
  `/health`.

Confira depois que nada ficou para trás:

```bash
grep -rn "1\.1\.0" --exclude-dir={node_modules,.git,dist,build} . | head -30
```

(troque `1.1.0` pela versão antiga; ignore lockfiles, fixtures e changelogs
históricos). Versões de contrato que **não** são a versão do produto — schema,
prefs, `LOADER_INTENT_VERSION` — não devem ser tocadas.

## 4. Verificar antes de taguear

Rode o que o projeto oferece, na ordem declarada nos scripts do manifesto:

```bash
# exemplos; use os scripts reais do repositório
bun run typecheck && bun test && bun run build
npm run lint && npm test
cargo test
```

- **Nunca** pule a verificação "porque mudou só a versão".
- Se algo falhar, **pare**: release quebrada exige tag deletada e release
  apagada, o que é bem pior do que atrasar o publish.
- Rode o binário/entrypoint para confirmar a versão: `./bin/<tool> --version`
  deve imprimir a versão nova.

## 5. Commit e tag

Espelhe o padrão dos commits de release anteriores (`git log --grep="release"`).
Convenção usual:

```bash
git add package.json src/core/version.ts   # só os arquivos de versão
git commit -m "chore(release): v1.1.1"
git tag -a v1.1.1 -m "projeto v1.1.1"      # tag ANOTADA
```

- Tag anotada (`-a -m`), nunca leve.
- Não empacote outras mudanças no commit de release; o bump é um commit
  isolado.
- Se o projeto assina tags (`git tag -v`), assine também.

## 6. Push

```bash
git push origin main          # branch padrão identificada no passo 1
git push origin v1.1.1
```

Nunca `--force`, nunca force-push de tag, nunca reescreva tag já publicada.

## 7. Release no GitHub

Escreva as notas em arquivo temporário e passe por `--notes-file` (evita
escapes de shell em Markdown):

```bash
gh release create v1.1.1 \
  --title "projeto v1.1.1" \
  --notes-file /tmp/opencode/release-v1.1.1.md
```

Espelhe a estrutura das releases anteriores, se houver:

```bash
gh release view v1.1.0 | sed -n '1,60p'
```

Formato padrão quando não há precedente:

```markdown
<Rótulo do tipo: Patch|Feature|Major> release of <projeto>: <resumo em uma linha>.

## Highlights

- <mudança orientada a quem usa, com o efeito observável>

## Install

```sh
<comandos reais de instalação do repositório>
```

## Requirements

- <runtime e versão>

## Verification

```sh
<comandos do passo 4, com a contagem de testes>
```
```

Diretrizes das notas:

- Agrupe por **impacto no usuário**, não por commit. Vários commits podem virar
  um bullet só; commits de `chore:`/`test:` normalmente não aparecem.
- Nada de "diversas melhorias" — diga o que mudou e o que deixa de doer.
- Só marque `--prerelease` se o usuário pedir ou a versão for `-rc`/`-beta`.
- Use `--draft` quando o usuário quiser revisar antes de publicar.

## 8. Confirmar

```bash
gh release list                                  # mostra qual é a "Latest"
gh release view v1.1.1 --json tagName,isDraft,isPrerelease,url
git status -sb   # tree limpo e branch sincronizada
```

`gh release view --json` **não** expõe `isLatest`: confira o rótulo *Latest* em
`gh release list` (ou `gh api repos/{owner}/{repo}/releases/latest`).

Reporte a URL da release e o que ficou fora dela (se algo ficou). Se houver uma
próxima release provável, diga qual é a base dela.

## Guardrails

- **Ordem é contrato**: verificar → commit → tag → push → `gh release create`.
  Release publicada antes do push da tag gera link quebrado.
- Nunca reuse tag existente nem apague release/tag publicada para "corrigir";
  publique `patch` seguinte (exceção: usuário pediu explicitamente e a release
  tem minutos de vida).
- Nunca invente data, contagem de testes ou URL: rode o comando.
- Nunca faça `git push --force`, `git tag -f` em tag já enviada ou `gh release
  delete` sem pedido explícito.
- Não faça bump em arquivos de lockfile à mão; se o lockfile carrega a versão,
  use o gerenciador (`bun install`, `npm install --package-lock-only`,
  `cargo update -p <pkg>`).
- Release com repositório sujo, verificação falhando ou tag já existente é
  **motivo de parada**, não de improviso.

## Exemplo real (sessão de origem desta skill)

Repositório `md-preview` (Bun + TypeScript), última tag `v1.1.0`, um único
commit não lançado: `7306253 fix: improve sidebar animation` → patch `v1.1.1`.
Bump em `package.json` e `src/core/version.ts`; `bun run typecheck && bun test
(184) && bun run build`; commit `chore(release): v1.1.1`; tag anotada
`v1.1.1 -m "md-preview v1.1.1"`; push de `main` + tag; `gh release create`
com notas em `Highlights / Install / Requirements / Verification`, publicada
como *Latest*. Tempo total: ~4 min, sem retrabalho.
