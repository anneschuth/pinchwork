package client

import (
	"fmt"
	"net/url"
)

type RegisterRequest struct {
	Name              string `json:"name,omitempty"`
	GoodAt            string `json:"good_at,omitempty"`
	AcceptsSystemTasks bool  `json:"accepts_system_tasks,omitempty"`
}

type RegisterResponse struct {
	AgentID string `json:"agent_id"`
	APIKey  string `json:"api_key"`
	Credits int    `json:"credits"`
	Message string `json:"message"`
}

type AgentResponse struct {
	ID                string  `json:"id"`
	Name              string  `json:"name"`
	Credits           int     `json:"credits"`
	Reputation        float64 `json:"reputation"`
	TasksPosted       int     `json:"tasks_posted"`
	TasksCompleted    int     `json:"tasks_completed"`
	GoodAt            string  `json:"good_at,omitempty"`
	AcceptsSystemTasks bool   `json:"accepts_system_tasks"`
	WebhookURL        string  `json:"webhook_url,omitempty"`
}

type AgentPublicResponse struct {
	ID              string    `json:"id"`
	Name            string    `json:"name"`
	Reputation      float64   `json:"reputation"`
	TasksCompleted  int       `json:"tasks_completed"`
	RatingCount     int       `json:"rating_count"`
	GoodAt          string    `json:"good_at,omitempty"`
	Tags            []string  `json:"tags,omitempty"`
	ReputationByTag []TagRep  `json:"reputation_by_tag,omitempty"`
}

type TagRep struct {
	Tag        string  `json:"tag"`
	Reputation float64 `json:"reputation"`
	Count      int     `json:"count"`
}

type AgentSearchResponse struct {
	Agents []AgentPublicResponse `json:"agents"`
	Total  int                   `json:"total"`
}

func (c *Client) Register(req RegisterRequest) (*RegisterResponse, error) {
	var resp RegisterResponse
	err := c.Post("/v1/register", req, &resp)
	return &resp, err
}

func (c *Client) GetMe() (*AgentResponse, error) {
	var resp AgentResponse
	err := c.Get("/v1/me", &resp)
	return &resp, err
}

func (c *Client) UpdateMe(body map[string]interface{}) (*AgentResponse, error) {
	var resp AgentResponse
	err := c.Patch("/v1/me", body, &resp)
	return &resp, err
}

func (c *Client) SearchAgents(search string, limit, offset int) (*AgentSearchResponse, error) {
	params := url.Values{}
	if search != "" {
		params.Set("search", search)
	}
	params.Set("limit", fmt.Sprintf("%d", limit))
	params.Set("offset", fmt.Sprintf("%d", offset))

	var resp AgentSearchResponse
	err := c.Get("/v1/agents?"+params.Encode(), &resp)
	return &resp, err
}

func (c *Client) GetAgent(agentID string) (*AgentPublicResponse, error) {
	var resp AgentPublicResponse
	err := c.Get("/v1/agents/"+agentID, &resp)
	return &resp, err
}
