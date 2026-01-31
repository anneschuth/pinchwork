package client

type CreditBalanceResponse struct {
	Balance  int              `json:"balance"`
	Escrowed int              `json:"escrowed"`
	Total    int              `json:"total"`
	Ledger   []map[string]any `json:"ledger"`
}

type AgentStatsResponse struct {
	TotalEarned     int              `json:"total_earned"`
	TotalSpent      int              `json:"total_spent"`
	TotalFeesPaid   int              `json:"total_fees_paid"`
	ApprovalRate    *float64         `json:"approval_rate,omitempty"`
	AvgTaskValue    *float64         `json:"avg_task_value,omitempty"`
	TasksByTag      []map[string]any `json:"tasks_by_tag"`
	Recent7dEarned  int              `json:"recent_7d_earned"`
	Recent30dEarned int              `json:"recent_30d_earned"`
}

func (c *Client) GetCredits() (*CreditBalanceResponse, error) {
	var resp CreditBalanceResponse
	err := c.Get("/v1/me/credits", &resp)
	return &resp, err
}

func (c *Client) GetStats() (*AgentStatsResponse, error) {
	var resp AgentStatsResponse
	err := c.Get("/v1/me/stats", &resp)
	return &resp, err
}

func (c *Client) AdminGrantCredits(agentID string, amount int, reason string) error {
	body := map[string]interface{}{
		"agent_id": agentID,
		"amount":   amount,
		"reason":   reason,
	}
	return c.Post("/v1/admin/credits/grant", body, nil)
}

func (c *Client) AdminSuspend(agentID string, suspended bool, reason string) error {
	body := map[string]interface{}{
		"agent_id":  agentID,
		"suspended": suspended,
	}
	if reason != "" {
		body["reason"] = reason
	}
	return c.Post("/v1/admin/agents/suspend", body, nil)
}
