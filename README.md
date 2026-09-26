# Windows Emulator Online

Um Windows 11 num servidor Linux, acessível pelo navegador na porta 80, com:

- VM Windows executada com QEMU/KVM através do Dockur Windows
- visualizador web/noVNC fornecido pelo próprio Dockur
- botão Enviar ficheiros que coloca os ficheiros na pasta Shared do Windows
- botão Teclado pensado para iPad e outros dispositivos táteis
- configuração simples por .env
- armazenamento persistente em data/windows
- ficheiros enviados persistidos em data/shared

## Requisitos do servidor

O Windows 11 tem como requisitos mínimos oficiais da Microsoft 4 GB de RAM e 64 GB de armazenamento. O Dockur Windows indica também que o host precisa de Docker/Podman, suporte a KVM e pelo menos 2 GB de RAM disponível e 32 GB de disco livre para o seu próprio container. Para uma VM Windows 11 utilizável remotamente, estes números são apenas o ponto de partida.

| Recurso | Mínimo para Windows 11 | Recomendado para este projeto |
|---|---:|---:|
| RAM da VM | 4 GB | 8 GB |
| Disco da VM | 64 GB | 100 GB |
| CPU da VM | 2 cores | 4 cores |
| RAM total do servidor | 8 GB | 16 GB |
| Espaço total do servidor | 100 GB | 150–200 GB SSD |

O disco da VM é expansível, mas aumentar o tamanho do disco virtual não estende automaticamente a partição do Windows. Faça isso dentro do Windows depois, se necessário.

## Arranque

1. Copie o ficheiro de exemplo:
   cp .env.example .env

2. Abra .env e altere pelo menos WINDOWS_PASSWORD.

3. Inicie:
   docker compose up -d --build

4. Abra:
   http://IP_DO_SERVIDOR/

Na primeira instalação, o Dockur descarrega a imagem do Windows e executa a instalação automaticamente. A primeira inicialização é, por isso, significativamente mais demorada do que as seguintes.

## Porta 80

Só o serviço web publica uma porta: 80:80.

O Windows fica na rede interna do Docker em 8006, e o Nginx encaminha o visualizador para a porta 80. O RDP não é publicado pelo projeto por defeito.

## Enviar ficheiros para o Windows

O botão Enviar ficheiros envia o conteúdo para data/shared no host.

O Dockur cria uma pasta/partilha Shared no Windows através de Samba. Depois de o Windows arrancar, os ficheiros enviados aparecem nessa pasta.

O limite do projeto é de 2 GiB por ficheiro por defeito. Pode alterar MAX_FILE_SIZE no .env.

## Teclado no iPad

O botão Teclado chama o controlo de teclado tátil do noVNC quando ele está disponível. O noVNC expõe explicitamente esse botão para dispositivos táteis.

No iPad, toca em Teclado antes de escrever. Isto evita depender de um teclado físico e usa o mecanismo de entrada do visualizador.

## Windows 11 e Windows 10

O projeto vem configurado para Windows 11.

Não fiz um downgrade automático para Windows 10. O suporte do Windows 10 terminou em 14 de outubro de 2025, portanto, em 2026, é preferível manter o Windows 11 e resolver eventuais incompatibilidades do host/KVM.

Ainda assim, a imagem pode ser alterada manualmente para Windows 10 colocando WINDOWS_VERSION=10 no .env.

Se a instalação já tiver criado data/windows, mudar WINDOWS_VERSION não converte a instalação existente. Para instalar outra versão, use uma pasta de armazenamento nova/vazia.

## KVM

O projeto depende de /dev/kvm para aceleração de hardware. No host Linux, confirme:

ls -l /dev/kvm

e certifique-se de que a virtualização está ativa na BIOS/UEFI.

Se o seu fornecedor de hosting não disponibilizar KVM/nested virtualization, uma VM Windows baseada em QEMU pode ficar extremamente lenta ou nem iniciar corretamente. Nesse caso, o problema é a capacidade do host, não a interface web.

## Licenciamento

Este repositório não contorna ativação do Windows. Use uma licença/chave válida conforme os termos da Microsoft. O container Dockur também permite configurar uma chave através da variável KEY caso queira fazer isso durante a instalação.

## Segurança

Este projeto expõe um desktop Windows diretamente na Internet através da porta 80. Para uso público, coloque-o atrás de HTTPS e de uma camada de autenticação/rede confiável antes de o disponibilizar a terceiros.

Além disso, a opção de upload deve ser tratada como entrada não confiável: não execute automaticamente ficheiros enviados e mantenha o acesso ao servidor restrito.

## Estrutura

.
├── compose.yml
├── .env.example
├── nginx/
│   ├── nginx.conf
│   ├── portal.css
│   └── portal.js
└── upload-server/
    ├── Dockerfile
    ├── package.json
    └── server.js

## Referências

- Microsoft — requisitos do Windows 11: https://www.microsoft.com/pt-pt/windows/windows-11-specifications
- Microsoft — Windows: https://www.microsoft.com/pt-pt/windows
- Dockur Windows — projeto e requisitos: https://github.com/dockur/windows
- Dockur Windows — variáveis de ambiente: https://github.com/dockur/windows/blob/master/docs/environment.md
- noVNC — interface de teclado em dispositivos táteis: https://github.com/novnc/noVNC/blob/master/vnc.html


## Launcher Python

O projeto tem um ponto de entrada em Python que funciona sem bibliotecas externas:

    python3 launcher.py

O launcher verifica Python, KVM, RAM, espaço livre, Docker e Docker Compose; cria o .env na primeira execução; e depois inicia a stack.

Verificação sem iniciar:

    python3 launcher.py --check-only

Iniciar com os valores definidos no .env:

    python3 launcher.py

Forçar uma configuração:

    python3 launcher.py --ram 8G --disk 100G --cpu 4

Ver estado:

    python3 launcher.py --status

Ver logs:

    python3 launcher.py --logs

Parar:

    python3 launcher.py --down

Windows 10 pode ser escolhido explicitamente, sem alterar o padrão do projeto:

    python3 launcher.py --windows-version 10

O launcher não instala Docker nem altera a BIOS/UEFI automaticamente. Quando o host não oferece KVM/nested virtualization, ele pára com uma mensagem clara.
