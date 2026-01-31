.PHONY: build test lint clean install snapshot

BINARY := pinchwork
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS := -ldflags "-s -w -X main.version=$(VERSION)"

build:
	go build $(LDFLAGS) -o $(BINARY) .

test:
	go test ./... -v

lint:
	go vet ./...

clean:
	rm -f $(BINARY)
	rm -rf dist/

install:
	go install $(LDFLAGS) .

# Cross-compilation
build-all:
	GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o dist/$(BINARY)-linux-amd64 .
	GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o dist/$(BINARY)-linux-arm64 .
	GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o dist/$(BINARY)-darwin-amd64 .
	GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o dist/$(BINARY)-darwin-arm64 .
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o dist/$(BINARY)-windows-amd64.exe .

# Local test of goreleaser (no publish)
snapshot:
	goreleaser release --snapshot --clean

# Docker
docker:
	docker build -t pinchwork-cli .
