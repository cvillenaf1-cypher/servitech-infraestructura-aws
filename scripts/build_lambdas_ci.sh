set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build
mkdir -p build/package

python -m pip install \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --abi cp312 \
  --only-binary=:all: \
  --no-compile \
  --target build/package \
  -r lambda/requirements.txt

cp lambda/certs/amazon-trust-roots.pem \
  build/package/amazon-trust-roots.pem

for nombre in \
  registrar_servicio \
  consultar_servicio \
  actualizar_diagnostico \
  actualizar_estado \
  gestionar_evidencias
do
  cp "lambda/$nombre/lambda_function.py" \
    build/package/lambda_function.py

  (
    cd build/package
    zip -qr "../$nombre.zip" .
  )

  echo "Generado: build/$nombre.zip"
done

rm -rf build/package
ls -lh build/*.zip