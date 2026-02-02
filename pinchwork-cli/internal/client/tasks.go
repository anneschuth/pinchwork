package client

import (
	"encoding/json"
	"fmt"
	"net/url"
)

type TaskCreateRequest struct {
	Need                  string   `json:"need"`
	Context               string   `json:"context,omitempty"`
	MaxCredits            int      `json:"max_credits,omitempty"`
	Tags                  []string `json:"tags,omitempty"`
	Wait                  int      `json:"wait,omitempty"`
	DeadlineMinutes       int      `json:"deadline_minutes,omitempty"`
	ReviewTimeoutMinutes  int      `json:"review_timeout_minutes,omitempty"`
	ClaimTimeoutMinutes   int      `json:"claim_timeout_minutes,omitempty"`
}

type TaskCreateResponse struct {
	TaskID string `json:"task_id"`
	Status string `json:"status"`
	Need   string `json:"need"`
}

type TaskResponse struct {
	TaskID               string `json:"task_id"`
	Status               string `json:"status"`
	Need                 string `json:"need"`
	Context              string `json:"context,omitempty"`
	Result               string `json:"result,omitempty"`
	CreditsCharged       *int   `json:"credits_charged,omitempty"`
	PosterID             string `json:"poster_id,omitempty"`
	WorkerID             string `json:"worker_id,omitempty"`
	Deadline             string `json:"deadline,omitempty"`
	ClaimDeadline        string `json:"claim_deadline,omitempty"`
	ReviewTimeoutMinutes *int   `json:"review_timeout_minutes,omitempty"`
	ClaimTimeoutMinutes  *int   `json:"claim_timeout_minutes,omitempty"`
}

type TaskAvailableItem struct {
	TaskID           string   `json:"task_id"`
	Need             string   `json:"need"`
	Context          string   `json:"context,omitempty"`
	MaxCredits       int      `json:"max_credits"`
	Tags             []string `json:"tags,omitempty"`
	CreatedAt        string   `json:"created_at,omitempty"`
	PosterID         string   `json:"poster_id"`
	PosterReputation *float64 `json:"poster_reputation,omitempty"`
	IsMatched        bool     `json:"is_matched"`
	MatchRank        *int     `json:"match_rank,omitempty"`
	RejectionCount   int      `json:"rejection_count"`
	Deadline         string   `json:"deadline,omitempty"`
}

type TaskAvailableResponse struct {
	Tasks []TaskAvailableItem `json:"tasks"`
	Total int                 `json:"total"`
}

type TaskPickupResponse struct {
	TaskID           string   `json:"task_id"`
	Need             string   `json:"need"`
	Context          string   `json:"context,omitempty"`
	MaxCredits       int      `json:"max_credits"`
	PosterID         string   `json:"poster_id"`
	Tags             []string `json:"tags,omitempty"`
	CreatedAt        string   `json:"created_at,omitempty"`
	PosterReputation *float64 `json:"poster_reputation,omitempty"`
	Deadline         string   `json:"deadline,omitempty"`
	ClaimDeadline       string `json:"claim_deadline,omitempty"`
	ClaimTimeoutMinutes *int   `json:"claim_timeout_minutes,omitempty"`
}

type MyTasksResponse struct {
	Tasks []TaskResponse `json:"tasks"`
	Total int            `json:"total"`
}

type QuestionResponse struct {
	ID         string `json:"id"`
	TaskID     string `json:"task_id"`
	AskerID    string `json:"asker_id"`
	Question   string `json:"question"`
	Answer     string `json:"answer,omitempty"`
	CreatedAt  string `json:"created_at,omitempty"`
	AnsweredAt string `json:"answered_at,omitempty"`
}

type QuestionsListResponse struct {
	Questions []QuestionResponse `json:"questions"`
	Total     int                `json:"total"`
}

type MessageResponse struct {
	ID        string `json:"id"`
	TaskID    string `json:"task_id"`
	SenderID  string `json:"sender_id"`
	Message   string `json:"message"`
	CreatedAt string `json:"created_at,omitempty"`
}

type MessagesListResponse struct {
	Messages []MessageResponse `json:"messages"`
	Total    int               `json:"total"`
}

func (c *Client) CreateTask(req TaskCreateRequest) (*TaskCreateResponse, error) {
	var resp TaskCreateResponse
	err := c.Post("/v1/tasks", req, &resp)
	return &resp, err
}

func (c *Client) ListAvailableTasks(tags, search string, limit, offset int) (*TaskAvailableResponse, error) {
	params := url.Values{}
	if tags != "" {
		params.Set("tags", tags)
	}
	if search != "" {
		params.Set("search", search)
	}
	params.Set("limit", fmt.Sprintf("%d", limit))
	params.Set("offset", fmt.Sprintf("%d", offset))

	var resp TaskAvailableResponse
	err := c.Get("/v1/tasks/available?"+params.Encode(), &resp)
	return &resp, err
}

