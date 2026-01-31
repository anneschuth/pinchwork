package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

type Profile struct {
	Server string `yaml:"server"`
	APIKey string `yaml:"api_key"`
}

type Config struct {
	CurrentProfile string             `yaml:"current_profile"`
	Profiles       map[string]Profile `yaml:"profiles"`
}

func DefaultConfigPath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".config", "pinchwork", "config.yaml")
}

func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return &Config{
				CurrentProfile: "default",
				Profiles:       map[string]Profile{},
			}, nil
		}
		return nil, err
	}
	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("invalid config file: %w", err)
	}
	if cfg.Profiles == nil {
		cfg.Profiles = map[string]Profile{}
	}
	if cfg.CurrentProfile == "" {
		cfg.CurrentProfile = "default"
	}
	return &cfg, nil
}

func (c *Config) Save(path string) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	data, err := yaml.Marshal(c)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}

func (c *Config) ActiveProfile(override string) (Profile, string) {
	name := c.CurrentProfile
	if override != "" {
		name = override
	}
	p, ok := c.Profiles[name]
	if !ok {
		return Profile{Server: "https://pinchwork.dev"}, name
	}
	return p, name
}

func (c *Config) SetProfile(name string, p Profile) {
	c.Profiles[name] = p
}
