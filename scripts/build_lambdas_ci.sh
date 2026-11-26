#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p build
build_directory="$(pwd)/build"
temporary_directory="$(mktemp -d "$build_directory/tmp-ci-XXXXXXXX")"
cleanup() {
  case "$temporary_directory" in
    "$build_directory"/tmp-ci-*) rm -rf -- "$temporary_directory" ;;
    *) echo "Ruta temporal fuera de build; no se elimina." >&2; return 1 ;;
  esac
}
trap cleanup EXIT
package_directory="$temporary_directory/package"
mkdir -p "$package_directory"

python -m pip install \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --abi cp312 \
  --only-binary=:all: \
  --no-compile \
  --target "$package_directory" \
  -r lambda/requirements.txt

cp lambda/certs/amazon-trust-roots.pem \
  "$package_directory/amazon-trust-roots.pem"

cp lambda/shared/servitech_authz.py "$package_directory/servitech_authz.py"

for nombre in \
  registrar_servicio \
  consultar_servicio \
  actualizar_diagnostico \
  actualizar_estado \
  gestionar_evidencias
do
  cp "lambda/$nombre/lambda_function.py" \
    "$package_directory/lambda_function.py"

  # Mismo formato reproducible que PowerShell; no requiere el ejecutable zip.
  python -B - "$package_directory" "build/$nombre.zip" <<'PY'
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

package = Path(sys.argv[1])
with ZipFile(sys.argv[2], "w", compression=ZIP_DEFLATED) as archive:
    for path in sorted(package.rglob("*")):
        if path.is_file():
            entry = ZipInfo(path.relative_to(package).as_posix(), (2020, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
PY

  echo "Generado: build/$nombre.zip"
done

ls -lh build/*.zip
