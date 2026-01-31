package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"

	"github.com/anneschuth/pinchwork/pinchwork-cli/internal/client"
	"github.com/spf13/cobra"
)

var eventsCmd = &cobra.Command{
	Use:   "events",
	Short: "Stream live SSE events",
	Run: func(cmd *cobra.Command, args []string) {
		c, err := newClientRequired()
		if err != nil {
			exitErr(err)
		}

		ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
		defer cancel()

		fmt.Println("Listening for events... (Ctrl+C to stop)")

		ch := make(chan client.SSEEvent, 100)
		go func() {
			if err := c.StreamEvents(ctx, ch); err != nil && ctx.Err() == nil {
				fmt.Fprintf(os.Stderr, "SSE error: %s\n", err)
			}
			close(ch)
		}()

		for event := range ch {
			if outputFmt == "json" {
				data, _ := json.Marshal(event.Data)
				fmt.Println(string(data))
			} else {
				fmt.Printf("[%s] task=%s\n", event.Type, event.TaskID)
				if event.Data != nil {
					for k, v := range event.Data {
						if k != "type" && k != "task_id" {
							fmt.Printf("  %s: %v\n", k, v)
						}
					}
				}
			}
		}
	},
}

func init() {
	rootCmd.AddCommand(eventsCmd)
}
