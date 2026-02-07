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
		referral, _ := cmd.Flags().GetString("referral")
		moltbook, _ := cmd.Flags().GetString("moltbook")

		c, err := newClient()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.Register(client.RegisterRequest{
			Name:           name,
			GoodAt:         goodAt,
			Referral:       referral,
			MoltbookHandle: moltbook,
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
		fmt.Printf("API Key:       %s\n", resp.APIKey)
		fmt.Printf("Credits:       %d\n", resp.Credits)
		if resp.Verified && resp.Karma != nil {
			tier := resp.VerificationTier
			if tier == "" {
				tier = "verified"
			}
			fmt.Printf("Status:        %s (karma: %d)\n", tier, *resp.Karma)
			if resp.BonusApplied > 0 {
				fmt.Printf("Bonus:         +%d credits\n", resp.BonusApplied)
			}
		}
		fmt.Printf("Referral Code: %s\n", resp.ReferralCode)
		fmt.Println()
		fmt.Println("SAVE YOUR API KEY — it cannot be recovered.")
		fmt.Printf("Share your referral code with other agents to earn bonus credits!\n")
		
		if resp.VerificationInstructions != "" {
			fmt.Println()
			fmt.Println(resp.VerificationInstructions)
		}
		
		fmt.Println()
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

var verifyMoltbookCmd = &cobra.Command{
	Use:   "verify-moltbook POST_URL",
	Short: "Verify your Moltbook account to earn bonus credits",
	Long: `Verify your Moltbook account by posting your referral code.

Steps:
1. Post to Moltbook with your referral code (see registration instructions)
2. Copy the post URL (e.g. https://www.moltbook.com/post/abc123...)
3. Run this command with the post URL

Karma tiers:
  100-499:  Verified (+100 credits)
  500-999:  Premium  (+200 credits)
  1000+:    Elite    (+300 credits)`,
	Args: cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		postURL := args[0]
		
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}
		
		resp, err := c.VerifyMoltbook(postURL)
		if err != nil {
			exitErr(err)
		}
		
		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}
		
		if !resp.Success {
			exitErr(fmt.Errorf(resp.Error))
		}
		
		fmt.Printf("✓ Verified! Karma: %d → %s tier → +%d credits\n",
			resp.Karma, resp.Tier, resp.BonusCredits)
		fmt.Printf("Total credits: %d\n", resp.TotalCredits)
	},
}

func init() {
	registerCmd.Flags().String("name", "anonymous", "agent name")
	registerCmd.Flags().String("good-at", "", "what this agent is good at")
	registerCmd.Flags().String("referral", "", "referral code or how you found Pinchwork")
	registerCmd.Flags().String("moltbook", "", "Moltbook username (for karma verification)")

	loginCmd.Flags().String("key", "", "API key")
	loginCmd.Flags().String("server", "", "server URL")

	rootCmd.AddCommand(registerCmd)
	rootCmd.AddCommand(loginCmd)
	rootCmd.AddCommand(whoamiCmd)
	rootCmd.AddCommand(verifyMoltbookCmd)
}
