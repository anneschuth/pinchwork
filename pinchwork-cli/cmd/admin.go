package cmd

import (
	"fmt"

	"github.com/spf13/cobra"
)

var adminCmd = &cobra.Command{
	Use:   "admin",
	Short: "Admin commands (requires admin key)",
}

var adminGrantCmd = &cobra.Command{
	Use:   "grant AGENT_ID AMOUNT",
	Short: "Grant credits to an agent",
	Args:  cobra.ExactArgs(2),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		agentID := args[0]
		var amount int
		fmt.Sscanf(args[1], "%d", &amount)
		if amount <= 0 {
			exitErr(fmt.Errorf("amount must be a positive integer"))
		}

		reason, _ := cmd.Flags().GetString("reason")
		if reason == "" {
			reason = "admin_grant"
		}

		err = c.AdminGrantCredits(agentID, amount, reason)
		if err != nil {
			exitErr(err)
		}

		fmt.Printf("Granted %d credits to %s\n", amount, agentID)
	},
}

var adminSuspendCmd = &cobra.Command{
	Use:   "suspend AGENT_ID",
	Short: "Suspend an agent",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		reason, _ := cmd.Flags().GetString("reason")

		err = c.AdminSuspend(args[0], true, reason)
		if err != nil {
			exitErr(err)
		}

		fmt.Printf("Suspended agent %s\n", args[0])
	},
}

var adminUnsuspendCmd = &cobra.Command{
	Use:   "unsuspend AGENT_ID",
	Short: "Unsuspend an agent",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		err = c.AdminSuspend(args[0], false, "")
		if err != nil {
			exitErr(err)
		}

		fmt.Printf("Unsuspended agent %s\n", args[0])
	},
}

func init() {
	adminGrantCmd.Flags().String("reason", "admin_grant", "reason for granting credits")
	adminSuspendCmd.Flags().String("reason", "", "reason for suspension")

	adminCmd.AddCommand(adminGrantCmd)
	adminCmd.AddCommand(adminSuspendCmd)
	adminCmd.AddCommand(adminUnsuspendCmd)

	rootCmd.AddCommand(adminCmd)
}
