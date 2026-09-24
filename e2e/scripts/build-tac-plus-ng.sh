#!/usr/bin/env bash
# Build tac_plus-ng (Marc Huber's event-driven-servers) from source into a reusable prefix.
#
# Idempotent: if "$PREFIX/sbin/tac_plus-ng" exists and was built from the requested commit,
# nothing is done. Usage:
#   TACPLUS_PREFIX=/opt/tac_plus-ng TACPLUS_REF=master e2e/scripts/build-tac-plus-ng.sh
# Env:
#   TACPLUS_PREFIX   install prefix              (default: $HOME/.cache/nom-e2e/tac_plus-ng)
#   TACPLUS_REF      git ref (branch/tag/sha)    (default: master)
#   TACPLUS_REPO     git URL                     (default: upstream GitHub)
#   TACPLUS_SRC      source checkout dir         (default: $PREFIX/src/event-driven-servers)
#   MAKE_JOBS        parallel make jobs          (default: 1 - upstream makefiles race under -j)
#   INSTALL_DEPS=1   apt-get install build deps (needs root/sudo)
set -euo pipefail

PREFIX="${TACPLUS_PREFIX:-$HOME/.cache/nom-e2e/tac_plus-ng}"
REF="${TACPLUS_REF:-master}"
REPO="${TACPLUS_REPO:-https://github.com/MarcJHuber/event-driven-servers.git}"
SRC="${TACPLUS_SRC:-$PREFIX/src/event-driven-servers}"
JOBS="${MAKE_JOBS:-1}"

if [[ "${INSTALL_DEPS:-0}" == "1" ]]; then
  SUDO=""; [[ $(id -u) -ne 0 ]] && SUDO="sudo"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq build-essential libpcre2-dev libssl-dev libc-ares-dev \
    libldap2-dev libpam0g-dev zlib1g-dev perl git >/dev/null
fi

if [[ ! -d "$SRC/.git" ]]; then
  rm -rf "$SRC"
  git clone --quiet "$REPO" "$SRC"
fi
git -C "$SRC" fetch --quiet origin "$REF" 2>/dev/null || git -C "$SRC" fetch --quiet origin
want=$(git -C "$SRC" rev-parse "FETCH_HEAD^{commit}" 2>/dev/null || git -C "$SRC" rev-parse "$REF^{commit}")

stamp="$PREFIX/.built-commit"
if [[ -x "$PREFIX/sbin/tac_plus-ng" && -f "$stamp" && "$(cat "$stamp")" == "$want" ]]; then
  echo "tac_plus-ng $want already installed in $PREFIX"
  exit 0
fi

git -C "$SRC" checkout --quiet --force "$want"
git -C "$SRC" clean -fdxq
cd "$SRC"
./configure --prefix="$PREFIX" tac_plus-ng >"$PREFIX.configure.log" 2>&1 || { tail -50 "$PREFIX.configure.log"; exit 1; }
make -j"$JOBS" >"$PREFIX.make.log" 2>&1 || { tail -80 "$PREFIX.make.log"; exit 1; }
make install >"$PREFIX.install.log" 2>&1 || { tail -50 "$PREFIX.install.log"; exit 1; }
echo "$want" >"$stamp"
echo "installed tac_plus-ng $want into $PREFIX"
"$PREFIX/sbin/tac_plus-ng" -v 2>&1 | head -1 || true
