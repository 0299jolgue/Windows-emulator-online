# Windows Emulator Online

Uma VM Windows num servidor Linux, sem Docker e sem Nginx.

A arquitetura agora é direta:

```
subdomínio da hospedagem
        │
        ▼
      noVNC
        │
        ▼
    QEMU/KVM
        │
        ▼
      Windows
```

O `main.py` prepara o armazenamento e inicia QEMU/KVM e noVNC diretamente no host. Quando QEMU não existe no sistema, o projeto tenta usar uma cópia pré-compilada instalada pelo próprio Python, sem root.

## O que precisas na hospedagem

O servidor precisa de permitir Linux e um processo persistente. KVM é opcional porque o projeto tem fallback para TCG. QEMU pode vir do sistema ou de uma cópia pré-compilada instalada via `pip` sem root; noVNC também pode ser obtido localmente. O hosting ainda precisa permitir processos persistentes e tráfego web na porta publicada.

## Configuração

1. Coloca a ISO oficial do Windows na localização definida por `WINDOWS_ISO`. Por defeito:

```text
data/Windows11.iso
```

2. Executa:

```bash
python3 main.py --check-only
```

3. Se as verificações passarem:

```bash
python3 main.py
```

Na primeira execução, o programa cria:

```text
data/windows/windows.qcow2
data/run/
data/logs/
```

A primeira execução arranca pela ISO para instalar o Windows. Depois de a instalação terminar, os arranques seguintes usam o disco virtual.

## Subdomínio da hospedagem

O noVNC fica por defeito na porta `80`, porque esta hospedagem só permite publicar a porta 80.

Na tua hospedagem, cria o site/subdomínio, por exemplo:

```text
nomequemeter.shardweb.app
```

e configura o proxy/encaminhamento desse domínio para:

```text
127.0.0.1:80
```

ou para a porta interna `80` conforme o painel da hospedagem.

Não é preciso Nginx dentro deste projeto. A própria hospedagem faz o encaminhamento do domínio para o noVNC.

Para verificar sem domínio, abre:

```text
http://IP_DO_SERVIDOR/vnc.html
```

## iPad e teclado

O noVNC já fornece os controlos de entrada para dispositivos táteis. No iPad, abre o menu do noVNC e usa o botão de teclado quando precisares de escrever.

Não é necessário instalar um teclado web adicional no projeto.

## Ficheiros

O antigo uploader Node foi removido juntamente com o Docker e o Nginx.

A VM pode continuar a usar o armazenamento persistente em `data/windows`, mas o upload de ficheiros pelo próprio site deixou de fazer parte desta versão simples.

Podes transferir ficheiros usando um método disponibilizado pela própria hospedagem, uma partilha de rede configurada no Windows, ou outra ferramenta de transferência que o teu servidor permita.

## Windows 10 e Windows 11

O padrão é Windows 11.

Para usar Windows 10:

```bash
python3 main.py --windows-version 10
```

Isto só altera a configuração da VM; a instalação existente não é convertida automaticamente.

## Comandos úteis

Verificar o servidor sem iniciar a VM:

```bash
python3 main.py --check-only
```

Iniciar:

```bash
python3 main.py
```

Ver estado:

```bash
python3 main.py --status
```

Ver logs:

```bash
python3 main.py --logs
```

Parar:

```bash
python3 main.py --down
```

Alterar recursos:

```bash
python3 main.py --ram 10G --disk 100G --cpu 4
```

O perfil padrão é 10G de RAM para a VM. O projeto reduz automaticamente esse valor apenas quando o limite real do container não deixa margem suficiente.

## Segurança

Não publiques diretamente a porta VNC (`5900`) na Internet. O acesso de browser deve ser feito pelo noVNC na porta 80 e, quando disponível, pela camada HTTPS da própria hospedagem.

Usa uma conta Windows própria e uma configuração de autenticação/rede adequada para o teu caso.

## Estrutura

```text
.
├── main.py
├── .env.example
├── .gitignore
└── .github/
    └── workflows/
        └── validate.yml
```

Não há Docker, Compose, Nginx ou Node neste projeto.

## Licenciamento do Windows

O projeto apenas arranca a VM. A instalação e ativação do Windows devem ser feitas com uma licença e meios de instalação apropriados.
