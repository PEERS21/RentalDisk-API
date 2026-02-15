set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/PEERS21/RentalDisk-API.git}"
REPO_COMMON_URL="${REPO_URL:-https://github.com/PEERS21/Common-python.git}"
REPO_BRANCH="${REPO_BRANCH:-develop}"
REPO_DIR="/srv/repo"
REPO_COMMON_DIR="/srv/repo/common"
SCRIPT="${SCRIPT:-auth_server}"
APP_PORT="${APP_PORT:-4235}"

if [ ! -d "${REPO_DIR}/.git" ]; then
  echo "Клонирую ${REPO_URL} -> ${REPO_DIR} (branch ${REPO_BRANCH})"
  git clone --branch "${REPO_BRANCH}" "${REPO_URL}" "${REPO_DIR}"
else
  echo "Репозиторий уже существует, обновляю ветку ${REPO_BRANCH}"
  cd "${REPO_DIR}"
  git fetch origin "${REPO_BRANCH}"
  git checkout "${REPO_BRANCH}"
  git pull --ff-only origin "${REPO_BRANCH}" || true
fi

cd "${REPO_DIR}"

if [ ! -d "common/.git" ]; then
  echo "Клонирую ${REPO_COMMON_URL} -> ${REPO_COMMON_DIR} (branch ${REPO_BRANCH})"
  git clone --branch "${REPO_BRANCH}" "${REPO_COMMON_URL}" "${REPO_COMMON_DIR}"
else
  echo "Репозиторий уже существует, обновляю ветку ${REPO_BRANCH}"
  cd "common"
  git fetch origin "${REPO_BRANCH}"
  git checkout "${REPO_BRANCH}"
  git pull --ff-only origin "${REPO_BRANCH}" || true
  cd ..
fi

if [ -f requirements.txt ]; then
  echo "Устанавливаю зависимости из requirements.txt"
  pip install --no-cache-dir -r requirements.txt
fi

export PORT="${APP_PORT}"

echo "Запускаю python ${SCRIPT} (порт ${APP_PORT})"
exec python3 -m "${SCRIPT}"
