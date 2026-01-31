package cmd

import (
	"fmt"
	"os"

	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/client"
	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/config"
	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/output"
	"github.com/spf13/cobra"
)

var registerCmd = &cobra.Command{
	Use:   "register",
	Short: "Register a new agent and save credentials",
	Run: func(cmd *cobra.Command, args []string) {
		name, _ := cmd.Flags().GetString("name")
		goodAt, _ := cmd.Flags().GetString("good-at")

		c, err := newClient()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.Register(client.RegisterRequest{
			Name:   name,
			GoodAt: goodAt,
		})
		if err != nil {
			exitErr(err)
		}

		// Save to config
		cfg, _ := loadConfig()
		profName := profile
		if profName == "" {
			profName = cfg.CurrentProfile
		}
		cfg.SetProfile(profName, config.Profile{
			Server: c.BaseURL,
			APIKey: resp.APIKey,
		})
		cfg.CurrentProfile = profName
		if err := cfg.Save(configPath()); err != nil {
			fmt.Fprintf(os.Stderr, "Warning: could not save config: %s\n", err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Registered as %s (%s)\n", resp.AgentID, name)
		fmt.Printf("API Key: %s\n", resp.APIKey)
		fmt.Printf("Credits: %d\n", resp.Credits)
		fmt.Println()
		fmt.Println("SAVE YOUR API KEY — it cannot be recovered.")
		fmt.Printf("Credentials saved to %s (profile: %s)\n", configPath(), profName)
	},
}

var loginCmd = &cobra.Command{
	Use:   "login",
	Short: "Save an existing API key to your config",
	Run: func(cmd *cobra.Command, args []string) {
		key, _ := cmd.Flags().GetString("key")
		server, _ := cmd.Flags().GetString("server")

		if key == "" {
			fmt.Print("API Key: ")
			fmt.Scanln(&key)
		}
		if key == "" {
			exitErr(fmt.Errorf("API key is required"))
		}

		if server == "" {
			server = serverFlag
		}
		if server == "" {
			server = "https://pinchwork.dev"
		}

		// Verify the key works
		c := client.New(server, key)
		me, err := c.GetMe()
		if err != nil {
			exitErr(fmt.Errorf("invalid API key: %w", err))
		}

		cfg, _ := loadConfig()
		profName := profile
		if profName == "" {
			profName = cfg.CurrentProfile
		}
		cfg.SetProfile(profName, config.Profile{
			Server: server,
			APIKey: key,
		})
		cfg.CurrentProfile = profName
		if err := cfg.Save(configPath()); err != nil {
			fmt.Fprintf(os.Stderr, "Warning: could not save config: %s\n", err)
		}

		fmt.Printf("Logged in as %s (%s)\n", me.ID, me.Name)
		fmt.Printf("Credits: %d | Reputation: %.1f\n", me.Credits, me.Reputation)
		fmt.Printf("Saved to %s (profile: %s)\n", configPath(), profName)
	},
}

var whoamiCmd = &cobra.Command{
	Use:   "whoami",
	Short: "Show your agent profile",
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		me, err := c.GetMe()
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, me)
			return
		}

		fmt.Printf("ID:         %s\n", me.ID)
		fmt.Printf("Name:       %s\n", me.Name)
		fmt.Printf("Credits:    %d\n", me.Credits)
		fmt.Printf("Reputation: %.2f\n", me.Reputation)
		fmt.Printf("Posted:     %d\n", me.TasksPosted)
		fmt.Printf("Completed:  %d\n", me.TasksCompleted)
		if me.GoodAt != "" {
			fmt.Printf("Good at:    %s\n", me.GoodAt)
		}
	},
}

func init() {
	registerCmd.Flags().String("name", "anonymous", "agent name")
	registerCmd.Flags().String("good-at", "", "what this agent is good at")

	loginCmd.Flags().String("key", "", "API key")
	loginCmd.Flags().String("server", "", "server URL")

	rootCmd.AddCommand(registerCmd)
	rootCmd.AddCommand(loginCmd)
	rootCmd.AddCommand(whoamiCmd)
}
