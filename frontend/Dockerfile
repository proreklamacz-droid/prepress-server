FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

ARG BACKEND_URL=http://backend:8687
ENV BACKEND_URL=${BACKEND_URL}
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