func (c *Client) ListMyTasks(role, status string, limit, offset int) (*MyTasksResponse, error) {
	params := url.Values{}
	if role != "" {
		params.Set("role", role)
	}
	if status != "" {
		params.Set("status", status)
	}
	params.Set("limit", fmt.Sprintf("%d", limit))
	params.Set("offset", fmt.Sprintf("%d", offset))

	var resp MyTasksResponse
	err := c.Get("/v1/tasks/mine?"+params.Encode(), &resp)
	return &resp, err
}

func (c *Client) GetTask(taskID string) (*TaskResponse, error) {
	var resp TaskResponse
	err := c.Get("/v1/tasks/"+taskID, &resp)
	return &resp, err
}

func (c *Client) PickupTask(tags, search string) (*TaskPickupResponse, error) {
	params := url.Values{}
	if tags != "" {
		params.Set("tags", tags)
	}
	if search != "" {
		params.Set("search", search)
	}

	path := "/v1/tasks/pickup"
	if len(params) > 0 {
		path += "?" + params.Encode()
	}

	resp, data, err := c.DoRaw("POST", path, nil)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode == 204 {
		return nil, nil // no tasks available
	}

	if resp.StatusCode >= 400 {
		var errResp struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(data, &errResp)
		return nil, &APIError{StatusCode: resp.StatusCode, Message: errResp.Error}
	}

	var result TaskPickupResponse
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &result, nil
}

func (c *Client) PickupSpecificTask(taskID string) (*TaskPickupResponse, error) {
	resp, data, err := c.DoRaw("POST", "/v1/tasks/"+taskID+"/pickup", nil)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode == 204 {
		return nil, nil
	}

	if resp.StatusCode >= 400 {
		var errResp struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(data, &errResp)
		return nil, &APIError{StatusCode: resp.StatusCode, Message: errResp.Error}
	}

	var result TaskPickupResponse
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &result, nil
}

func (c *Client) DeliverTask(taskID, result string, creditsClaimed *int) (*TaskResponse, error) {
	body := map[string]interface{}{
		"result": result,
	}
	if creditsClaimed != nil {
		body["credits_claimed"] = *creditsClaimed
	}
	var resp TaskResponse
	err := c.Post("/v1/tasks/"+taskID+"/deliver", body, &resp)
	return &resp, err
}

func (c *Client) ApproveTask(taskID string, rating *int, feedback string) (*TaskResponse, error) {
	body := map[string]interface{}{}
	if rating != nil {
		body["rating"] = *rating
	}
	if feedback != "" {
		body["feedback"] = feedback
	}
	var resp TaskResponse
	err := c.Post("/v1/tasks/"+taskID+"/approve", body, &resp)
	return &resp, err
}

func (c *Client) RejectTask(taskID, reason, feedback string) (*TaskResponse, error) {
	body := map[string]interface{}{
		"reason": reason,
	}
	if feedback != "" {
		body["feedback"] = feedback
	}
	var resp TaskResponse
	err := c.Post("/v1/tasks/"+taskID+"/reject", body, &resp)
	return &resp, err
}

func (c *Client) CancelTask(taskID string) (*TaskResponse, error) {
	var resp TaskResponse
	err := c.Post("/v1/tasks/"+taskID+"/cancel", nil, &resp)
	return &resp, err
}

func (c *Client) AbandonTask(taskID string) (*TaskResponse, error) {
	var resp TaskResponse
	err := c.Post("/v1/tasks/"+taskID+"/abandon", nil, &resp)
	return &resp, err
}

func (c *Client) AskQuestion(taskID, question string) (*QuestionResponse, error) {
	body := map[string]interface{}{
		"question": question,
	}
	var resp QuestionResponse
	err := c.Post("/v1/tasks/"+taskID+"/questions", body, &resp)
	return &resp, err
}

func (c *Client) AnswerQuestion(taskID, questionID, answer string) (*QuestionResponse, error) {
	body := map[string]interface{}{
		"answer": answer,
	}
	var resp QuestionResponse
	err := c.Post("/v1/tasks/"+taskID+"/questions/"+questionID+"/answer", body, &resp)
	return &resp, err
}

func (c *Client) ListQuestions(taskID string) (*QuestionsListResponse, error) {
	var resp QuestionsListResponse
	err := c.Get("/v1/tasks/"+taskID+"/questions", &resp)
	return &resp, err
}

func (c *Client) SendMessage(taskID, message string) (*MessageResponse, error) {
	body := map[string]interface{}{
		"message": message,
	}
	var resp MessageResponse
	err := c.Post("/v1/tasks/"+taskID+"/messages", body, &resp)
	return &resp, err
}

func (c *Client) ListMessages(taskID string) (*MessagesListResponse, error) {
	var resp MessagesListResponse
	err := c.Get("/v1/tasks/"+taskID+"/messages", &resp)
	return &resp, err
}
