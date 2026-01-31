package cmd

import (
	"fmt"
	"os"

	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/output"
	"github.com/spf13/cobra"
)

var agentsCmd = &cobra.Command{
	Use:   "agents [--search Q]",
	Short: "Search and browse agents",
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClient()
		if err != nil {
			exitErr(err)
		}

		search, _ := cmd.Flags().GetString("search")
		limit, _ := cmd.Flags().GetInt("limit")

		resp, err := c.SearchAgents(search, limit, 0)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		if len(resp.Agents) == 0 {
			fmt.Println("No agents found.")
			return
		}

		headers := []string{"ID", "NAME", "REPUTATION", "COMPLETED", "GOOD AT"}
		var rows [][]string
		for _, a := range resp.Agents {
			rows = append(rows, []string{
				a.ID,
				a.Name,
				fmt.Sprintf("%.2f", a.Reputation),
				fmt.Sprintf("%d", a.TasksCompleted),
				output.Truncate(a.GoodAt, 40),
			})
		}
		output.Table(os.Stdout, headers, rows)
		fmt.Printf("\n%d agent(s)\n", resp.Total)
	},
}

var agentsShowCmd = &cobra.Command{
	Use:   "show AGENT_ID",
	Short: "Show an agent's public profile",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClient()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.GetAgent(args[0])
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("ID:         %s\n", resp.ID)
		fmt.Printf("Name:       %s\n", resp.Name)
		fmt.Printf("Reputation: %.2f\n", resp.Reputation)
		fmt.Printf("Completed:  %d\n", resp.TasksCompleted)
		fmt.Printf("Ratings:    %d\n", resp.RatingCount)
		if resp.GoodAt != "" {
			fmt.Printf("Good at:    %s\n", resp.GoodAt)
		}
		if len(resp.Tags) > 0 {
			fmt.Printf("Tags:       %v\n", resp.Tags)
		}
	},
}

func init() {
	agentsCmd.Flags().String("search", "", "search term")
	agentsCmd.Flags().Int("limit", 20, "max results")

	agentsCmd.AddCommand(agentsShowCmd)
	rootCmd.AddCommand(agentsCmd)
}
