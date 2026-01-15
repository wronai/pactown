# Go API Gateway

Lightweight API gateway written in Go. Demonstrates Go service in a polyglot ecosystem.

## Endpoints

- `GET /health` – Health check
- `GET /status` – Aggregated status from all services
- `ANY /ml/*` – Proxy to ML service
- `ANY /api/*` – Proxy to Node API

---

```go markpact:file path=main.go
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sync"
	"time"
)

var (
	mlServiceURL   = getEnv("ML_SERVICE_URL", "http://localhost:8010")
	nodeServiceURL = getEnv("NODE_SERVICE_URL", "http://localhost:3000")
	port           = getEnv("MARKPACT_PORT", "8080")
)

func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

type ServiceStatus struct {
	Name    string `json:"name"`
	URL     string `json:"url"`
	Status  string `json:"status"`
	Latency int64  `json:"latency_ms"`
}

type HealthResponse struct {
	Status   string          `json:"status"`
	Service  string          `json:"service"`
	Services []ServiceStatus `json:"services,omitempty"`
}

func checkService(name, url string, wg *sync.WaitGroup, results chan<- ServiceStatus) {
	defer wg.Done()
	
	start := time.Now()
	resp, err := http.Get(url + "/health")
	latency := time.Since(start).Milliseconds()
	
	status := ServiceStatus{
		Name:    name,
		URL:     url,
		Latency: latency,
	}
	
	if err != nil {
		status.Status = "unreachable"
	} else {
		defer resp.Body.Close()
		if resp.StatusCode == 200 {
			status.Status = "healthy"
		} else {
			status.Status = fmt.Sprintf("unhealthy (%d)", resp.StatusCode)
		}
	}
	
	results <- status
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(HealthResponse{
		Status:  "ok",
		Service: "go-gateway",
	})
}

func statusHandler(w http.ResponseWriter, r *http.Request) {
	services := []struct{ name, url string }{
		{"ml-service", mlServiceURL},
		{"node-api", nodeServiceURL},
	}
	
	results := make(chan ServiceStatus, len(services))
	var wg sync.WaitGroup
	
	for _, svc := range services {
		wg.Add(1)
		go checkService(svc.name, svc.url, &wg, results)
	}
	
	wg.Wait()
	close(results)
	
	var statuses []ServiceStatus
	allHealthy := true
	for status := range results {
		statuses = append(statuses, status)
		if status.Status != "healthy" {
			allHealthy = false
		}
	}
	
	overallStatus := "healthy"
	if !allHealthy {
		overallStatus = "degraded"
	}
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(HealthResponse{
		Status:   overallStatus,
		Service:  "go-gateway",
		Services: statuses,
	})
}

func proxyHandler(targetURL string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Create proxy request
		proxyURL := targetURL + r.URL.Path
		if r.URL.RawQuery != "" {
			proxyURL += "?" + r.URL.RawQuery
		}
		
		proxyReq, err := http.NewRequest(r.Method, proxyURL, r.Body)
		if err != nil {
			http.Error(w, "Failed to create proxy request", http.StatusInternalServerError)
			return
		}
		
		// Copy headers
		for key, values := range r.Header {
			for _, value := range values {
				proxyReq.Header.Add(key, value)
			}
		}
		
		// Make request
		client := &http.Client{Timeout: 30 * time.Second}
		resp, err := client.Do(proxyReq)
		if err != nil {
			http.Error(w, "Service unavailable", http.StatusServiceUnavailable)
			return
		}
		defer resp.Body.Close()
		
		// Copy response headers
		for key, values := range resp.Header {
			for _, value := range values {
				w.Header().Add(key, value)
			}
		}
		
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	}
}

func main() {
	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/status", statusHandler)
	
	// Proxy routes
	http.HandleFunc("/ml/", http.StripPrefix("/ml", proxyHandler(mlServiceURL)).ServeHTTP)
	http.HandleFunc("/api/", http.StripPrefix("/api", proxyHandler(nodeServiceURL+"/api")).ServeHTTP)
	
	fmt.Printf("Go Gateway listening on :%s\n", port)
	fmt.Printf("ML Service: %s\n", mlServiceURL)
	fmt.Printf("Node API: %s\n", nodeServiceURL)
	
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		fmt.Fprintf(os.Stderr, "Server error: %v\n", err)
		os.Exit(1)
	}
}
```

```text markpact:file path=go.mod
module go-gateway

go 1.21
```

```bash markpact:run
go run main.go
```

```http markpact:test
GET /health EXPECT 200
GET /status EXPECT 200
```
