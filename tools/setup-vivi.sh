#!/usr/bin/env bash
#
# Bootstrap the local vivi mailspace for this repository.
#
# What it does, in order:
#   1. Installs the vivi release pinned in VIVI_VERSION, or confirms the vivi
#      already on PATH matches that pin.
#   2. Initializes .vivi/ (local state, gitignored) if it does not exist.
#   3. Adds the roles mind, hand, auditor and operator, each with the kind of
#      the same name. Existing roles are left untouched.
#   4. Re-installs vivi's embedded skills into .agents/skills so the vendored
#      copies stay byte-identical to the pinned release.
#
# It creates no tasks, needs, wants, mail, memos, or rules.
#
# Environment:
#   VIVI_INSTALL_DIR  Where the installer places the binary (default ~/.local/bin).

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly repository_root
readonly pinned_version_file="${repository_root}/VIVI_VERSION"
readonly installer_url="https://raw.githubusercontent.com/ianzepp/vivi/main/install.sh"
readonly install_directory="${VIVI_INSTALL_DIR:-${HOME}/.local/bin}"
readonly vendored_skills_directory="${repository_root}/.agents/skills"
readonly role_names=(mind hand auditor operator)

select_pinned_vivi_version() {
  local pinned_version
  pinned_version="$(tr -d '[:space:]' <"${pinned_version_file}")"
  if [[ ! "${pinned_version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "error: ${pinned_version_file} must hold one release tag like v12.0.4, found '${pinned_version}'." >&2
    exit 1
  fi
  echo "${pinned_version}"
}

select_installed_vivi_version() {
  if command -v vivi >/dev/null 2>&1; then
    vivi --version | awk '{print "v" $2}'
  fi
}

insert_pinned_vivi_binary() {
  local pinned_version="$1"
  echo "Installing vivi ${pinned_version} into ${install_directory}"
  curl -fsSL "${installer_url}" |
    VIVI_VERSION="${pinned_version}" VIVI_INSTALL_DIR="${install_directory}" bash
  export PATH="${install_directory}:${PATH}"
}

insert_vivi_binary_matching_pin() {
  local pinned_version="$1"
  local installed_version
  installed_version="$(select_installed_vivi_version)"

  if [[ "${installed_version}" == "${pinned_version}" ]]; then
    echo "vivi ${installed_version} already matches VIVI_VERSION"
    return
  fi

  insert_pinned_vivi_binary "${pinned_version}"

  installed_version="$(select_installed_vivi_version)"
  if [[ "${installed_version}" != "${pinned_version}" ]]; then
    echo "error: 'vivi --version' reports '${installed_version:-nothing}' after installing ${pinned_version}." >&2
    echo "Another vivi earlier on PATH is probably shadowing ${install_directory}/vivi; remove it or reorder PATH." >&2
    exit 1
  fi
}

insert_role_into_mailspace() {
  local role_name="$1"
  if vivi role show "${role_name}" --project "${repository_root}" >/dev/null 2>&1; then
    echo "role ${role_name} already exists"
    return
  fi
  vivi role add "${role_name}" --kind "${role_name}" --project "${repository_root}"
}

main() {
  local pinned_version
  pinned_version="$(select_pinned_vivi_version)"

  insert_vivi_binary_matching_pin "${pinned_version}"

  vivi mailspace init --project "${repository_root}"

  local role_name
  for role_name in "${role_names[@]}"; do
    insert_role_into_mailspace "${role_name}"
  done

  vivi skills install "${vendored_skills_directory}" --force --project "${repository_root}"
}

main "$@"
