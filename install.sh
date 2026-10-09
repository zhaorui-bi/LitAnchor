#!/usr/bin/env bash
# LitExtract ZCode 工具包 一键安装/更新/卸载
#
# 用法:
#   bash install.sh              安装或更新 SKILL.md + scripts/ 到
#                                ~/.zcode/skills/lit-extract/（旧版先备份到
#                                ~/.zcode/skills/lit-extract.bak.<日期>）
#   bash install.sh --uninstall  卸载 ~/.zcode/skills/lit-extract/
#
# 特性: 无交互输入、无网络请求、无凭据；仅操作本包目录与
#       ~/.zcode/skills/lit-extract/ 两个位置。

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${HOME}/.zcode/skills"
DEST="${SKILLS_DIR}/lit-extract"

if [[ "${1:-}" == "--uninstall" ]]; then
  if [[ -d "${DEST}" ]]; then
    rm -rf "${DEST}"
    echo "已卸载: ${DEST}"
  else
    echo "未安装（无需卸载）: ${DEST}"
  fi
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "用法: bash install.sh [--uninstall]" >&2
  exit 1
fi

for f in "${SRC_DIR}/SKILL.md" \
         "${SRC_DIR}/scripts/stage0_anchor.py" \
         "${SRC_DIR}/scripts/validate.py"; do
  if [[ ! -f "${f}" ]]; then
    echo "ERROR: 缺少包文件: ${f}" >&2
    exit 1
  fi
done

if [[ -d "${DEST}" ]]; then
  BAK="${SKILLS_DIR}/lit-extract.bak.$(date +%Y%m%d-%H%M%S)"
  mv "${DEST}" "${BAK}"
  echo "已备份旧版: ${BAK}"
fi

mkdir -p "${DEST}/scripts"
cp "${SRC_DIR}/SKILL.md" "${DEST}/SKILL.md"
cp "${SRC_DIR}/scripts/stage0_anchor.py" "${DEST}/scripts/stage0_anchor.py"
cp "${SRC_DIR}/scripts/validate.py" "${DEST}/scripts/validate.py"

echo "已安装到: ${DEST}"
ls -l "${DEST}/SKILL.md" "${DEST}/scripts/"
