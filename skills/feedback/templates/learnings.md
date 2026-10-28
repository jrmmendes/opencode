# LEARNINGS — feedback

Log durável e curado de melhorias de **processo** (não de resultado de trabalho).
Uma entrada por linha (no máximo 5 por run; quebre em duas linhas se precisar).
Dedupe por hash normalizado do texto. Só entram entradas aprovadas via `question`.

Formato:

```markdown
- YYYY-MM-DD [local|global] [contexto|instrução|workflow|falha] `<arquivo/alvo>`: mudança
  proposta. Evidência: `ses_x` seq 12, `ses_y` seq 40.
```

Regras:

- ≤2 linhas por entrada; sem transcrição, sem prompt colado.
- Toda entrada cita ao menos uma sessão e um `seq` (ou dois IDs de sessão).
- `[global]` para hábito de harness; `[local]` para padrão de um projeto.
- Não registrar preferência pessoal sem repetição (≥2 ocorrências ou ≥2 sessões).
- Revisar privacidade antes de versionar (home já redigido pelo scanner).
