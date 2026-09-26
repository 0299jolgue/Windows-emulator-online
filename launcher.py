#!/usr/bin/env python3
"""Windows Emulator Online launcher."""

from __future__ import annotations

import argparse
import os
import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE_FILE = ROOT / "compose.yml"

VM_RAM_MIN_GIB = 4
VM_RAM_RECOMMENDED_GIB = 8
VM_DISK_MIN_GIB = 64
VM_DISK_RECOMMENDED_GIB = 100
HOST_RAM_MIN_GIB = 8
HOST_RAM_RECOMMENDED_GIB = 16
HOST_DISK_MIN_GIB = 100
HOST_DISK_RECOMMENDED_GIB = 150


def color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def info(text: str) -> None:
    print(color("[•] ", "36") + text)


def ok(text: str) -> None:
    print(color("[✓] ", "32") + text)


def warn(text: str) -> None:
    print(color("[!] ", "33") + text)


def fail(text: str) -> None:
    print(color("[✗] ", "31") + text)


def title() -> None:
    print()
    print(color("Windows Emulator Online", "1;36"))
    print(color("Linux host → Docker → QEMU/KVM → Windows → browser", "90"))
    print()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values

    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def write_env(values: dict[str, str]) -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    seen: set[str] = set()

    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            out.append(line)
            continue

        key = line.split("=", 1)[0].strip()
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)

    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def ensure_env(args: argparse.Namespace) -> dict[str, str]:
    if not ENV_EXAMPLE.exists():
        raise RuntimeError(f"Não encontrei {ENV_EXAMPLE.name}.")

    values = read_env()

    if not values:
        values = {
            "WINDOWS_VERSION": args.windows_version or "11",
            "WINDOWS_LANGUAGE": "Portuguese",
            "WINDOWS_REGION": "pt-PT",
            "WINDOWS_KEYBOARD": "pt-PT",
            "WINDOWS_USERNAME": "WindowsUser",
            "WINDOWS_PASSWORD": secrets.token_urlsafe(18),
            "WINDOWS_KEY": "",
            "WINDOWS_AUTOLOGIN": "Y",
            "WINDOWS_CPU": str(args.cpu or 4),
            "WINDOWS_RAM": args.ram or "8G",
            "WINDOWS_DISK": args.disk or "100G",
            "WINDOWS_PROTECT": "N",
            "WINDOWS_AUDIO": "N",
            "MAX_FILE_SIZE": str(2 * 1024 * 1024 * 1024),
        }

        write_env(values)

        warn("Foi gerada uma palavra-passe inicial do Windows.")
        print(color(f"    Utilizador: {values['WINDOWS_USERNAME']}", "33"))
        print(color(f"    Palavra-passe: {values['WINDOWS_PASSWORD']}", "33"))
        print(color("    Guarda estes dados e muda-os no .env quando quiseres.", "33"))
    else:
        changed = False

        requested = {
            "WINDOWS_VERSION": args.windows_version,
            "WINDOWS_CPU": str(args.cpu) if args.cpu is not None else None,
            "WINDOWS_RAM": args.ram,
            "WINDOWS_DISK": args.disk,
        }

        for key, value in requested.items():
            if value is not None and values.get(key) != value:
                values[key] = value
                changed = True

        if changed:
            write_env(values)

    return values


def parse_gib(value: str) -> float:
    normalized = value.strip().upper()

    if normalized.endswith("G"):
        return float(normalized[:-1])
    if normalized.endswith("M"):
        return float(normalized[:-1]) / 1024
    if normalized.endswith("T"):
        return float(normalized[:-1]) * 1024

    raise ValueError(
        f"Valor de tamanho inválido: {value}. Usa, por exemplo, 8G ou 100G."
    )


def check_python() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError("Este launcher precisa de Python 3.10 ou superior.")

    ok(f"Python {platform.python_version()}")


