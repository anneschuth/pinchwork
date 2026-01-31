package main

import "github.com/anneschuth/pinchwork/pinchwork-cli/cmd"

// Set by goreleaser/ldflags at build time.
var version = "dev"

func main() {
	cmd.SetVersion(version)
	cmd.Execute()
}
