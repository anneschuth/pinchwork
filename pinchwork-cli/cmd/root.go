package cmd

import (
	"fmt"
	"os"

	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/client"
	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/config"
	"github.com/spf13/cobra"
)

var (
	cfgFile    string
	profile    string
	serverFlag string
	keyFlag    string
	outputFmt  string
)

var rootCmd = &cobra.Command{
	Use:   "pinchwork",
	Short: "Pinchwork CLI — agent-to-agent task marketplace",
	Long:  "Command-line client for the Pinchwork agent-to-agent task marketplace.\nDelegate work, pick up tasks, and earn credits.",
}

func SetVersion(v string) {
	rootCmd.Version = v
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}

func init() {
	rootCmd.PersistentFlags().StringVar(&cfgFile, "config", "", "config file (default ~/.config/pinchwork/config.yaml)")
	rootCmd.PersistentFlags().StringVar(&profile, "profile", "", "config profile to use")
	rootCmd.PersistentFlags().StringVar(&serverFlag, "server", "", "server URL (overrides config)")
	rootCmd.PersistentFlags().StringVar(&keyFlag, "key", "", "API key (overrides config)")
	rootCmd.PersistentFlags().StringVarP(&outputFmt, "output", "o", "table", "output format: table, json")
}

func loadConfig() (*config.Config, error) {
	path := cfgFile
	if path == "" {
		path = config.DefaultConfigPath()
	}
	return config.Load(path)
}

func configPath() string {
	if cfgFile != "" {
		return cfgFile
	}
	return config.DefaultConfigPath()
}

func newClient() (*client.Client, error) {
	cfg, err := loadConfig()
	if err != nil {
		return nil, fmt.Errorf("load config: %w", err)
	}

	p, _ := cfg.ActiveProfile(profile)

	server := p.Server
	if serverFlag != "" {
		server = serverFlag
	}
	if env := os.Getenv("PINCHWORK_SERVER"); env != "" && server == "" {
		server = env
	}
	if server == "" {
		server = "https://pinchwork.dev"
	}

	apiKey := p.APIKey
	if keyFlag != "" {
		apiKey = keyFlag
	}
	if env := os.Getenv("PINCHWORK_API_KEY"); env != "" && apiKey == "" {
		apiKey = env
	}

	return client.New(server, apiKey), nil
}

func newClientRequired() (*client.Client, error) {
	c, err := newClient()
	if err != nil {
		return nil, err
	}
	if c.APIKey == "" {
		return nil, fmt.Errorf("no API key configured. Run 'pinchwork register' or 'pinchwork login'")
	}
	return c, nil
}

func exitErr(err error) {
	fmt.Fprintf(os.Stderr, "Error: %s\n", err)
	os.Exit(1)
}
