# Web image: Next.js standalone output (docs/spec/08). Node 22 per the ADR-001 addendum.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S bridge && adduser -S bridge -G bridge
COPY --from=build --chown=bridge:bridge /app/.next/standalone ./
COPY --from=build --chown=bridge:bridge /app/.next/static ./.next/static
COPY --from=build --chown=bridge:bridge /app/public ./public
USER bridge
EXPOSE 3000
CMD ["node", "server.js"]
