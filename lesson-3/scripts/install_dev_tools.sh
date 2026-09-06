#!/usr/bin/env bash
#
# Verify and prepare the development environment for this assignment:
# Docker, Docker Compose V2, Python >= 3.13, pip and the ML dependencies.
#
# The script is idempotent: running it twice changes nothing the second time,
# it only re-reports the state. Everything it does is appended to install.log.
#
# Python packages are installed into a local virtual environment (.venv) and
# never into the system Python. This keeps the system clean. It is also
# necessary here: the system Python is 3.14, and torch 2.7.0 has no packages
# for that version.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_FILE="${PROJECT_ROOT}/install.log"
VENV_DIR="${PROJECT_ROOT}/.venv"
REQUIREMENTS="${PROJECT_ROOT}/requirements.txt"
REQUIRED_PYTHON="3.13"
PYTHON_PACKAGES=(torch torchvision pillow)

MANUAL_ACTIONS=()

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${LOG_FILE}"; }
ok()   { log "  OK       $*"; }
warn() { log "  MISSING  $*"; }
step() { log ""; log "== $* =="; }

# Returns success when $1 >= $2, comparing dotted version numbers.
version_gte() {
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

need_manual() {
    MANUAL_ACTIONS+=("$1")
    log "  ACTION   $1"
}

log "==============================================================="
log "Environment setup started (project: ${PROJECT_ROOT})"
log "Host: $(uname -s) $(uname -m)"

# --------------------------------------------------------------------------
step "Docker"
# --------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
    ok "docker  -> $(docker --version)"
    if docker info >/dev/null 2>&1; then
        ok "docker daemon is running"
    else
        warn "docker daemon is not running"
        need_manual "Start Docker Desktop (or 'colima start'), then re-run this script."
    fi
else
    warn "docker is not installed"
    # Docker Desktop is an application with a licence agreement, so a script
    # should not install it silently.
    need_manual "Install Docker Desktop: 'brew install --cask docker' (macOS) or https://docs.docker.com/get-docker/"
fi

# --------------------------------------------------------------------------
step "Docker Compose V2"
# --------------------------------------------------------------------------
# V2 is the 'docker compose' command. The older 'docker-compose' program is V1.
if docker compose version >/dev/null 2>&1; then
    ok "docker compose -> $(docker compose version)"
else
    warn "docker compose (V2) is not available"
    need_manual "Install the Compose V2 plugin: https://docs.docker.com/compose/install/"
fi

# --------------------------------------------------------------------------
step "Python >= ${REQUIRED_PYTHON}"
# --------------------------------------------------------------------------
UV_AVAILABLE=0
if command -v uv >/dev/null 2>&1; then
    UV_AVAILABLE=1
    ok "uv      -> $(uv --version)"
else
    log "  INFO     uv is not installed; falling back to the system python3 -m venv"
fi

SYSTEM_PYTHON=""
if command -v python3 >/dev/null 2>&1; then
    SYSTEM_PYTHON="$(command -v python3)"
    ok "python3 -> $(python3 --version) at ${SYSTEM_PYTHON}"
else
    warn "python3 is not installed"
    need_manual "Install Python ${REQUIRED_PYTHON}: 'brew install python@3.13' or https://www.python.org/downloads/"
fi

if command -v pip3 >/dev/null 2>&1; then
    ok "pip3    -> $(pip3 --version)"
else
    log "  INFO     pip3 is not on PATH; the virtual environment provides its own pip"
fi

# --------------------------------------------------------------------------
step "Virtual environment (${VENV_DIR})"
# --------------------------------------------------------------------------
VENV_PYTHON="${VENV_DIR}/bin/python"

venv_version_ok() {
    [ -x "${VENV_PYTHON}" ] || return 1
    local version
    version="$("${VENV_PYTHON}" -c 'import platform; print(platform.python_version())')"
    version_gte "${version}" "${REQUIRED_PYTHON}"
}

if venv_version_ok; then
    ok "virtual environment present -> $("${VENV_PYTHON}" --version)"
else
    if [ -x "${VENV_PYTHON}" ]; then
        log "  INFO     existing virtual environment is older than ${REQUIRED_PYTHON}, recreating it"
        rm -rf "${VENV_DIR}"
    fi
    log "  CREATE   virtual environment with Python ${REQUIRED_PYTHON}"
    if [ "${UV_AVAILABLE}" -eq 1 ]; then
        # uv downloads a managed CPython if the host has no 3.13 --
        # still without touching the system interpreter.
        # --seed installs pip into the environment; uv does not need pip itself,
        # but the assignment requires 'pip3 --version' to work after setup.
        uv venv --seed --python "${REQUIRED_PYTHON}" "${VENV_DIR}" 2>&1 | tee -a "${LOG_FILE}"
    elif [ -n "${SYSTEM_PYTHON}" ] && version_gte "$(python3 -c 'import platform; print(platform.python_version())')" "${REQUIRED_PYTHON}"; then
        python3 -m venv "${VENV_DIR}" 2>&1 | tee -a "${LOG_FILE}"
    else
        warn "cannot create a Python ${REQUIRED_PYTHON} environment"
        need_manual "Install uv ('brew install uv') or Python ${REQUIRED_PYTHON}, then re-run this script."
    fi
    if [ -x "${VENV_PYTHON}" ]; then
        ok "virtual environment created -> $("${VENV_PYTHON}" --version)"
    fi
fi

# pip may be absent when the environment was created by an older uv without --seed.
if [ -x "${VENV_PYTHON}" ] && ! "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
    log "  INSTALL  adding pip to the virtual environment"
    if [ "${UV_AVAILABLE}" -eq 1 ]; then
        VIRTUAL_ENV="${VENV_DIR}" uv pip install pip 2>&1 | tee -a "${LOG_FILE}"
    else
        "${VENV_PYTHON}" -m ensurepip --upgrade 2>&1 | tee -a "${LOG_FILE}"
    fi
fi
if [ -x "${VENV_PYTHON}" ] && "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
    ok "pip in virtual environment -> $("${VENV_PYTHON}" -m pip --version)"
fi

# --------------------------------------------------------------------------
step "ML dependencies (${PYTHON_PACKAGES[*]})"
# --------------------------------------------------------------------------
if [ -x "${VENV_PYTHON}" ]; then
    missing=()
    for package in "${PYTHON_PACKAGES[@]}"; do
        # 'pillow' is the distribution name; the import name is 'PIL'.
        import_name="${package}"
        [ "${package}" = "pillow" ] && import_name="PIL"
        if version="$("${VENV_PYTHON}" -c "import ${import_name}; print(${import_name}.__version__)" 2>/dev/null)"; then
            ok "${package} ${version}"
        else
            warn "${package} is not installed"
            missing+=("${package}")
        fi
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        log "  INSTALL  installing from ${REQUIREMENTS}"
        if [ "${UV_AVAILABLE}" -eq 1 ]; then
            VIRTUAL_ENV="${VENV_DIR}" uv pip install -r "${REQUIREMENTS}" 2>&1 | tee -a "${LOG_FILE}"
        else
            "${VENV_PYTHON}" -m pip install --upgrade pip 2>&1 | tee -a "${LOG_FILE}"
            "${VENV_PYTHON}" -m pip install -r "${REQUIREMENTS}" 2>&1 | tee -a "${LOG_FILE}"
        fi
        for package in "${missing[@]}"; do
            import_name="${package}"
            [ "${package}" = "pillow" ] && import_name="PIL"
            version="$("${VENV_PYTHON}" -c "import ${import_name}; print(${import_name}.__version__)" 2>/dev/null)" \
                && ok "${package} ${version} (installed)" \
                || warn "${package} still missing after install"
        done
    else
        log "  INFO     all dependencies already satisfied, nothing to install"
    fi
else
    warn "no usable virtual environment, skipping dependency installation"
fi

# --------------------------------------------------------------------------
step "Verification"
# --------------------------------------------------------------------------
# The commands the assignment asks to work after setup. Inside an activated
# .venv, 'python3' and 'pip3' resolve to the environment's own interpreter,
# which is what makes the torch import below succeed.
run_check() {
    local description="$1"; shift
    if output="$("$@" 2>&1)"; then
        ok "${description}: ${output%%$'\n'*}"
    else
        warn "${description}: FAILED"
    fi
}

command -v docker >/dev/null 2>&1 && run_check "docker --version" docker --version
docker compose version >/dev/null 2>&1 && run_check "docker compose version" docker compose version
if [ -x "${VENV_PYTHON}" ]; then
    run_check "python3 --version" "${VENV_PYTHON}" --version
    run_check "pip3 --version" "${VENV_PYTHON}" -m pip --version
    run_check "import torch" "${VENV_PYTHON}" -c 'import torch; print(torch.__version__)'
    run_check "import torchvision" "${VENV_PYTHON}" -c 'import torchvision; print(torchvision.__version__)'
    run_check "import PIL" "${VENV_PYTHON}" -c 'import PIL; print(PIL.__version__)'
fi

# --------------------------------------------------------------------------
step "Summary"
# --------------------------------------------------------------------------
if [ "${#MANUAL_ACTIONS[@]}" -eq 0 ]; then
    log "Environment is ready."
    log "Activate it with:  source .venv/bin/activate"
    log "==============================================================="
    exit 0
fi

log "Manual action required:"
for action in "${MANUAL_ACTIONS[@]}"; do
    log "  - ${action}"
done
log "==============================================================="
exit 1
