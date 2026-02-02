package cmd

import (
	"fmt"
	"os"
	"strings"

	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/client"
	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/output"
	"github.com/spf13/cobra"
)

var tasksCmd = &cobra.Command{
	Use:     "tasks",
	Aliases: []string{"task", "t"},
	Short:   "Task lifecycle commands",
}

var tasksListCmd = &cobra.Command{
	Use:   "list",
	Short: "List available tasks",
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		tags, _ := cmd.Flags().GetString("tags")
		search, _ := cmd.Flags().GetString("search")
		limit, _ := cmd.Flags().GetInt("limit")

		resp, err := c.ListAvailableTasks(tags, search, limit, 0)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		if len(resp.Tasks) == 0 {
			fmt.Println("No tasks available.")
			return
		}

		headers := []string{"ID", "NEED", "CREDITS", "TAGS", "POSTER"}
		var rows [][]string
		for _, t := range resp.Tasks {
			tagStr := ""
			if len(t.Tags) > 0 {
				tagStr = strings.Join(t.Tags, ",")
			}
			rows = append(rows, []string{
				t.TaskID,
				output.Truncate(t.Need, 50),
				fmt.Sprintf("%d", t.MaxCredits),
				tagStr,
				t.PosterID,
			})
		}
		output.Table(os.Stdout, headers, rows)
		fmt.Printf("\n%d task(s) available\n", resp.Total)
	},
}

var tasksMineCmd = &cobra.Command{
	Use:   "mine",
	Short: "List your tasks (posted and claimed)",
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		role, _ := cmd.Flags().GetString("role")
		status, _ := cmd.Flags().GetString("status")
		limit, _ := cmd.Flags().GetInt("limit")

		resp, err := c.ListMyTasks(role, status, limit, 0)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		if len(resp.Tasks) == 0 {
			fmt.Println("No tasks found.")
			return
		}

		headers := []string{"ID", "STATUS", "NEED", "POSTER", "WORKER"}
		var rows [][]string
		for _, t := range resp.Tasks {
			rows = append(rows, []string{
				t.TaskID,
				t.Status,
				output.Truncate(t.Need, 50),
				t.PosterID,
				t.WorkerID,
			})
		}
		output.Table(os.Stdout, headers, rows)
		fmt.Printf("\n%d task(s)\n", resp.Total)
	},
}

var tasksCreateCmd = &cobra.Command{
	Use:   "create NEED",
	Short: "Create a new task",
	Args:  cobra.MinimumNArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		need := strings.Join(args, " ")
		credits, _ := cmd.Flags().GetInt("credits")
		tags, _ := cmd.Flags().GetString("tags")
		context, _ := cmd.Flags().GetString("context")
		contextFile, _ := cmd.Flags().GetString("context-file")
		deadline, _ := cmd.Flags().GetInt("deadline")
		reviewTimeout, _ := cmd.Flags().GetInt("review-timeout")
		claimTimeout, _ := cmd.Flags().GetInt("claim-timeout")

		if contextFile != "" {
			data, err := os.ReadFile(contextFile)
			if err != nil {
				exitErr(fmt.Errorf("read context file: %w", err))
			}
			context = string(data)
		}

		req := client.TaskCreateRequest{
			Need:       need,
			MaxCredits: credits,
			Context:    context,
		}
		if tags != "" {
			req.Tags = strings.Split(tags, ",")
		}
		if deadline > 0 {
			req.DeadlineMinutes = deadline
		}
		if reviewTimeout > 0 {
			req.ReviewTimeoutMinutes = reviewTimeout
		}
		if claimTimeout > 0 {
			req.ClaimTimeoutMinutes = claimTimeout
		}

		resp, err := c.CreateTask(req)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Created task %s (status: %s)\n", resp.TaskID, resp.Status)
	},
}

var tasksShowCmd = &cobra.Command{
	Use:   "show TASK_ID",
	Short: "Show task details",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.GetTask(args[0])
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Task:     %s\n", resp.TaskID)
		fmt.Printf("Status:   %s\n", resp.Status)
		fmt.Printf("Need:     %s\n", resp.Need)
		if resp.Context != "" {
			fmt.Printf("Context:  %s\n", output.Truncate(resp.Context, 200))
		}
		if resp.PosterID != "" {
			fmt.Printf("Poster:   %s\n", resp.PosterID)
		}
		if resp.WorkerID != "" {
			fmt.Printf("Worker:   %s\n", resp.WorkerID)
		}
		if resp.Result != "" {
			fmt.Printf("Result:   %s\n", resp.Result)
		}
		if resp.CreditsCharged != nil {
			fmt.Printf("Credits:  %d\n", *resp.CreditsCharged)
		}
		if resp.Deadline != "" {
			fmt.Printf("Deadline: %s\n", resp.Deadline)
		}
		if resp.ClaimDeadline != "" {
			fmt.Printf("Claim deadline: %s\n", resp.ClaimDeadline)
		}
	},
}

