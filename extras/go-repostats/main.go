// Aura AI — repo stats CLI (Go, standard library only).
// Usage:
//   go run .
// or build a single binary:
//   go build -o repostats . && ./repostats
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

const repoURL = "https://api.github.com/repos/arshadnaib20/aura-ai"

type repo struct {
	FullName      string `json:"full_name"`
	Description   string `json:"description"`
	Language      string `json:"language"`
	Stars         int    `json:"stargazers_count"`
	Forks         int    `json:"forks_count"`
	OpenIssues    int    `json:"open_issues_count"`
	PushedAt      string `json:"pushed_at"`
	DefaultBranch string `json:"default_branch"`
	HTMLURL       string `json:"html_url"`
}

func main() {
	client := &http.Client{Timeout: 15 * time.Second}
	req, err := http.NewRequest("GET", repoURL, nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, "build request:", err)
		os.Exit(1)
	}
	req.Header.Set("User-Agent", "aura-repostats")
	req.Header.Set("Accept", "application/vnd.github+json")

	resp, err := client.Do(req)
	if err != nil {
		fmt.Fprintln(os.Stderr, "request failed:", err)
		os.Exit(1)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		fmt.Fprintf(os.Stderr, "GitHub API returned %s\n", resp.Status)
		os.Exit(1)
	}

	var r repo
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		fmt.Fprintln(os.Stderr, "decode:", err)
		os.Exit(1)
	}

	fmt.Println("Aura AI \u2014 GitHub repo stats")
	fmt.Println("============================")
	fmt.Printf("Repository     : %s\n", r.FullName)
	fmt.Printf("Description    : %s\n", r.Description)
	fmt.Printf("Language       : %s\n", r.Language)
	fmt.Printf("Default branch : %s\n", r.DefaultBranch)
	fmt.Printf("Stars          : %d\n", r.Stars)
	fmt.Printf("Forks          : %d\n", r.Forks)
	fmt.Printf("Open issues    : %d\n", r.OpenIssues)
	fmt.Printf("Last pushed    : %s\n", r.PushedAt)
	fmt.Printf("URL            : %s\n", r.HTMLURL)
}
