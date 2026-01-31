FROM golang:1.21-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o pinchwork .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=builder /build/pinchwork /usr/local/bin/pinchwork
ENTRYPOINT ["pinchwork"]
