# Базовый образ — лёгкий веб-сервер Nginx
FROM nginx:alpine

# Удаляем страницу по умолчанию
RUN rm -rf /usr/share/nginx/html/*

# Копируем нашу веб-страницу в директорию, которую отдаёт Nginx
COPY index.html /usr/share/nginx/html/index.html

# Открываем порт 80
EXPOSE 80

# Nginx уже настроен на запуск в качестве основного процесса образа nginx:alpine
CMD ["nginx", "-g", "daemon off;"]
