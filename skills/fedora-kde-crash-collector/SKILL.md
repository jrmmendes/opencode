---
name: fedora-kde-crash-collector
description: Coleta logs do sistema, relatórios de crash (coredumps e Drkonqi) e diagnóstico de ambiente Fedora Linux com KDE Plasma 6 (Wayland) para análise de falhas via OpenCode.
compatibility: opencode
---

## Visão Geral
Esta skill orienta o agente OpenCode na automação da coleta de logs de diagnóstico e relatórios de falhas (crashes) em ambientes Fedora Linux executando KDE Plasma 6 sobre Wayland.

## Binários Utilizados no Fluxo
Esta skill pressupõe que as ferramentas e utilitários necessários já se encontram instalados no ambiente de execução:

* **`coredumpctl`** (Parte do `systemd-coredump`): Utilizado para gerenciar, listar e extrair rastreamentos de pilha (*stack traces*) de coredumps.
* **`abrt-cli`** (Automatic Bug Reporting Tool): Ferramenta padrão do Fedora para capturar falhas de aplicativos e do sistema.
* **`gdb`**: Depurador GNU utilizado para gerar rastreamentos de pilha simbólicos a partir dos coredumps.
* **`wayland-utils`**: Utilizado para inspecionar o estado do servidor Wayland e protocolos ativos.
* **`journalctl`** (Nativo do systemd): Utilizado para filtrar logs do kernel, do gerenciador de login SDDM e da sessão KWin.

---

## Fluxo de Execução da Skill

<Steps>
  <Step title="Verificar Integridade e Ambiente" subtitle="1 min">
    Identificar a versão exata do Fedora, do kernel, da sessão Wayland e do KDE Plasma 6.
    
    *Comando:*
    ```bash
    cat /etc/fedora-release
    uname -r
    echo "Sessão: $XDG_SESSION_TYPE \vert{} Desktop:$XDG_CURRENT_DESKTOP"
    plasmashell --version
    ```
    *Verificação:* Confirme se `XDG_SESSION_TYPE` é `wayland` e se o Plasma exibido é a versão 6.
  </Step>

  <Step title="Coletar Logs do Journalctl (KWin, Plasma e SDDM)" subtitle="2 min">
    Extrair logs recentes relacionados a falhas do compositor KWin, do gerenciador de janelas e do gerenciador de exibição.
    
    *Comando:*
    ```bash
    journalctl -b 0 -u sddm --no-pager -n 100 > /tmp/sddm_log.txt
    journalctl -b 0 /usr/bin/kwin_wayland --no-pager -n 200 > /tmp/kwin_wayland_log.txt
    journalctl -b 0 -e --no-pager -p err > /tmp/system_errors.txt
    ```
    *Verificação:* Verifique se os arquivos gerados em `/tmp/` contêm registros e não estão vazios.
  </Step>

  <Step title="Inspecionar Coredumps Recentes" subtitle="3 min">
    Listar falhas de aplicativos e do sistema capturadas pelo systemd-coredump.
    
    *Comando:*
    ```bash
    coredumpctl list --since="1 day ago" > /tmp/coredumps_list.txt
    coredumpctl info -1 > /tmp/latest_coredump_info.txt
    ```
    *Verificação:* Confira se o arquivo `/tmp/coredumps_list.txt` lista PIDs e executáveis que falharam recentemente.
  </Step>

  <Step title="Extrair Stack Trace com GDB (Se aplicável)" subtitle="3 min">
    Gerar o rastreamento de pilha do último coredump registrado para análise do crash.
    
    *Comando:*
    ```bash
    coredumpctl debug --batch -q -e > /tmp/latest_stacktrace.txt || echo "Nenhum coredump interativo disponível"
    ```
    *Verificação:* Verifique se o arquivo `/tmp/latest_stacktrace.txt` contém chamadas de funções e endereços de memória da falha.
  </Step>

  <Step title="Verificar Relatórios do ABRT" subtitle="2 min">
    Consultar problemas detectados e salvos pelo subsistema ABRT do Fedora.
    
    *Comando:*
    ```bash
    abrt-cli list > /tmp/abrt_list.txt
    ```
    *Verificação:* Certifique-se de que o resumo dos relatórios do ABRT foi gravado corretamente.
  </Step>

  <Step title="Consolidar Pacote de Diagnóstico" subtitle="1 min">
    Compactar todos os relatórios coletados em um único arquivo para inspeção ou anexo.
    
    *Comando:*
    ```bash
    tar -czf /tmp/fedora_kde_crash_report.tar.gz /tmp/*_log.txt /tmp/coredumps_list.txt /tmp/latest_coredump_info.txt /tmp/latest_stacktrace.txt /tmp/abrt_list.txt /tmp/system_errors.txt 2>/dev/null
    echo "Relatório gerado em: /tmp/fedora_kde_crash_report.tar.gz"
    ```
    *Verificação:* Confirme que o arquivo tar.gz existe e possui tamanho superior a zero bytes.
  </Step>
</Steps>
