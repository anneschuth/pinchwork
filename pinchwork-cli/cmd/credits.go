package cmd

import (
	"fmt"
	"os"

	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/output"
	"github.com/spf13/cobra"
)

var creditsCmd = &cobra.Command{
	Use:   "credits",
	Short: "Show your credit balance and ledger",
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.GetCredits()
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Balance:  %d credits\n", resp.Balance)
		fmt.Printf("Escrowed: %d credits\n", resp.Escrowed)

		if len(resp.Ledger) > 0 {
			fmt.Printf("\nRecent transactions (%d total):\n", resp.Total)
			headers := []string{"AMOUNT", "REASON", "TASK"}
			var rows [][]string
			for _, entry := range resp.Ledger {
				amount := fmt.Sprintf("%v", entry["amount"])
				reason := fmt.Sprintf("%v", entry["reason"])
				taskID := ""
				if tid, ok := entry["task_id"]; ok && tid != nil {
					taskID = fmt.Sprintf("%v", tid)
				}
				rows = append(rows, []string{amount, reason, taskID})
			}
			output.Table(os.Stdout, headers, rows)
		}
	},
}

var statsCmd = &cobra.Command{
	Use:   "stats",
	Short: "Show your earnings dashboard",
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.GetStats()
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Total Earned:    %d credits\n", resp.TotalEarned)
		fmt.Printf("Total Spent:     %d credits\n", resp.TotalSpent)
		fmt.Printf("Fees Paid:       %d credits\n", resp.TotalFeesPaid)
		if resp.ApprovalRate != nil {
			fmt.Printf("Approval Rate:   %.1f%%\n", *resp.ApprovalRate*100)
		}
		if resp.AvgTaskValue != nil {
			fmt.Printf("Avg Task Value:  %.1f credits\n", *resp.AvgTaskValue)
		}
		fmt.Printf("Earned (7d):     %d credits\n", resp.Recent7dEarned)
		fmt.Printf("Earned (30d):    %d credits\n", resp.Recent30dEarned)
	},
}

func init() {
	rootCmd.AddCommand(creditsCmd)
	rootCmd.AddCommand(statsCmd)
}
