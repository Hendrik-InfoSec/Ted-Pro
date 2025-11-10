FROM node:20-slim

WORKDIR /action
COPY package.json .
RUN npm install

COPY . .
CMD ["node", "index.js"]