def check_host(required_ram_gib: float, required_disk_gib: float) -> None:
    if platform.system() != "Linux":
        warn("O projeto foi desenhado para um host Linux.")

    meminfo = Path("/proc/meminfo")
    total_ram_gib = None

    if meminfo.exists():
        data = meminfo.read_text(encoding="utf-8", errors="ignore")
        for line in data.splitlines():
            if line.startswith("MemTotal:"):
                kib = int(line.split()[1])
                total_ram_gib = kib / (1024 * 1024)
                break

    if total_ram_gib is not None:
        if total_ram_gib < HOST_RAM_MIN_GIB:
            fail(
                f"RAM do host: {total_ram_gib:.1f} GiB — abaixo do mínimo "
                f"prático de {HOST_RAM_MIN_GIB} GiB."
            )
        elif total_ram_gib < HOST_RAM_RECOMMENDED_GIB:
            warn(
                f"RAM do host: {total_ram_gib:.1f} GiB — recomenda-se "
                f"{HOST_RAM_RECOMMENDED_GIB} GiB ou mais."
            )
        else:
            ok(f"RAM do host: {total_ram_gib:.1f} GiB")

        if total_ram_gib < required_ram_gib:
            raise RuntimeError(
                f"A VM pede {required_ram_gib:.1f} GiB, mas o host só tem "
                f"{total_ram_gib:.1f} GiB."
            )

    usage = shutil.disk_usage(ROOT)
    free_gib = usage.free / (1024**3)
    needed = max(HOST_DISK_MIN_GIB, required_disk_gib + 20)

    if free_gib < needed:
        raise RuntimeError(
            f"Espaço livre: {free_gib:.1f} GiB. Preciso de pelo menos "
            f"{needed:.0f} GiB para esta configuração."
        )

    if free_gib < HOST_DISK_RECOMMENDED_GIB:
        warn(
            f"Espaço livre: {free_gib:.1f} GiB — recomenda-se pelo menos "
            f"{HOST_DISK_RECOMMENDED_GIB} GiB."
        )
    else:
        ok(f"Espaço livre: {free_gib:.1f} GiB")


def check_kvm() -> None:
    kvm = Path("/dev/kvm")

    if not kvm.exists():
        raise RuntimeError(
            "/dev/kvm não existe. Ativa a virtualização no host/BIOS ou usa "
            "um servidor com KVM/nested virtualization."
        )

    if not os.access(kvm, os.R_OK | os.W_OK):
        raise RuntimeError(
            "/dev/kvm existe, mas o utilizador atual não tem acesso "
            "de leitura/escrita."
        )

    ok("/dev/kvm disponível")


def compose_command() -> list[str]:
    docker = shutil.which("docker")

    if docker:
        result = run([docker, "compose", "version"])
        if result.returncode == 0:
            return [docker, "compose"]

    legacy = shutil.which("docker-compose")
    if legacy:
        result = run([legacy, "version"])
        if result.returncode == 0:
            return [legacy]

    raise RuntimeError(
        "Não encontrei Docker Compose. Instala Docker Engine + Compose "
        "plugin no host Linux."
    )


def check_docker(compose: list[str]) -> None:
    result = run(compose + ["version"])

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "Docker Compose não respondeu."
        )

    version = (
        result.stdout.strip().splitlines()[0]
        if result.stdout
        else "Docker Compose disponível"
    )
    ok(version)

    docker_binary = compose[0]
    daemon = run([docker_binary, "info"])

    if daemon.returncode != 0:
        raise RuntimeError(
            "O Docker está instalado, mas o daemon não está disponível "
            "para este utilizador."
        )

    ok("Docker daemon acessível")


