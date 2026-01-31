package cmd

import (
	"fmt"
	"os"
	"strings"

	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/output"
	"github.com/spf13/cobra"
)

var askCmd = &cobra.Command{
	Use:   "ask TASK_ID QUESTION",
	Short: "Ask a clarifying question on a task",
	Args:  cobra.MinimumNArgs(2),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		taskID := args[0]
		question := strings.Join(args[1:], " ")

		resp, err := c.AskQuestion(taskID, question)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Question posted: %s\n", resp.ID)
	},
}

var answerCmd = &cobra.Command{
	Use:   "answer TASK_ID QUESTION_ID ANSWER",
	Short: "Answer a question on your posted task",
	Args:  cobra.MinimumNArgs(3),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		taskID := args[0]
		questionID := args[1]
		answer := strings.Join(args[2:], " ")

		resp, err := c.AnswerQuestion(taskID, questionID, answer)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Answer posted on %s\n", resp.TaskID)
	},
}

var msgCmd = &cobra.Command{
	Use:   "msg TASK_ID MESSAGE",
	Short: "Send a message on a claimed task",
	Args:  cobra.MinimumNArgs(2),
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		taskID := args[0]
		message := strings.Join(args[1:], " ")

		resp, err := c.SendMessage(taskID, message)
		if err != nil {
			exitErr(err)
		}

		if outputFmt == "json" {
			output.JSON(os.Stdout, resp)
			return
		}

		fmt.Printf("Message sent on %s\n", resp.TaskID)
	},
}

func init() {
	rootCmd.AddCommand(askCmd)
	rootCmd.AddCommand(answerCmd)
	rootCmd.AddCommand(msgCmd)
}
