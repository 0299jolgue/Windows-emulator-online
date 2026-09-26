#!/usr/bin/env python3
"""Inicializador do Windows Emulator Online sem Docker/Nginx."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
DATA_DIR = ROOT / "data"
RUN_DIR = DATA_DIR / "run"
LOG_DIR = DATA_DIR / "logs"

PID_FILES = {
    "qemu": RUN_DIR / "qemu.pid",
    "novnc": RUN_DIR / "novnc.pid",
    "swtpm": RUN_DIR / "swtpm.pid",
}

VM_RAM_MIN_GIB = 4
VM_RAM_RECOMMENDED_GIB = 8
VM_DISK_MIN_GIB = 64
VM_DISK_RECOMMENDED_GIB = 100


def color(text: str, code: str) -> str:
    return text if not sys.stdout.isatty() else f"\033[{code}m{text}\033[0m"


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
    print(color("Linux → QEMU/KVM → Windows → noVNC", "90"))
    print()


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
        raise RuntimeError("Não encontrei .env.example.")

    values = read_env()
    defaults = {
        "WINDOWS_VERSION": args.windows_version or "11",
        "WINDOWS_ISO": "data/Windows11.iso",
        "WINDOWS_DISK": "data/windows/windows.qcow2",
        "WINDOWS_DISK_SIZE": args.disk or "100G",
        "WINDOWS_CPU": str(args.cpu or 4),
        "WINDOWS_RAM": args.ram or "8G",
        "VNC_BIND": "127.0.0.1",
        "VNC_PORT": "5900",
        "NOVNC_BIND": "0.0.0.0",
        "NOVNC_PORT": "6080",
        "NOVNC_WEB": "",
        "OVMF_CODE": "",
        "OVMF_VARS": "",
        "WINDOWS_TPM": "Y",
    }

    if not values:
        values = defaults
        write_env(values)
        warn(".env criado com a configuração inicial.")
    else:
        changed = False
        requested = {
            "WINDOWS_VERSION": args.windows_version,
            "WINDOWS_CPU": str(args.cpu) if args.cpu is not None else None,
            "WINDOWS_RAM": args.ram,
            "WINDOWS_DISK_SIZE": args.disk,
        }
        for key, value in requested.items():
            if value is not None and values.get(key) != value:
                values[key] = value
                changed = True
        for key, value in defaults.items():
            if key not in values:
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
    raise ValueError(f"Tamanho inválido: {value}. Usa 8G, 100G, etc.")


def command_exists(name: str) -> str | None:
    return shutil.which(name)


def find_first(paths: list[str]) -> Path | None:
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return path
    return None


def find_ovmf(values: dict[str, str]) -> tuple[Path, Path]:
    code = Path(values["OVMF_CODE"]) if values.get("OVMF_CODE") else None
    vars_file = Path(values["OVMF_VARS"]) if values.get("OVMF_VARS") else None

    code = code or find_first(
        [
            "/usr/share/OVMF/OVMF_CODE_4M.fd",
            "/usr/share/OVMF/OVMF_CODE.fd",
            "/usr/share/edk2/ovmf/OVMF_CODE.fd",
            "/usr/share/edk2/ovmf/x64/OVMF_CODE.fd",
        ]
    )
    vars_file = vars_file or find_first(
        [
            "/usr/share/OVMF/OVMF_VARS_4M.fd",
            "/usr/share/OVMF/OVMF_VARS.fd",
            "/usr/share/edk2/ovmf/OVMF_VARS.fd",
            "/usr/share/edk2/ovmf/x64/OVMF_VARS.fd",
        ]
    )

    if not code or not vars_file:
        raise RuntimeError(
            "Não encontrei OVMF/UEFI. Instala o pacote OVMF/edk2-ovmf "
            "ou define OVMF_CODE e OVMF_VARS no .env."
        )

    return code, vars_file


def check_python() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError("É necessário Python 3.10 ou superior.")
    ok(f"Python {platform.python_version()}")


def check_linux_and_kvm() -> None:
    if platform.system() != "Linux":
        raise RuntimeError("Este projeto requer um host Linux.")

    kvm = Path("/dev/kvm")
    if not kvm.exists():
        raise RuntimeError(
            "/dev/kvm não existe. A hospedagem precisa de KVM/nested virtualization."
        )
    if not os.access(kvm, os.R_OK | os.W_OK):
        raise RuntimeError("/dev/kvm existe, mas não está acessível ao utilizador atual.")
    ok("/dev/kvm disponível")


def check_resources(ram_gib: float, disk_gib: float) -> None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        total_gib = None
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("MemTotal:"):
                total_gib = int(line.split()[1]) / (1024 * 1024)
                break

        if total_gib is not None:
            if total_gib < ram_gib:
                raise RuntimeError(
                    f"O host tem {total_gib:.1f} GiB de RAM e a VM pede {ram_gib:.1f} GiB."
                )
            if total_gib < 8:
                warn(f"RAM total do host: {total_gib:.1f} GiB")
            else:
                ok(f"RAM total do host: {total_gib:.1f} GiB")

    free_gib = shutil.disk_usage(ROOT).free / (1024**3)
    if free_gib < disk_gib + 10:
        raise RuntimeError(
            f"Espaço livre insuficiente: {free_gib:.1f} GiB. "
            f"Liberta espaço antes de criares um disco de {disk_gib:.0f} GiB."
        )
    ok(f"Espaço livre: {free_gib:.1f} GiB")


def check_tools(values: dict[str, str]) -> tuple[str, str, str]:
    qemu = command_exists("qemu-system-x86_64")
    qemu_img = command_exists("qemu-img")
    novnc = command_exists("novnc_proxy")

    if not qemu:
        raise RuntimeError("qemu-system-x86_64 não está instalado.")
    if not qemu_img:
        raise RuntimeError("qemu-img não está instalado.")

    if not novnc:
        candidates = [
            Path("/usr/share/novnc/utils/novnc_proxy"),
            Path("/usr/local/share/novnc/utils/novnc_proxy"),
        ]
        novnc_path = next((p for p in candidates if p.exists()), None)
        if not novnc_path:
            raise RuntimeError(
                "Não encontrei noVNC (novnc_proxy). Instala noVNC no host."
            )
        novnc = str(novnc_path)

    ovmf_code, ovmf_vars = find_ovmf(values)
    ok(f"QEMU: {qemu}")
    ok(f"noVNC: {novnc}")
    ok(f"OVMF: {ovmf_code}")
    return qemu, qemu_img, novnc


def validate(values: dict[str, str]) -> tuple[float, float, int]:
    version = values.get("WINDOWS_VERSION", "11")
    if version not in {"10", "11"}:
        raise RuntimeError("WINDOWS_VERSION deve ser 10 ou 11.")

    ram = parse_gib(values.get("WINDOWS_RAM", "8G"))
    disk = parse_gib(values.get("WINDOWS_DISK_SIZE", "100G"))
    cpu = int(values.get("WINDOWS_CPU", "4"))

    if ram < VM_RAM_MIN_GIB:
        raise RuntimeError(f"WINDOWS_RAM deve ser pelo menos {VM_RAM_MIN_GIB}G.")
    if disk < VM_DISK_MIN_GIB:
        raise RuntimeError(f"WINDOWS_DISK_SIZE deve ser pelo menos {VM_DISK_MIN_GIB}G.")
    if cpu < 2:
        raise RuntimeError("WINDOWS_CPU deve ser pelo menos 2.")

    if version == "11":
        if ram < VM_RAM_RECOMMENDED_GIB:
            warn("Para Windows 11, 8G de RAM é o perfil recomendado.")
        if disk < VM_DISK_RECOMMENDED_GIB:
            warn("Para Windows 11, 100G de disco é o perfil recomendado.")

    return ram, disk, cpu


def ensure_dirs() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "windows").mkdir(parents=True, exist_ok=True)


def pid_from_file(name: str) -> int | None:
    path = PID_FILES[name]
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cleanup_pid(name: str) -> None:
    PID_FILES[name].unlink(missing_ok=True)


def stop_process(name: str, timeout: float = 5.0) -> bool:
    pid = pid_from_file(name)
    if not pid:
        cleanup_pid(name)
        return False
    if not process_alive(pid):
        cleanup_pid(name)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + timeout
        while time.time() < deadline and process_alive(pid):
            time.sleep(0.2)
        if process_alive(pid):
            os.kill(pid, signal.SIGKILL)
    finally:
        cleanup_pid(name)
    return True


def start_process(
    name: str,
    command: list[str],
    log_name: str,
) -> subprocess.Popen[bytes]:
    log_path = LOG_DIR / log_name
    handle = open(log_path, "ab", buffering=0)
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    handle.close()
    PID_FILES[name].write_text(str(process.pid), encoding="utf-8")
    return process


def ensure_disk(qemu_img: str, disk_path: Path, disk_size: str) -> bool:
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    if disk_path.exists():
        return False

    info(f"A criar disco virtual {disk_size}...")
    result = subprocess.run(
        [qemu_img, "create", "-f", "qcow2", str(disk_path), disk_size],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Falha ao criar o disco virtual.")

    ok(f"Disco criado: {disk_path}")
    return True


def prepare_ovmf_vars(template: Path, target: Path) -> None:
    if target.exists():
        return
    shutil.copyfile(template, target)
    ok(f"Variáveis UEFI criadas: {target}")


def build_qemu_command(
    values: dict[str, str],
    qemu: str,
    ovmf_code: Path,
    ovmf_vars: Path,
    disk_path: Path,
    iso_path: Path,
    first_boot: bool,
    tpm_socket: Path | None,
) -> list[str]:
    ram = values["WINDOWS_RAM"]
    cpu = values["WINDOWS_CPU"]
    vnc_bind = values.get("VNC_BIND", "127.0.0.1")
    vnc_port = int(values.get("VNC_PORT", "5900"))
    vnc_display = vnc_port - 5900
    if vnc_display < 0:
        raise RuntimeError("VNC_PORT deve ser 5900 ou superior.")

    if first_boot and not iso_path.exists():
        raise RuntimeError(
            f"Não encontrei a ISO: {iso_path}. Coloca a ISO do Windows nessa localização "
            "ou altera WINDOWS_ISO no .env."
        )

    command = [
        qemu,
        "-name", "windows-emulator-online",
        "-machine", "q35,accel=kvm",
        "-cpu", "host",
        "-smp", cpu,
        "-m", ram,
        "-nodefaults",
        "-boot", "order=d" if first_boot else "order=c",
        "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code}",
        "-drive", f"if=pflash,format=raw,file={ovmf_vars}",
        "-drive", f"file={disk_path},format=qcow2,if=ide",
        "-device", "VGA,vgamem_mb=64",
        "-nic", "user,model=e1000e",
        "-vnc", f"{vnc_bind}:{vnc_display}",
        "-monitor", "none",
        "-serial", "none",
        "-no-reboot",
    ]

    if first_boot:
        command += ["-cdrom", str(iso_path)]

    if tpm_socket is not None:
        command += [
            "-chardev", f"socket,id=chrtpm,path={tpm_socket}",
            "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
            "-device", "tpm-tis,tpmdev=tpm0",
        ]

    return command


def start_tpm(values: dict[str, str]) -> Path | None:
    if values.get("WINDOWS_VERSION") != "11" or values.get("WINDOWS_TPM", "Y").upper() != "Y":
        return None

    swtpm = command_exists("swtpm")
    if not swtpm:
        warn("swtpm não encontrado; o Windows 11 pode recusar a instalação por falta de TPM 2.0.")
        return None

    if process_alive(pid_from_file("swtpm")):
        return RUN_DIR / "swtpm.sock"

    tpm_dir = RUN_DIR / "tpm"
    tpm_dir.mkdir(parents=True, exist_ok=True)
    socket_path = RUN_DIR / "swtpm.sock"
    socket_path.unlink(missing_ok=True)

    command = [
        swtpm,
        "socket",
        "--tpm2",
        "--tpmstate", f"dir={tpm_dir}",
        "--ctrl", f"type=unixio,path={socket_path}",
    ]
    start_process("swtpm", command, "swtpm.log")
    time.sleep(1)

    if not socket_path.exists():
        stop_process("swtpm")
        raise RuntimeError("swtpm iniciou mas não criou o socket TPM.")

    ok("TPM 2.0 virtual disponível")
    return socket_path


def locate_novnc_web(values: dict[str, str]) -> Path:
    configured = values.get("NOVNC_WEB", "").strip()
    if configured:
        web = Path(configured)
        if not web.exists():
            raise RuntimeError(f"NOVNC_WEB não existe: {web}")
        return web

    candidates = [
        Path("/usr/share/novnc"),
        Path("/usr/local/share/novnc"),
    ]
    web = next((p for p in candidates if (p / "vnc.html").exists()), None)
    if not web:
        novnc = shutil.which("novnc_proxy")
        if novnc:
            candidate = Path(novnc).resolve().parent.parent
            if (candidate / "vnc.html").exists():
                return candidate
        raise RuntimeError(
            "Não encontrei os ficheiros web do noVNC. Define NOVNC_WEB no .env."
        )
    return web


def start_novnc(values: dict[str, str], novnc: str) -> None:
    if process_alive(pid_from_file("novnc")):
        ok("noVNC já está em execução")
        return

    web = locate_novnc_web(values)
    vnc_host = values.get("VNC_BIND", "127.0.0.1")
    vnc_port = int(values.get("VNC_PORT", "5900"))
    listen = int(values.get("NOVNC_PORT", "6080"))
    bind = values.get("NOVNC_BIND", "0.0.0.0")

    command = [
        novnc,
        "--vnc",
        f"{vnc_host}:{vnc_port}",
        "--listen",
        f"{bind}:{listen}",
        "--web",
        str(web),
    ]

    start_process("novnc", command, "novnc.log")
    time.sleep(1)

    if not process_alive(pid_from_file("novnc")):
        raise RuntimeError(
            f"noVNC não arrancou. Consulta {LOG_DIR / 'novnc.log'}."
        )

    ok(f"noVNC disponível na porta {listen}")


def start_vm(values: dict[str, str], qemu: str, novnc: str) -> None:
    ensure_dirs()

    if process_alive(pid_from_file("qemu")):
        start_novnc(values, novnc)
        ok("Windows VM já está em execução")
        return

    disk_path = ROOT / values["WINDOWS_DISK"]
    iso_path = ROOT / values["WINDOWS_ISO"]
    disk_size = values["WINDOWS_DISK_SIZE"]

    _, disk_size_gib = parse_gib(values["WINDOWS_RAM"]), parse_gib(disk_size)
    check_resources(disk_size_gib, disk_size_gib)

    created = ensure_disk(
        shutil.which("qemu-img") or "qemu-img",
        disk_path,
        disk_size,
    )

    ovmf_code, ovmf_vars_template = find_ovmf(values)
    vars_target = RUN_DIR / "OVMF_VARS.fd"
    if created:
        prepare_ovmf_vars(ovmf_vars_template, vars_target)
    elif not vars_target.exists():
        prepare_ovmf_vars(ovmf_vars_template, vars_target)

    first_boot = created
    if not first_boot and not disk_path.exists():
        first_boot = True

    tpm_socket = start_tpm(values)

    command = build_qemu_command(
        values,
        qemu,
        ovmf_code,
        vars_target,
        disk_path,
        iso_path,
        first_boot,
        tpm_socket,
    )

    info("A iniciar QEMU/KVM...")
    start_process("qemu", command, "qemu.log")
    time.sleep(2)

    if not process_alive(pid_from_file("qemu")):
        stop_process("swtpm")
        raise RuntimeError(
            f"QEMU não arrancou. Consulta {LOG_DIR / 'qemu.log'}."
        )

    ok("Windows VM em execução")
    start_novnc(values, novnc)

    if first_boot:
        print()
        warn("Primeiro arranque: a VM está a arrancar pela ISO do Windows.")
        warn("Conclui a instalação dentro do noVNC; nos próximos arranques arrancará pelo disco.")
    print()
    print(color(
        f"    noVNC: http://IP_DO_SERVIDOR:{values.get('NOVNC_PORT', '6080')}/vnc.html",
        "1;32",
    ))
    print(color(
        f"    Domínio: aponta o teu subdomínio da hospedagem para a porta {values.get('NOVNC_PORT', '6080')}.",
        "1;32",
    ))
    print()


def show_status(values: dict[str, str]) -> None:
    for name, label in [
        ("qemu", "QEMU/Windows"),
        ("novnc", "noVNC"),
        ("swtpm", "TPM"),
    ]:
        pid = pid_from_file(name)
        state = "em execução" if process_alive(pid) else "parado"
        extra = f" (PID {pid})" if pid and process_alive(pid) else ""
        print(f"{label}: {state}{extra}")

    print(f"Porta noVNC: {values.get('NOVNC_PORT', '6080')}")


def show_logs() -> None:
    found = False
    for name in ("qemu.log", "novnc.log", "swtpm.log"):
        path = LOG_DIR / name
        if not path.exists():
            continue
        found = True
        print()
        print(color(f"===== {name} =====", "1;36"))
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-80:]:
            print(line)
    if not found:
        info("Ainda não existem logs.")


def stop_all() -> None:
    stopped = False
    for name, label in [
        ("novnc", "noVNC"),
        ("qemu", "QEMU/Windows"),
        ("swtpm", "TPM"),
    ]:
        if stop_process(name):
            ok(f"{label} parado")
            stopped = True
    if not stopped:
        info("Nada estava em execução.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa Windows diretamente com QEMU/KVM e noVNC."
    )
    parser.add_argument("--windows-version", choices=["10", "11"])
    parser.add_argument("--ram", help="RAM da VM, por exemplo 8G")
    parser.add_argument("--disk", help="Tamanho do disco, por exemplo 100G")
    parser.add_argument("--cpu", type=int, help="Número de CPUs virtuais")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--logs", action="store_true")
    parser.add_argument("--down", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    title()

    try:
        check_python()
        values = ensure_env(args)
        ram_gib, disk_gib, cpu = validate(values)

        info(f"Windows {values.get('WINDOWS_VERSION', '11')}")
        info(f"VM: {cpu} CPU / {ram_gib:g} GiB RAM / {disk_gib:g} GiB disco")

        ensure_dirs()

        if args.down:
            stop_all()
            return 0

        if args.status:
            show_status(values)
            return 0

        if args.logs:
            show_logs()
            return 0

        check_linux_and_kvm()
        check_resources(ram_gib, disk_gib)
        qemu, _, novnc = check_tools(values)
        find_ovmf(values)

        if args.check_only:
            ok("Todas as verificações passaram.")
            return 0

        start_vm(values, qemu, novnc)

    except KeyboardInterrupt:
        print()
        warn("Interrompido pelo utilizador.")
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))
        print()
        info("Usa python3 main.py --help para ver as opções.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
