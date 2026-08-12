#!/usr/bin/env bash
set -euo pipefail

readonly MI_URL="https://www.takahiro.co.jp/en/product/cad/me10/index.zip"
readonly MI_SHA256="5b56a6777e8bc6c5023c31e3ee503f67d7fdd4a3cb9e35e79c284bb977c6a30d"
readonly DXF_URL="https://www.takahiro.co.jp/en/product/cad/dxf/index.zip"
readonly DXF_SHA256="cd3fdd2097f3b89e15669878ba0d8000ccfcd204e4f880987965b2efc4bda65a"
readonly PTC_URL="https://community.ptc.com/topic/trackAttachment?file_uuid=2139133a-0e3d-4a8b-106d-99764a16a18d&redirect=1"
readonly PTC_ARCHIVE_SHA256="e1e5ee6c0c63dab1bba8dcf7780645398da70c59a230a41ac20c363e3a6431ec"
readonly PTC_BUNDLE_SHA256="63b2952002451d0693b9db56e466dce1f09810528d92c7e28722afcf422a7b0d"
readonly PTC_COMPRESSED_MI_SHA256="60303e5f6dd38f434fd20b20798b3a9d3d9dfcb0e9883015119db6b3d1b49ecc"
readonly PTC_LOGICAL_MI_SHA256="3bb45897b8cdbb9bc0e82048af65677274548002234c4a0190b4f0f14a1d1d65"

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly DESTINATION="${REPO_ROOT}/samples/external/takahiro-soarerdex"
readonly PTC_DESTINATION="${REPO_ROOT}/samples/external/ptc-community-mandrel"
readonly TEMP_DIRECTORY="$(mktemp -d "${TMPDIR:-/tmp}/ezmi-samples.XXXXXX")"

cleanup() {
  rm -rf -- "${TEMP_DIRECTORY}"
}
trap cleanup EXIT

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "required command not found: $1" >&2
    exit 1
  fi
}

verify_archive() {
  local expected_sha256="$1"
  local archive="$2"

  if ! printf '%s  %s\n' "${expected_sha256}" "${archive}" | sha256sum --check --status; then
    echo "checksum mismatch: ${archive}" >&2
    exit 1
  fi
}

for command_name in curl gzip sha256sum unzip; do
  require_command "${command_name}"
done

readonly MI_ARCHIVE="${TEMP_DIRECTORY}/takahiro-soarerdex-me10.zip"
readonly DXF_ARCHIVE="${TEMP_DIRECTORY}/takahiro-soarerdex-dxf.zip"
readonly PTC_ARCHIVE="${TEMP_DIRECTORY}/1_09_04_010_MANDREL.zip"
readonly PTC_BUNDLE="${TEMP_DIRECTORY}/09_04_010_MANDREL.bdl"
readonly PTC_COMPRESSED_MI="${TEMP_DIRECTORY}/am_2d_0.compressed.mi"
readonly PTC_LOGICAL_MI="${TEMP_DIRECTORY}/am_2d_0.logical.mi"

curl --fail --location --retry 3 --proto '=https' --output "${MI_ARCHIVE}" "${MI_URL}"
curl --fail --location --retry 3 --proto '=https' --output "${DXF_ARCHIVE}" "${DXF_URL}"
curl --fail --location --retry 3 --proto '=https' --output "${PTC_ARCHIVE}" "${PTC_URL}"

verify_archive "${MI_SHA256}" "${MI_ARCHIVE}"
verify_archive "${DXF_SHA256}" "${DXF_ARCHIVE}"
verify_archive "${PTC_ARCHIVE_SHA256}" "${PTC_ARCHIVE}"

unzip -p "${PTC_ARCHIVE}" '09_04_010_MANDREL.bdl' > "${PTC_BUNDLE}"
verify_archive "${PTC_BUNDLE_SHA256}" "${PTC_BUNDLE}"
unzip -p "${PTC_BUNDLE}" 'am_2d_0.mi' > "${PTC_COMPRESSED_MI}"
verify_archive "${PTC_COMPRESSED_MI_SHA256}" "${PTC_COMPRESSED_MI}"
gzip -dc "${PTC_COMPRESSED_MI}" > "${PTC_LOGICAL_MI}"
verify_archive "${PTC_LOGICAL_MI_SHA256}" "${PTC_LOGICAL_MI}"

mkdir -p "${DESTINATION}/archives" "${DESTINATION}/mi" "${DESTINATION}/dxf"
cp "${MI_ARCHIVE}" "${DESTINATION}/archives/"
cp "${DXF_ARCHIVE}" "${DESTINATION}/archives/"
unzip -oq "${MI_ARCHIVE}" -d "${DESTINATION}/mi"
unzip -oq "${DXF_ARCHIVE}" -d "${DESTINATION}/dxf"

mkdir -p \
  "${PTC_DESTINATION}/archives" \
  "${PTC_DESTINATION}/compressed" \
  "${PTC_DESTINATION}/mi"
cp "${PTC_ARCHIVE}" "${PTC_DESTINATION}/archives/"
cp "${PTC_BUNDLE}" "${PTC_DESTINATION}/archives/"
cp "${PTC_COMPRESSED_MI}" "${PTC_DESTINATION}/compressed/am_2d_0.mi"
cp "${PTC_LOGICAL_MI}" "${PTC_DESTINATION}/mi/am_2d_0.mi"

readonly SAMPLE_NAMES=(
  F100 F125 F160 F200 F50 F63 F80
  S100 S125 S40 S50 S63 S80
  T100 T125 T160 T200 T250 T80
)

for sample_name in "${SAMPLE_NAMES[@]}"; do
  test -f "${DESTINATION}/mi/${sample_name}"
  test -f "${DESTINATION}/dxf/${sample_name}.DXF"
done

(
  cd "${DESTINATION}"
  LC_ALL=C sha256sum archives/*.zip mi/* dxf/* > SHA256SUMS
)

(
  cd "${PTC_DESTINATION}"
  LC_ALL=C sha256sum archives/* compressed/* mi/* > SHA256SUMS
)

echo "Fetched and verified 19 MI/DXF pairs in ${DESTINATION}"
echo "Fetched and verified one genuine compressed/logical MI pair in ${PTC_DESTINATION}"