var tasksPickupCmd = &cobra.Command{
	Use:   "pickup [TASK_ID]",
	Short: "Pick up a task (next available or by ID)",
	Args:  cobra.MaximumNArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		var resp *client.TaskPickupResponse

		if len(args) == 1 {
			resp, err = c.PickupSpecificTask(args[0])
		} else {
			tags, _ := cmd.Flags().GetString("tags")
			search, _ := cmd.Flags().GetString("search")
			resp, err = c.PickupTask(tags, search)
		}
		if err != nil {
			exitErr(err)
		}

		if resp == nil {
			fmt.Println("No tasks available.")
			return
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Picked up task %s\n", resp.TaskID)
		fmt.Printf("Need:    %s\n", resp.Need)
		fmt.Printf("Budget:  %d credits\n", resp.MaxCredits)
		if resp.Context != "" {
			fmt.Printf("Context: %s\n", output.Truncate(resp.Context, 200))
		}
	},
}

var tasksDeliverCmd = &cobra.Command{
	Use:   "deliver TASK_ID RESULT",
	Short: "Deliver completed work",
	Args:  cobra.MinimumNArgs(2),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		taskID := args[0]
		result := strings.Join(args[1:], " ")

		file, _ := cmd.Flags().GetString("file")
		if file != "" {
			data, err := os.ReadFile(file)
			if err != nil {
				exitErr(fmt.Errorf("read file: %w", err))
			}
			result = string(data)
		}

		var creditsClaimed *int
		if cmd.Flags().Changed("credits") {
			v, _ := cmd.Flags().GetInt("credits")
			creditsClaimed = &v
		}

		resp, err := c.DeliverTask(taskID, result, creditsClaimed)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Delivered task %s (status: %s)\n", resp.TaskID, resp.Status)
	},
}

var tasksApproveCmd = &cobra.Command{
	Use:   "approve TASK_ID",
	Short: "Approve a delivery",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		var rating *int
		if cmd.Flags().Changed("rating") {
			v, _ := cmd.Flags().GetInt("rating")
			rating = &v
		}
		feedback, _ := cmd.Flags().GetString("feedback")

		resp, err := c.ApproveTask(args[0], rating, feedback)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Approved task %s\n", resp.TaskID)
	},
}

var tasksRejectCmd = &cobra.Command{
	Use:   "reject TASK_ID",
	Short: "Reject a delivery",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		reason, _ := cmd.Flags().GetString("reason")
		if reason == "" {
			exitErr(fmt.Errorf("--reason is required"))
		}
		feedback, _ := cmd.Flags().GetString("feedback")

		resp, err := c.RejectTask(args[0], reason, feedback)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Rejected task %s\n", resp.TaskID)
	},
}

var tasksCancelCmd = &cobra.Command{
	Use:   "cancel TASK_ID",
	Short: "Cancel a task you posted",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.CancelTask(args[0])
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Cancelled task %s\n", resp.TaskID)
	},
}

var tasksAbandonCmd = &cobra.Command{
	Use:   "abandon TASK_ID",
	Short: "Abandon a claimed task",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		resp, err := c.AbandonTask(args[0])
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Abandoned task %s\n", resp.TaskID)
	},
}

func init() {
	tasksListCmd.Flags().String("tags", "", "filter by tags (comma-separated)")
	tasksListCmd.Flags().String("search", "", "search term")
	tasksListCmd.Flags().Int("limit", 20, "max results")

	tasksMineCmd.Flags().String("role", "", "filter by role: poster or worker")
	tasksMineCmd.Flags().String("status", "", "filter by status")
	tasksMineCmd.Flags().Int("limit", 20, "max results")

	tasksCreateCmd.Flags().Int("credits", 50, "max credits for the task")
	tasksCreateCmd.Flags().String("tags", "", "tags (comma-separated)")
	tasksCreateCmd.Flags().String("context", "", "background context")
	tasksCreateCmd.Flags().String("context-file", "", "read context from file")
	tasksCreateCmd.Flags().Int("deadline", 0, "deadline in minutes")
	tasksCreateCmd.Flags().Int("review-timeout", 0, "auto-approve after N minutes (default: 30)")
	tasksCreateCmd.Flags().Int("claim-timeout", 0, "worker must deliver within N minutes (default: 10)")

	tasksPickupCmd.Flags().String("tags", "", "filter by tags (comma-separated)")
	tasksPickupCmd.Flags().String("search", "", "search term")

	tasksDeliverCmd.Flags().String("file", "", "read result from file")
	tasksDeliverCmd.Flags().Int("credits", 0, "credits to claim")

	tasksApproveCmd.Flags().Int("rating", 0, "rate the worker 1-5")
	tasksApproveCmd.Flags().String("feedback", "", "feedback for the worker")

	tasksRejectCmd.Flags().String("reason", "", "reason for rejection (required)")
	tasksRejectCmd.Flags().String("feedback", "", "constructive feedback")

	tasksCmd.AddCommand(tasksListCmd)
	tasksCmd.AddCommand(tasksMineCmd)
	tasksCmd.AddCommand(tasksCreateCmd)
	tasksCmd.AddCommand(tasksShowCmd)
	tasksCmd.AddCommand(tasksPickupCmd)
	tasksCmd.AddCommand(tasksDeliverCmd)
	tasksCmd.AddCommand(tasksApproveCmd)
	tasksCmd.AddCommand(tasksRejectCmd)
	tasksCmd.AddCommand(tasksCancelCmd)
	tasksCmd.AddCommand(tasksAbandonCmd)

	rootCmd.AddCommand(tasksCmd)
}
