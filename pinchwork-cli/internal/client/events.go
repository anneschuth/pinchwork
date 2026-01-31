package client

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

type SSEEvent struct {
	Type   string         `json:"type"`
	TaskID string         `json:"task_id"`
	Data   map[string]any `json:"-"`
	Raw    string         `json:"-"`
}

// StreamEvents connects to the SSE endpoint and sends events on the channel.
// It blocks until the context is cancelled or the connection drops.
func (c *Client) StreamEvents(ctx context.Context, ch chan<- SSEEvent) error {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/v1/events", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.APIKey)
	req.Header.Set("Accept", "text/event-stream")

	httpClient := &http.Client{}
	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("SSE connection failed: %d", resp.StatusCode)
	}

	scanner := bufio.NewScanner(resp.Body)
	var eventType string
	var dataLines []string

	for scanner.Scan() {
		line := scanner.Text()

		if line == "" {
			// End of event
			if len(dataLines) > 0 {
				raw := strings.Join(dataLines, "\n")
				event := SSEEvent{
					Type: eventType,
					Raw:  raw,
				}
				// Try to parse JSON data
				var parsed map[string]any
				if err := json.Unmarshal([]byte(raw), &parsed); err == nil {
					event.Data = parsed
					if t, ok := parsed["type"].(string); ok {
						event.Type = t
					}
					if tid, ok := parsed["task_id"].(string); ok {
						event.TaskID = tid
					}
				}
				ch <- event
			}
			eventType = ""
			dataLines = nil
			continue
		}

		if strings.HasPrefix(line, "event: ") {
			eventType = strings.TrimPrefix(line, "event: ")
		} else if strings.HasPrefix(line, "data: ") {
			dataLines = append(dataLines, strings.TrimPrefix(line, "data: "))
		} else if strings.HasPrefix(line, ": ") {
			// Comment/keepalive, ignore
		}
	}

	return scanner.Err()
}
