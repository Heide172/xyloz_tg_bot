# Лёгкий форк cobalt: апстрим-образ + оверлей 3 пропатченных JS-файлов,
# которые добавляют поле `caption` (текст поста) в JSON-ответ.
#
# Запинено по digest = ровно та версия (cobalt 11.7.1), из которой
# извлечены и пропатчены файлы в patched/. При апгрейде cobalt:
#   1. docker pull ghcr.io/imputnet/cobalt:latest
#   2. извлечь свежие src/processing/{services/instagram.js,
#      match-action.js,request.js} из образа
#   3. перенести наш патч (искать `caption`), обновить digest ниже.
FROM ghcr.io/imputnet/cobalt@sha256:63186dd68afd57ce3bb1f62cc4c139f5fa95b9c3e87a3cf5c6e4c7a570523f62

COPY patched/instagram.js    /app/src/processing/services/instagram.js
COPY patched/match-action.js /app/src/processing/match-action.js
COPY patched/request.js      /app/src/processing/request.js