def validate_configuration(
    values: dict[str, str],
) -> tuple[float, float, int]:
    version = values.get("WINDOWS_VERSION", "11").strip()

    if version not in {"11", "10"}:
        raise RuntimeError("WINDOWS_VERSION deve ser 11 ou 10.")

    ram = parse_gib(values.get("WINDOWS_RAM", "8G"))
    disk = parse_gib(values.get("WINDOWS_DISK", "100G"))
    cpu = int(values.get("WINDOWS_CPU", "4"))

    if cpu < 2:
        raise RuntimeError("WINDOWS_CPU deve ser pelo menos 2.")

    if ram < VM_RAM_MIN_GIB:
        raise RuntimeError(
            f"WINDOWS_RAM deve ser pelo menos {VM_RAM_MIN_GIB}G."
        )

    if disk < VM_DISK_MIN_GIB:
        raise RuntimeError(
            f"WINDOWS_DISK deve ser pelo menos {VM_DISK_MIN_GIB}G."
        )

    if version == "11":
        if ram < VM_RAM_RECOMMENDED_GIB:
            warn(
                f"Windows 11: {VM_RAM_RECOMMENDED_GIB}G de RAM é o recomendado."
            )

        if disk < VM_DISK_RECOMMENDED_GIB:
            warn(
                f"Windows 11: {VM_DISK_RECOMMENDED_GIB}G de disco é o recomendado."
            )

    return ram, disk, cpu


def run_compose(compose: list[str], args: argparse.Namespace) -> None:
    command = compose + ["-f", str(COMPOSE_FILE)]

    if args.down:
        subprocess.run(command + ["down"], cwd=str(ROOT), check=True)
        ok("Containers parados.")
        return

    if args.status:
        subprocess.run(command + ["ps"], cwd=str(ROOT), check=False)
        return

    if args.logs:
        subprocess.run(
            command + ["logs", "-f", "--tail", "200"],
            cwd=str(ROOT),
            check=False,
        )
        return

    command += ["up", "-d"]

    if not args.no_build:
        command.append("--build")

    info("A iniciar a stack...")
    subprocess.run(command, cwd=str(ROOT), check=True)

    print()
    ok("Windows Emulator Online está a arrancar.")
    print(color("    URL: http://IP_DO_SERVIDOR/", "1;32"))
    print(color("    Porta pública: 80", "1;32"))
    print()
    info("A primeira instalação do Windows pode demorar bastante.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inicializador do Windows Emulator Online."
    )

    parser.add_argument(
        "--windows-version",
        choices=["11", "10"],
        default=None,
        help="Só altera WINDOWS_VERSION quando for indicado.",
    )
    parser.add_argument(
        "--ram",
        default=None,
        help="RAM da VM, por exemplo 4G ou 8G.",
    )
    parser.add_argument(
        "--disk",
        default=None,
        help="Disco da VM, por exemplo 64G ou 100G.",
    )
    parser.add_argument(
        "--cpu",
        type=int,
        default=None,
        help="Número de cores da VM.",
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--logs", action="store_true")
    parser.add_argument("--down", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    title()

    if not COMPOSE_FILE.exists():
        fail(f"Não encontrei {COMPOSE_FILE.name}.")
        return 1

    try:
        check_python()
        values = ensure_env(args)
        ram, disk, cpu = validate_configuration(values)

        info(f"Configuração: Windows {values.get('WINDOWS_VERSION', '11')}")
        info(f"VM: {cpu} CPU / {ram:g} GiB RAM / {disk:g} GiB disco")

        check_kvm()
        check_host(ram, disk)

        compose = compose_command()
        check_docker(compose)

        if args.check_only:
            ok("Todas as verificações passaram.")
            return 0

        run_compose(compose, args)

    except KeyboardInterrupt:
        print()
        warn("Interrompido pelo utilizador.")
        return 130
    except subprocess.CalledProcessError as exc:
        fail(f"Comando falhou com código {exc.returncode}.")
        return exc.returncode or 1
    except (OSError, ValueError, RuntimeError) as exc:
        fail(str(exc))
        print()
        info("Usa python3 launcher.py --help para ver as opções.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
